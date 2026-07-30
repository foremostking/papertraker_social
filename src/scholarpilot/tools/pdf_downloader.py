"""全文 PDF 下载模块.

整合多源全文下载能力，支持 VPN 机构 IP 认证和 OA 开放获取。
用户需通过 EasyConnect 登录 VPN 后才能访问付费数据库全文资源。

下载策略（按优先级）:
    1. OA 源（无需 VPN）: arXiv、ChinaXiv、Unpaywall 发现的 OA 版本
    2. VPN 机构源（需 EasyConnect 已连接）:
       - ScienceDirect (Elsevier)
       - SpringerLink
       - Wiley Online Library
       - CNKI 知网
    3. DOI 直接解析（尝试通过 doi.org 跳转）

VPN 认证说明:
    EasyConnect 工作在 IP 网络层，连接后系统出口 IP 变为机构 IP。
    出版商通过 IP 认证识别机构订阅权限，无需额外 Cookie/Token。
    但部分出版商可能需要 Shibboleth/SSO 登录，需配合浏览器使用。

Usage:
    manager = PDFDownloadManager()
    result = await manager.download(
        doi="10.1016/j.jfineco.2023.01.001",
        title="Fiscal policy and economic growth",
        output_dir="./downloads",
    )
    if result.success:
        print(f"PDF saved to {result.file_path}")
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import aiohttp

from scholarpilot.utils.network import configure_no_proxy
from scholarpilot.utils.vpn import VPNStatus, get_vpn_detector

logger = logging.getLogger(__name__)


# ===== 下载源枚举 =====

class PDFDownloadSource(str, Enum):
    """PDF 下载来源."""

    ARXIV = "arxiv"
    CHINAXIV = "chinaxiv"
    UNPAYWALL = "unpaywall"
    SCIENCEDIRECT = "sciencedirect"
    SPRINGER = "springer"
    WILEY = "wiley"
    CNKI = "cnki"
    DOI_DIRECT = "doi_direct"
    UNKNOWN = "unknown"


class DownloadStatus(str, Enum):
    """下载状态."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # VPN 未连接，跳过付费源
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"


# ===== 数据模型 =====

@dataclass
class DownloadResult:
    """单次下载结果."""

    source: PDFDownloadSource = PDFDownloadSource.UNKNOWN
    status: DownloadStatus = DownloadStatus.FAILED
    file_path: str = ""
    file_size: int = 0  # bytes
    doi: str = ""
    title: str = ""
    url: str = ""  # 实际下载 URL
    error: str = ""
    download_time: float = 0.0  # seconds
    vpn_required: bool = False  # 是否需要 VPN
    vpn_used: bool = False  # 是否使用了 VPN

    @property
    def success(self) -> bool:
        return self.status == DownloadStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "status": self.status.value,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "doi": self.doi,
            "title": self.title,
            "url": self.url,
            "error": self.error,
            "download_time": round(self.download_time, 2),
            "vpn_required": self.vpn_required,
            "vpn_used": self.vpn_used,
        }


@dataclass
class BatchDownloadResult:
    """批量下载结果."""

    results: list[DownloadResult] = field(default_factory=list)
    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    total_size: int = 0
    total_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "total_size": self.total_size,
            "total_time": round(self.total_time, 2),
            "results": [r.to_dict() for r in self.results],
        }


# ===== 出版商配置 =====

# 各出版商的 PDF URL 构建规则
# VPN 连接后，机构 IP 可直接访问这些 URL 下载 PDF
PUBLISHER_PDF_URLS: dict[str, dict[str, Any]] = {
    "sciencedirect": {
        # Elsevier ScienceDirect
        # PII (Publisher Item Identifier) 从 DOI 解析或从 URL 提取
        "doi_to_pdf": lambda doi: f"https://www.sciencedirect.com/science/article/pii/{_doi_to_pii(doi)}/pdfft",
        "content_type_check": True,
        "needs_vpn": True,
    },
    "springer": {
        # SpringerLink
        "doi_to_pdf": lambda doi: f"https://link.springer.com/content/pdf/{doi}.pdf",
        "content_type_check": True,
        "needs_vpn": True,
    },
    "wiley": {
        # Wiley Online Library
        "doi_to_pdf": lambda doi: f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
        "content_type_check": True,
        "needs_vpn": True,
    },
    "tandfonline": {
        # Taylor & Francis
        "doi_to_pdf": lambda doi: f"https://www.tandfonline.com/doi/pdf/{doi}",
        "content_type_check": True,
        "needs_vpn": True,
    },
    "sagepub": {
        # SAGE Publications
        "doi_to_pdf": lambda doi: f"https://journals.sagepub.com/doi/pdf/{doi}",
        "content_type_check": True,
        "needs_vpn": True,
    },
    "mdpi": {
        # MDPI (Open Access, 不需要 VPN)
        "doi_to_pdf": lambda doi: f"https://doi.org/{doi}",
        "content_type_check": True,
        "needs_vpn": False,
    },
}

# DOI 前缀到出版商的映射
DOI_PREFIX_TO_PUBLISHER: dict[str, str] = {
    "10.1016": "sciencedirect",  # Elsevier
    "10.1007": "springer",  # Springer
    "10.1111": "wiley",  # Wiley
    "10.1002": "wiley",  # Wiley
    "10.1080": "tandfonline",  # Taylor & Francis
    "10.4324": "tandfonline",  # Routledge (T&F)
    "10.1177": "sagepub",  # SAGE
    "10.3390": "mdpi",  # MDPI (OA)
}


def _doi_to_pii(doi: str) -> str:
    """尝试从 DOI 推断 ScienceDirect PII.

    PII 格式: SXXXXXXXXXXYYYYY (S + 18 chars)
    这不是精确转换，仅作为 fallback。
    实际 PII 需从 ScienceDirect 页面或 API 获取。

    Args:
        doi: DOI 字符串.

    Returns:
        推断的 PII 字符串.
    """
    # 移除 DOI 前缀和特殊字符
    clean = re.sub(r"[^a-zA-Z0-9]", "", doi)
    # 填充到 18 字符
    padded = clean[:18].ljust(18, "0")
    return f"S{padded}"


def _get_publisher_from_doi(doi: str) -> str:
    """根据 DOI 前缀识别出版商.

    Args:
        doi: DOI 字符串.

    Returns:
        出版商名称（匹配 PUBLISHER_PDF_URLS 的 key），未知返回空字符串.
    """
    if not doi:
        return ""

    for prefix, publisher in DOI_PREFIX_TO_PUBLISHER.items():
        if doi.startswith(prefix):
            return publisher

    return ""


# ===== OA 源下载器 =====

class UnpaywallClient:
    """Unpaywall API 客户端.

    Unpaywall 是免费 API，查找论文的 OA 版本（预印本、作者自存档、出版商 OA 等）。
    无需 VPN，无需 API Key（仅需邮箱用于 polite pool）。

    API: https://api.unpaywall.org/v2/{DOI}?email={email}
    """

    BASE_URL = "https://api.unpaywall.org/v2"

    def __init__(self, email: str = "scholarpilot@example.com", timeout: int = 15) -> None:
        """初始化 Unpaywall 客户端.

        Args:
            email: 邮箱地址（Unpaywall 要求提供，用于 polite pool）.
            timeout: 请求超时秒数.
        """
        self.email = email
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            configure_no_proxy()
            self._session = aiohttp.ClientSession(trust_env=False)
        return self._session

    async def find_oa_pdf(self, doi: str) -> dict[str, Any]:
        """查找 DOI 对应的 OA PDF URL.

        Args:
            doi: 论文 DOI.

        Returns:
            包含 oa_pdf_url, oa_status, host_type 等信息的字典.
            如果未找到 OA 版本，oa_pdf_url 为空字符串.
        """
        if not doi:
            return {"oa_pdf_url": "", "oa_status": "", "error": "No DOI provided"}

        session = await self._get_session()
        url = f"{self.BASE_URL}/{doi}"
        params = {"email": self.email}

        try:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status == 404:
                    return {"oa_pdf_url": "", "oa_status": "not_found", "error": "DOI not in Unpaywall"}
                if resp.status == 429:
                    return {"oa_pdf_url": "", "oa_status": "rate_limited", "error": "Rate limited"}
                resp.raise_for_status()

                data = await resp.json()
                oa_status = data.get("oa_status", "unknown")
                best_oa = data.get("best_oa_location", {})

                pdf_url = best_oa.get("url_for_pdf", "") if best_oa else ""
                # 如果没有直接 PDF URL，尝试 landing page
                if not pdf_url and best_oa:
                    pdf_url = best_oa.get("url", "")

                host_type = best_oa.get("host_type", "") if best_oa else ""

                return {
                    "oa_pdf_url": pdf_url,
                    "oa_status": oa_status,
                    "host_type": host_type,
                    "title": data.get("title", ""),
                    "journal": data.get("journal_name", ""),
                    "year": data.get("year", ""),
                }

        except asyncio.TimeoutError:
            return {"oa_pdf_url": "", "oa_status": "", "error": "Timeout"}
        except Exception as e:
            logger.debug(f"Unpaywall lookup failed for {doi}: {e}")
            return {"oa_pdf_url": "", "oa_status": "", "error": str(e)}

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# ===== HTTP 下载器 =====

class HTTPDownloader:
    """通用 HTTP PDF 下载器.

    处理实际的 HTTP 请求和文件保存。
    支持 Cookie、自定义 Headers、重试和进度跟踪。
    """

    # PDF 文件魔数（前几字节）
    PDF_MAGIC = b"%PDF-"

    def __init__(self, timeout: int = 60, max_retries: int = 2) -> None:
        """初始化 HTTP 下载器.

        Args:
            timeout: 下载超时秒数（大文件可能需要较长时间）.
            max_retries: 最大重试次数.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            configure_no_proxy()
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/144.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            self._session = aiohttp.ClientSession(
                trust_env=False,
                headers=headers,
            )
        return self._session

    async def download(
        self,
        url: str,
        output_path: Path,
        referer: str = "",
        cookies: dict[str, str] | None = None,
    ) -> tuple[bool, int, str]:
        """下载 PDF 文件.

        Args:
            url: PDF 下载 URL.
            output_path: 输出文件路径.
            referer: Referer 头（部分出版商需要）.
            cookies: Cookie 字典（可选）.

        Returns:
            (success, file_size, error_message).
        """
        if not url:
            return False, 0, "Empty URL"

        session = await self._get_session()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                headers: dict[str, str] = {}
                if referer:
                    headers["Referer"] = referer

                async with session.get(
                    url,
                    headers=headers,
                    cookies=cookies,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=True,
                ) as resp:
                    if resp.status == 429:
                        wait = 5 * (attempt + 1)
                        logger.warning(f"Rate limited (429), waiting {wait}s")
                        if attempt < self.max_retries:
                            await asyncio.sleep(wait)
                            continue
                        return False, 0, "Rate limited"

                    if resp.status == 403:
                        return False, 0, "Forbidden (可能需要 VPN 机构认证或 Shibboleth 登录)"

                    if resp.status == 404:
                        return False, 0, "PDF not found"

                    resp.raise_for_status()

                    # 检查 Content-Type
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "pdf" not in content_type and "octet-stream" not in content_type:
                        # 可能返回了 HTML 页面（登录页/错误页）
                        text = await resp.text()
                        if "login" in text.lower() or "sign in" in text.lower():
                            return False, 0, "Redirected to login page (需要机构认证)"
                        return False, 0, f"Unexpected Content-Type: {content_type}"

                    # 读取内容并验证 PDF 魔数
                    content = await resp.read()
                    if not content.startswith(self.PDF_MAGIC):
                        # 可能是 HTML 或其他格式
                        if content[:1] == b"<":
                            return False, 0, "Response is HTML, not PDF (可能需要认证)"
                        return False, 0, "Invalid PDF format"

                    # 写入文件
                    output_path.write_bytes(content)
                    file_size = len(content)

                    logger.info(
                        f"Downloaded PDF: {output_path.name} "
                        f"({file_size / 1024:.0f} KB) from {url[:80]}"
                    )
                    return True, file_size, ""

            except asyncio.TimeoutError:
                last_error = "Download timeout"
                logger.warning(f"Download timeout (attempt {attempt + 1}): {url[:80]}")
                if attempt < self.max_retries:
                    await asyncio.sleep(3 * (attempt + 1))
            except aiohttp.ClientError as e:
                last_error = f"HTTP client error: {e}"
                logger.warning(f"Download error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(3 * (attempt + 1))
            except Exception as e:
                last_error = str(e)
                logger.error(f"Download failed: {e}")
                break

        return False, 0, last_error

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# ===== 统一 PDF 下载管理器 =====

class PDFDownloadManager:
    """统一 PDF 下载管理器.

    整合多源下载能力，按优先级尝试：
    1. OA 源（无需 VPN）: arXiv → Unpaywall
    2. VPN 机构源（需 EasyConnect 已连接）: 出版商直接下载
    3. DOI 直接解析

    VPN 检测流程:
    - 下载前自动检测 EasyConnect VPN 连通性
    - VPN 未连接时，跳过付费源（ScienceDirect/Springer/Wiley 等）
    - 仅尝试 OA 源下载
    - 提示用户需通过 EasyConnect 登录 VPN

    Usage:
        manager = PDFDownloadManager()
        result = await manager.download(
            doi="10.1016/j.jfineco.2023.01.001",
            title="Fiscal policy and economic growth",
            output_dir="./downloads",
        )
    """

    def __init__(
        self,
        output_dir: str | Path = "./downloads",
        timeout: int = 60,
        max_concurrent: int = 2,
        unpaywall_email: str = "scholarpilot@example.com",
    ) -> None:
        """初始化 PDF 下载管理器.

        Args:
            output_dir: 默认下载目录.
            timeout: 单次下载超时秒数.
            max_concurrent: 最大并发下载数.
            unpaywall_email: Unpaywall API 邮箱.
        """
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # 子模块
        self.http_downloader = HTTPDownloader(timeout=timeout)
        self.unpaywall = UnpaywallClient(email=unpaywall_email, timeout=15)

        # VPN 状态缓存
        self._vpn_status: VPNStatus | None = None
        self._vpn_check_time: float = 0.0
        self._vpn_cache_ttl: float = 120.0  # VPN 状态缓存 2 分钟

    async def _ensure_vpn_status(self, force_check: bool = False) -> VPNStatus:
        """获取 VPN 状态（带缓存）.

        Args:
            force_check: 是否强制重新检测.

        Returns:
            VPNStatus: VPN 连接状态.
        """
        if (
            not force_check
            and self._vpn_status
            and (time.time() - self._vpn_check_time) < self._vpn_cache_ttl
        ):
            return self._vpn_status

        detector = get_vpn_detector()
        self._vpn_status = await detector.check_vpn()
        self._vpn_check_time = time.time()

        if not self._vpn_status.connected:
            logger.warning(
                "VPN not connected. Paid source downloads will be skipped. "
                "请通过 EasyConnect 登录 VPN 以访问付费数据库全文资源。"
            )

        return self._vpn_status

    def _sanitize_filename(self, title: str, doi: str = "") -> str:
        """生成安全的文件名.

        Args:
            title: 论文标题.
            doi: DOI（作为 fallback）.

        Returns:
            安全的文件名（不含扩展名）.
        """
        if title:
            # 保留中英文字符、数字、连字符
            safe = re.sub(r'[<>:"/\\|?*\n\r\t]', "", title)
            safe = safe.strip()[:100]  # 限制长度
            if safe:
                return safe

        if doi:
            return doi.replace("/", "_").replace("\\", "_")

        return f"paper_{int(time.time())}"

    async def _try_arxiv(self, doi: str, arxiv_id: str, output_path: Path) -> DownloadResult:
        """尝试从 arXiv 下载 PDF（免费，无需 VPN）.

        Args:
            doi: 论文 DOI.
            arxiv_id: arXiv ID（如 "2301.00001"）.
            output_path: 输出路径.

        Returns:
            DownloadResult: 下载结果.
        """
        start_time = time.monotonic()
        result = DownloadResult(
            source=PDFDownloadSource.ARXIV,
            doi=doi,
            vpn_required=False,
        )

        if not arxiv_id:
            result.status = DownloadStatus.NOT_FOUND
            result.error = "No arXiv ID"
            return result

        # arXiv PDF URL
        # 处理旧式 ID（如 math/0701234）和新式 ID（如 2301.00001）
        if "/" in arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        else:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        success, size, error = await self.http_downloader.download(pdf_url, output_path)

        result.url = pdf_url
        result.download_time = time.monotonic() - start_time
        if success:
            result.status = DownloadStatus.SUCCESS
            result.file_path = str(output_path)
            result.file_size = size
        else:
            result.status = DownloadStatus.FAILED
            result.error = error

        return result

    async def _try_unpaywall(self, doi: str, output_path: Path) -> DownloadResult:
        """通过 Unpaywall 查找并下载 OA PDF（免费，无需 VPN）.

        Args:
            doi: 论文 DOI.
            output_path: 输出路径.

        Returns:
            DownloadResult: 下载结果.
        """
        start_time = time.monotonic()
        result = DownloadResult(
            source=PDFDownloadSource.UNPAYWALL,
            doi=doi,
            vpn_required=False,
        )

        if not doi:
            result.status = DownloadStatus.NOT_FOUND
            result.error = "No DOI for Unpaywall lookup"
            return result

        # 查找 OA PDF URL
        oa_info = await self.unpaywall.find_oa_pdf(doi)
        pdf_url = oa_info.get("oa_pdf_url", "")

        if not pdf_url:
            result.status = DownloadStatus.NOT_FOUND
            result.error = oa_info.get("error", "No OA version found")
            result.download_time = time.monotonic() - start_time
            return result

        # 下载
        success, size, error = await self.http_downloader.download(pdf_url, output_path)

        result.url = pdf_url
        result.download_time = time.monotonic() - start_time
        if success:
            result.status = DownloadStatus.SUCCESS
            result.file_path = str(output_path)
            result.file_size = size
        else:
            result.status = DownloadStatus.FAILED
            result.error = error

        return result

    async def _try_publisher(
        self,
        doi: str,
        output_path: Path,
        vpn_status: VPNStatus,
    ) -> DownloadResult:
        """尝试从出版商网站下载 PDF（需 VPN 机构 IP 认证）.

        Args:
            doi: 论文 DOI.
            output_path: 输出路径.
            vpn_status: VPN 连接状态.

        Returns:
            DownloadResult: 下载结果.
        """
        start_time = time.monotonic()
        result = DownloadResult(
            doi=doi,
            vpn_required=True,
            vpn_used=vpn_status.connected,
        )

        if not vpn_status.connected:
            result.status = DownloadStatus.SKIPPED
            result.error = "VPN 未连接，跳过付费源下载。请通过 EasyConnect 登录 VPN。"
            result.download_time = time.monotonic() - start_time
            return result

        if not doi:
            result.status = DownloadStatus.NOT_FOUND
            result.error = "No DOI for publisher download"
            result.download_time = time.monotonic() - start_time
            return result

        # 识别出版商
        publisher = _get_publisher_from_doi(doi)
        if not publisher:
            result.status = DownloadStatus.NOT_FOUND
            result.source = PDFDownloadSource.UNKNOWN
            result.error = f"Unknown publisher for DOI: {doi}"
            result.download_time = time.monotonic() - start_time
            return result

        config = PUBLISHER_PDF_URLS.get(publisher, {})
        pdf_url_builder = config.get("doi_to_pdf")
        needs_vpn = config.get("needs_vpn", True)

        # 如果出版商不需要 VPN（如 MDPI OA），直接下载
        if needs_vpn and not vpn_status.connected:
            result.status = DownloadStatus.SKIPPED
            result.error = "VPN 未连接"
            result.download_time = time.monotonic() - start_time
            return result

        if not pdf_url_builder:
            result.status = DownloadStatus.NOT_FOUND
            result.error = f"No PDF URL builder for {publisher}"
            result.download_time = time.monotonic() - start_time
            return result

        # 设置来源
        source_map = {
            "sciencedirect": PDFDownloadSource.SCIENCEDIRECT,
            "springer": PDFDownloadSource.SPRINGER,
            "wiley": PDFDownloadSource.WILEY,
            "tandfonline": PDFDownloadSource.UNKNOWN,
            "sagepub": PDFDownloadSource.UNKNOWN,
            "mdpi": PDFDownloadSource.UNKNOWN,
        }
        result.source = source_map.get(publisher, PDFDownloadSource.UNKNOWN)

        # 构建 PDF URL
        try:
            pdf_url = pdf_url_builder(doi)
        except Exception as e:
            result.status = DownloadStatus.FAILED
            result.error = f"Failed to build PDF URL: {e}"
            result.download_time = time.monotonic() - start_time
            return result

        # 构建 Referer（部分出版商需要）
        referer = ""
        if publisher == "sciencedirect":
            referer = f"https://www.sciencedirect.com/science/article/pii/{_doi_to_pii(doi)}"
        elif publisher == "springer":
            referer = f"https://link.springer.com/article/{doi}"
        elif publisher == "wiley":
            referer = f"https://onlinelibrary.wiley.com/doi/{doi}"

        # 下载
        success, size, error = await self.http_downloader.download(
            pdf_url, output_path, referer=referer,
        )

        result.url = pdf_url
        result.download_time = time.monotonic() - start_time
        if success:
            result.status = DownloadStatus.SUCCESS
            result.file_path = str(output_path)
            result.file_size = size
        else:
            result.status = DownloadStatus.FAILED
            result.error = error

        return result

    async def _try_doi_direct(self, doi: str, output_path: Path) -> DownloadResult:
        """尝试通过 doi.org 直接解析并下载.

        doi.org 会重定向到出版商页面，可能直接获得 PDF。
        成功率较低，作为最后手段。

        Args:
            doi: 论文 DOI.
            output_path: 输出路径.

        Returns:
            DownloadResult: 下载结果.
        """
        start_time = time.monotonic()
        result = DownloadResult(
            source=PDFDownloadSource.DOI_DIRECT,
            doi=doi,
            vpn_required=False,  # 取决于重定向目标
        )

        if not doi:
            result.status = DownloadStatus.NOT_FOUND
            result.error = "No DOI"
            return result

        url = f"https://doi.org/{doi}"

        success, size, error = await self.http_downloader.download(url, output_path)

        result.url = url
        result.download_time = time.monotonic() - start_time
        if success:
            result.status = DownloadStatus.SUCCESS
            result.file_path = str(output_path)
            result.file_size = size
        else:
            result.status = DownloadStatus.FAILED
            result.error = error

        return result

    async def download(
        self,
        doi: str = "",
        title: str = "",
        arxiv_id: str = "",
        output_dir: str | Path | None = None,
        check_vpn: bool = True,
    ) -> DownloadResult:
        """下载单篇论文 PDF.

        按优先级尝试多个下载源:
        1. arXiv（如有 arXiv ID，免费）
        2. Unpaywall OA 查找（免费）
        3. 出版商直接下载（需 VPN）
        4. DOI 直接解析（最后手段）

        Args:
            doi: 论文 DOI.
            title: 论文标题（用于文件命名）.
            arxiv_id: arXiv ID（如有）.
            output_dir: 输出目录（默认使用 self.output_dir）.
            check_vpn: 是否在下载前检测 VPN.

        Returns:
            DownloadResult: 下载结果.
        """
        out_dir = Path(output_dir) if output_dir else self.output_dir
        filename = self._sanitize_filename(title, doi)
        output_path = out_dir / f"{filename}.pdf"

        # 如果文件已存在，跳过
        if output_path.exists() and output_path.stat().st_size > 1024:
            logger.info(f"PDF already exists: {output_path}")
            return DownloadResult(
                source=PDFDownloadSource.UNKNOWN,
                status=DownloadStatus.SUCCESS,
                file_path=str(output_path),
                file_size=output_path.stat().st_size,
                doi=doi,
                title=title,
                error="File already exists (skipped download)",
            )

        # VPN 状态检测
        vpn_status = VPNStatus()
        if check_vpn:
            vpn_status = await self._ensure_vpn_status()

        async with self._semaphore:
            # 策略 1: arXiv（免费，无需 VPN）
            if arxiv_id:
                logger.info(f"Trying arXiv download: {arxiv_id}")
                result = await self._try_arxiv(doi, arxiv_id, output_path)
                if result.success:
                    result.title = title
                    return result

            # 策略 2: Unpaywall OA 查找（免费，无需 VPN）
            if doi:
                logger.info(f"Trying Unpaywall OA lookup: {doi}")
                result = await self._try_unpaywall(doi, output_path)
                if result.success:
                    result.title = title
                    return result

            # 策略 3: 出版商直接下载（需 VPN 机构 IP）
            if doi:
                logger.info(f"Trying publisher download: {doi}")
                result = await self._try_publisher(doi, output_path, vpn_status)
                if result.success:
                    result.title = title
                    return result

            # 策略 4: DOI 直接解析（最后手段）
            if doi:
                logger.info(f"Trying DOI direct resolution: {doi}")
                result = await self._try_doi_direct(doi, output_path)
                if result.success:
                    result.title = title
                    return result

        # 所有策略都失败
        return DownloadResult(
            doi=doi,
            title=title,
            status=DownloadStatus.FAILED,
            error="All download strategies failed. "
                  "如需下载付费全文，请确保已通过 EasyConnect 登录 VPN。",
            vpn_required=True,
            vpn_used=vpn_status.connected,
        )

    async def download_batch(
        self,
        papers: list[dict[str, Any]],
        output_dir: str | Path | None = None,
        check_vpn: bool = True,
    ) -> BatchDownloadResult:
        """批量下载论文 PDF.

        Args:
            papers: 论文列表，每项含 doi, title, arxiv_id 等字段.
            output_dir: 输出目录.
            check_vpn: 是否在下载前检测 VPN.

        Returns:
            BatchDownloadResult: 批量下载结果.
        """
        batch_start = time.monotonic()
        out_dir = Path(output_dir) if output_dir else self.output_dir

        # VPN 状态检测（批量下载只检测一次）
        vpn_status = VPNStatus()
        if check_vpn:
            vpn_status = await self._ensure_vpn_status()
            if not vpn_status.connected:
                logger.warning(
                    "VPN 未连接，仅尝试 OA 源下载。"
                    "请通过 EasyConnect 登录 VPN 以访问付费数据库全文资源。"
                )

        # 并发下载（受 max_concurrent 限制）
        tasks = []
        for paper in papers:
            task = self.download(
                doi=paper.get("doi", ""),
                title=paper.get("title", ""),
                arxiv_id=paper.get("arxiv_id", ""),
                output_dir=out_dir,
                check_vpn=False,  # 已在批量层面检测
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总结果
        batch = BatchDownloadResult(total=len(papers))
        for res in results:
            if isinstance(res, Exception):
                batch.results.append(DownloadResult(
                    status=DownloadStatus.FAILED,
                    error=str(res),
                ))
                batch.failed_count += 1
            elif isinstance(res, DownloadResult):
                batch.results.append(res)
                if res.success:
                    batch.success_count += 1
                    batch.total_size += res.file_size
                elif res.status == DownloadStatus.SKIPPED:
                    batch.skipped_count += 1
                else:
                    batch.failed_count += 1

        batch.total_time = time.monotonic() - batch_start
        logger.info(
            f"Batch download complete: {batch.success_count}/{batch.total} success, "
            f"{batch.failed_count} failed, {batch.skipped_count} skipped (VPN), "
            f"{batch.total_size / 1024 / 1024:.1f} MB total, "
            f"{batch.total_time:.1f}s"
        )

        return batch

    async def close(self) -> None:
        """关闭所有子模块."""
        await self.http_downloader.close()
        await self.unpaywall.close()


# ===== 便捷函数 =====

_pdf_manager: PDFDownloadManager | None = None


def get_pdf_manager(
    output_dir: str | Path = "./downloads",
) -> PDFDownloadManager:
    """获取全局 PDF 下载管理器单例.

    Args:
        output_dir: 下载目录.

    Returns:
        PDFDownloadManager 实例.
    """
    global _pdf_manager
    if _pdf_manager is None:
        _pdf_manager = PDFDownloadManager(output_dir=output_dir)
    return _pdf_manager


async def download_paper_pdf(
    doi: str = "",
    title: str = "",
    arxiv_id: str = "",
    output_dir: str | Path = "./downloads",
) -> DownloadResult:
    """便捷函数: 下载单篇论文 PDF.

    Args:
        doi: 论文 DOI.
        title: 论文标题.
        arxiv_id: arXiv ID（如有）.
        output_dir: 输出目录.

    Returns:
        DownloadResult: 下载结果.
    """
    manager = get_pdf_manager(output_dir)
    return await manager.download(doi=doi, title=title, arxiv_id=arxiv_id)
