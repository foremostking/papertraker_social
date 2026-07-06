"""Global Literature Library - 全局文献库管理器.

管理跨论文项目的文献复用，解决科研工作者的真实痛点：
- 写3-4篇"地方政府债务"相关论文，文献高度重叠
- 每次重新检索浪费 API 额度，PDF 重复占磁盘
- 在 A 论文读过分析的文献，B 论文还要重新检索

设计理念：
- 全局文献库存储所有检索过的文献元数据（~/.scholarpilot/library/）
- 项目通过引用链接复用全局文献，不存副本
- 新项目检索时先查全局库，命中则直接复用
- 记录每篇文献被哪些项目引用过，支持"这篇文献你已在 X 篇论文中使用"

存储结构:
    ~/.scholarpilot/library/
    ├── library.json      # 文献元数据索引
    └── pdfs/             # 全局 PDF 存储（按 paper_id 命名）
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _normalize_title(title: str) -> str:
    """规范化标题用于去重比较.

    去除空格、标点、大小写差异，使"地方政府债务研究"和"地方政府 债务 研究"能匹配。
    """
    # 去除所有空格和常见标点
    cleaned = re.sub(r"[\s\u3000，。、；：！？\u201c\u201d\u2018\u2019（）()\[\]【】]", "", title)
    return cleaned.lower()


def _generate_paper_id(title: str, year: str | int | None = "") -> str:
    """根据标题和年份生成稳定的文献 ID.

    使用标题规范化+年份的 hash，确保同一篇文献多次检索得到相同 ID。
    """
    normalized = _normalize_title(title)
    key = f"{normalized}_{year}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


class GlobalLibrary:
    """全局文献库管理器.

    所有论文项目共享同一份文献库，实现跨项目文献复用。

    Usage:
        lib = GlobalLibrary()  # 默认 ~/.scholarpilot/library/

        # 检索前先查全局库
        existing = lib.find_paper("地方政府债务风险研究", year=2024)
        if existing:
            print(f"已在 {len(existing['used_by_projects'])} 篇论文中使用")
        else:
            # 未命中才调 API 检索
            paper_data = search_api(...)
            lib.add_paper(paper_data, project_name="debt_paper")

        # 导出项目引用的文献为 BibTeX
        papers = lib.get_project_papers("debt_paper")
        bib = lib.to_bibtex([p["id"] for p in papers])
    """

    def __init__(self, library_dir: Path | str | None = None) -> None:
        """初始化全局文献库.

        Args:
            library_dir: 文献库目录。默认 ~/.scholarpilot/library/。
        """
        if library_dir is None:
            library_dir = Path.home() / ".scholarpilot" / "library"
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)

        self.library_path = self.library_dir / "library.json"
        self.pdfs_dir = self.library_dir / "pdfs"
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.feed_history_path = self.library_dir / "feed_history.json"

        self._data: dict[str, Any] = {"papers": {}, "created_at": None}
        self._feed_history: list[dict[str, Any]] = []
        self._load_from_disk()
        self._load_feed_history()

    # ===== 文献增删改查 =====

    def add_paper(
        self,
        paper_data: dict[str, Any],
        project_name: str = "",
    ) -> dict[str, Any]:
        """添加文献到全局库.

        如果文献已存在（标题+年份去重），则更新信息并记录项目引用。
        不会重复添加。

        Args:
            paper_data: 文献数据，建议包含:
                - title: 标题（必填）
                - authors: 作者列表
                - year: 年份
                - journal: 期刊/来源
                - doi: DOI
                - abstract: 摘要
                - source: 检索来源 (cnki/semantic_scholar/arxiv/openalex/ncpssd)
                - url: 原文链接
                - language: 语言 (zh/en)
            project_name: 引用该文献的项目名称。

        Returns:
            文献记录（含生成的 id）。
        """
        title = paper_data.get("title", "")
        year = paper_data.get("year", "")
        paper_id = _generate_paper_id(title, year)

        if paper_id in self._data["papers"]:
            # 已存在：更新信息，记录项目引用
            existing = self._data["papers"][paper_id]
            # 合并更新（新数据覆盖旧数据，但保留 used_by_projects）
            for key, value in paper_data.items():
                if value:  # 只更新非空值
                    existing[key] = value
            # 确保订阅字段存在（兼容旧数据）
            existing.setdefault("ss_paper_id", "")
            existing.setdefault("openalex_id", "")
            existing.setdefault("is_seed", False)
            existing.setdefault("subscribed_at", "")
            existing.setdefault("known_citation_ids", [])
            existing.setdefault("last_citation_count", 0)
            existing.setdefault("last_checked_citations_at", "")
            if project_name and project_name not in existing.get("used_by_projects", []):
                existing.setdefault("used_by_projects", []).append(project_name)
            existing["updated_at"] = datetime.now().isoformat()
            self._save_to_disk()
            return existing
        else:
            # 新文献
            paper_data["id"] = paper_id
            paper_data.setdefault("authors", [])
            paper_data.setdefault("abstract", "")
            paper_data.setdefault("source", "")
            paper_data.setdefault("language", "")
            paper_data.setdefault("tags", [])
            paper_data.setdefault("has_pdf", False)
            # 订阅相关字段
            paper_data.setdefault("ss_paper_id", "")
            paper_data.setdefault("openalex_id", "")
            paper_data.setdefault("is_seed", False)
            paper_data.setdefault("subscribed_at", "")
            paper_data.setdefault("known_citation_ids", [])
            paper_data.setdefault("last_citation_count", 0)
            paper_data.setdefault("last_checked_citations_at", "")
            paper_data["used_by_projects"] = [project_name] if project_name else []
            paper_data["added_at"] = datetime.now().isoformat()
            paper_data["updated_at"] = paper_data["added_at"]
            self._data["papers"][paper_id] = paper_data
            self._save_to_disk()
            return paper_data

    def find_paper(
        self,
        title: str,
        year: str | int | None = None,
    ) -> dict[str, Any] | None:
        """按标题查重（规范化匹配）.

        Args:
            title: 文献标题。
            year: 年份（可选，提高匹配精度）。

        Returns:
            匹配的文献记录，未找到返回 None。
        """
        normalized = _normalize_title(title)
        for paper in self._data["papers"].values():
            if _normalize_title(paper.get("title", "")) == normalized:
                if year is None or str(paper.get("year", "")) == str(year):
                    return paper
        return None

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """按 ID 获取文献."""
        return self._data["papers"].get(paper_id)

    def search(
        self,
        keyword: str = "",
        source: str = "",
        project_name: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """搜索文献库.

        Args:
            keyword: 关键词（匹配标题、摘要、标签）。
            source: 检索来源筛选。
            project_name: 只返回被该项目引用的文献。
            limit: 最多返回数量。

        Returns:
            匹配的文献列表。
        """
        results = []
        keyword_lower = keyword.lower() if keyword else ""

        for paper in self._data["papers"].values():
            # 项目筛选
            if project_name and project_name not in paper.get("used_by_projects", []):
                continue
            # 来源筛选
            if source and paper.get("source", "") != source:
                continue
            # 关键词筛选
            if keyword_lower:
                searchable = " ".join([
                    paper.get("title", ""),
                    paper.get("abstract", ""),
                    " ".join(paper.get("tags", [])),
                ]).lower()
                if keyword_lower not in searchable:
                    continue
            results.append(paper)

        return results[:limit]

    def get_project_papers(self, project_name: str) -> list[dict[str, Any]]:
        """获取某项目引用的所有文献."""
        return [
            p for p in self._data["papers"].values()
            if project_name in p.get("used_by_projects", [])
        ]

    def link_to_project(self, paper_id: str, project_name: str) -> bool:
        """记录文献被某项目引用.

        Returns:
            是否成功（文献不存在返回 False）。
        """
        paper = self._data["papers"].get(paper_id)
        if not paper:
            return False
        if project_name not in paper.get("used_by_projects", []):
            paper.setdefault("used_by_projects", []).append(project_name)
            paper["updated_at"] = datetime.now().isoformat()
            self._save_to_disk()
        return True

    def remove_paper(self, paper_id: str) -> bool:
        """从库中删除文献（同时删除 PDF）."""
        if paper_id not in self._data["papers"]:
            return False
        del self._data["papers"][paper_id]
        pdf_path = self.pdfs_dir / f"{paper_id}.pdf"
        if pdf_path.exists():
            pdf_path.unlink()
        self._save_to_disk()
        return True

    # ===== PDF 管理 =====

    def save_pdf(self, paper_id: str, pdf_bytes: bytes) -> Path:
        """保存 PDF 到全局库.

        Args:
            paper_id: 文献 ID。
            pdf_bytes: PDF 文件内容。

        Returns:
            PDF 文件路径。
        """
        pdf_path = self.pdfs_dir / f"{paper_id}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # 更新文献记录
        paper = self._data["papers"].get(paper_id)
        if paper:
            paper["has_pdf"] = True
            self._save_to_disk()

        return pdf_path

    def get_pdf_path(self, paper_id: str) -> Path | None:
        """获取 PDF 路径（不存在返回 None）."""
        pdf_path = self.pdfs_dir / f"{paper_id}.pdf"
        return pdf_path if pdf_path.exists() else None

    # ===== 批量操作 =====

    def add_papers_batch(
        self,
        papers: list[dict[str, Any]],
        project_name: str = "",
    ) -> tuple[int, int]:
        """批量添加文献，返回（新增数, 复用数）.

        科研场景：检索返回50篇文献，一次性导入全局库。
        已存在的文献自动记录项目引用，不重复存储。
        """
        new_count = 0
        reuse_count = 0
        for paper_data in papers:
            title = paper_data.get("title", "")
            year = paper_data.get("year", "")
            existing = self.find_paper(title, year)
            if existing:
                self.link_to_project(existing["id"], project_name)
                reuse_count += 1
            else:
                self.add_paper(paper_data, project_name)
                new_count += 1
        return new_count, reuse_count

    def to_bibtex(self, paper_ids: list[str]) -> str:
        """将指定文献导出为 BibTeX 格式.

        Args:
            paper_ids: 要导出的文献 ID 列表。

        Returns:
            BibTeX 格式字符串。
        """
        entries = []
        for paper_id in paper_ids:
            paper = self._data["papers"].get(paper_id)
            if not paper:
                continue

            # 生成 citation key: 第一作者姓+年份+标题首词
            authors = paper.get("authors", [])
            first_author = authors[0] if authors else "anonymous"
            # 取姓氏（中文取全名首2字，英文取最后词）
            if paper.get("language") == "zh" or len(first_author) <= 4:
                author_key = first_author[:2] if len(first_author) >= 2 else first_author
            else:
                author_key = first_author.split()[-1].lower()
            year = paper.get("year", "nd")
            title_first_word = re.sub(r"[^\w]", "", paper.get("title", "")[:10].lower())
            cite_key = f"{author_key}{year}{title_first_word}"

            # 生成 BibTeX 条目
            entry = f"@article{{{cite_key},\n"
            entry += f"  title = {{{paper.get('title', '')}}},\n"
            if authors:
                entry += f"  author = {{{' and '.join(authors)}}},\n"
            if year:
                entry += f"  year = {{{year}}},\n"
            if paper.get("journal"):
                entry += f"  journal = {{{paper['journal']}}},\n"
            if paper.get("doi"):
                entry += f"  doi = {{{paper['doi']}}},\n"
            if paper.get("url"):
                entry += f"  url = {{{paper['url']}}},\n"
            if paper.get("abstract"):
                # 摘要截断避免过长
                abstract = paper["abstract"][:200]
                entry += f"  abstract = {{{abstract}}},\n"
            entry += "}\n"
            entries.append(entry)

        return "\n".join(entries)

    # ===== 种子论文管理（订阅功能） =====

    def get_seed_papers(self) -> list[dict[str, Any]]:
        """获取所有种子论文.

        种子论文是用户关注的焦点文献，系统会定期追踪谁引用了它们。

        Returns:
            种子论文记录列表。
        """
        seeds = [
            p for p in self._data["papers"].values()
            if p.get("is_seed", False)
        ]
        # 按订阅时间排序
        seeds.sort(key=lambda p: p.get("subscribed_at", ""), reverse=True)
        return seeds

    def mark_as_seed(
        self,
        paper_id: str,
        ss_paper_id: str = "",
        openalex_id: str = "",
    ) -> bool:
        """将文献标记为种子论文.

        Args:
            paper_id: 文献 ID。
            ss_paper_id: Semantic Scholar 论文 ID（用于引用追踪）。
            openalex_id: OpenAlex Work ID（用于引用追踪）。

        Returns:
            是否成功。
        """
        paper = self._data["papers"].get(paper_id)
        if not paper:
            return False
        paper["is_seed"] = True
        paper["subscribed_at"] = datetime.now().isoformat()
        if ss_paper_id:
            paper["ss_paper_id"] = ss_paper_id
        if openalex_id:
            paper["openalex_id"] = openalex_id
        paper["updated_at"] = datetime.now().isoformat()
        self._save_to_disk()
        return True

    def unmark_seed(self, paper_id: str) -> bool:
        """取消种子论文标记.

        Returns:
            是否成功。
        """
        paper = self._data["papers"].get(paper_id)
        if not paper:
            return False
        paper["is_seed"] = False
        paper["subscribed_at"] = ""
        paper["updated_at"] = datetime.now().isoformat()
        self._save_to_disk()
        return True

    def auto_select_seeds(
        self,
        count: int = 5,
        min_citations: int = 5,
    ) -> list[dict[str, Any]]:
        """从全局文献库中自动选取种子论文.

        策略：选取引用数最高、被多个项目复用的文献作为种子。
        已标记为种子的不重复选取。

        Args:
            count: 选取数量。
            min_citations: 最低引用数门槛。

        Returns:
            被选中的种子论文列表。
        """
        candidates = []
        for paper in self._data["papers"].values():
            if paper.get("is_seed", False):
                continue
            # 引用数：优先用 last_citation_count，否则从原始数据推断
            citation_count = paper.get("last_citation_count", 0)
            if not citation_count:
                # 从 source 特定字段推断
                citation_count = paper.get("citation_count", 0) or paper.get("cited_by_count", 0) or 0
            if citation_count < min_citations:
                continue
            # 复用次数加分
            reuse_count = len(paper.get("used_by_projects", []))
            score = citation_count + reuse_count * 10
            candidates.append((score, paper))

        # 按分数降序选取
        candidates.sort(key=lambda x: x[0], reverse=True)
        selected = []
        for _, paper in candidates[:count]:
            paper["is_seed"] = True
            paper["subscribed_at"] = datetime.now().isoformat()
            selected.append(paper)
        if selected:
            self._save_to_disk()
        return selected

    def set_external_ids(
        self,
        paper_id: str,
        ss_paper_id: str = "",
        openalex_id: str = "",
    ) -> bool:
        """设置文献的外部 API ID（用于引用追踪）.

        Args:
            paper_id: 文献 ID。
            ss_paper_id: Semantic Scholar 论文 ID。
            openalex_id: OpenAlex Work ID。

        Returns:
            是否成功。
        """
        paper = self._data["papers"].get(paper_id)
        if not paper:
            return False
        if ss_paper_id:
            paper["ss_paper_id"] = ss_paper_id
        if openalex_id:
            paper["openalex_id"] = openalex_id
        paper["updated_at"] = datetime.now().isoformat()
        self._save_to_disk()
        return True

    # ===== 引用追踪状态管理 =====

    def update_citation_tracking(
        self,
        paper_id: str,
        citing_ids: list[str],
        citation_count: int = 0,
    ) -> dict[str, str]:
        """更新文献的引用追踪状态，返回新增的引用 ID.

        增量检测核心：对比已知引用 ID 列表与新获取的列表，
        返回新增部分（即新引用该论文的文献）。

        Args:
            paper_id: 文献 ID。
            citing_ids: 最新获取的引用者 ID 列表。
            citation_count: 最新引用总数。

        Returns:
            {"new_ids": "id1,id2,...", "total_new": "3"} 格式的字典。
            new_ids 为新增引用者 ID 的逗号分隔字符串。
        """
        paper = self._data["papers"].get(paper_id)
        if not paper:
            return {"new_ids": "", "total_new": "0"}

        known_ids = set(paper.get("known_citation_ids", []))
        current_ids = set(citing_ids)
        new_ids = current_ids - known_ids

        # 更新已知引用列表（保持原有顺序 + 追加新ID）
        existing_ordered = paper.get("known_citation_ids", [])
        updated_list = [id_ for id_ in existing_ordered if id_ in current_ids]
        updated_list.extend(sorted(current_ids - set(updated_list)))
        paper["known_citation_ids"] = updated_list
        paper["last_citation_count"] = citation_count or len(current_ids)
        paper["last_checked_citations_at"] = datetime.now().isoformat()
        paper["updated_at"] = datetime.now().isoformat()
        self._save_to_disk()

        return {
            "new_ids": ",".join(sorted(new_ids)),
            "total_new": str(len(new_ids)),
        }

    def get_papers_by_external_id(
        self,
        ss_paper_id: str = "",
        openalex_id: str = "",
    ) -> list[dict[str, Any]]:
        """按外部 API ID 查找文献（用于引用追踪结果去重）.

        Args:
            ss_paper_id: Semantic Scholar 论文 ID。
            openalex_id: OpenAlex Work ID。

        Returns:
            匹配的文献列表。
        """
        results = []
        for paper in self._data["papers"].values():
            if ss_paper_id and paper.get("ss_paper_id") == ss_paper_id:
                results.append(paper)
            if openalex_id and paper.get("openalex_id") == openalex_id:
                if paper not in results:
                    results.append(paper)
        return results

    # ===== Feed 历史记录 =====

    def record_feed_result(
        self,
        strategy: str,
        seed_count: int,
        recommendations: list[dict[str, Any]],
    ) -> None:
        """记录一次 feed 推送结果.

        Args:
            strategy: 使用的策略 (citation/author/topic)。
            seed_count: 本次使用的种子论文数。
            recommendations: 推荐文献列表，每项含 title/year/source/reason。
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy,
            "seed_count": seed_count,
            "recommendation_count": len(recommendations),
            "recommendations": recommendations[:50],  # 最多保留50条
        }
        self._feed_history.insert(0, record)
        # 保留最近 100 次记录
        self._feed_history = self._feed_history[:100]
        self._save_feed_history()

    def get_feed_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取 feed 推送历史.

        Args:
            limit: 返回条数。

        Returns:
            历史记录列表（最新在前）。
        """
        return self._feed_history[:limit]

    def get_last_feed_time(self) -> str:
        """获取上次 feed 推送时间."""
        if self._feed_history:
            return self._feed_history[0].get("timestamp", "")
        return ""

    # ===== 统计与展示 =====

    def get_stats(self) -> dict[str, Any]:
        """获取文献库统计信息."""
        papers = self._data["papers"]
        total = len(papers)
        with_pdf = sum(1 for p in papers.values() if p.get("has_pdf"))
        by_source: dict[str, int] = {}
        by_language: dict[str, int] = {}
        for p in papers.values():
            src = p.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
            lang = p.get("language", "unknown")
            by_language[lang] = by_language.get(lang, 0) + 1

        # 统计被多个项目引用的文献数
        shared = sum(1 for p in papers.values() if len(p.get("used_by_projects", [])) > 1)
        # 种子论文数
        seed_count = sum(1 for p in papers.values() if p.get("is_seed", False))

        return {
            "total_papers": total,
            "with_pdf": with_pdf,
            "by_source": by_source,
            "by_language": by_language,
            "shared_papers": shared,
            "seed_papers": seed_count,
            "last_feed_time": self.get_last_feed_time(),
            "projects": self._get_all_projects(),
        }

    def _get_all_projects(self) -> list[str]:
        """获取所有引用过文献的项目名."""
        projects = set()
        for paper in self._data["papers"].values():
            projects.update(paper.get("used_by_projects", []))
        return sorted(projects)

    # ===== 持久化 =====

    def _load_from_disk(self) -> None:
        """从磁盘加载文献库."""
        if not self.library_path.exists():
            return
        try:
            content = self.library_path.read_text(encoding="utf-8")
            loaded = json.loads(content)
            if "papers" in loaded:
                self._data["papers"] = loaded["papers"]
            if "created_at" in loaded:
                self._data["created_at"] = loaded["created_at"]
            else:
                self._data["created_at"] = datetime.now().isoformat()
        except (json.JSONDecodeError, OSError):
            pass

    def _save_to_disk(self) -> None:
        """保存文献库到磁盘."""
        self._data["updated_at"] = datetime.now().isoformat()
        if not self._data.get("created_at"):
            self._data["created_at"] = self._data["updated_at"]

        self.library_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_feed_history(self) -> None:
        """从磁盘加载 feed 历史."""
        if not self.feed_history_path.exists():
            return
        try:
            content = self.feed_history_path.read_text(encoding="utf-8")
            self._feed_history = json.loads(content)
        except (json.JSONDecodeError, OSError):
            self._feed_history = []

    def _save_feed_history(self) -> None:
        """保存 feed 历史到磁盘."""
        self.feed_history_path.write_text(
            json.dumps(self._feed_history, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
