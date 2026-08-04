"""NCPSSD 全文 PDF 下载器.

国家哲学社会科学文献中心（NCPSSD, ncpssd.org）是由中国社会科学院牵头建设的
免费学术文献资源平台，收录 10,000,000+ 篇中文学术论文，完全免费开放获取，
无需登录或 API Key。

本模块负责从 NCPSSD 下载论文全文 PDF 并转换为纯文本，用于构建优秀论文
知识库（写作规范、引用模式、语言特征分析）。

下载流程:
    1. 从检索结果中获取论文详情页 URL（含 encryptedUrl 参数）
       格式: https://www.ncpssd.org/Literature/secure/articleinfo?params={encryptedUrl}
    2. GET 详情页 HTML，解析其中的 PDF 下载链接
       常见模式: /Literature/secure/downloadPDF, downloadPDF, readDownloadUrl 等
    3. 下载 PDF 文件到 ~/.scholarpilot/benchmark/pdfs/
    4. 使用 PyPDF2（主）或 pdfplumber（备）将 PDF 转为纯文本
    5. 文本存储到 ~/.scholarpilot/benchmark/fulltext/

NCPSSD SSL 说明:
    NCPSSD 可能使用自签名或链不完整的 SSL 证书，因此下载时需禁用 SSL 验证
    (verify=False)。同时通过 configure_no_proxy() 确保请求绕过系统代理直连。

Usage:
    downloader = FullTextDownloader()
    text = await downloader.download_paper({
        "title": "地方政府债务对经济增长的影响",
        "url": "https://www.ncpssd.org/Literature/secure/articleinfo?params=abc123",
        "source": "ncpssd",
    })
    if text:
        print(f"全文长度: {len(text)} 字符")

    # 批量下载
    stats = await downloader.download_batch(papers, max_papers=200)
    print(f"成功: {stats['success']}, 失败: {stats['failed']}")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)


# ===== PDF 文本提取库的可选导入 =====
# 主选 PyPDF2，备选 pdfplumber，兜底 PyMuPDF（项目已安装）

_PYPDF2_AVAILABLE = False
_PDFPLUMBER_AVAILABLE = False
_FITZ_AVAILABLE = False

try:
    from PyPDF2 import PdfReader as _PyPDF2Reader
    _PYPDF2_AVAILABLE = True
except ImportError:
    pass

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    pass

try:
    import fitz as _fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    pass


# ===== 常量 =====

# NCPSSD 基础 URL
NCPSSD_BASE_URL = "https://www.ncpssd.org"

# NCPSSD 文章详情页 URL 模板
NCPSSD_ARTICLE_INFO_URL = "https://www.ncpssd.org/Literature/secure/articleinfo"

# NCPSSD PDF 下载相关的 URL 路径模式（用于 HTML 解析时匹配）
PDF_URL_PATTERNS = [
    r"/Literature/secure/downloadPDF",
    r"/Literature/secure/download",
    r"/Literature/downloadPDF",
    r"/Literature/attachmentDownload",
    r"/Literature/fullTextRead",
    r"/Literature/readDownloadUrl",
]

# PDF 文件魔数
PDF_MAGIC = b"%PDF-"

# 默认存储根目录
DEFAULT_STORAGE_DIR = Path.home() / ".scholarpilot" / "benchmark"

# User-Agent 池（模拟浏览器访问）
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
    "Gecko/20100101 Firefox/123.0",
]


class FullTextDownloader:
    """NCPSSD 全文 PDF 下载器.

    从国家哲学社会科学文献中心下载论文全文 PDF 并转换为纯文本。
    NCPSSD 完全免费开放，无需登录认证。

    下载策略:
        1. 访问文章详情页（articleinfo），解析 HTML 获取 PDF 下载链接
        2. 如果 HTML 中无直接链接，尝试调用 readDownloadUrl AJAX 接口
        3. 下载 PDF 二进制数据
        4. 使用 PyPDF2 / pdfplumber / PyMuPDF 将 PDF 转为文本

    存储结构:
        storage_dir/
        ├── pdfs/        # 原始 PDF 文件
        │   └── {paper_id}.pdf
        └── fulltext/    # 提取的纯文本
            └── {paper_id}.txt

    Attributes:
        storage_dir: 存储根目录，默认 ~/.scholarpilot/benchmark/.
        pdf_dir: PDF 文件存储目录.
        text_dir: 文本文件存储目录.
        timeout: HTTP 请求超时秒数.
        min_delay: 下载间最小延迟（秒）.
        max_delay: 下载间最大延迟（秒）.
    """

    def __init__(
        self,
        storage_dir: Path | None = None,
        timeout: int = 60,
    ) -> None:
        """初始化全文下载器.

        Args:
            storage_dir: 存储根目录。默认为 ~/.scholarpilot/benchmark/.
                         PDF 存储在 {storage_dir}/pdfs/，
                         文本存储在 {storage_dir}/fulltext/.
            timeout: HTTP 请求超时秒数（大 PDF 可能需要较长时间）.
        """
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.pdf_dir = self.storage_dir / "pdfs"
        self.text_dir = self.storage_dir / "fulltext"
        self.timeout = timeout

        # 速率限制参数（1-2 秒随机延迟）
        self.min_delay = 1.0
        self.max_delay = 2.0

        # 确保目录存在
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.text_dir.mkdir(parents=True, exist_ok=True)

        # HTTP 客户端（延迟初始化）
        self._client: httpx.AsyncClient | None = None

        # 检查可用的 PDF 解析库
        if not any([_PYPDF2_AVAILABLE, _PDFPLUMBER_AVAILABLE, _FITZ_AVAILABLE]):
            logger.warning(
                "未找到任何 PDF 解析库（PyPDF2 / pdfplumber / PyMuPDF）。"
                "请安装至少一个：pip install PyPDF2 或 pip install pdfplumber 或 pip install PyMuPDF"
            )
        else:
            libs = []
            if _PYPDF2_AVAILABLE:
                libs.append("PyPDF2(主)")
            if _PDFPLUMBER_AVAILABLE:
                libs.append("pdfplumber(备)")
            if _FITZ_AVAILABLE:
                libs.append("PyMuPDF(兜底)")
            logger.debug(f"PDF 解析库可用: {', '.join(libs)}")

    # ===== HTTP 客户端管理 =====

    def _get_random_ua(self) -> str:
        """随机选择 User-Agent."""
        return random.choice(_USER_AGENTS)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 异步客户端.

        客户端配置:
            - trust_env=False: 不读取系统代理环境变量
            - proxy=None: 不使用代理
            - follow_redirects=True: 自动跟随重定向
            - verify=False: 禁用 SSL 证书验证（NCPSSD 证书可能不完整）

        Returns:
            httpx.AsyncClient 实例.
        """
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self._get_random_ua(),
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,application/pdf,*/*;q=0.8"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                },
                timeout=httpx.Timeout(self.timeout, connect=15.0),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
                verify=False,
            )
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端，释放资源."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ===== Paper ID 生成 =====

    @staticmethod
    def _get_paper_id(paper: dict[str, Any]) -> str:
        """从论文字典生成唯一且稳定的 paper_id.

        优先使用 NCPSSD 详情页 URL 中的 encryptedUrl 参数作为 ID，
        因为它是每篇论文的唯一标识。如果没有 URL，则使用标题的 MD5 哈希。

        Args:
            paper: 论文字典，应包含 url 或 title 字段.

        Returns:
            稳定的 paper_id 字符串（仅含字母数字和下划线）.
        """
        # 优先从 URL 提取 encryptedUrl 参数
        url = paper.get("url", "")
        if url:
            # 从 articleinfo?params=xxx 中提取 params 值
            match = re.search(r"[?&]params=([^&]+)", url)
            if match:
                raw_id = match.group(1)
                # 清理为安全的文件名
                safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", raw_id)
                if safe_id:
                    return f"ncpssd_{safe_id[:80]}"

            # 如果 URL 中没有 params，使用 URL 路径部分
            parsed = urlsplit(url)
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                raw_id = "_".join(path_parts)
                safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", raw_id)
                if safe_id:
                    return f"ncpssd_{safe_id[:80]}"

        # 使用标题哈希作为兜底
        title = paper.get("title", "")
        if title:
            title_hash = hashlib.md5(title.encode("utf-8")).hexdigest()[:16]
            return f"ncpssd_{title_hash}"

        # 最终兜底
        return f"ncpssd_{int(time.time())}"

    # ===== 全文存储与检索 =====

    def _pdf_path(self, paper_id: str) -> Path:
        """获取 paper_id 对应的 PDF 文件路径."""
        return self.pdf_dir / f"{paper_id}.pdf"

    def _text_path(self, paper_id: str) -> Path:
        """获取 paper_id 对应的文本文件路径."""
        return self.text_dir / f"{paper_id}.txt"

    def has_fulltext(self, paper_id: str) -> bool:
        """检查指定论文的全文文本是否已存在.

        Args:
            paper_id: 论文唯一标识.

        Returns:
            True 如果文本文件已存在且非空.
        """
        text_path = self._text_path(paper_id)
        return text_path.exists() and text_path.stat().st_size > 0

    def get_fulltext(self, paper_id: str) -> str | None:
        """读取已存储的全文文本.

        Args:
            paper_id: 论文唯一标识.

        Returns:
            全文文本内容，如果文件不存在则返回 None.
        """
        text_path = self._text_path(paper_id)
        if not text_path.exists():
            return None
        try:
            return text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"读取全文文本失败 {paper_id}: {e}")
            return None

    # ===== HTML 解析：提取 PDF 下载链接 =====

    def _extract_pdf_url(self, html: str, base_url: str) -> str | None:
        """从文章详情页 HTML 中解析 PDF 下载链接.

        解析策略（按优先级）:
            1. 查找 <a> 标签中直接包含 PDF 下载关键词的 href
            2. 查找 JavaScript 代码中的 downloadPDF / readDownloadUrl URL
            3. 查找 onclick 事件中的下载逻辑
            4. 查找任何包含 .pdf 或 download 的链接

        Args:
            html: 文章详情页 HTML 内容.
            base_url: 详情页基础 URL（用于拼接相对路径）.

        Returns:
            完整的 PDF 下载 URL，如果未找到则返回 None.
        """
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 策略 1: 查找 <a> 标签中包含 PDF 下载关键词的 href
        pdf_keywords = [
            "downloadPDF", "downloadpdf", "download_pdf",
            "attachmentDownload", "fullTextRead",
            "readDownloadUrl", "download",
        ]

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            href_lower = href.lower()

            # 检查是否是 PDF 下载链接
            if any(kw.lower() in href_lower for kw in pdf_keywords):
                full_url = urljoin(base_url, href)
                logger.debug(f"找到 PDF 下载链接 (<a>): {full_url}")
                return full_url

            # 检查 href 是否直接指向 .pdf 文件
            if href_lower.endswith(".pdf") or ".pdf?" in href_lower:
                full_url = urljoin(base_url, href)
                logger.debug(f"找到 PDF 文件链接 (<a .pdf>): {full_url}")
                return full_url

        # 策略 2: 查找 <a> 标签的 onclick 属性中的下载 URL
        for anchor in soup.find_all("a", onclick=True):
            onclick = anchor["onclick"]
            # 提取 onclick 中的 URL
            url_match = re.search(
                r"['\"]([^'\"]*(?:downloadPDF|attachmentDownload|readDownloadUrl)[^'\"]*)['\"]",
                onclick,
                re.IGNORECASE,
            )
            if url_match:
                extracted = url_match.group(1)
                full_url = urljoin(base_url, extracted)
                logger.debug(f"从 onclick 提取 PDF 下载链接: {full_url}")
                return full_url

        # 策略 3: 从 JavaScript 代码中查找下载 URL
        for script in soup.find_all("script"):
            script_text = script.string or script.get_text()
            if not script_text:
                continue

            # 查找 downloadPDF 相关的 URL
            for pattern in PDF_URL_PATTERNS:
                # 匹配 var url = "/Literature/secure/downloadPDF?params=xxx"
                # 或 window.location = "downloadPDF?..."
                matches = re.findall(
                    r"""['"]([^'"]*""" + re.escape(pattern) + r"""[^'"]*)['"]""",
                    script_text,
                )
                if matches:
                    # 取最后一个匹配（通常是实际使用的 URL）
                    extracted = matches[-1]
                    full_url = urljoin(base_url, extracted)
                    logger.debug(f"从 JavaScript 提取 PDF 下载链接: {full_url}")
                    return full_url

        # 策略 4: 查找所有包含 download 或 pdf 的 URL（更宽松的匹配）
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            href_lower = href.lower()
            if "pdf" in href_lower or "download" in href_lower:
                # 排除导航类链接
                if any(skip in href_lower for skip in ["downloadcount", "download_history"]):
                    continue
                full_url = urljoin(base_url, href)
                logger.debug(f"宽松匹配 PDF 下载链接: {full_url}")
                return full_url

        # 策略 5: 从整个 HTML 文本中正则搜索下载 URL 模式
        for pattern in PDF_URL_PATTERNS:
            matches = re.findall(
                r"""['"]?([^'"\s<>]*""" + re.escape(pattern) + r"""[^'"\s<>]*)['"]?""",
                html,
            )
            if matches:
                extracted = matches[0]
                full_url = urljoin(base_url, extracted)
                logger.debug(f"从 HTML 正则搜索提取 PDF 下载链接: {full_url}")
                return full_url

        logger.debug("未在详情页 HTML 中找到 PDF 下载链接")
        return None

    def _extract_params_from_url(self, url: str) -> str | None:
        """从 NCPSSD URL 中提取 params 参数值.

        Args:
            url: NCPSSD 文章详情页 URL.

        Returns:
            params 参数值，如果不存在则返回 None.
        """
        match = re.search(r"[?&]params=([^&]+)", url)
        if match:
            return match.group(1)
        return None

    def _build_download_url_from_params(self, params: str) -> str:
        """根据 params 参数构建 PDF 下载 URL.

        NCPSSD 的 PDF 下载链接通常使用与详情页相同的 params 参数。
        常见的下载路径包括:
            - /Literature/secure/downloadPDF?params={params}
            - /Literature/readDownloadUrl?params={params}

        Args:
            params: 从详情页 URL 提取的加密参数.

        Returns:
            推测的 PDF 下载 URL.
        """
        return f"{NCPSSD_BASE_URL}/Literature/secure/downloadPDF?params={params}"

    # ===== PDF 下载 =====

    async def _download_pdf(self, pdf_url: str) -> bytes | None:
        """下载 PDF 文件并返回二进制内容.

        执行 HTTP GET 请求下载 PDF，验证响应内容确实是 PDF 格式。

        Args:
            pdf_url: PDF 下载 URL.

        Returns:
            PDF 文件的二进制内容，如果下载失败则返回 None.
        """
        if not pdf_url:
            return None

        client = await self._get_client()

        try:
            response = await client.get(
                pdf_url,
                headers={
                    "Referer": NCPSSD_ARTICLE_INFO_URL,
                    "Accept": "application/pdf,*/*",
                },
            )

            # 处理常见 HTTP 错误
            if response.status_code == 404:
                logger.warning(f"PDF 未找到 (404): {pdf_url[:100]}")
                return None

            if response.status_code == 403:
                logger.warning(f"PDF 下载被拒绝 (403): {pdf_url[:100]}")
                return None

            if response.status_code == 429:
                logger.warning(f"请求过于频繁 (429): {pdf_url[:100]}")
                return None

            response.raise_for_status()

            # 获取响应内容
            content = response.content

            if not content:
                logger.warning(f"PDF 下载响应为空: {pdf_url[:100]}")
                return None

            # 验证是否为 PDF 文件（检查魔数）
            if not content.startswith(PDF_MAGIC):
                # 可能返回了 HTML 页面（错误页/登录页）
                if content[:1] == b"<":
                    # 尝试从 HTML 中再次提取 PDF 链接
                    html_text = content.decode("utf-8", errors="ignore")
                    real_pdf_url = self._extract_pdf_url(html_text, pdf_url)
                    if real_pdf_url and real_pdf_url != pdf_url:
                        logger.info(
                            f"首次响应为 HTML，重定向到 PDF: {real_pdf_url[:100]}"
                        )
                        return await self._download_pdf(real_pdf_url)
                    logger.warning(
                        f"响应为 HTML 而非 PDF: {pdf_url[:100]} "
                        f"(可能是错误页或需要登录)"
                    )
                    return None
                logger.warning(
                    f"响应内容不是有效 PDF（魔数不匹配）: {pdf_url[:100]}"
                )
                return None

            file_size_kb = len(content) / 1024
            logger.info(
                f"PDF 下载成功: {pdf_url[:80]}... ({file_size_kb:.0f} KB)"
            )
            return content

        except httpx.TimeoutException:
            logger.warning(f"PDF 下载超时: {pdf_url[:100]}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"PDF 下载 HTTP 错误 {e.response.status_code}: {pdf_url[:100]}"
            )
            return None
        except httpx.RequestError as e:
            logger.warning(f"PDF 下载网络错误: {e} - {pdf_url[:100]}")
            return None
        except Exception as e:
            logger.error(f"PDF 下载异常: {e} - {pdf_url[:100]}")
            return None

    # ===== PDF 转文本 =====

    def _pdf_to_text(self, pdf_bytes: bytes) -> str:
        """将 PDF 二进制数据转换为纯文本.

        转换策略（按优先级）:
            1. PyPDF2: 轻量级，速度快（主选）
            2. pdfplumber: 对复杂排版支持更好（备选）
            3. PyMuPDF (fitz): 对中文支持最佳（兜底，项目已安装）

        如果所有库都不可用或都返回空文本，返回空字符串。

        Args:
            pdf_bytes: PDF 文件的二进制内容.

        Returns:
            提取的纯文本内容。如果提取失败则返回空字符串.
        """
        if not pdf_bytes or not pdf_bytes.startswith(PDF_MAGIC):
            logger.warning("无效的 PDF 数据，无法提取文本")
            return ""

        text = ""

        # 策略 1: PyPDF2（主选）
        if _PYPDF2_AVAILABLE:
            text = self._extract_with_pypdf2(pdf_bytes)
            if text.strip():
                logger.debug(f"PyPDF2 提取成功: {len(text)} 字符")
                return text
            logger.debug("PyPDF2 提取结果为空，尝试备选方案")

        # 策略 2: pdfplumber（备选）
        if _PDFPLUMBER_AVAILABLE:
            text = self._extract_with_pdfplumber(pdf_bytes)
            if text.strip():
                logger.debug(f"pdfplumber 提取成功: {len(text)} 字符")
                return text
            logger.debug("pdfplumber 提取结果为空，尝试兜底方案")

        # 策略 3: PyMuPDF / fitz（兜底）
        if _FITZ_AVAILABLE:
            text = self._extract_with_fitz(pdf_bytes)
            if text.strip():
                logger.debug(f"PyMuPDF 提取成功: {len(text)} 字符")
                return text
            logger.debug("PyMuPDF 提取结果为空")

        if not text.strip():
            logger.warning(
                "所有 PDF 解析库均未能提取文本（可能是扫描版 PDF 或加密 PDF）"
            )

        return text

    @staticmethod
    def _extract_with_pypdf2(pdf_bytes: bytes) -> str:
        """使用 PyPDF2 提取 PDF 文本.

        Args:
            pdf_bytes: PDF 二进制数据.

        Returns:
            提取的文本内容.
        """
        try:
            import io
            reader = _PyPDF2Reader(io.BytesIO(pdf_bytes))
            text_parts: list[str] = []

            for page in reader.pages:
                try:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                except Exception as e:
                    logger.debug(f"PyPDF2 页面提取异常: {e}")
                    continue

            return "\n\n".join(text_parts)
        except Exception as e:
            logger.debug(f"PyPDF2 提取失败: {e}")
            return ""

    @staticmethod
    def _extract_with_pdfplumber(pdf_bytes: bytes) -> str:
        """使用 pdfplumber 提取 PDF 文本.

        pdfplumber 对复杂排版和表格的文本提取效果优于 PyPDF2。

        Args:
            pdf_bytes: PDF 二进制数据.

        Returns:
            提取的文本内容.
        """
        try:
            import io
            text_parts: list[str] = []
            with _pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    try:
                        page_text = page.extract_text() or ""
                        text_parts.append(page_text)
                    except Exception as e:
                        logger.debug(f"pdfplumber 页面提取异常: {e}")
                        continue
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.debug(f"pdfplumber 提取失败: {e}")
            return ""

    @staticmethod
    def _extract_with_fitz(pdf_bytes: bytes) -> str:
        """使用 PyMuPDF (fitz) 提取 PDF 文本.

        PyMuPDF 对中文 PDF 的文本提取效果最佳，且性能优异。

        Args:
            pdf_bytes: PDF 二进制数据.

        Returns:
            提取的文本内容.
        """
        try:
            import io
            text_parts: list[str] = []
            doc = _fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
            for page in doc:
                try:
                    page_text = page.get_text("text") or ""
                    text_parts.append(page_text)
                except Exception as e:
                    logger.debug(f"PyMuPDF 页面提取异常: {e}")
                    continue
            doc.close()
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.debug(f"PyMuPDF 提取失败: {e}")
            return ""

    # ===== 核心下载方法 =====

    async def download_paper(self, paper: dict[str, Any]) -> str | None:
        """下载单篇论文的全文并返回文本内容.

        下载流程:
            1. 生成 paper_id，检查是否已有缓存的全文文本
            2. 获取文章详情页 URL（从 paper["url"] 或构建）
            3. GET 详情页 HTML，解析 PDF 下载链接
            4. 如果 HTML 中未找到链接，尝试从 params 构建下载 URL
            5. 下载 PDF 二进制数据
            6. 将 PDF 转为文本并保存
            7. 应用速率限制延迟

        Args:
            paper: 论文字典，应包含以下字段:
                - url: NCPSSD 详情页 URL（必需，含 params 参数）
                - title: 论文标题（用于日志和兜底 ID 生成）
                - source: 数据来源（应为 "ncpssd"）

        Returns:
            全文文本内容，如果下载或转换失败则返回 None.
        """
        paper_id = self._get_paper_id(paper)
        title = paper.get("title", "")
        url = paper.get("url", "")

        # 检查缓存：如果文本已存在，直接返回
        if self.has_fulltext(paper_id):
            logger.debug(f"全文已缓存，跳过下载: {paper_id}")
            return self.get_fulltext(paper_id)

        # 检查 URL 是否有效
        if not url:
            logger.warning(f"论文缺少 URL，无法下载: {title[:50]}")
            return None

        # 仅处理 NCPSSD 来源的论文
        source = paper.get("source", "")
        if source and source != "ncpssd":
            logger.debug(
                f"非 NCPSSD 来源 (source={source})，跳过: {title[:50]}"
            )
            return None

        logger.info(f"开始下载全文: {title[:60]} (ID: {paper_id})")

        client = await self._get_client()

        # 步骤 1: GET 文章详情页
        try:
            response = await client.get(
                url,
                headers={
                    "Referer": NCPSSD_BASE_URL,
                    "Accept": "text/html,application/xhtml+xml,*/*",
                },
            )

            if response.status_code == 404:
                logger.warning(f"文章详情页不存在 (404): {url[:100]}")
                return None

            if response.status_code == 403:
                logger.warning(f"文章详情页访问被拒 (403): {url[:100]}")
                return None

            response.raise_for_status()
            html = response.text

        except httpx.TimeoutException:
            logger.warning(f"文章详情页请求超时: {url[:100]}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"文章详情页 HTTP 错误 {e.response.status_code}: {url[:100]}"
            )
            return None
        except httpx.RequestError as e:
            logger.warning(f"文章详情页网络错误: {e} - {url[:100]}")
            return None
        except Exception as e:
            logger.error(f"文章详情页请求异常: {e} - {url[:100]}")
            return None

        # 步骤 2: 从 HTML 解析 PDF 下载链接
        pdf_url = self._extract_pdf_url(html, url)

        # 步骤 3: 如果 HTML 中未找到，尝试从 params 参数构建下载 URL
        if not pdf_url:
            params = self._extract_params_from_url(url)
            if params:
                pdf_url = self._build_download_url_from_params(params)
                logger.debug(f"HTML 未找到下载链接，使用 params 构建: {pdf_url[:100]}")
            else:
                logger.warning(
                    f"无法从详情页提取 PDF 下载链接: {title[:50]}"
                )
                return None

        # 步骤 4: 下载 PDF
        pdf_bytes = await self._download_pdf(pdf_url)
        if not pdf_bytes:
            logger.warning(f"PDF 下载失败: {title[:50]}")
            return None

        # 步骤 5: 保存 PDF 文件
        pdf_path = self._pdf_path(paper_id)
        try:
            pdf_path.write_bytes(pdf_bytes)
            logger.debug(f"PDF 已保存: {pdf_path}")
        except OSError as e:
            logger.warning(f"PDF 文件保存失败: {e}")

        # 步骤 6: PDF 转文本
        text = self._pdf_to_text(pdf_bytes)
        if not text.strip():
            logger.warning(
                f"PDF 文本提取为空（可能是扫描版）: {title[:50]}"
            )
            return None

        # 清理文本：去除多余空白行
        text = self._clean_text(text)

        # 步骤 7: 保存文本文件
        text_path = self._text_path(paper_id)
        try:
            text_path.write_text(text, encoding="utf-8")
            logger.info(
                f"全文提取完成: {title[:50]} "
                f"({len(text)} 字符, {len(pdf_bytes) / 1024:.0f} KB PDF)"
            )
        except OSError as e:
            logger.warning(f"文本文件保存失败: {e}")
            return None

        # 步骤 8: 速率限制延迟
        await self._rate_limit_delay()

        return text

    async def _rate_limit_delay(self) -> None:
        """执行速率限制延迟.

        在每次下载后等待 1-2 秒随机时间，避免对 NCPSSD 服务器造成过大压力。
        """
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理提取的文本内容.

        处理:
            - 去除连续空行（保留单个空行作为段落分隔）
            - 去除行首行尾多余空白
            - 统一换行符
            - 去除 PDF 提取常见的水印/页码噪声

        Args:
            text: 原始提取文本.

        Returns:
            清理后的文本.
        """
        if not text:
            return ""

        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 去除行首行尾空白
        lines = [line.strip() for line in text.split("\n")]

        # 合并连续空行为单个空行
        cleaned_lines: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty:
                    cleaned_lines.append("")
                prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False

        # 去除首尾空行
        while cleaned_lines and not cleaned_lines[0]:
            cleaned_lines.pop(0)
        while cleaned_lines and not cleaned_lines[-1]:
            cleaned_lines.pop()

        text = "\n".join(cleaned_lines)

        # 去除常见的 PDF 水印/页码噪声
        # 匹配纯数字行（可能是页码），同时折叠周围的多余空行
        text = re.sub(r"\n+\s*\d{1,4}\s*\n+", "\n\n", text)

        # 折叠可能因页码移除产生的连续空行（再次清理）
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    # ===== 批量下载 =====

    async def download_batch(
        self,
        papers: list[dict[str, Any]],
        max_papers: int = 200,
    ) -> dict[str, int]:
        """批量下载论文全文.

        逐篇下载论文全文 PDF 并转换为文本，支持进度跟踪。
        下载过程中会自动跳过已缓存的论文，并对每篇下载应用速率限制。

        进度跟踪:
            使用 rich（如已安装）在终端显示进度条；
            同时通过 logger 输出阶段性进度日志。

        Args:
            papers: 论文字典列表，每项应包含 url, title, source 字段.
            max_papers: 最大下载数量限制，防止过多请求.

        Returns:
            统计字典，包含:
                - total: 总论文数
                - success: 成功下载数
                - failed: 下载失败数
                - skipped: 跳过数（已缓存或非 NCPSSD 来源）
                - empty_text: PDF 下载成功但文本提取为空的数量
        """
        if not papers:
            logger.warning("批量下载: 论文列表为空")
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "empty_text": 0,
            }

        # 限制下载数量
        to_download = papers[:max_papers]
        total = len(to_download)

        stats = {
            "total": total,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "empty_text": 0,
        }

        logger.info(f"开始批量下载: {total} 篇论文 (上限 {max_papers})")

        # 尝试使用 rich 进度条
        progress_ctx = None
        try:
            from rich.console import Console
            from rich.progress import (
                BarColumn,
                Progress,
                TaskProgressColumn,
                TextColumn,
                TimeRemainingColumn,
            )

            console = Console()
            progress_ctx = Progress(
                TextColumn("[bold blue]下载全文"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("{task.description}"),
                TimeRemainingColumn(),
                console=console,
            )
        except ImportError:
            progress_ctx = None

        if progress_ctx is not None:
            with progress_ctx as progress:
                task = progress.add_task(
                    f"0/{total} 成功", total=total
                )

                for i, paper in enumerate(to_download):
                    title = paper.get("title", "")[:40]
                    paper_id = self._get_paper_id(paper)

                    # 检查缓存
                    if self.has_fulltext(paper_id):
                        stats["skipped"] += 1
                        progress.update(
                            task,
                            advance=1,
                            description=(
                                f"{stats['success']}/{total} 成功 "
                                f"(跳过: {title})"
                            ),
                        )
                        continue

                    # 下载
                    text = await self.download_paper(paper)

                    if text is not None and text.strip():
                        stats["success"] += 1
                    elif text is not None and not text.strip():
                        stats["empty_text"] += 1
                    else:
                        stats["failed"] += 1

                    progress.update(
                        task,
                        advance=1,
                        description=(
                            f"{stats['success']}/{total} 成功 "
                            f"(当前: {title})"
                        ),
                    )

                    # 阶段性日志（每 10 篇）
                    if (i + 1) % 10 == 0:
                        logger.info(
                            f"批量下载进度: {i + 1}/{total} "
                            f"(成功 {stats['success']}, "
                            f"失败 {stats['failed']}, "
                            f"跳过 {stats['skipped']})"
                        )
        else:
            # 无 rich 时使用日志跟踪进度
            for i, paper in enumerate(to_download):
                title = paper.get("title", "")[:40]
                paper_id = self._get_paper_id(paper)

                # 检查缓存
                if self.has_fulltext(paper_id):
                    stats["skipped"] += 1
                    logger.debug(f"[{i + 1}/{total}] 跳过（已缓存）: {title}")
                    continue

                # 下载
                text = await self.download_paper(paper)

                if text is not None and text.strip():
                    stats["success"] += 1
                    logger.debug(f"[{i + 1}/{total}] 成功: {title}")
                elif text is not None and not text.strip():
                    stats["empty_text"] += 1
                    logger.debug(f"[{i + 1}/{total}] 文本为空: {title}")
                else:
                    stats["failed"] += 1
                    logger.debug(f"[{i + 1}/{total}] 失败: {title}")

                # 阶段性日志（每 10 篇）
                if (i + 1) % 10 == 0:
                    logger.info(
                        f"批量下载进度: {i + 1}/{total} "
                        f"(成功 {stats['success']}, "
                        f"失败 {stats['failed']}, "
                        f"跳过 {stats['skipped']})"
                    )

        logger.info(
            f"批量下载完成: 共 {total} 篇, "
            f"成功 {stats['success']}, "
            f"失败 {stats['failed']}, "
            f"跳过 {stats['skipped']}, "
            f"空文本 {stats['empty_text']}"
        )

        return stats

    # ===== 上下文管理器支持 =====

    async def __aenter__(self) -> FullTextDownloader:
        """异步上下文管理器入口."""
        await self._get_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器退出."""
        await self.close()


# ===== 便捷函数 =====

_downloader: FullTextDownloader | None = None


def get_downloader(storage_dir: Path | None = None) -> FullTextDownloader:
    """获取全局 FullTextDownloader 单例.

    Args:
        storage_dir: 存储目录（仅首次调用时生效）.

    Returns:
        FullTextDownloader 实例.
    """
    global _downloader
    if _downloader is None:
        _downloader = FullTextDownloader(storage_dir=storage_dir)
    return _downloader


async def download_fulltext(paper: dict[str, Any]) -> str | None:
    """便捷函数: 下载单篇论文全文.

    Args:
        paper: 论文字典，应包含 url, title, source 字段.

    Returns:
        全文文本内容，失败返回 None.
    """
    downloader = get_downloader()
    return await downloader.download_paper(paper)
