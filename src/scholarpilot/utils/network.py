"""网络工具 - 统一处理代理和 HTTP 客户端.

解决系统代理（如 127.0.0.1:8080）对国内学术站点的拦截问题。
"""

from __future__ import annotations

import os
from typing import Any


def configure_no_proxy() -> None:
    """配置 NO_PROXY 环境变量，让国内学术站点绕过系统代理.

    某些环境（如企业内网或 IDE 插件）会注入 HTTP_PROXY，导致 aiohttp/httpx
    把 CNKI、NCPSSD、火山方舟等国内请求也转发到代理，从而连接失败。
    本函数将关键国内域名加入 NO_PROXY。
    """
    domestic_domains = [
        # 中文文献
        "kns.cnki.net",
        "navi.cnki.net",
        "gwz.cass.org.cn",
        "www.ncpssd.cn",
        "ncpssd.org",
        # 火山方舟
        "ark.cn-beijing.volces.com",
        "volces.com",
        # 其他国内学术服务
        "www.wanfangdata.com.cn",
        "s.wanfangdata.com.cn",
        "www.cqvip.com",
        # Web of Science (中国镜像)
        "webofscience.clarivate.cn",
        # ChinaXiv (中科院预印本)
        "chinaxiv.org",
        "www.chinaxiv.org",
        # PubScholar (公共学术OA)
        "pubscholar.cn",
        "www.pubscholar.cn",
        # 国际学术 API（绕过系统代理，直连）
        "export.arxiv.org",
        "arxiv.org",
        "api.semanticscholar.org",
        "www.semanticscholar.org",
        "api.openalex.org",
        "api.unpaywall.org",
        # 本地地址
        "localhost",
        "127.0.0.1",
        "::1",
    ]

    existing = os.environ.get("NO_PROXY", "")
    existing_list = [d.strip() for d in existing.split(",") if d.strip()]

    new_domains = [d for d in domestic_domains if d not in existing_list]
    if new_domains:
        all_domains = existing_list + new_domains
        no_proxy_value = ",".join(all_domains)
        os.environ["NO_PROXY"] = no_proxy_value
        os.environ["no_proxy"] = no_proxy_value


def get_aiohttp_session_kwargs(**extra: Any) -> dict[str, Any]:
    """返回绕过系统代理的 aiohttp ClientSession 参数.

    trust_env=False 表示不读取 HTTP_PROXY/HTTPS_PROXY 环境变量。
    """
    configure_no_proxy()
    return {"trust_env": False, **extra}


def get_httpx_client_kwargs(**extra: Any) -> dict[str, Any]:
    """返回绕过系统代理的 httpx AsyncClient 参数."""
    configure_no_proxy()
    return {"proxy": None, "follow_redirects": True, **extra}
