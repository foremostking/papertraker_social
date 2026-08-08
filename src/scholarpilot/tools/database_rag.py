"""学术数据库 RAG 查询接口.

基于预构建的 database_rag.db (SQLite + FTS5) 和 database_rag.json,
提供按研究主题快速定位数据库、指标和 API 端点的能力。

RAG 数据库覆盖:
    - CNKI 14个专题数据库 (财政/金融/城市统计/县域/人口普查/科技/能源/卫生/
      乡村振兴/数字经济/环境/农产品成本/城乡建设)
    - RESSET 金融研究数据库 (宏观/股票/债券/基金/期货/外汇/行业)
    - CSMAR 国泰安数据库 (股票/公司/基金/债券/期货/经济/汇率/海外)
    - EPS 数据平台 (宏观/行业/贸易/财政/金融/人口/教育/科技)
    - 万方/WoS/ScienceDirect/Springer/CNKI期刊库

Usage:
    from scholarpilot.tools.database_rag import DatabaseRAG

    rag = DatabaseRAG()

    # 按研究主题查找数据库
    results = rag.find_databases_by_topic("财政政策")
    # -> [{"db_key": "cnki_fiscal", "name": "财政专题数据库", ...}]

    # 按关键词搜索指标
    indicators = rag.search_indicators("增值税")
    # -> [{"indicator": "增值税", "database": "财政专题数据库", "path": "..."}]

    # 获取数据库详情
    info = rag.get_database_info("cnki_fiscal")
    # -> {"name": "财政专题数据库", "dimensionId": "...", "categories": [...]}

    # 获取推荐数据获取方案
    plan = rag.get_data_retrieval_plan("货币政策对经济增长的影响")
    # -> {"databases": [...], "indicators": [...], "api_calls": [...]}
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# RAG 数据库文件路径
# 模块位于 scholarpilot/src/scholarpilot/tools/database_rag.py
# 项目根目录为 d:\副业\2026\AI论文自动化工程
_MODULE_FILE = Path(__file__).resolve()
_RAG_DB_PATH = _MODULE_FILE.parent.parent.parent.parent.parent / "database_rag.db"
_RAG_JSON_PATH = _MODULE_FILE.parent.parent.parent.parent.parent / "database_rag.json"

# 备用路径: ScholarPilot 包目录
_PKG_DIR = _MODULE_FILE.parent.parent
_RAG_DB_ALT = _PKG_DIR / "data" / "database_rag.db"
_RAG_JSON_ALT = _PKG_DIR / "data" / "database_rag.json"


def _find_rag_db() -> Path:
    """查找 RAG 数据库文件."""
    for p in [_RAG_DB_PATH, _RAG_DB_ALT]:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"database_rag.db not found. Expected at {_RAG_DB_PATH} or {_RAG_DB_ALT}. "
        "Please run build_rag_index.py first."
    )


def _find_rag_json() -> Path:
    """查找 RAG JSON 文件."""
    for p in [_RAG_JSON_PATH, _RAG_JSON_ALT]:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"database_rag.json not found. Expected at {_RAG_JSON_PATH} or {_RAG_JSON_ALT}. "
        "Please run build_rag_index.py first."
    )


class DatabaseRAG:
    """学术数据库 RAG 查询接口.

    提供三种核心查询能力:
    1. 按研究主题定位数据库 (topic -> databases)
    2. 按关键词搜索指标 (keyword -> indicators, FTS)
    3. 生成数据获取方案 (research topic -> databases + indicators + API calls)

    Attributes:
        db_path: SQLite 数据库路径.
        json_path: JSON 索引文件路径.
    """

    def __init__(self, db_path: Path | None = None, json_path: Path | None = None) -> None:
        """初始化 RAG 查询接口.

        Args:
            db_path: 自定义 SQLite 数据库路径.
            json_path: 自定义 JSON 索引文件路径.
        """
        self.db_path = db_path or _find_rag_db()
        self.json_path = json_path or _find_rag_json()

        # 加载 JSON 索引
        with open(self.json_path, encoding="utf-8") as f:
            self._json_index: dict[str, Any] = json.load(f)

        logger.debug(f"DatabaseRAG initialized: db={self.db_path}, json={self.json_path}")

    # ===== 核心查询 API =====

    def find_databases_by_topic(self, topic: str) -> list[dict[str, Any]]:
        """按研究主题查找匹配的数据库.

        Args:
            topic: 研究主题关键词,如 "财政政策"、"货币供应量"、"股票市场".

        Returns:
            匹配的数据库列表,按相关性评分排序. 每项含:
            - db_key: 数据库键名
            - name: 数据库名称
            - platform: 平台 (CNKI/RESSET/CSMAR/EPS/...)
            - dimensionId: CNKI 维度ID (如有)
            - frequency: 数据频率
            - description: 数据库描述
            - relevance_score: 相关性评分 (0-1)
            - topics: 数据库关联的所有主题
        """
        topic_lower = topic.lower().strip()

        # 先精确匹配
        exact_matches: list[tuple[str, float]] = []
        fuzzy_matches: list[tuple[str, float]] = []

        # 从 JSON topic_index 查找
        topic_index = self._json_index.get("topic_index", {})
        for idx_topic, db_keys in topic_index.items():
            if topic_lower == idx_topic.lower():
                for db_key in db_keys:
                    exact_matches.append((db_key, 1.0))
            elif topic_lower in idx_topic.lower() or idx_topic.lower() in topic_lower:
                for db_key in db_keys:
                    fuzzy_matches.append((db_key, 0.7))

        # 从 SQLite topic_mapping 表查找
        # 双向匹配：1) topic_mapping中的topic包含在用户输入中 2) 用户输入包含topic_mapping中的topic
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                # 方向1: topic_mapping中的topic是用户输入的子串（如"预算"在"零基预算改革"中）
                c.execute(
                    "SELECT database_id, topic, relevance_score FROM topic_mapping "
                    "WHERE ? LIKE '%' || topic || '%'",
                    (topic,),
                )
                for row in c.fetchall():
                    db_id = row["database_id"]
                    score = row["relevance_score"]
                    c.execute("SELECT db_key, name FROM databases WHERE id=?", (db_id,))
                    db_row = c.fetchone()
                    if db_row:
                        pair = (db_row["db_key"], score)
                        if pair not in exact_matches:
                            fuzzy_matches.append(pair)

                # 方向2: 用户输入是topic_mapping中topic的子串（原有逻辑）
                c.execute(
                    "SELECT database_id, topic, relevance_score FROM topic_mapping "
                    "WHERE topic LIKE ?",
                    (f"%{topic}%",),
                )
                for row in c.fetchall():
                    db_id = row["database_id"]
                    score = row["relevance_score"]
                    c.execute("SELECT db_key, name FROM databases WHERE id=?", (db_id,))
                    db_row = c.fetchone()
                    if db_row:
                        pair = (db_row["db_key"], score)
                        if pair not in exact_matches:
                            fuzzy_matches.append(pair)
        except Exception as e:
            logger.warning(f"SQLite topic query failed: {e}")

        # 合并去重
        all_matches: dict[str, float] = {}
        for db_key, score in exact_matches + fuzzy_matches:
            if db_key not in all_matches or score > all_matches[db_key]:
                all_matches[db_key] = score

        # 构建结果
        results: list[dict[str, Any]] = []
        databases = self._json_index.get("databases", {})
        for db_key, score in sorted(all_matches.items(), key=lambda x: -x[1]):
            db_info = databases.get(db_key, {})
            if not db_info:
                # 尝试按名称匹配
                for key, info in databases.items():
                    if info.get("name") == db_key:
                        db_info = info
                        db_key = key
                        break

            if db_info:
                # 过滤非研究类库（research_relevant=False）
                if db_info.get("research_relevant") is False:
                    continue

                results.append({
                    "db_key": db_key,
                    "name": db_info.get("name", db_key),
                    "platform": db_info.get("platform", ""),
                    "dimensionId": db_info.get("dimensionId", ""),
                    "frequency": db_info.get("frequency", ""),
                    "description": db_info.get("description", ""),
                    "relevance_score": score,
                    "topics": db_info.get("topics", []),
                    "access_method": db_info.get("access_method", ""),
                    "research_relevant": db_info.get("research_relevant", True),
                })

        return results

    def search_indicators(
        self, keyword: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """按关键词全文搜索指标.

        使用 SQLite FTS5 全文搜索引擎,支持中文和英文关键词.

        Args:
            keyword: 搜索关键词,如 "增值税"、"GDP"、"财政支出".
            limit: 最多返回结果数.

        Returns:
            匹配的指标列表. 每项含:
            - indicator: 指标名称
            - database: 数据库名称
            - category: 所属分类
            - full_path: 完整路径 (数据库 > 分类 > 指标)
            - platform: 数据库平台
        """
        results: list[dict[str, Any]] = []

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                # FTS5 搜索
                # 对中文关键词,使用前缀通配符匹配（FTS5的unicode61分词器对中文按字分词）
                # "税收" -> "税收*" 可匹配 "税收收入"
                fts_query = f'"{keyword}" OR {keyword}*'
                c.execute(
                    "SELECT indicator_name, full_path, category_name, db_name, platform "
                    "FROM indicators_fts "
                    "WHERE indicators_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                )

                for row in c.fetchall():
                    results.append({
                        "indicator": row["indicator_name"],
                        "database": row["db_name"],
                        "category": row["category_name"],
                        "full_path": row["full_path"],
                        "platform": row["platform"],
                    })
        except sqlite3.OperationalError:
            # FTS 搜索失败,回退到 LIKE 查询
            logger.debug(f"FTS search failed for '{keyword}', falling back to LIKE")
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    c = conn.cursor()
                    c.execute(
                        "SELECT i.indicator_name, i.full_path, c.name as category_name, "
                        "d.name as db_name, d.platform "
                        "FROM indicators i "
                        "JOIN databases d ON i.database_id=d.id "
                        "LEFT JOIN categories c ON i.category_id=c.id "
                        "WHERE i.indicator_name LIKE ? OR i.full_path LIKE ? "
                        "LIMIT ?",
                        (f"%{keyword}%", f"%{keyword}%", limit),
                    )
                    for row in c.fetchall():
                        results.append({
                            "indicator": row["indicator_name"],
                            "database": row["db_name"],
                            "category": row["category_name"],
                            "full_path": row["full_path"],
                            "platform": row["platform"],
                        })
            except Exception as e:
                logger.error(f"Indicator search failed: {e}")

        return results

    def get_database_info(self, db_key: str) -> dict[str, Any] | None:
        """获取指定数据库的详细信息.

        Args:
            db_key: 数据库键名,如 "cnki_fiscal"、"resset"、"csmar".

        Returns:
            数据库完整信息,包括分类和指标列表. 如不存在返回 None.
        """
        databases = self._json_index.get("databases", {})

        # 直接键名匹配
        if db_key in databases:
            return databases[db_key]

        # 模糊匹配 (键名或名称)
        for key, info in databases.items():
            if db_key.lower() in key.lower() or db_key in info.get("name", ""):
                return info

        return None

    def list_all_databases(self) -> list[dict[str, Any]]:
        """列出所有可用数据库.

        Returns:
            所有数据库的摘要信息列表.
        """
        databases = self._json_index.get("databases", {})
        results: list[dict[str, Any]] = []

        for db_key, info in databases.items():
            results.append({
                "db_key": db_key,
                "name": info.get("name", db_key),
                "platform": info.get("platform", ""),
                "dimensionId": info.get("dimensionId", ""),
                "frequency": info.get("frequency", ""),
                "description": info.get("description", ""),
                "topics": info.get("topics", []),
                "category_count": len(info.get("categories", [])),
                "access_method": info.get("access_method", ""),
                "research_relevant": info.get("research_relevant", True),
            })

        return results

    def get_data_retrieval_plan(self, research_topic: str) -> dict[str, Any]:
        """根据研究主题生成数据获取方案.

        综合分析研究主题,推荐最合适的数据库、指标和 API 调用方式.

        Args:
            research_topic: 研究主题描述,如 "货币政策对经济增长的影响".

        Returns:
            数据获取方案,含:
            - topic: 原始研究主题
            - recommended_databases: 推荐数据库列表
            - key_indicators: 关键指标列表
            - api_calls: CNKI API 调用方案
            - access_methods: 访问方式说明
            - notes: 注意事项
        """
        # 1. 按主题查找数据库
        databases = self.find_databases_by_topic(research_topic)

        # 2. 如果没有精确匹配,尝试分解关键词
        if not databases:
            # 提取关键词并搜索
            keywords = extract_keywords(research_topic)
            all_indicators: list[dict[str, Any]] = []
            seen_dbs: set[str] = set()

            for kw in keywords:
                indicators = self.search_indicators(kw, limit=10)
                for ind in indicators:
                    all_indicators.append(ind)
                    if ind["database"] not in seen_dbs:
                        seen_dbs.add(ind["database"])
                        # 查找对应的数据库信息
                        db_info = self._find_db_by_name(ind["database"])
                        if db_info:
                            databases.append(db_info)

            # 使用指标搜索结果补充
            return {
                "topic": research_topic,
                "recommended_databases": databases[:5],
                "key_indicators": all_indicators[:20],
                "api_calls": self._build_api_calls(databases[:3]),
                "access_methods": self._summarize_access_methods(databases[:5]),
                "notes": "基于关键词分解的模糊匹配结果,建议人工确认.",
            }

        # 3. 搜索相关指标
        # 用关键词分解搜索（完整研究主题不会匹配到按关键词存储的指标）
        key_indicators: list[dict[str, Any]] = []
        keywords = extract_keywords(research_topic)
        seen_ind_keys: set[str] = set()
        for kw in keywords:
            indicators = self.search_indicators(kw, limit=10)
            for ind in indicators:
                ind_key = f"{ind.get('indicator', '')}-{ind.get('database', '')}"
                if ind_key not in seen_ind_keys:
                    seen_ind_keys.add(ind_key)
                    key_indicators.append(ind)

        # 4. 构建 API 调用方案
        api_calls = self._build_api_calls(databases[:3])

        # 5. 汇总访问方式
        access_methods = self._summarize_access_methods(databases[:5])

        return {
            "topic": research_topic,
            "recommended_databases": databases[:5],
            "key_indicators": key_indicators[:20],
            "api_calls": api_calls,
            "access_methods": access_methods,
            "notes": "基于 RAG 索引的推荐方案,CNKI 数据可通过 API 直接获取.",
        }

    def get_cnki_api_config(self, db_key: str) -> dict[str, Any] | None:
        """获取 CNKI 数据库的 API 调用配置.

        Args:
            db_key: CNKI 数据库键名,如 "cnki_fiscal".

        Returns:
            API 配置,含:
            - api_base: API 基础 URL
            - dimension_id: 维度 ID
            - frequency: 数据频率
            - endpoints: API 端点列表
            - headers: 请求头
            如不是 CNKI 数据库返回 None.
        """
        db_info = self.get_database_info(db_key)
        if not db_info or db_info.get("platform") != "CNKI":
            return None

        api_config = self._json_index.get("api_config", {})
        return {
            "api_base": api_config.get("cnki_api_base", "https://szjk.cnki.net"),
            "dimension_id": db_info.get("dimensionId", ""),
            "frequency": db_info.get("frequency", "year"),
            "endpoints": api_config.get("cnki_api_endpoints", {}),
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://data.cnki.net/",
                "Content-Type": "application/json",
            },
            "authentication": "VPN IP-based (连接VPN后无需显式登录)",
        }

    # ===== 内部辅助方法 =====

    def _find_db_by_name(self, name: str) -> dict[str, Any] | None:
        """按名称查找数据库."""
        databases = self._json_index.get("databases", {})
        for key, info in databases.items():
            if info.get("name") == name:
                return {
                    "db_key": key,
                    "name": info.get("name", key),
                    "platform": info.get("platform", ""),
                    "dimensionId": info.get("dimensionId", ""),
                    "frequency": info.get("frequency", ""),
                    "description": info.get("description", ""),
                    "relevance_score": 0.5,
                    "topics": info.get("topics", []),
                    "access_method": info.get("access_method", ""),
                }
        return None

    def _build_api_calls(
        self, databases: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """构建 CNKI API 调用方案."""
        api_calls: list[dict[str, Any]] = []
        api_config = self._json_index.get("api_config", {})
        api_base = api_config.get("cnki_api_base", "https://szjk.cnki.net")

        for db in databases:
            if db.get("platform") != "CNKI" or not db.get("dimensionId"):
                continue

            dim_id = db["dimensionId"]
            freq = db.get("frequency", "year")

            api_calls.append({
                "database": db["name"],
                "dimension_id": dim_id,
                "calls": [
                    {
                        "name": "获取数据计数",
                        "method": "POST",
                        "url": f"{api_base}/numerical-db-building/select/getDataCounts",
                        "body": {"dimensionId": dim_id},
                    },
                    {
                        "name": "获取指标树",
                        "method": "POST",
                        "url": f"{api_base}/numerical-db-building/select/getProjectLibIndexTreeForArea",
                        "body": {
                            "dimensionId": dim_id,
                            "timeFrequency": freq,
                            "regionCode": "",
                        },
                    },
                    {
                        "name": "获取可用频率",
                        "method": "POST",
                        "url": f"{api_base}/numerical-db-building/select/getHaveDataOfFrequency",
                        "body": {"dimensionId": dim_id},
                    },
                ],
            })

        return api_calls

    def _summarize_access_methods(
        self, databases: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """汇总各数据库的访问方式."""
        methods: dict[str, list[str]] = {
            "vpn_ip_auth": [],  # VPN IP认证
            "library_portal": [],  # 需通过图书馆入口
            "api_available": [],  # 有API接口
            "browser_only": [],  # 仅限浏览器
        }

        for db in databases:
            name = db.get("name", "")
            platform = db.get("platform", "")
            access = db.get("access_method", "")

            if "VPN" in access or "IP认证" in access:
                methods["vpn_ip_auth"].append(name)

            if "图书馆" in access or "portal" in access.lower():
                methods["library_portal"].append(name)

            if platform == "CNKI" and db.get("dimensionId"):
                methods["api_available"].append(name)

            if "ScienceDirect" in platform or "Springer" in platform:
                methods["browser_only"].append(name)

        return methods


# ===== 便捷函数 =====

def find_databases(topic: str) -> list[dict[str, Any]]:
    """便捷函数: 按研究主题查找数据库."""
    rag = DatabaseRAG()
    return rag.find_databases_by_topic(topic)


def search_indicators(keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    """便捷函数: 按关键词搜索指标."""
    rag = DatabaseRAG()
    return rag.search_indicators(keyword, limit)


def get_data_plan(research_topic: str) -> dict[str, Any]:
    """便捷函数: 生成数据获取方案."""
    rag = DatabaseRAG()
    return rag.get_data_retrieval_plan(research_topic)


if __name__ == "__main__":
    # 演示用法
    rag = DatabaseRAG()

    print("=" * 60)
    print("DatabaseRAG 演示")
    print("=" * 60)

    # 1. 按主题查找数据库
    print("\n[1] 按主题查找: 财政政策")
    results = rag.find_databases_by_topic("财政政策")
    for r in results:
        print(f"  -> {r['name']} (score: {r['relevance_score']})")

    # 2. 搜索指标
    print("\n[2] 搜索指标: 增值税")
    indicators = rag.search_indicators("增值税")
    for ind in indicators:
        print(f"  -> {ind['full_path']}")

    # 3. 生成数据获取方案
    print("\n[3] 数据获取方案: 货币政策对经济增长的影响")
    plan = rag.get_data_retrieval_plan("货币政策对经济增长的影响")
    print(f"  推荐数据库: {len(plan['recommended_databases'])}")
    for db in plan["recommended_databases"]:
        print(f"    - {db['name']} (score: {db.get('relevance_score', 0)})")
    print(f"  关键指标: {len(plan['key_indicators'])}")
    for ind in plan["key_indicators"][:5]:
        print(f"    - {ind.get('full_path', ind.get('indicator', ''))}")
    print(f"  API调用: {len(plan['api_calls'])}")
    for call in plan["api_calls"]:
        print(f"    - {call['database']}: {len(call['calls'])} endpoints")
