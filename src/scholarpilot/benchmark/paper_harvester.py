"""批量论文采集器 - 从 CNKI 和 NCPSSD 采集 CSSCI 核心期刊论文元数据.

采集策略:
    1. 主源 NCPSSD (国家哲学社会科学文献中心): 免费、无需认证,
       通过 Solr 语法按期刊名 (cbw_name) + 关键词 (IKET) 批量检索,
       覆盖面广且元数据完整 (摘要、关键词、基金、页码等).
    2. 辅源 CNKI (中国知网): 使用缓存的 Cookie 或机构 IP 认证,
       通过 search() 的 journal 参数按期刊名过滤,
       补充 NCPSSD 未覆盖的期刊或论文 (含被引频次、下载次数).

数据存储:
    ~/.scholarpilot/benchmark/papers_metadata.json

去重策略:
    基于标题标准化 (去除空白与标点、小写化) + 年份的组合键去重,
    跨数据源与跨关键词均生效.

速率控制:
    每次请求间随机休眠 0.5-1.0 秒, 避免触发反爬机制.

Usage:
    harvester = PaperHarvester()
    stats = await harvester.harvest_all(papers_per_journal=50)
    print(harvester.get_stats())
    papers = harvester.get_all_papers()

    # 或者分别采集
    journals = get_journal_names()
    await harvester.harvest_from_ncpssd(journals, papers_per_journal=50)
    await harvester.harvest_from_cnki(journals, papers_per_journal=50)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from scholarpilot.utils.network import configure_no_proxy
from scholarpilot.benchmark.journal_list import get_journal_names
from scholarpilot.mcp.servers.ncpssd import NCPSSDEngine, NCPSSDPaper
from scholarpilot.mcp.servers.cnki import CNKIAiohttpEngine, CNKIPaper, DEFAULT_SOURCE_CATEGORIES

logger = logging.getLogger(__name__)


# 经济/金融/财政领域的宽泛检索关键词.
# 这些关键词作为 IKET (NCPSSD) 或 SU (CNKI) 检索词,
# 配合期刊名过滤, 可以从每个期刊采集多样化的论文.
_BROAD_KEYWORDS: list[str] = [
    "经济", "金融", "财政", "税收", "货币",
    "市场", "投资", "风险", "政策", "增长",
    "贸易", "银行", "企业", "产业", "区域",
    "发展", "改革", "创新", "消费", "收入",
    "债务", "利率", "汇率", "通胀", "就业",
]


class PaperHarvester:
    """批量论文采集器 - 从 CSSCI 核心期刊采集论文元数据.

    使用 NCPSSD (主源, 免费) 和 CNKI (辅源, Cookie 缓存) 两个数据源,
    按期刊名 + 关键词批量检索, 收集论文元数据用于构建质量基准知识库.

    Attributes:
        BROAD_KEYWORDS: 宽泛检索关键词列表.
        DEFAULT_STORAGE_DIR: 默认存储目录 (~/.scholarpilot/benchmark).
        STORAGE_FILENAME: 存储文件名 (papers_metadata.json).
        MAX_PAGES_PER_KEYWORD: 每个关键词的最大翻页数.
        MAX_SEARCHES_PER_JOURNAL: 每个期刊的最大检索次数上限.
        RATE_LIMIT_MIN: 请求间最小休眠秒数.
        RATE_LIMIT_MAX: 请求间最大休眠秒数.
    """

    BROAD_KEYWORDS: list[str] = _BROAD_KEYWORDS
    DEFAULT_STORAGE_DIR: Path = Path.home() / ".scholarpilot" / "benchmark"
    STORAGE_FILENAME: str = "papers_metadata.json"
    MAX_PAGES_PER_KEYWORD: int = 2
    MAX_SEARCHES_PER_JOURNAL: int = 30
    RATE_LIMIT_MIN: float = 0.5
    RATE_LIMIT_MAX: float = 1.0
    NCPSSD_PAGE_SIZE: int = 50
    CNKI_PAGE_SIZE: int = 50

    def __init__(self, storage_dir: Path | None = None) -> None:
        """初始化论文采集器.

        Args:
            storage_dir: 存储目录路径. 默认为 ~/.scholarpilot/benchmark.
                         如果目录不存在会在保存时自动创建.
        """
        # 配置无代理环境, 确保国内学术站点直连
        configure_no_proxy()

        self._storage_dir: Path = storage_dir or self.DEFAULT_STORAGE_DIR
        self._storage_path: Path = self._storage_dir / self.STORAGE_FILENAME
        self._papers: list[dict[str, Any]] = []
        self._seen_keys: set[str] = set()

        # 初始化检索引擎
        self._ncpssd_engine: NCPSSDEngine = NCPSSDEngine()
        self._cnki_engine: CNKIAiohttpEngine = CNKIAiohttpEngine()

        # 辅助 HTTP 客户端 (用于可能的直接 API 调用, 如健康检查)
        self._http_client: httpx.AsyncClient | None = None

        # 加载已有数据
        self._load()

        logger.info(
            "PaperHarvester initialized: %d papers loaded from %s",
            len(self._papers),
            self._storage_path,
        )

    # ==================================================================
    # 公开采集方法
    # ==================================================================

    async def harvest_from_ncpssd(
        self,
        journals: list[str],
        year_start: str = "2020",
        year_end: str = "2026",
        papers_per_journal: int = 50,
    ) -> int:
        """从 NCPSSD 批量采集论文 (主源, 免费无需认证).

        对每个期刊, 使用宽泛关键词列表构建 Solr 查询式:
            (IKET={keyword}) AND cbw_name:{journal_name}
        并附加日期范围过滤, 翻页采集直到达到目标数量或耗尽关键词.

        Args:
            journals: 期刊名称列表.
            year_start: 起始年份 (如 "2020").
            year_end: 结束年份 (如 "2026").
            papers_per_journal: 每个期刊的目标论文数.

        Returns:
            新增论文数量.
        """
        count_before = len(self._papers)
        total_journals = len(journals)

        for idx, journal in enumerate(journals, 1):
            journal_new = 0
            search_count = 0

            # 统计该期刊已有论文数
            journal_existing = sum(
                1 for p in self._papers if p.get("journal", "") == journal
            )
            target = papers_per_journal - journal_existing

            if target <= 0:
                logger.info(
                    "NCPSSD [%d/%d] %s: already have %d papers, skipping",
                    idx, total_journals, journal, journal_existing,
                )
                continue

            logger.info(
                "NCPSSD [%d/%d] %s: target %d papers (have %d)",
                idx, total_journals, journal, target, journal_existing,
            )

            for keyword in self.BROAD_KEYWORDS:
                if journal_new >= target:
                    break
                if search_count >= self.MAX_SEARCHES_PER_JOURNAL:
                    logger.warning(
                        "NCPSSD %s: reached max searches (%d), stopping",
                        journal, self.MAX_SEARCHES_PER_JOURNAL,
                    )
                    break

                for page in range(1, self.MAX_PAGES_PER_KEYWORD + 1):
                    if journal_new >= target:
                        break
                    if search_count >= self.MAX_SEARCHES_PER_JOURNAL:
                        break

                    search_count += 1

                    # 构建 Solr 查询式: 关键词 + 期刊名过滤
                    solr_query = self._build_ncpssd_query(keyword, journal)

                    try:
                        result = await self._ncpssd_engine.search(
                            query=solr_query,
                            limit=self.NCPSSD_PAGE_SIZE,
                            page=page,
                            year_start=year_start,
                            year_end=year_end,
                        )
                    except Exception as e:
                        logger.error(
                            "NCPSSD search failed for %s / '%s' page %d: %s",
                            journal, keyword, page, e,
                        )
                        await self._rate_limit()
                        continue

                    if not result.papers:
                        # 该关键词无更多结果, 换下一个关键词
                        break

                    for paper in result.papers:
                        # 后置过滤: 确保论文确实来自目标期刊
                        # (Solr cbw_name 可能分词匹配, 导致跨期刊结果)
                        if not self._journal_match(paper.journal, journal):
                            continue

                        paper_dict = self._convert_ncpssd_paper(paper)
                        if self._add_paper(paper_dict):
                            journal_new += 1
                            if journal_new >= target:
                                break

                    # 不足一页, 说明没有更多结果
                    if len(result.papers) < self.NCPSSD_PAGE_SIZE:
                        break

                    await self._rate_limit()

                await self._rate_limit()

            # 每个期刊采集完后保存
            self._save()

            logger.info(
                "NCPSSD %s: collected %d new papers (total for journal: %d)",
                journal, journal_new, journal_existing + journal_new,
            )

        new_count = len(self._papers) - count_before
        logger.info(
            "NCPSSD harvest complete: %d new papers (total: %d)",
            new_count, len(self._papers),
        )
        return new_count

    async def harvest_from_cnki(
        self,
        journals: list[str],
        year_start: str = "2020",
        year_end: str = "2026",
        papers_per_journal: int = 50,
    ) -> int:
        """从 CNKI 批量采集论文 (辅源, 使用 Cookie 缓存).

        对每个期刊, 使用宽泛关键词调用 CNKIAiohttpEngine.search(),
        通过 journal 参数按期刊名过滤, 翻页采集直到达到目标数量.

        CNKI 的优势在于提供被引频次 (cited_count) 和下载次数 (download_count),
        但可能遇到验证码拦截, 需要有效的 Cookie 或机构 IP.

        Args:
            journals: 期刊名称列表.
            year_start: 起始年份.
            year_end: 结束年份.
            papers_per_journal: 每个期刊的目标论文数.

        Returns:
            新增论文数量.
        """
        count_before = len(self._papers)
        total_journals = len(journals)

        for idx, journal in enumerate(journals, 1):
            journal_new = 0
            search_count = 0

            # 统计该期刊已有论文数 (含 NCPSSD 已采集的)
            journal_existing = sum(
                1 for p in self._papers if p.get("journal", "") == journal
            )
            target = papers_per_journal - journal_existing

            if target <= 0:
                logger.info(
                    "CNKI [%d/%d] %s: already have %d papers, skipping",
                    idx, total_journals, journal, journal_existing,
                )
                continue

            logger.info(
                "CNKI [%d/%d] %s: target %d papers (have %d)",
                idx, total_journals, journal, target, journal_existing,
            )

            for keyword in self.BROAD_KEYWORDS:
                if journal_new >= target:
                    break
                if search_count >= self.MAX_SEARCHES_PER_JOURNAL:
                    logger.warning(
                        "CNKI %s: reached max searches (%d), stopping",
                        journal, self.MAX_SEARCHES_PER_JOURNAL,
                    )
                    break

                # 交替使用排序方式: 奇数关键词按发表时间, 偶数按被引
                sort_field = "FFD" if (search_count % 2 == 0) else "RU"

                for page in range(1, self.MAX_PAGES_PER_KEYWORD + 1):
                    if journal_new >= target:
                        break
                    if search_count >= self.MAX_SEARCHES_PER_JOURNAL:
                        break

                    search_count += 1

                    try:
                        result = await self._cnki_engine.search(
                            query=keyword,
                            limit=self.CNKI_PAGE_SIZE,
                            page=page,
                            year_start=year_start,
                            year_end=year_end,
                            sort_field=sort_field,
                            journal=journal,
                            source_categories=DEFAULT_SOURCE_CATEGORIES,
                        )
                    except Exception as e:
                        logger.error(
                            "CNKI search failed for %s / '%s' page %d: %s",
                            journal, keyword, page, e,
                        )
                        await self._rate_limit()
                        continue

                    if not result.papers:
                        break

                    for paper in result.papers:
                        # 后置过滤: 确保论文确实来自目标期刊
                        if not self._journal_match(paper.journal, journal):
                            continue

                        paper_dict = self._convert_cnki_paper(paper)
                        if self._add_paper(paper_dict):
                            journal_new += 1
                            if journal_new >= target:
                                break

                    if len(result.papers) < self.CNKI_PAGE_SIZE:
                        break

                    await self._rate_limit()

                await self._rate_limit()

            # 每个期刊采集完后保存
            self._save()

            logger.info(
                "CNKI %s: collected %d new papers (total for journal: %d)",
                journal, journal_new, journal_existing + journal_new,
            )

        new_count = len(self._papers) - count_before
        logger.info(
            "CNKI harvest complete: %d new papers (total: %d)",
            new_count, len(self._papers),
        )
        return new_count

    async def harvest_all(
        self,
        year_start: str = "2020",
        year_end: str = "2026",
        papers_per_journal: int = 50,
    ) -> dict[str, int]:
        """从所有数据源采集论文 (NCPSSD 主源 + CNKI 辅源).

        采集流程:
            1. 从 NCPSSD 采集所有期刊 (免费, 无需认证).
            2. 统计各期刊已采集数量, 找出未达目标的期刊.
            3. 从 CNKI 补充采集未达目标的期刊 (使用 Cookie 缓存).
            4. 去重并保存.

        Args:
            year_start: 起始年份.
            year_end: 结束年份.
            papers_per_journal: 每个期刊的目标论文数.

        Returns:
            采集统计字典, 包含各源新增数量和总量.
        """
        journals = get_journal_names()
        logger.info(
            "Starting full harvest: %d journals, target %d papers/journal, "
            "years %s-%s",
            len(journals), papers_per_journal, year_start, year_end,
        )

        # Phase 1: NCPSSD (主源)
        ncpssd_count = await self.harvest_from_ncpssd(
            journals, year_start, year_end, papers_per_journal,
        )

        # Phase 2: 统计各期刊覆盖情况, 找出缺口
        journal_counts: dict[str, int] = {}
        for paper in self._papers:
            j = paper.get("journal", "")
            journal_counts[j] = journal_counts.get(j, 0) + 1

        gap_journals = [
            j for j in journals
            if journal_counts.get(j, 0) < papers_per_journal
        ]

        logger.info(
            "NCPSSD phase done: %d papers. %d/%d journals need CNKI supplement.",
            ncpssd_count, len(gap_journals), len(journals),
        )

        # Phase 3: CNKI (辅源, 仅补充缺口期刊)
        cnki_count = 0
        if gap_journals:
            cnki_count = await self.harvest_from_cnki(
                gap_journals, year_start, year_end, papers_per_journal,
            )

        # 最终保存
        self._save()

        # 统计覆盖情况
        journal_counts.clear()
        for paper in self._papers:
            j = paper.get("journal", "")
            journal_counts[j] = journal_counts.get(j, 0) + 1

        covered = sum(1 for j in journals if journal_counts.get(j, 0) > 0)

        stats = {
            "ncpssd_new": ncpssd_count,
            "cnki_new": cnki_count,
            "total": len(self._papers),
            "journals_total": len(journals),
            "journals_covered": covered,
        }

        logger.info("Harvest complete: %s", stats)
        return stats

    # ==================================================================
    # 数据访问方法
    # ==================================================================

    def get_all_papers(self) -> list[dict]:
        """返回所有已采集论文的副本.

        Returns:
            论文字典列表, 每个字典包含:
            title, authors, journal, year, abstract, keywords,
            url, source, cited_count, download_count, page_range, fund.
        """
        return list(self._papers)

    def get_stats(self) -> dict[str, Any]:
        """返回采集统计信息.

        Returns:
            统计字典, 包含:
            - total: 论文总数.
            - by_source: 按数据源统计 {ncpssd: N, cnki: N}.
            - by_journal: 按期刊统计 {期刊名: N}.
            - by_year: 按年份统计 {年份: N}.
            - journals_covered: 覆盖期刊数.
        """
        stats: dict[str, Any] = {
            "total": len(self._papers),
            "by_source": {},
            "by_journal": {},
            "by_year": {},
            "journals_covered": 0,
        }

        for paper in self._papers:
            source = paper.get("source", "unknown")
            stats["by_source"][source] = stats["by_source"].get(source, 0) + 1

            journal = paper.get("journal", "")
            if journal:
                stats["by_journal"][journal] = (
                    stats["by_journal"].get(journal, 0) + 1
                )

            year = paper.get("year", "")
            if year:
                stats["by_year"][year] = stats["by_year"].get(year, 0) + 1

        stats["journals_covered"] = len(stats["by_journal"])
        return stats

    # ==================================================================
    # 内部方法: 查询构建
    # ==================================================================

    @staticmethod
    def _build_ncpssd_query(keyword: str, journal: str) -> str:
        """构建 NCPSSD Solr 查询式 (关键词 + 期刊名过滤).

        查询格式:
            (IKET={keyword}) AND cbw_name:{journal_name}

        其中 IKET 是关键词检索字段 (不加引号), cbw_name 是期刊名字段.
        Solr 特殊字符通过 NCPSSDEngine._escape_solr() 转义.

        Args:
            keyword: 检索关键词.
            journal: 期刊名称.

        Returns:
            Solr 查询字符串.
        """
        escaped_kw = NCPSSDEngine._escape_solr(keyword)
        escaped_jr = NCPSSDEngine._escape_solr(journal)
        return f"(IKET={escaped_kw}) AND cbw_name:{escaped_jr}"

    # ==================================================================
    # 内部方法: 论文格式转换
    # ==================================================================

    @staticmethod
    def _convert_ncpssd_paper(paper: NCPSSDPaper) -> dict[str, Any]:
        """将 NCPSSDPaper 转换为标准论文字典.

        NCPSSD 提供丰富的元数据 (摘要、关键词、基金、页码等),
        但不提供被引频次 (cited_count 设为 0).

        Args:
            paper: NCPSSDPaper 对象.

        Returns:
            标准论文字典.
        """
        return {
            "title": paper.title,
            "authors": paper.authors,
            "journal": paper.journal,
            "year": paper.year,
            "abstract": paper.abstract,
            "keywords": paper.keywords,
            "url": paper.url,
            "source": "ncpssd",
            "cited_count": 0,  # NCPSSD 不提供被引频次
            "download_count": paper.download_count,
            "page_range": paper.page_range,
            "fund": paper.fund,
        }

    @staticmethod
    def _convert_cnki_paper(paper: CNKIPaper) -> dict[str, Any]:
        """将 CNKIPaper 转换为标准论文字典.

        CNKI grid 结果提供被引频次和下载次数,
        但通常不包含摘要、关键词和页码 (需详情页才能获取).

        Args:
            paper: CNKIPaper 对象.

        Returns:
            标准论文字典.
        """
        return {
            "title": paper.title,
            "authors": paper.authors,
            "journal": paper.journal,
            "year": paper.year,
            "abstract": paper.abstract,
            "keywords": paper.keywords,
            "url": paper.url,
            "source": "cnki",
            "cited_count": paper.cited_count,
            "download_count": paper.download_count,
            "page_range": "",  # CNKI grid 结果不含页码
            "fund": paper.fund,
        }

    # ==================================================================
    # 内部方法: 去重
    # ==================================================================

    def _normalize_title(self, title: str) -> str:
        """标准化论文标题用于去重.

        处理步骤:
            1. 去除首尾空白.
            2. 移除所有空白字符.
            3. 移除所有标点符号 (中文和英文).
            4. 转为小写.

        Args:
            title: 原始标题.

        Returns:
            标准化后的标题.
        """
        if not title:
            return ""
        # 去除首尾空白并移除所有内部空白
        normalized = re.sub(r"\s+", "", title.strip())
        # 仅保留字母、数字、下划线和 CJK 字符
        normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", normalized, flags=re.UNICODE)
        return normalized.lower()

    def _dedup_key(self, paper: dict[str, Any]) -> str:
        """生成去重键 (标准化标题 + 年份).

        Args:
            paper: 论文字典.

        Returns:
            去重键字符串.
        """
        title = self._normalize_title(paper.get("title", ""))
        year = str(paper.get("year", "")).strip()
        return f"{title}_{year}"

    def _add_paper(self, paper: dict[str, Any]) -> bool:
        """添加论文到集合 (自动去重).

        Args:
            paper: 论文字典.

        Returns:
            True 如果论文是新添加的, False 如果已存在或标题为空.
        """
        if not paper.get("title"):
            return False
        key = self._dedup_key(paper)
        if not key or key == "_" or key in self._seen_keys:
            return False
        self._seen_keys.add(key)
        self._papers.append(paper)
        return True

    def _deduplicate(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """对论文列表去重 (基于标准化标题 + 年份).

        Args:
            papers: 论文字典列表.

        Returns:
            去重后的论文列表.
        """
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for paper in papers:
            if not paper.get("title"):
                continue
            key = self._dedup_key(paper)
            if key and key != "_" and key not in seen:
                seen.add(key)
                result.append(paper)
        return result

    # ==================================================================
    # 内部方法: 期刊名匹配
    # ==================================================================

    @staticmethod
    def _journal_match(paper_journal: str, target_journal: str) -> bool:
        """检查论文的期刊名是否匹配目标期刊.

        Solr 的 cbw_name 字段可能分词匹配, 导致返回其他期刊的论文.
        此方法做后置过滤, 检查双向包含关系.

        Args:
            paper_journal: 论文元数据中的期刊名.
            target_journal: 目标期刊名.

        Returns:
            True 如果匹配.
        """
        if not paper_journal or not target_journal:
            return False
        pj = paper_journal.strip()
        tj = target_journal.strip()
        # 精确匹配或双向包含
        return pj == tj or tj in pj or pj in tj

    # ==================================================================
    # 内部方法: 速率控制
    # ==================================================================

    async def _rate_limit(self) -> None:
        """请求间随机休眠, 避免触发反爬机制."""
        delay = random.uniform(self.RATE_LIMIT_MIN, self.RATE_LIMIT_MAX)
        await asyncio.sleep(delay)

    # ==================================================================
    # 内部方法: 持久化
    # ==================================================================

    def _save(self) -> None:
        """将采集的论文保存到 JSON 文件."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "papers": self._papers,
            "stats": self.get_stats(),
            "updated_at": datetime.now().isoformat(),
            "paper_count": len(self._papers),
        }

        try:
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("Saved %d papers to %s", len(self._papers), self._storage_path)
        except Exception as e:
            logger.error("Failed to save papers: %s", e)

    def _load(self) -> None:
        """从 JSON 文件加载已有论文数据."""
        if not self._storage_path.exists():
            return

        try:
            data = json.loads(
                self._storage_path.read_text(encoding="utf-8")
            )
            papers = data.get("papers", [])
            if not isinstance(papers, list):
                logger.warning("Invalid papers format in storage file")
                return

            # 加载并重建去重集合
            for paper in papers:
                if not isinstance(paper, dict):
                    continue
                if not paper.get("title"):
                    continue
                key = self._dedup_key(paper)
                if key and key != "_":
                    self._seen_keys.add(key)
                    self._papers.append(paper)

            logger.info(
                "Loaded %d papers from %s",
                len(self._papers), self._storage_path,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load papers from %s: %s", self._storage_path, e)
        except Exception as e:
            logger.error("Unexpected error loading papers: %s", e)

    # ==================================================================
    # 内部方法: HTTP 客户端
    # ==================================================================

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建辅助 HTTP 客户端.

        使用 trust_env=False 和 proxy=None 确保绕过系统代理.
        """
        if self._http_client is None or self._http_client.is_closed:
            configure_no_proxy()
            self._http_client = httpx.AsyncClient(
                trust_env=False,
                proxy=None,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http_client

    # ==================================================================
    # 资源清理
    # ==================================================================

    async def close(self) -> None:
        """关闭所有引擎和 HTTP 客户端, 释放资源."""
        # 保存数据
        self._save()

        # 关闭 NCPSSD 引擎
        try:
            await self._ncpssd_engine.close()
        except Exception as e:
            logger.warning("Error closing NCPSSD engine: %s", e)

        # 关闭 CNKI 引擎
        try:
            await self._cnki_engine.close()
        except Exception as e:
            logger.warning("Error closing CNKI engine: %s", e)

        # 关闭辅助 HTTP 客户端
        if self._http_client and not self._http_client.is_closed:
            try:
                await self._http_client.aclose()
            except Exception as e:
                logger.warning("Error closing HTTP client: %s", e)

        logger.info("PaperHarvester closed, %d papers saved", len(self._papers))

    async def __aenter__(self) -> PaperHarvester:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


# ==================================================================
# 独立运行入口
# ==================================================================

async def _main() -> None:
    """独立运行入口: 采集 CSSCI 核心期刊论文元数据."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import argparse

    parser = argparse.ArgumentParser(
        description="批量采集 CSSCI 核心期刊论文元数据",
    )
    parser.add_argument(
        "--papers-per-journal", type=int, default=50,
        help="每个期刊的目标论文数 (默认 50)",
    )
    parser.add_argument(
        "--year-start", default="2020",
        help="起始年份 (默认 2020)",
    )
    parser.add_argument(
        "--year-end", default="2026",
        help="结束年份 (默认 2026)",
    )
    parser.add_argument(
        "--source", choices=["all", "ncpssd", "cnki"], default="all",
        help="数据源 (默认 all)",
    )
    parser.add_argument(
        "--storage-dir", type=str, default="",
        help="存储目录 (默认 ~/.scholarpilot/benchmark)",
    )

    args = parser.parse_args()

    storage_dir = Path(args.storage_dir) if args.storage_dir else None

    async with PaperHarvester(storage_dir=storage_dir) as harvester:
        if args.source == "all":
            stats = await harvester.harvest_all(
                year_start=args.year_start,
                year_end=args.year_end,
                papers_per_journal=args.papers_per_journal,
            )
        elif args.source == "ncpssd":
            journals = get_journal_names()
            n = await harvester.harvest_from_ncpssd(
                journals,
                year_start=args.year_start,
                year_end=args.year_end,
                papers_per_journal=args.papers_per_journal,
            )
            stats = {"ncpssd_new": n, "total": len(harvester.get_all_papers())}
        else:
            journals = get_journal_names()
            n = await harvester.harvest_from_cnki(
                journals,
                year_start=args.year_start,
                year_end=args.year_end,
                papers_per_journal=args.papers_per_journal,
            )
            stats = {"cnki_new": n, "total": len(harvester.get_all_papers())}

    print("\n===== 采集完成 =====")
    print(f"采集统计: {stats}")
    print(f"存储路径: {harvester._storage_path}")
    detailed = harvester.get_stats()
    print(f"论文总数: {detailed['total']}")
    print(f"覆盖期刊: {detailed['journals_covered']}")
    print(f"按数据源: {detailed['by_source']}")


if __name__ == "__main__":
    asyncio.run(_main())
