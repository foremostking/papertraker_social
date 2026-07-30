"""万方数据知识服务平台检索引擎.

万方数据(wanfangdata.com.cn)是中文三大学术数据库之一,
覆盖期刊论文、学位论文、会议论文、专利、标准等多类型文献。

特点:
- 学位论文覆盖面广(万方优势领域)
- 机构 IP 认证(VPN 模式)或 Cookie 认证
- 与 CNKI 互补:万方在学位论文、会议论文方面覆盖更全

检索 API(gRPC-Web + Protobuf,通过浏览器逆向分析确认):
- URL: POST https://s.wanfangdata.com.cn/SearchService.SearchService/search
- Content-Type: application/grpc-web+proto
- 请求: gRPC-Web 帧封装的 protobuf 消息
- 响应: gRPC-Web 帧封装的 protobuf 消息
- 每页固定 20 条

Protobuf 请求结构(手动构造,无需 .proto 文件):
  message SearchRequest {
    message SearchQuery {
      string type = 1;        // "paper"
      string query = 2;       // 检索词
      int32 sort = 5;         // 2 (相关度排序)
      int32 page_size = 6;    // 20
      bytes field8 = 8;       // 0x00
      bool field9 = 9;        // true
      string platform = 12;   // "pc"
      string source = 13;     // "search"
    }
    SearchQuery query = 1;
    int32 page = 2;
    repeated string features = 4;  // ["AI_READ", "AI_EXTRACT"]
  }

Protobuf 响应结构:
  message SearchResponse {
    int32 status = 1;           // 1 = success
    string query_id = 2;        // 查询ID
    int32 total_count = 3;      // 总结果数
    repeated PaperItem results = 4;
  }

  message PaperItem {
    string type = 1;            // "Periodical" / "Dissertation" / "Conference"
    PermissionMsg perms = 2;
    string id_base64 = 3;       // Base64 编码的 ID
    PaperData data = 101;       // 论文详细数据
  }

  message PaperData {
    string paper_id = 1;        // 如 "tjllysj202604006"
    string title = 2;           // 标题(可能含 highlight 标签)
    string first_author_zh = 3; // 第一作者(中文)
    string first_author_en = 6; // 第一作者(英文/拼音)
    string institution = 8;     // 机构
    string institution_full = 10;
    repeated string keywords_zh = 16;  // 中文关键词
    repeated string keywords_en = 17;  // 英文关键词
    string abstract = 20;       // 摘要(可能含 highlight 标签)
    string journal_code = 22;
    string journal_name_en = 23;
    string journal_name_en2 = 24;
    string publish_date = 28;   // "2026-04-25 00:00:00"
    int32 year = 33;
    string issue = 34;          // 期号
    string page_range = 36;
    string section = 38;
    string core_tag = 39;       // "AMI" / "北大核心" 等
    string doi = 41;
    string language = 44;       // "chi" / "eng"
    string issn = 45;
    string cn_number = 46;
    int32 cited_count = 48;
    int32 download_count = 50;
    string article_type = 53;   // "Regular"
    string resource_type = 54;  // "Periodical"
    string fulltext_status = 74; // "FULLTEXT"
  }

Usage:
    engine = WanfangEngine(vpn_mode=True)
    result = await engine.search("地方政府债务", limit=20)
    for paper in result.papers:
        print(paper.title, paper.authors, paper.journal)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any

import httpx

from scholarpilot.utils.network import configure_no_proxy, get_httpx_client_kwargs

logger = logging.getLogger(__name__)


# ===== 数据模型 =====

@dataclass
class WanfangPaper:
    """万方检索结果中的单篇论文."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    url: str = ""
    source: str = "wanfang"
    paper_type: str = ""  # 期刊论文/学位论文/会议论文
    cited_count: int = 0
    download_count: int = 0
    fund: str = ""
    institution: str = ""  # 作者机构
    degree_level: str = ""  # 学位论文级别(硕士/博士)
    paper_id: str = ""  # 万方内部ID(如 periodical_xxx)
    core_tags: list[str] = field(default_factory=list)
    issue: str = ""
    page_range: str = ""
    language: str = ""
    issn: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "abstract": self.abstract,
            "keywords": self.keywords,
            "doi": self.doi,
            "url": self.url,
            "source": self.source,
            "paper_type": self.paper_type,
            "cited_count": self.cited_count,
            "download_count": self.download_count,
            "fund": self.fund,
            "institution": self.institution,
            "degree_level": self.degree_level,
            "paper_id": self.paper_id,
            "core_tags": self.core_tags,
            "issue": self.issue,
            "page_range": self.page_range,
            "language": self.language,
            "issn": self.issn,
        }


@dataclass
class WanfangSearchResult:
    """万方检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[WanfangPaper] = field(default_factory=list)
    raw_response_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
        }


# ===== gRPC-Web 帧编解码 =====

def _encode_grpc_web_frame(message: bytes) -> bytes:
    """编码 gRPC-Web 帧: 1字节压缩标志 + 4字节大端长度 + 消息体."""
    return b"\x00" + struct.pack(">I", len(message)) + message


def _decode_grpc_web_frame(data: bytes) -> bytes:
    """解码 gRPC-Web 帧,返回消息体."""
    if len(data) < 5:
        raise ValueError(f"Invalid gRPC-Web frame: too short ({len(data)} bytes)")
    compressed = data[0]
    length = struct.unpack(">I", data[1:5])[0]
    if compressed:
        raise ValueError("Compressed gRPC-Web frames not supported")
    return data[5:5 + length]


# ===== Protobuf 原始编解码 =====

def _encode_varint(value: int) -> bytes:
    """编码 varint."""
    result = b""
    while value > 0x7f:
        result += bytes([0x80 | (value & 0x7f)])
        value >>= 7
    result += bytes([value & 0x7f])
    return result


def _encode_len_delim(field_number: int, data: bytes) -> bytes:
    """编码 length-delimited 字段(字符串/bytes/嵌套消息)."""
    tag = (field_number << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(data)) + data


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """编码 varint 字段."""
    tag = (field_number << 3) | 0
    return _encode_varint(tag) + _encode_varint(value)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    """解码 varint,返回 (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        result |= (b & 0x7f) << shift
        offset += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset


def _decode_protobuf_fields(data: bytes) -> list[tuple[int, int, bytes | int]]:
    """解码 protobuf 字段列表.

    返回 [(field_number, wire_type, value), ...]
    - wire_type 0: value = int (varint)
    - wire_type 2: value = bytes (length-delimited)
    - wire_type 5: value = bytes (32-bit)
    - wire_type 1: value = bytes (64-bit)

    支持重复字段(同一 field_number 出现多次).
    """
    fields: list[tuple[int, int, bytes | int]] = []
    offset = 0
    while offset < len(data):
        tag, offset = _decode_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number == 0:
            break
        if wire_type == 0:  # varint
            value, offset = _decode_varint(data, offset)
            fields.append((field_number, wire_type, value))
        elif wire_type == 2:  # length-delimited
            length, offset = _decode_varint(data, offset)
            value = data[offset:offset + length]
            offset += length
            fields.append((field_number, wire_type, value))
        elif wire_type == 5:  # 32-bit
            value = data[offset:offset + 4]
            offset += 4
            fields.append((field_number, wire_type, value))
        elif wire_type == 1:  # 64-bit
            value = data[offset:offset + 8]
            offset += 8
            fields.append((field_number, wire_type, value))
        else:
            break
    return fields


def _fields_to_dict(
    fields: list[tuple[int, int, bytes | int]],
) -> dict[int, list[bytes | int]]:
    """将字段列表转为字典(支持重复字段).

    返回 {field_number: [value1, value2, ...]}
    """
    result: dict[int, list[bytes | int]] = {}
    for fn, _wt, val in fields:
        if fn not in result:
            result[fn] = []
        result[fn].append(val)
    return result


def _try_str(data: bytes | int) -> str | None:
    """尝试将 bytes 解码为 UTF-8 字符串."""
    if isinstance(data, int):
        return None
    try:
        s = data.decode("utf-8")
        if all(c.isprintable() or c in "\n\r\t" for c in s):
            return s
    except (UnicodeDecodeError, ValueError):
        pass
    return None


def _strip_highlight(text: str) -> str:
    """去除万方高亮标签 <span class='highlight'>...</span>."""
    return re.sub(r"<span[^>]*>(.*?)</span>", r"\1", text)


# ===== 万方检索引擎 =====

class WanfangEngine:
    """万方数据知识服务平台检索引擎.

    通过 gRPC-Web + Protobuf 协议检索中文学术文献。
    VPN 接入后可通过机构 IP 认证,无需登录。

    检索流程:
    1. 构造 protobuf 请求(检索词、页码、每页数量)
    2. 用 gRPC-Web 帧封装,POST 到 SearchService.SearchService/search
    3. 解析 gRPC-Web 响应,提取论文数据

    特点:
    - 期刊论文、学位论文、会议论文、专利、标准等多类型覆盖
    - 与 CNKI 互补:万方在学位论文、会议论文方面覆盖更全
    - 机构 IP 认证(VPN 模式)或 Cookie 认证
    - 每页固定 20 条结果
    - 直接 API 调用,无需浏览器渲染

    Usage:
        engine = WanfangEngine(vpn_mode=True)
        result = await engine.search("地方政府债务", limit=20)
    """

    # 万方 gRPC-Web API 端点
    SEARCH_API = "https://s.wanfangdata.com.cn/SearchService.SearchService/search"
    HOME_URL = "https://www.wanfangdata.com.cn/index.html"

    # 每页固定 20 条
    PAGE_SIZE = 20

    # User-Agent
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: int = 30,
        vpn_mode: bool = False,
        cookies: dict[str, str] | None = None,
    ) -> None:
        """初始化万方检索引擎.

        Args:
            timeout: 请求超时秒数.
            vpn_mode: VPN 机构访问模式。启用后依赖机构 IP 认证。
            cookies: Cookie 字典(非 VPN 模式可选).
        """
        self.timeout = timeout
        self.vpn_mode = vpn_mode
        self._cookies = cookies or {}
        self._client: httpx.AsyncClient | None = None
        self._session_initialized = False

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 httpx 客户端(延迟初始化)."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            kwargs = get_httpx_client_kwargs(timeout=self.timeout)
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def _ensure_session(self) -> None:
        """确保 Session 已建立(访问首页获取 Cookie)."""
        if self._session_initialized:
            return

        client = await self._get_client()
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        try:
            resp = await client.get(
                self.HOME_URL, headers=headers, follow_redirects=True
            )
            logger.debug(
                f"Wanfang session init: HTTP {resp.status_code}, "
                f"cookies: {len(resp.cookies)}"
            )
            for name, value in resp.cookies.items():
                self._cookies[name] = value
            self._session_initialized = True
        except Exception as e:
            logger.warning(f"Wanfang session init failed (non-fatal): {e}")
            self._session_initialized = True

    @staticmethod
    def build_query(
        topic: str,
        region: str = "",
        content: str = "",
    ) -> str:
        """构建万方检索词.

        万方使用空格分隔的多关键词检索,支持 AND 逻辑。

        Args:
            topic: 核心主题.
            region: 研究区域.
            content: 研究内容.

        Returns:
            检索词字符串.
        """
        parts = []
        if topic:
            parts.append(topic)
        if region and region not in topic:
            parts.append(region)
        if content and content not in topic:
            parts.append(content)
        return " ".join(parts) if parts else topic

    def _build_grpc_web_request(
        self, query: str, page: int = 1, page_size: int = 20
    ) -> bytes:
        """构造万方搜索 gRPC-Web 请求.

        请求结构(通过浏览器逆向分析确认):
        - 外层 SearchRequest:
          - field 1 (message): SearchQuery
          - field 2 (varint): page
          - field 4 (repeated string): features ["AI_READ", "AI_EXTRACT"]
        - 内层 SearchQuery:
          - field 1 (string): type = "paper"
          - field 2 (string): query = 检索词
          - field 5 (varint): sort = 2 (相关度)
          - field 6 (varint): page_size
          - field 8 (bytes): 0x00
          - field 9 (varint): 1 (true)
          - field 12 (string): "pc"
          - field 13 (string): "search"
        """
        # 构造内层 SearchQuery 消息
        inner = b""
        inner += _encode_len_delim(1, b"paper")            # type = "paper"
        inner += _encode_len_delim(2, query.encode("utf-8"))  # query
        inner += _encode_varint_field(5, 2)                 # sort = 2
        inner += _encode_varint_field(6, page_size)         # page_size
        inner += _encode_len_delim(8, b"\x00")              # field8 = 0x00
        inner += _encode_varint_field(9, 1)                 # field9 = true
        inner += _encode_len_delim(12, b"pc")               # platform = "pc"
        inner += _encode_len_delim(13, b"search")           # source = "search"

        # 构造外层 SearchRequest 消息
        outer = b""
        outer += _encode_len_delim(1, inner)                # query = SearchQuery
        outer += _encode_varint_field(2, page)              # page
        outer += _encode_len_delim(4, b"AI_READ")           # features
        outer += _encode_len_delim(4, b"AI_EXTRACT")        # features

        # gRPC-Web 帧封装
        return _encode_grpc_web_frame(outer)

    def _parse_grpc_web_response(self, data: bytes, query: str) -> WanfangSearchResult:
        """解析万方搜索 gRPC-Web 响应.

        响应结构:
        - field 1 (varint): status (1 = success)
        - field 2 (string): query_id
        - field 3 (varint): total_count
        - field 4 (repeated message): PaperItem
        """
        result = WanfangSearchResult(query=query, raw_response_size=len(data))

        try:
            message = _decode_grpc_web_frame(data)
        except ValueError as e:
            logger.error(f"Failed to decode gRPC-Web frame: {e}")
            return result

        fields = _decode_protobuf_fields(message)
        field_dict = _fields_to_dict(fields)

        # 解析状态、查询ID、总数
        if 1 in field_dict:
            result.total_count = 0  # status, not total
        if 2 in field_dict:
            qid = _try_str(field_dict[2][0])
            if qid:
                logger.debug(f"Wanfang query_id: {qid}")
        if 3 in field_dict:
            val = field_dict[3][0]
            if isinstance(val, int):
                result.total_count = val

        # 解析搜索结果
        if 4 in field_dict:
            for item_data in field_dict[4]:
                if isinstance(item_data, bytes):
                    paper = self._parse_paper_item(item_data)
                    if paper and paper.title:
                        result.papers.append(paper)

        return result

    def _parse_paper_item(self, data: bytes) -> WanfangPaper | None:
        """解析单篇论文条目(PaperItem)."""
        fields = _decode_protobuf_fields(data)
        field_dict = _fields_to_dict(fields)

        paper = WanfangPaper()

        # field 1: 类型 ("Periodical" / "Dissertation" / "Conference")
        if 1 in field_dict:
            type_str = _try_str(field_dict[1][0])
            if type_str:
                type_map = {
                    "Periodical": "期刊论文",
                    "Dissertation": "学位论文",
                    "Conference": "会议论文",
                    "Patent": "专利",
                    "Standard": "标准",
                }
                paper.paper_type = type_map.get(type_str, type_str)

        # field 101: 论文详细数据 (PaperData)
        if 101 in field_dict:
            paper_data = field_dict[101][0]
            if isinstance(paper_data, bytes):
                self._fill_paper_data(paper, paper_data)

        return paper if paper.title else None

    def _fill_paper_data(self, paper: WanfangPaper, data: bytes) -> None:
        """从 PaperData protobuf 填充论文信息.

        字段映射(通过浏览器逆向分析确认):
        - f1: paper_id
        - f2: title (可能含 highlight 标签)
        - f3: first_author_zh (中文作者)
        - f6: first_author_en (英文/拼音作者)
        - f8: institution
        - f10: institution_full
        - f16: repeated keywords_zh (中文关键词)
        - f17: repeated keywords_en (英文关键词)
        - f20: abstract (可能含 highlight 标签)
        - f22: journal_code
        - f23: journal_name_en
        - f28: publish_date
        - f33: year (int32)
        - f34: issue
        - f36: page_range
        - f39: core_tag
        - f41: doi
        - f44: language
        - f45: issn
        - f46: cn_number
        - f48: cited_count (int32)
        - f50: download_count (int32)
        - f53: article_type
        - f54: resource_type
        - f74: fulltext_status
        """
        fields = _decode_protobuf_fields(data)
        field_dict = _fields_to_dict(fields)

        # paper_id (f1)
        if 1 in field_dict:
            val = _try_str(field_dict[1][0])
            if val:
                paper.paper_id = val
                paper.url = f"https://d.wanfangdata.com.cn/periodical_{val}" \
                    if not val.startswith("periodical_") \
                    else f"https://d.wanfangdata.com.cn/{val}"

        # title (f2) - 去除高亮标签
        if 2 in field_dict:
            val = _try_str(field_dict[2][0])
            if val:
                paper.title = _strip_highlight(val).strip()

        # authors (f3 中文, f6 英文)
        authors: list[str] = []
        if 3 in field_dict:
            for v in field_dict[3]:
                s = _try_str(v)
                if s and s.strip():
                    # 万方作者可能用逗号/分号分隔
                    for a in re.split(r"[,;，；]", s):
                        a = a.strip()
                        if a:
                            authors.append(a)
        if not authors and 6 in field_dict:
            for v in field_dict[6]:
                s = _try_str(v)
                if s and s.strip():
                    for a in re.split(r"[,;]", s):
                        a = a.strip()
                        if a:
                            authors.append(a)
        paper.authors = authors[:5]  # 限制作者数量

        # institution (f8)
        if 8 in field_dict:
            val = _try_str(field_dict[8][0])
            if val:
                paper.institution = val.strip()

        # keywords (f16 中文, f17 英文) - 重复字段
        keywords: list[str] = []
        if 16 in field_dict:
            for v in field_dict[16]:
                s = _try_str(v)
                if s and s.strip():
                    keywords.append(_strip_highlight(s).strip())
        if not keywords and 17 in field_dict:
            for v in field_dict[17]:
                s = _try_str(v)
                if s and s.strip():
                    keywords.append(_strip_highlight(s).strip())
        paper.keywords = keywords

        # abstract (f20) - 去除高亮标签
        if 20 in field_dict:
            val = _try_str(field_dict[20][0])
            if val:
                paper.abstract = _strip_highlight(val).strip()

        # journal (f23 英文期刊名, f24 备用)
        if 23 in field_dict:
            val = _try_str(field_dict[23][0])
            if val:
                paper.journal = val.strip()
        if not paper.journal and 24 in field_dict:
            val = _try_str(field_dict[24][0])
            if val:
                paper.journal = val.strip()

        # year (f33)
        if 33 in field_dict:
            val = field_dict[33][0]
            if isinstance(val, int):
                paper.year = str(val)

        # issue (f34)
        if 34 in field_dict:
            val = _try_str(field_dict[34][0])
            if val:
                paper.issue = val.strip()

        # page_range (f36)
        if 36 in field_dict:
            val = _try_str(field_dict[36][0])
            if val:
                paper.page_range = val.strip()

        # core_tag (f39) - 可能是重复字段
        core_tags: list[str] = []
        if 39 in field_dict:
            for v in field_dict[39]:
                s = _try_str(v)
                if s and s.strip():
                    core_tags.append(s.strip())
        paper.core_tags = core_tags

        # doi (f41)
        if 41 in field_dict:
            val = _try_str(field_dict[41][0])
            if val:
                paper.doi = val.strip()

        # language (f44)
        if 44 in field_dict:
            val = _try_str(field_dict[44][0])
            if val:
                paper.language = val.strip()

        # issn (f45)
        if 45 in field_dict:
            val = _try_str(field_dict[45][0])
            if val:
                paper.issn = val.strip()

        # cited_count (f48)
        if 48 in field_dict:
            val = field_dict[48][0]
            if isinstance(val, int):
                paper.cited_count = val

        # download_count (f50)
        if 50 in field_dict:
            val = field_dict[50][0]
            if isinstance(val, int):
                paper.download_count = val

        # 学位论文级别检测(从 institution 或其他字段)
        if 38 in field_dict:
            val = _try_str(field_dict[38][0])
            if val:
                if "硕士" in val:
                    paper.degree_level = "硕士"
                elif "博士" in val:
                    paper.degree_level = "博士"

    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 1,
        year_start: str = "",
        year_end: str = "",
        paper_type: str = "",
    ) -> WanfangSearchResult:
        """执行万方检索.

        Args:
            query: 检索词.
            limit: 返回数量(最大 20,每页固定 20 条).
            page: 页码(从1开始).
            year_start: 起始年份(可选,客户端过滤).
            year_end: 结束年份(可选,客户端过滤).
            paper_type: 文献类型(可选,客户端过滤).

        Returns:
            WanfangSearchResult: 检索结果.
        """
        await self._ensure_session()
        client = await self._get_client()

        # 构造 gRPC-Web 请求
        request_body = self._build_grpc_web_request(
            query, page=page, page_size=self.PAGE_SIZE
        )

        headers = {
            "Content-Type": "application/grpc-web+proto",
            "X-Grpc-Web": "1",
            "X-User-Agent": "grpc-web-javascript/0.1",
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://s.wanfangdata.com.cn",
            "Referer": "https://s.wanfangdata.com.cn/paper",
        }

        try:
            resp = await client.post(
                self.SEARCH_API,
                content=request_body,
                headers=headers,
                cookies=self._cookies,
            )

            if resp.status_code != 200:
                logger.warning(
                    f"Wanfang search HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                return WanfangSearchResult(query=query, total_count=0)

            # 解析 gRPC-Web 响应
            result = self._parse_grpc_web_response(resp.content, query)

            # 客户端年份过滤
            if year_start or year_end:
                result.papers = self._filter_by_year(
                    result.papers, year_start, year_end
                )

            # 客户端文献类型过滤
            if paper_type:
                result.papers = self._filter_by_type(result.papers, paper_type)

            # 限制返回数量
            if limit and len(result.papers) > limit:
                result.papers = result.papers[:limit]

            logger.info(
                f"Wanfang search '{query}': {result.total_count} total, "
                f"{len(result.papers)} returned"
            )
            return result

        except asyncio.TimeoutError:
            logger.error("Wanfang search timeout")
            return WanfangSearchResult(query=query, total_count=0)
        except Exception as e:
            logger.error(f"Wanfang search failed: {e}")
            return WanfangSearchResult(query=query, total_count=0)

    def _filter_by_year(
        self,
        papers: list[WanfangPaper],
        year_start: str,
        year_end: str,
    ) -> list[WanfangPaper]:
        """按年份过滤论文(客户端过滤)."""
        filtered = []
        for paper in papers:
            if not paper.year:
                continue
            try:
                year = int(paper.year)
                if year_start and year < int(year_start):
                    continue
                if year_end and year > int(year_end):
                    continue
                filtered.append(paper)
            except ValueError:
                continue
        return filtered

    def _filter_by_type(
        self,
        papers: list[WanfangPaper],
        paper_type: str,
    ) -> list[WanfangPaper]:
        """按文献类型过滤(客户端过滤).

        Args:
            papers: 论文列表.
            paper_type: 类型映射:
                - periodical/期刊 → 期刊论文
                - dissertation/学位 → 学位论文
                - conference/会议 → 会议论文
        """
        type_map = {
            "periodical": "期刊论文",
            "期刊": "期刊论文",
            "dissertation": "学位论文",
            "学位": "学位论文",
            "conference": "会议论文",
            "会议": "会议论文",
        }
        target_type = type_map.get(paper_type, paper_type)
        return [p for p in papers if target_type in p.paper_type]

    async def close(self) -> None:
        """关闭引擎."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
