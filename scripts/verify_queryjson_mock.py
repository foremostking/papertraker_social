"""Mock 数据验证: 7 类来源筛选的 QueryJson 生成与 search 关键步骤日志.

用途:
    1. 用 mock 数据模拟一次包含 7 类来源筛选(SCI/北大核心/CSSCI/EI/CSCD/AMI/WJCI)
       的实际检索请求。
    2. 验证 build_query_json 生成的 QueryJson 结构是否正确。
    3. 验证 search 方法关键步骤(构建 queryJson、发送请求)的日志是否完整。
    4. 通过 mock 化 aiohttp 请求, 无需真实联网即可走通完整 search 流程。

运行:
    py -3.13 scripts/verify_queryjson_mock.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scholarpilot.mcp.servers.cnki.aiohttp_engine import (
    CNKIAiohttpEngine,
    SOURCE_CATEGORY_MAPPING,
    DEFAULT_SOURCE_CATEGORIES,
)

# ---- 配置日志输出到控制台, 便于观察 search 关键步骤 ----
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


def human_readable(qj_json: str) -> dict:
    """把 QueryJson JSON 字符串转回 dict 便于断言."""
    return json.loads(qj_json)


def verify_queryjson_structure(qj_dict: dict) -> list[str]:
    """核对 QueryJson 关键结构, 返回问题列表(空 = 全部通过)."""
    problems: list[str] = []

    # 顶层必填字段
    for key in ["Platform", "Resource", "Classid", "QNode", "ExScope",
                "SearchType", "Rlang", "View", "SearchFrom"]:
        if key not in qj_dict:
            problems.append(f"缺失顶层字段: {key}")

    if qj_dict.get("Resource") != "JOURNAL":
        problems.append(f"Resource 应为 JOURNAL, 实际={qj_dict.get('Resource')}")
    if qj_dict.get("Classid") != "YSTT4HG0":
        problems.append(f"Classid 应为 YSTT4HG0, 实际={qj_dict.get('Classid')}")

    qgroup = qj_dict.get("QNode", {}).get("QGroup", [])
    if not qgroup:
        problems.append("QNode.QGroup 为空")

    # 找到 ControlGroup
    control_group = next(
        (g for g in qgroup if g.get("Key") == "ControlGroup"), None
    )
    if control_group is None:
        problems.append("QGroup 中缺少 ControlGroup")
        return problems

    children = control_group.get("ChildItems", [])
    if not children:
        problems.append("ControlGroup.ChildItems 为空(缺少年份与来源类别)")

    # 年份子项
    year_child = next(
        (c for c in children if c.get("Key") == ".tit-startend-yearbox"), None
    )
    if year_child is None:
        problems.append("ControlGroup 中缺少年份子项 .tit-startend-yearbox")

    # 来源类别子项
    source_child = next(
        (c for c in children if c.get("Key") == ".extend-tit-checklist"), None
    )
    if source_child is None:
        problems.append("ControlGroup 中缺少来源类别子项 .extend-tit-checklist")
        return problems

    items = source_child.get("Items", [])
    titles = [it.get("Title") for it in items]
    # 7 类来源都要出现
    for cat in DEFAULT_SOURCE_CATEGORIES:
        expected_title = SOURCE_CATEGORY_MAPPING[cat]["Title"]
        if expected_title not in titles:
            problems.append(f"来源类别缺失: {cat} ({expected_title})")

    # 每个来源类别的 Field/Value 都要正确
    for it in items:
        title = it.get("Title")
        field = it.get("Field")
        value = it.get("Value")
        match = None
        for cat, m in SOURCE_CATEGORY_MAPPING.items():
            if m["Title"] == title:
                match = m
                break
        if match is None:
            problems.append(f"来源类别标题未识别: {title}")
            continue
        if field != match["Field"]:
            problems.append(f"{title}: Field 应为 {match['Field']}, 实际={field}")
        if value != match["Value"]:
            problems.append(f"{title}: Value 应为 {match['Value']}, 实际={value}")
        if it.get("Logic") != 1:
            problems.append(f"{title}: Logic 应为 1(OR), 实际={it.get('Logic')}")

    return problems


def build_mock_html(total: int = 1736, rows: int = 3) -> str:
    """构造模拟 CNKI grid 返回的 HTML."""
    papers_html = ""
    for i in range(rows):
        papers_html += f"""
        <tr>
          <td>{i+1}</td>
          <td><a class="fz14"><font>地方政府债务<i>空间溢出</i>研究 {i+1}</font></a></td>
          <td><a class="KnowledgeNetLink">张三</a>;<a class="KnowledgeNetLink">李四</a></td>
          <td><a class="KnowledgeNetLink">财政研究</a></td>
          <td>2023-01-15</td>
          <td>{100-i}</td>
          <td><a class="downloadCnt">{50-i}</a></td>
        </tr>"""
    return f"""
    <html><body>
      <div id="countPageDiv"><em>{total}</em></div>
      <table class="result-table-list"><tbody>{papers_html}</tbody></table>
    </body></html>"""


async def main() -> None:
    passed = 0
    failed = 0

    print("=" * 80)
    print("STEP 1: 用 mock 数据构建含 7 类来源筛选的 QueryJson")
    print("=" * 80)

    topic = "地方政府债务"
    search_query = "SU %= '地方政府债务'"
    year_start, year_end = "2020", "2026"

    qj_json = CNKIAiohttpEngine.build_query_json(
        search_query,
        year_start,
        year_end,
        source_categories=DEFAULT_SOURCE_CATEGORIES,
    )
    qj_dict = human_readable(qj_json)

    print(f"\n[生成成功] 检索式: {search_query}")
    print(f"[来源类别] ({len(DEFAULT_SOURCE_CATEGORIES)} 类): {DEFAULT_SOURCE_CATEGORIES}")
    print("\n--- 生成的 QueryJson (格式化) ---")
    print(json.dumps(qj_dict, ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("STEP 2: 校验 QueryJson 结构")
    print("=" * 80)
    problems = verify_queryjson_structure(qj_dict)
    if problems:
        failed += len(problems)
        print("\n[校验失败] 发现问题:")
        for p in problems:
            print(f"  - {p}")
    else:
        passed += 1
        print("\n[校验通过] 7 类来源筛选的 QueryJson 结构完全正确")

    print("\n" + "=" * 80)
    print("STEP 3: 用 mock aiohttp 请求走通 search() 完整流程, 观察关键日志")
    print("=" * 80)

    # mock 掉 aiohttp.ClientSession.post, 返回伪造的 CNKI HTML
    import aiohttp

    original_post = aiohttp.ClientSession.post
    original_client = aiohttp.ClientSession

    class _FakeResponse:
        def __init__(self) -> None:
            self.status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def text(self) -> str:
            return build_mock_html(total=1736, rows=3)

    class _FakeRequestContextManager:
        """同时支持 await 与 async with 的模拟请求对象.

        aiohttp 的 session.post() 返回的对象既是一个 awaitable,
        又是一个 async context manager (async with session.post() as resp:)。
        """
        def __init__(self, resp: _FakeResponse) -> None:
            self._resp = resp

        def __await__(self):
            async def _a():
                return self._resp
            return _a().__await__()

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *exc):
            return False

    def fake_post(self, url, **kwargs):
        print(f"\n[LOG] 发送请求: {url}")
        print(f"       post_data.pageNum={kwargs.get('data', {}).get('pageNum')}")
        print(f"       post_data.pageSize={kwargs.get('data', {}).get('pageSize')}")
        qj = kwargs.get("data", {}).get("QueryJson", "")
        if qj:
            d = json.loads(qj)
            cg = next(
                (g for g in d["QNode"]["QGroup"] if g.get("Key") == "ControlGroup"), None
            )
            src_items = []
            if cg:
                for c in cg.get("ChildItems", []):
                    if c.get("Key") == ".extend-tit-checklist":
                        src_items = c.get("Items", [])
            print(f"       [LOG] 请求 QueryJson 中来源类别: "
                  f"{[it.get('Title') for it in src_items]}")
        return _FakeRequestContextManager(_FakeResponse())

    aiohttp.ClientSession.post = fake_post  # type: ignore[assignment]

    try:
        engine = CNKIAiohttpEngine(cookie_str="mock=1", timeout=10)
        result = await engine.search(
            query=topic,
            limit=20,
            year_start=year_start,
            year_end=year_end,
            source_categories=DEFAULT_SOURCE_CATEGORIES,
        )
        print(f"\n[结果] total_count={result.total_count}, "
              f"返回论文={len(result.papers)} 篇")
        if result.papers:
            print(f"[结果] 首篇: {result.papers[0].title} / "
                  f"{result.papers[0].journal} / {result.papers[0].year}")
            passed += 1
        else:
            failed += 1
            print("[结果] 未解析到论文, 解析逻辑可能有问题")
    finally:
        aiohttp.ClientSession.post = original_post  # type: ignore[assignment]
        aiohttp.ClientSession = original_client  # type: ignore[assignment]

    print("\n" + "=" * 80)
    print("STEP 4: 运行完整采集流程 (PaperHarvester.harvest_from_cnki, 含 7 类来源筛选)")
    print("=" * 80)

    # 用 mock CNKI 引擎替换 PaperHarvester 内部引擎, 捕获 source_categories 并返回伪造结果
    from scholarpilot.benchmark.paper_harvester import PaperHarvester
    from scholarpilot.mcp.servers.cnki import CNKIPaper, CNKISearchResult

    captured_categories: list[list[str]] = []
    captured_queries: list[str] = []

    # 注意: 这里替换的是实例方法, harvest_from_cnki 以 self._cnki_engine.search(query=...)
    # 的方式调用, 并在内层 await, 因此 mock 函数签名中不应再包含 self 且必须为 async。
    async def _mock_cnki_search(query, limit=20, page=1, year_start="", year_end="",
                                sort_field="FFD", author="", journal="", affiliation="",
                                min_citations=0, source_categories=None):
        captured_queries.append(query)
        captured_categories.append(list(source_categories or []))
        # 打印本次请求的来源类别, 验证 7 类已注入完整采集流程
        print(f"  [采集] query='{query}', journal='{journal}', "
              f"source_categories={list(source_categories or [])}")
        result = CNKISearchResult(query=query)
        result.total_count = 42
        # 返回 3 篇论文, 全部来自目标期刊(简化 _journal_match)
        for i in range(3):
            result.papers.append(CNKIPaper(
                title=f"{journal}《{query}》研究 {i+1}",
                authors=["张三", "李四"],
                journal=journal,
                year=str(year_start or "2020"),
                cited_count=10 - i,
                download_count=5 - i,
            ))
        return result

    harvester = PaperHarvester(storage_dir=Path("scripts/.mock_harvest_out"))
    harvester._cnki_engine.search = _mock_cnki_search  # type: ignore[assignment]
    # 缩短关键词, 只采 1 个期刊 2 个关键词, 快速跑通; 关闭限速
    harvester.BROAD_KEYWORDS = ["财政", "债务"]
    harvester.MAX_PAGES_PER_KEYWORD = 1
    harvester.MAX_SEARCHES_PER_JOURNAL = 2
    harvester.RATE_LIMIT_MIN = 0.0
    harvester.RATE_LIMIT_MAX = 0.0

    collected = await harvester.harvest_from_cnki(
        journals=["财政研究"], year_start="2020", year_end="2026",
        papers_per_journal=5,
    )
    print(f"\n[采集结果] 新增论文 {collected} 篇")
    print(f"[采集结果] 实际传递的来源类别(去重): "
          f"{list(dict.fromkeys(tuple(c) for c in captured_categories))}")

    all_7 = all(
        set(c) == set(DEFAULT_SOURCE_CATEGORIES) for c in captured_categories
    ) if captured_categories else False
    if all_7 and collected > 0:
        passed += 1
        print("[采集通过] 完整采集流程已注入 7 类来源筛选")
    else:
        failed += 1
        print("[采集失败] 完整采集流程未正确注入 7 类来源筛选")

    print("\n" + "=" * 80)
    print(f"SUMMARY: 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 80)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())