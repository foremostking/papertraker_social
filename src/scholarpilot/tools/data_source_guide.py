"""数据源指南生成器。

面向中国金融学实证研究，根据论文 SPEC 中的变量设计，
匹配推荐数据源（CSMAR/Wind/RESSET/NBS等），生成数据采集指南。
已集成 RAG 知识库，支持基于73个机构数据库的智能推荐。

作者: ScholarPilot
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["DataSourceGuide", "generate_data_source_guide"]


# ===== 数据源数据库 =====

DATA_SOURCES = {
    "CSMAR": {
        "name": "国泰安CSMAR数据库",
        "url": "https://www.gtarsc.com",
        "type": "付费",
        "strengths": ["上市公司财务数据", "股票交易数据", "公司治理", "创新专利"],
        "variables": [
            "资产", "负债", "营收", "利润", "roa", "roe", "tobin_q",
            "股票", "股价", "市值", "换手率", "波动率",
            "研发", "专利", "创新",
            "board", "董事", "高管", "薪酬",
        ],
    },
    "Wind": {
        "name": "万得Wind数据库",
        "url": "https://www.wind.com.cn",
        "type": "付费",
        "strengths": ["宏观经济", "地方财政", "债券市场", "行业数据"],
        "variables": [
            "gdp", "cpi", "ppi", "m2", "货币",
            "财政", "税收", "支出", "债务", "城投",
            "债券", "发行", "利差",
            "利率", "汇率",
            "行业", "产业",
        ],
    },
    "RESSET": {
        "name": "锐思RESSET数据库",
        "url": "http://www.resset.cn",
        "type": "付费",
        "strengths": ["金融研究", "债券", "基金"],
        "variables": [
            "基金", "债券", "回购",
            "利率", "收益率",
        ],
    },
    "NBS": {
        "name": "国家统计局",
        "url": "https://www.stats.gov.cn",
        "type": "免费",
        "strengths": ["省级宏观经济", "人口", "就业"],
        "variables": [
            "人口", "pop", "就业", "失业",
            "gdp", "工业", "投资", "消费",
            "城镇", "urban", "收入", "工资",
            "面积", "土地",
        ],
    },
    "MOF": {
        "name": "财政部",
        "url": "http://www.mof.gov.cn",
        "type": "免费",
        "strengths": ["财政收支", "地方政府债务"],
        "variables": [
            "财政", "fiscal", "债务", "debt",
            "预算", "决算", "转移支付",
            "专项债", "一般债", "城投",
        ],
    },
    "CCER": {
        "name": "CCER经济金融数据库",
        "url": "http://www.ccerdata.cn",
        "type": "付费",
        "strengths": ["宏观经济", "区域经济"],
        "variables": [
            "省", "市", "县", "区域",
            "gdp", "财政", "人口",
        ],
    },
    "CNRDS": {
        "name": "中国研究数据服务平台CNRDS",
        "url": "https://www.cnrds.com",
        "type": "付费",
        "strengths": ["文本分析", "ESG", "企业创新"],
        "variables": [
            "esg", "环保", "绿色", "社会责任",
            "文本", "语调", "情感",
            "创新", "专利",
        ],
    },
}

# 变量名关键词到数据源的映射（补充模糊匹配）
VARIABLE_KEYWORD_MAP = {
    "debt": ["Wind", "MOF"],
    "risk": ["Wind", "CSMAR"],
    "fiscal": ["Wind", "MOF", "NBS"],
    "gap": ["Wind", "MOF"],
    "gdp": ["NBS", "Wind"],
    "growth": ["NBS", "Wind"],
    "pop": ["NBS"],
    "density": ["NBS"],
    "urban": ["NBS"],
    "financial": ["CSMAR", "Wind"],
    "development": ["Wind", "NBS"],
    "spatial": ["CCER", "NBS"],
    "innovation": ["CSMAR", "CNRDS"],
    "esg": ["CNRDS"],
    "stock": ["CSMAR", "Wind"],
    "price": ["CSMAR", "Wind"],
}


class DataSourceGuide:
    """数据源指南生成器。

    根据论文 SPEC 中的变量设计，匹配推荐数据源，生成结构化的数据采集指南。
    """

    def __init__(self, project_dir: Path | None = None):
        """初始化。

        Args:
            project_dir: 项目目录路径（可选）。
        """
        self.project_dir = project_dir
        self._rag: Any = None

    def _get_rag(self) -> Any:
        """延迟加载 RAG 知识库."""
        if self._rag is None:
            try:
                from scholarpilot.tools.database_rag import DatabaseRAG
                self._rag = DatabaseRAG()
                logger.info("RAG 知识库已加载")
            except Exception as e:
                logger.warning(f"RAG 知识库加载失败，将使用静态数据源: {e}")
                self._rag = False  # 标记为不可用
        return self._rag if self._rag is not False else None

    def _query_rag_databases(self, research_topic: str) -> list[dict]:
        """通过 RAG 查询推荐数据库.

        Args:
            research_topic: 研究主题.

        Returns:
            推荐数据库列表.
        """
        rag = self._get_rag()
        if rag is None:
            return []

        results = rag.find_databases_by_topic(research_topic)
        # 过滤掉重复的数据库
        seen = set()
        unique = []
        for r in results:
            key = r.get("db_key", r.get("name", ""))
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique[:10]  # 最多10个

    def _query_rag_indicators(self, keywords: list[str]) -> list[dict]:
        """通过 RAG 搜索相关指标.

        Args:
            keywords: 关键词列表.

        Returns:
            匹配的指标列表.
        """
        rag = self._get_rag()
        if rag is None:
            return []

        all_indicators = []
        seen = set()
        for kw in keywords:
            indicators = rag.search_indicators(kw, limit=10)
            for ind in indicators:
                key = f"{ind.get('indicator', '')}-{ind.get('database', '')}"
                if key not in seen:
                    seen.add(key)
                    all_indicators.append(ind)
        return all_indicators[:20]

    def _extract_research_topic(self, spec_text: str) -> str:
        """从 SPEC 文本中提取研究主题."""
        # 尝试匹配标题或研究主题
        patterns = [
            r"(?:研究主题|题目|标题)[：:]\s*(.+?)(?:\n|$)",
            r"#\s*(.+?)(?:\n|$)",
            r"(?:本研究|本文|本研究旨在)[\s，,]*(.+?)(?:[。.])",
        ]
        for pattern in patterns:
            match = re.search(pattern, spec_text)
            if match:
                return match.group(1).strip()

        # 回退：取前200字符作为主题
        return spec_text[:200].replace("\n", " ").strip()

    def generate_guide(self, spec_text: str) -> str:
        """生成数据采集指南（Markdown）。

        Args:
            spec_text: 论文 SPEC 文本。

        Returns:
            Markdown 格式的数据采集指南。
        """
        variables = self._extract_variables(spec_text)
        source_mapping = self._match_sources(variables)

        # RAG 增强：查询推荐数据库和指标
        research_topic = self._extract_research_topic(spec_text)
        rag_databases = self._query_rag_databases(research_topic)
        var_keywords = [v["name"] for v in variables[:5]]
        rag_indicators = self._query_rag_indicators(var_keywords)

        lines: list[str] = []
        lines.append("# 数据采集指南")
        lines.append("")
        lines.append("> 本指南由 ScholarPilot 根据 SPEC 自动生成，帮助研究者快速定位数据来源。")
        if rag_databases:
            lines.append(">")
            lines.append(f"> **RAG 知识库已激活**: 覆盖 73 个机构数据库，智能推荐 {len(rag_databases)} 个相关数据库。")
        lines.append("")

        # 变量清单
        lines.append("## 一、变量清单")
        lines.append("")
        if variables:
            lines.append("| 变量名 | 类型 | 说明 |")
            lines.append("|---|---|---|")
            for var in variables:
                lines.append(f"| {var['name']} | {var['type']} | {var['description']} |")
        else:
            lines.append("（未能从 SPEC 中提取变量，请手动补充）")
        lines.append("")

        # 数据源推荐
        lines.append("## 二、推荐数据源")
        lines.append("")
        if source_mapping:
            lines.append("| 变量 | 推荐数据源 | 获取方式 |")
            lines.append("|---|---|---|")
            for var_name, sources in source_mapping.items():
                source_names = " / ".join(s["name"] for s in sources)
                access_types = " / ".join(s["type"] for s in sources)
                lines.append(f"| {var_name} | {source_names} | {access_types} |")
        else:
            lines.append("（未能自动匹配，请参考下方数据源一览手动选择）")
        lines.append("")

        # 数据源详情
        lines.append("## 三、数据源一览")
        lines.append("")
        for source_id, source in DATA_SOURCES.items():
            lines.append(f"### {source['name']}（{source_id}）")
            lines.append("")
            lines.append(f"- **网址**: {source['url']}")
            lines.append(f"- **类型**: {source['type']}")
            lines.append(f"- **优势领域**: {', '.join(source['strengths'])}")
            lines.append("")

        # RAG 推荐数据库
        if rag_databases:
            lines.append("## 四、RAG 智能推荐数据库")
            lines.append("")
            lines.append(f"> 基于研究主题「{research_topic[:50]}」从 73 个机构数据库中智能匹配。")
            lines.append("")
            lines.append("| 数据库 | 平台 | 分类 | 相关度 | 访问方式 |")
            lines.append("|---|---|---|---|---|")
            for db in rag_databases:
                name = db.get("name", "N/A")[:30]
                platform = db.get("platform", "N/A")
                category = db.get("description", "")[:20] if db.get("description") else "N/A"
                score = db.get("relevance_score", 0)
                access = db.get("access_method", db.get("access", "N/A"))[:30]
                lines.append(f"| {name} | {platform} | {category} | {score:.1f} | {access} |")
            lines.append("")

            # RAG 指标搜索结果
            if rag_indicators:
                lines.append("### 相关指标（RAG FTS 搜索）")
                lines.append("")
                lines.append("| 指标 | 所在数据库 | 完整路径 |")
                lines.append("|---|---|---|")
                for ind in rag_indicators[:10]:
                    indicator = ind.get("indicator", "N/A")[:20]
                    database = ind.get("database", "N/A")[:20]
                    path = ind.get("full_path", "N/A")[:40]
                    lines.append(f"| {indicator} | {database} | {path} |")
                lines.append("")


        # 样本建议
        lines.append("## 五、样本建议")
        lines.append("")
        sample_info = self._extract_sample_info(spec_text)
        if sample_info:
            for key, value in sample_info.items():
                lines.append(f"- **{key}**: {value}")
        else:
            lines.append("- 请根据研究设计确定样本期间和截面单元")
        lines.append("")

        # CSV 模板格式
        lines.append("## 六、CSV 数据模板格式")
        lines.append("")
        if variables:
            var_names = [v["name"] for v in variables]
            header = ",".join(["entity_id", "year"] + var_names)
            lines.append("```csv")
            lines.append(header)
            lines.append("1,2010,,,")
            lines.append("1,2011,,,")
            lines.append("```")
            lines.append("")
            lines.append("**字段说明**:")
            lines.append("- `entity_id`: 截面单元ID（省份/城市/企业编号）")
            lines.append("- `year`: 年份")
            for var in variables:
                lines.append(f"- `{var['name']}`: {var['description']}")
        lines.append("")

        # 数据质量要求
        lines.append("## 七、数据质量要求")
        lines.append("")
        lines.append("1. **缺失值处理**: 缺失比例 >30% 的变量建议删除，5-30% 用插值法，<5% 用均值填充")
        lines.append("2. **异常值处理**: 连续变量建议 1%/99% 缩尾处理（winsorize）")
        lines.append("3. **价格平减**: 涉及金额的变量需用 CPI 或 GDP 平减指数调整为实际值")
        lines.append("4. **对数化**: 变量取对数可缓解异方差和偏态分布（变量名加 ln_ 前缀）")
        lines.append("5. **数据一致性**: 跨年份数据需确保口径一致，注意统计标准变更")
        lines.append("")

        lines.append("---")
        lines.append("*生成自 ScholarPilot 数据源指南模块*")

        return "\n".join(lines)

    def _extract_variables(self, spec_text: str) -> list[dict]:
        """从 SPEC 文本提取变量定义。

        Args:
            spec_text: SPEC 文本。

        Returns:
            变量列表，每个含 name, type, description。
        """
        variables: list[dict] = []

        # 尝试匹配变量设计段落
        var_section_patterns = [
            r"变量设计[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量定义[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"核心变量[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量设计(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量定义(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
        ]

        var_section = ""
        for pattern in var_section_patterns:
            match = re.search(pattern, spec_text, re.DOTALL)
            if match:
                var_section = match.group(1)
                break

        if not var_section:
            return variables

        # 提取变量定义
        var_patterns = [
            r"[-•]\s*(?:被解释变量|核心解释变量|控制变量|中介变量|调节变量)[：:]\s*(\w+)\s*[（(]([^）)]+)",
            r"[-•]\s*(\w+)[：:]\s*([^\n]{2,30})",
            r"(\w+)\s*[（(]([^）)]{2,30})",
        ]

        seen = set()
        for pattern in var_patterns:
            for match in re.finditer(pattern, var_section):
                name = match.group(1).strip()
                desc = match.group(2).strip()
                if name and name not in seen and len(name) < 30:
                    # 判断变量类型
                    context = var_section[:match.start()]
                    if "被解释" in context[-50:]:
                        var_type = "被解释变量"
                    elif "核心解释" in context[-50:] or "解释变量" in context[-50:]:
                        var_type = "核心解释变量"
                    elif "控制" in context[-50:]:
                        var_type = "控制变量"
                    elif "中介" in context[-50:]:
                        var_type = "中介变量"
                    elif "调节" in context[-50:]:
                        var_type = "调节变量"
                    else:
                        var_type = "变量"

                    variables.append({
                        "name": name,
                        "type": var_type,
                        "description": desc,
                    })
                    seen.add(name)

        return variables

    def _match_sources(self, variables: list[dict]) -> dict:
        """将变量匹配到数据源。

        Args:
            variables: 变量列表。

        Returns:
            {var_name: [source_dict, ...]} 映射。
        """
        mapping: dict[str, list[dict]] = {}

        for var in variables:
            name = var["name"].lower()
            matched_sources: list[dict] = []
            matched_ids: set[str] = set()

            # 1. 精确关键词匹配
            for keyword, source_ids in VARIABLE_KEYWORD_MAP.items():
                if keyword in name:
                    for sid in source_ids:
                        if sid not in matched_ids:
                            matched_sources.append(DATA_SOURCES[sid])
                            matched_ids.add(sid)

            # 2. 数据源变量列表匹配
            if not matched_sources:
                for sid, source in DATA_SOURCES.items():
                    for src_var in source["variables"]:
                        if src_var in name or name in src_var:
                            if sid not in matched_ids:
                                matched_sources.append(source)
                                matched_ids.add(sid)
                            break

            # 3. 默认推荐 Wind + NBS
            if not matched_sources:
                matched_sources = [DATA_SOURCES["Wind"], DATA_SOURCES["NBS"]]

            mapping[var["name"]] = matched_sources

        return mapping

    def _extract_sample_info(self, spec_text: str) -> dict:
        """从 SPEC 提取样本信息。

        Args:
            spec_text: SPEC 文本。

        Returns:
            样本信息字典。
        """
        info: dict[str, str] = {}

        # 时间范围
        time_match = re.search(r"(\d{4})\s*[-—~]\s*(\d{4})", spec_text)
        if time_match:
            info["样本期间"] = f"{time_match.group(1)}-{time_match.group(2)}"

        # 截面单元
        if "省份" in spec_text or "省级" in spec_text:
            info["截面单元"] = "省份"
        elif "地级市" in spec_text or "城市" in spec_text:
            info["截面单元"] = "地级市"
        elif "县级" in spec_text or "区县" in spec_text:
            info["截面单元"] = "区县"
        elif "企业" in spec_text or "公司" in spec_text:
            info["截面单元"] = "企业"
        elif "行业" in spec_text:
            info["截面单元"] = "行业"

        # 数据频率
        if "季度" in spec_text:
            info["数据频率"] = "季度"
        elif "月度" in spec_text:
            info["数据频率"] = "月度"
        elif "年度" in spec_text or "年面板" in spec_text:
            info["数据频率"] = "年度"

        # 数据来源
        for source_name in ["Wind", "CSMAR", "RESSET", "国家统计局", "财政部"]:
            if source_name in spec_text:
                info["数据来源"] = source_name
                break

        return info


def generate_data_source_guide(spec_text: str, output_path: Path | None = None) -> str:
    """生成数据采集指南的便捷函数。

    Args:
        spec_text: 论文 SPEC 文本。
        output_path: 输出文件路径（可选）。如提供则写入文件。

    Returns:
        Markdown 格式的数据采集指南。
    """
    guide = DataSourceGuide()
    content = guide.generate_guide(spec_text)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info("数据采集指南已保存: %s", output_path)

    return content
