"""FeedManager - 文献动态订阅管理器.

科研工作者的核心痛点：写完论文后不知道谁引用了自己的核心文献，
也不知道同领域又出了什么新文章。FeedManager 解决这个问题。

三种订阅策略：
1. 反向引用追踪（citation）：追踪种子论文被谁引用了（SS + OpenAlex）
2. 同作者追踪（author）：追踪种子论文的作者又发了什么新文章（SS + OpenAlex）
3. 主题增量（topic）：用关键词重新检索，筛选出库中还没有的新文章（中英文全覆盖）

设计理念：
- 种子论文由用户选择或自动推荐，是追踪的起点
- 增量检测：只推送新内容，不重复推送已知的
- 中英文全覆盖：英文用 SS/OpenAlex，中文用 NCPSSD
- LLM 推荐理由可选：有 API Key 时生成，无时跳过
- 每次推送默认 20 篇，按相关度排序，用户可配置

Usage:
    from scholarpilot.agent.feed import FeedManager
    from scholarpilot.utils.library import GlobalLibrary
    from scholarpilot.config import get_settings

    lib = GlobalLibrary()
    settings = get_settings()
    manager = FeedManager(lib, settings)

    # 自动选取种子论文
    seeds = manager.setup_seeds(auto=True)

    # 运行订阅，获取推荐
    recommendations = await manager.run_feed()
    for rec in recommendations:
        print(f"[{rec['strategy']}] {rec['title']} ({rec['year']})")
        if rec['reason']:
            print(f"  理由: {rec['reason']}")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from scholarpilot.config import Settings, get_settings
from scholarpilot.utils.library import GlobalLibrary
from scholarpilot.utils.text import normalize_title

logger = logging.getLogger(__name__)


class FeedManager:
    """文献动态订阅管理器.

    基于种子论文，通过三种策略发现新文献，去重后按相关度排序推送。

    Attributes:
        library: 全局文献库实例。
        settings: 配置对象。
        llm_gateway: 可选的 LLM 网关（用于生成推荐理由）。
    """

    def __init__(
        self,
        library: GlobalLibrary,
        settings: Optional[Settings] = None,
        llm_gateway: Any = None,
    ) -> None:
        """初始化 FeedManager.

        Args:
            library: 全局文献库实例。
            settings: 配置对象，默认使用全局配置。
            llm_gateway: LLM 网关实例（可选，无则跳过推荐理由生成）。
        """
        self.library = library
        self.settings = settings or get_settings()
        self.llm_gateway = llm_gateway

        # 引擎实例（惰性初始化）
        self._ss_engine = None
        self._openalex_engine = None
        self._ncpssd_engine = None

    # ===== 引擎惰性初始化 =====

    async def _get_ss_engine(self):
        """获取 Semantic Scholar 引擎实例."""
        if self._ss_engine is None:
            from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
            self._ss_engine = SemanticScholarEngine(
                api_key=self.settings.ss_api_key,
            )
        return self._ss_engine

    async def _get_openalex_engine(self):
        """获取 OpenAlex 引擎实例."""
        if self._openalex_engine is None:
            from scholarpilot.mcp.servers.openalex import OpenAlexEngine
            self._openalex_engine = OpenAlexEngine(
                mailto=self.settings.openalex_mailto,
            )
        return self._openalex_engine

    async def _get_ncpssd_engine(self):
        """获取 NCPSSD 引擎实例."""
        if self._ncpssd_engine is None:
            from scholarpilot.mcp.servers.ncpssd import NCPSSDEngine
            self._ncpssd_engine = NCPSSDEngine()
        return self._ncpssd_engine

    async def _close_engines(self) -> None:
        """关闭所有引擎的 HTTP 客户端."""
        for engine in [self._ss_engine, self._openalex_engine, self._ncpssd_engine]:
            if engine is not None:
                try:
                    await engine.close()
                except Exception:
                    pass

    # ===== 种子论文管理 =====

    def setup_seeds(
        self,
        auto: bool = True,
        count: int = 0,
        manual_paper_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """设置种子论文：自动选取 + 手动增减.

        Args:
            auto: 是否自动选取种子论文。
            count: 自动选取数量（0 表示用配置默认值）。
            manual_paper_ids: 手动添加的文献 ID 列表。

        Returns:
            当前所有种子论文列表。
        """
        if auto:
            seed_count = count or self.settings.feed_auto_seed_count
            self.library.auto_select_seeds(count=seed_count)

        if manual_paper_ids:
            for paper_id in manual_paper_ids:
                self.library.mark_as_seed(paper_id)

        return self.library.get_seed_papers()

    def get_seeds(self) -> list[dict[str, Any]]:
        """获取当前种子论文列表."""
        return self.library.get_seed_papers()

    def add_seed(
        self,
        paper_id: str,
        ss_paper_id: str = "",
        openalex_id: str = "",
    ) -> bool:
        """添加种子论文."""
        return self.library.mark_as_seed(paper_id, ss_paper_id, openalex_id)

    def remove_seed(self, paper_id: str) -> bool:
        """移除种子论文."""
        return self.library.unmark_seed(paper_id)

    # ===== 核心：运行订阅 =====

    async def run_feed(
        self,
        max_recommendations: int = 0,
        strategies: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """运行一次文献订阅，返回推荐列表.

        Args:
            max_recommendations: 最大推荐数（0 表示用配置默认值）。
            strategies: 使用的策略列表（None 表示用配置默认值）。
                        可选: citation, author, topic

        Returns:
            推荐文献列表，每项包含:
            - title, authors, year, abstract, source, url, language
            - strategy: 推荐策略
            - seed_title: 触发推荐的种子论文名称
            - reason: LLM 生成的推荐理由（可选）
            - score: 相关度分数
        """
        max_recs = max_recommendations or self.settings.feed_max_recommendations
        if strategies is None:
            strategies = self.settings.feed_strategies.split(",")

        seeds = self.library.get_seed_papers()
        if not seeds:
            logger.warning("No seed papers found, auto-selecting...")
            seeds = self.library.auto_select_seeds(
                count=self.settings.feed_auto_seed_count
            )
            if not seeds:
                logger.warning("Still no seed papers available for feed")
                return []

        logger.info(f"FeedManager: running with {len(seeds)} seeds, strategies={strategies}")

        all_recommendations: list[dict[str, Any]] = []
        strategy_used: list[str] = []

        # 按策略并行执行
        tasks = []
        if "citation" in strategies:
            tasks.append(self._track_citations(seeds))
            strategy_used.append("citation")
        if "author" in strategies:
            tasks.append(self._track_authors(seeds))
            strategy_used.append("author")
        if "topic" in strategies:
            tasks.append(self._track_topics(seeds))
            strategy_used.append("topic")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Strategy {strategy_used[i]} failed: {result}")
                elif isinstance(result, list):
                    all_recommendations.extend(result)

        # 去重 + 排序 + 截断
        all_recommendations = self._deduplicate(all_recommendations)
        all_recommendations.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_recommendations = all_recommendations[:max_recs]

        # 可选：生成 LLM 推荐理由
        if self.settings.feed_enable_llm_reasons and self.llm_gateway and all_recommendations:
            await self._generate_llm_reasons(all_recommendations, seeds)

        # 记录到历史
        self.library.record_feed_result(
            strategy=",".join(strategy_used),
            seed_count=len(seeds),
            recommendations=all_recommendations,
        )

        # 关闭引擎
        await self._close_engines()

        logger.info(f"FeedManager: {len(all_recommendations)} recommendations generated")
        return all_recommendations

    # ===== 策略 1：反向引用追踪 =====

    async def _track_citations(
        self,
        seeds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """策略 1：追踪种子论文被谁新引用了.

        对每篇有外部 ID 的种子论文：
        - SS: 调用 get_citations 获取引用者列表
        - OpenAlex: 调用 get_citing_works 获取引用者列表
        - 与 known_citation_ids 对比，筛选出新增引用

        Returns:
            新引用者的推荐列表。
        """
        recommendations: list[dict[str, Any]] = []

        ss_engine = await self._get_ss_engine()
        openalex_engine = await self._get_openalex_engine()

        for seed in seeds:
            seed_title = seed.get("title", "")
            ss_id = seed.get("ss_paper_id", "")
            oa_id = seed.get("openalex_id", "")

            # Semantic Scholar 引用追踪
            if ss_id:
                try:
                    citing_papers = await ss_engine.get_citations(ss_id, limit=200)
                    citing_ids = [p.paper_id for p in citing_papers if p.paper_id]

                    # 增量检测
                    diff = self.library.update_citation_tracking(
                        seed["id"],
                        citing_ids,
                        citation_count=len(citing_ids),
                    )
                    new_ids = set(diff["new_ids"].split(",")) if diff["new_ids"] else set()

                    for paper in citing_papers:
                        if paper.paper_id in new_ids:
                            rec = self._ss_paper_to_recommendation(
                                paper, "citation", seed_title
                            )
                            recommendations.append(rec)

                    logger.info(
                        f"Citation tracking (SS) for '{seed_title}': "
                        f"{len(citing_papers)} total, {len(new_ids)} new"
                    )
                except Exception as e:
                    logger.error(f"SS citation tracking failed for '{seed_title}': {e}")

                # SS 有频率限制，适当等待
                await asyncio.sleep(1)

            # OpenAlex 引用追踪
            if oa_id:
                try:
                    result = await openalex_engine.get_citing_works(oa_id, limit=200)
                    citing_ids = [p.work_id for p in result.papers if p.work_id]

                    # 如果 SS 也追踪了同一篇，用同一个 known_citation_ids
                    # 这里用 OpenAlex ID 做增量检测
                    diff = self.library.update_citation_tracking(
                        seed["id"],
                        citing_ids,
                        citation_count=len(citing_ids),
                    )
                    new_ids = set(diff["new_ids"].split(",")) if diff["new_ids"] else set()

                    for paper in result.papers:
                        if paper.work_id in new_ids:
                            rec = self._oa_paper_to_recommendation(
                                paper, "citation", seed_title
                            )
                            recommendations.append(rec)

                    logger.info(
                        f"Citation tracking (OpenAlex) for '{seed_title}': "
                        f"{len(result.papers)} total, {len(new_ids)} new"
                    )
                except Exception as e:
                    logger.error(f"OpenAlex citation tracking failed for '{seed_title}': {e}")

        return recommendations

    # ===== 策略 2：同作者追踪 =====

    async def _track_authors(
        self,
        seeds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """策略 2：追踪种子论文的作者最近发了什么新文章.

        从种子论文中提取作者名，在 SS 和 OpenAlex 中搜索该作者的近期论文。

        Returns:
            同作者的新论文推荐列表。
        """
        recommendations: list[dict[str, Any]] = []

        # 收集所有作者（最多取每篇种子论文的前3位作者）
        author_seed_map: dict[str, str] = {}  # author_name -> seed_title
        for seed in seeds:
            authors = seed.get("authors", [])[:3]
            seed_title = seed.get("title", "")
            for author in authors:
                if author and author not in author_seed_map:
                    author_seed_map[author] = seed_title

        if not author_seed_map:
            return []

        # 只追踪前 10 位作者（避免过多 API 调用）
        authors_to_track = list(author_seed_map.items())[:10]

        ss_engine = await self._get_ss_engine()
        openalex_engine = await self._get_openalex_engine()

        # 当前年份
        current_year = datetime.now().year
        year_filter = f"{current_year - 2}-{current_year}"

        for author_name, seed_title in authors_to_track:
            # 英文作者用 SS 搜索
            if not _is_chinese_name(author_name):
                try:
                    result = await ss_engine.search(
                        query=author_name,
                        limit=10,
                        year=year_filter,
                    )
                    for paper in result.papers:
                        # 检查作者是否真的在这篇论文中
                        if author_name in paper.authors:
                            rec = self._ss_paper_to_recommendation(
                                paper, "author", seed_title
                            )
                            rec["matched_author"] = author_name
                            recommendations.append(rec)
                except Exception as e:
                    logger.error(f"SS author search failed for '{author_name}': {e}")

                await asyncio.sleep(1)

            # 所有作者都可以用 OpenAlex 搜索
            try:
                oa_result = await openalex_engine.search(
                    query=author_name,
                    limit=10,
                    year_start=str(current_year - 2),
                    year_end=str(current_year),
                )
                for paper in oa_result.papers:
                    if author_name in paper.authors:
                        rec = self._oa_paper_to_recommendation(
                            paper, "author", seed_title
                        )
                        rec["matched_author"] = author_name
                        recommendations.append(rec)
            except Exception as e:
                logger.error(f"OpenAlex author search failed for '{author_name}': {e}")

        return recommendations

    # ===== 策略 3：主题增量 =====

    async def _track_topics(
        self,
        seeds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """策略 3：用种子论文的关键词重新检索，找出库中还没有的新文章.

        从种子论文中提取关键词/主题，分别在 NCPSSD（中文）和 OpenAlex/SS（英文）中
        用近期日期过滤重新检索，与全局库对比后返回新文献。

        Returns:
            主题增量的新论文推荐列表。
        """
        recommendations: list[dict[str, Any]] = []

        # 收集关键词：从种子论文的标题和标签中提取
        keywords_zh: list[tuple[str, str]] = []  # (keyword, seed_title)
        keywords_en: list[tuple[str, str]] = []

        for seed in seeds:
            seed_title = seed.get("title", "")
            tags = seed.get("tags", [])
            language = seed.get("language", "")

            # 从标签提取关键词
            for tag in tags:
                if _is_chinese_text(tag):
                    keywords_zh.append((tag, seed_title))
                else:
                    keywords_en.append((tag, seed_title))

            # 如果没有标签，从标题提取前几个词作为关键词
            if not tags and seed_title:
                if _is_chinese_text(seed_title):
                    # 中文标题：取前 4-8 字作为关键词
                    core = seed_title[:8].replace("研究", "").replace("分析", "").strip()
                    if core:
                        keywords_zh.append((core, seed_title))
                else:
                    # 英文标题：取前 3 个实词
                    words = [w for w in seed_title.split() if len(w) > 3][:3]
                    if words:
                        keywords_en.append((" ".join(words), seed_title))

        # 去重关键词（最多各取 5 个）
        seen_zh = set()
        unique_zh = []
        for kw, title in keywords_zh:
            if kw not in seen_zh:
                seen_zh.add(kw)
                unique_zh.append((kw, title))
        unique_zh = unique_zh[:5]

        seen_en = set()
        unique_en = []
        for kw, title in keywords_en:
            if kw not in seen_en:
                seen_en.add(kw)
                unique_en.append((kw, title))
        unique_en = unique_en[:5]

        current_year = datetime.now().year
        year_start = str(current_year - 1)  # 只看最近1年的新文章

        # 中文文献增量检索（NCPSSD）
        if unique_zh:
            ncpssd_engine = await self._get_ncpssd_engine()
            for keyword, seed_title in unique_zh:
                try:
                    result = await ncpssd_engine.search(
                        query=keyword,
                        limit=20,
                        year_start=year_start,
                        year_end=str(current_year),
                    )
                    for paper in result.papers:
                        rec = self._ncpssd_paper_to_recommendation(
                            paper, "topic", seed_title
                        )
                        rec["matched_keyword"] = keyword
                        recommendations.append(rec)
                except Exception as e:
                    logger.error(f"NCPSSD topic search failed for '{keyword}': {e}")

        # 英文文献增量检索（OpenAlex + SS）
        if unique_en:
            openalex_engine = await self._get_openalex_engine()
            ss_engine = await self._get_ss_engine()

            for keyword, seed_title in unique_en:
                # OpenAlex
                try:
                    oa_result = await openalex_engine.search(
                        query=keyword,
                        limit=20,
                        year_start=year_start,
                        year_end=str(current_year),
                        sort="publication_date:desc",
                    )
                    for paper in oa_result.papers:
                        rec = self._oa_paper_to_recommendation(
                            paper, "topic", seed_title
                        )
                        rec["matched_keyword"] = keyword
                        recommendations.append(rec)
                except Exception as e:
                    logger.error(f"OpenAlex topic search failed for '{keyword}': {e}")

                # SS
                try:
                    ss_result = await ss_engine.search(
                        query=keyword,
                        limit=20,
                        year=f"{year_start}-{current_year}",
                    )
                    for paper in ss_result.papers:
                        rec = self._ss_paper_to_recommendation(
                            paper, "topic", seed_title
                        )
                        rec["matched_keyword"] = keyword
                        recommendations.append(rec)
                except Exception as e:
                    logger.error(f"SS topic search failed for '{keyword}': {e}")

                await asyncio.sleep(1)  # SS rate limit

        return recommendations

    # ===== 去重 =====

    def _deduplicate(
        self,
        recommendations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """去重：移除已在全局库中的文献和列表内重复.

        去重逻辑：
        1. 标题规范化去重（与全局库和列表内）
        2. 外部 ID 去重（ss_paper_id, openalex_id）

        Returns:
            去重后的推荐列表。
        """
        seen_titles: set[str] = set()
        seen_external_ids: set[str] = set()
        result: list[dict[str, Any]] = []

        for rec in recommendations:
            title = rec.get("title", "")
            if not title:
                continue

            # 标题规范化去重
            normalized = normalize_title(title)
            if normalized in seen_titles:
                continue

            # 外部 ID 去重
            ext_id = rec.get("ss_paper_id", "") or rec.get("openalex_id", "")
            if ext_id and ext_id in seen_external_ids:
                continue

            # 检查是否已在全局库中
            existing = self.library.find_paper(title)
            if existing:
                # 已在库中，跳过
                continue

            # 检查外部 ID 是否已在库中
            if ext_id:
                in_lib = self.library.get_papers_by_external_id(
                    ss_paper_id=rec.get("ss_paper_id", ""),
                    openalex_id=rec.get("openalex_id", ""),
                )
                if in_lib:
                    continue

            # 通过去重
            seen_titles.add(normalized)
            if ext_id:
                seen_external_ids.add(ext_id)
            result.append(rec)

        return result

    # ===== LLM 推荐理由（可选） =====

    async def _generate_llm_reasons(
        self,
        recommendations: list[dict[str, Any]],
        seeds: list[dict[str, Any]],
    ) -> None:
        """为推荐文献生成 LLM 推荐理由.

        批量处理：将多条推荐合并到一个 prompt 中，减少 API 调用。
        只在有 LLM Gateway 时调用。

        Args:
            recommendations: 推荐列表（原地修改，添加 reason 字段）。
            seeds: 种子论文列表（提供上下文）。
        """
        if not self.llm_gateway or not recommendations:
            return

        # 构建 seed 上下文
        seed_titles = [s.get("title", "") for s in seeds[:5]]
        seed_context = "；".join(seed_titles) if seed_titles else "无"

        # 批量处理（每批 5 条，避免 prompt 过长）
        batch_size = 5
        for i in range(0, len(recommendations), batch_size):
            batch = recommendations[i:i + batch_size]
            papers_text = []
            for j, rec in enumerate(batch, 1):
                title = rec.get("title", "")
                abstract = rec.get("abstract", "")[:200]
                strategy = rec.get("strategy", "")
                papers_text.append(f"{j}. [{strategy}] {title}\n   摘要: {abstract}")

            prompt = (
                f"你关注的研究方向包含以下文献：{seed_context}\n\n"
                f"以下是 {len(batch)} 篇新发现的文献，请为每篇生成一句简短的推荐理由（不超过50字），"
                f"说明它为什么值得关注：\n\n"
                + "\n\n".join(papers_text)
                + "\n\n请按以下格式输出（每篇一行）：\n"
                + "\n".join(f"{j}. 推荐理由" for j in range(1, len(batch) + 1))
            )

            try:
                response = await self.llm_gateway.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.settings.default_casual_model,
                )
                # 解析回复，按行匹配
                lines = response.strip().split("\n")
                for j, rec in enumerate(batch):
                    if j < len(lines):
                        # 提取 "1. xxx" 中的 xxx 部分
                        line = lines[j].strip()
                        reason = line.split(".", 1)[1].strip() if "." in line else line
                        rec["reason"] = reason[:100]  # 限制长度
                    else:
                        rec["reason"] = ""
            except Exception as e:
                logger.error(f"LLM reason generation failed: {e}")
                for rec in batch:
                    rec.setdefault("reason", "")

    # ===== 论文对象转推荐字典 =====

    def _ss_paper_to_recommendation(
        self,
        paper: Any,
        strategy: str,
        seed_title: str,
    ) -> dict[str, Any]:
        """将 SSPaper 转为推荐字典."""
        # 相关度评分：引用数 + 影响力引用
        score = (paper.citation_count or 0) + (paper.influential_citation_count or 0) * 5
        return {
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "abstract": paper.abstract or paper.tldr,
            "source": "semantic_scholar",
            "url": paper.url,
            "doi": paper.doi,
            "language": "en",
            "ss_paper_id": paper.paper_id,
            "openalex_id": "",
            "strategy": strategy,
            "seed_title": seed_title,
            "reason": "",
            "score": score,
        }

    def _oa_paper_to_recommendation(
        self,
        paper: Any,
        strategy: str,
        seed_title: str,
    ) -> dict[str, Any]:
        """将 OpenAlexPaper 转为推荐字典."""
        score = paper.cited_by_count or 0
        return {
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "abstract": paper.abstract,
            "source": "openalex",
            "url": paper.url,
            "doi": paper.doi,
            "language": "en" if paper.language != "zh" else "zh",
            "ss_paper_id": "",
            "openalex_id": paper.work_id,
            "strategy": strategy,
            "seed_title": seed_title,
            "reason": "",
            "score": score,
            "is_open_access": paper.is_open_access,
            "oa_pdf_url": paper.oa_pdf_url,
        }

    def _ncpssd_paper_to_recommendation(
        self,
        paper: Any,
        strategy: str,
        seed_title: str,
    ) -> dict[str, Any]:
        """将 NCPSSDPaper 转为推荐字典."""
        # NCPSSD 没有引用数，用下载和阅读数作为评分
        score = (paper.download_count or 0) + (paper.read_count or 0) * 2
        return {
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "abstract": paper.abstract,
            "source": "ncpssd",
            "url": paper.url,
            "doi": paper.doi,
            "language": "zh",
            "ss_paper_id": "",
            "openalex_id": "",
            "strategy": strategy,
            "seed_title": seed_title,
            "reason": "",
            "score": score,
            "journal": paper.journal,
        }


# ===== 辅助函数 =====

def _is_chinese_text(text: str) -> bool:
    """判断文本是否主要为中文."""
    if not text:
        return False
    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_count > len(text) * 0.3


def _is_chinese_name(name: str) -> bool:
    """判断作者名是否为中文名."""
    if not name:
        return False
    # 中文名通常 2-4 个汉字，不含空格
    if " " not in name and len(name) <= 4:
        return all('\u4e00' <= c <= '\u9fff' for c in name)
    return False
