"""Context Engine - 上下文引擎.

采用 Context Engineering 方法论：
- 精准的上下文选择和过滤，避免上下文污染
- 不同任务使用不同的上下文窗口
- 分级记忆：工作记忆 → 项目记忆 → 长期记忆
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from scholarpilot.context.memory import ProjectMemory
from scholarpilot.context.profile import ResearcherProfile


@dataclass
class ContextWindow:
    """上下文窗口 - 为特定任务组装的相关上下文."""

    system_prompt: str = ""
    task_prompt: str = ""
    project_context: str = ""
    literature_context: str = ""
    user_context: str = ""
    profile_context: str = ""  # 研究者画像（跨论文长期记忆）
    history: list[dict[str, str]] = field(default_factory=list)

    def to_messages(self) -> list[dict[str, str]]:
        """转换为 LLM 消息格式."""
        messages: list[dict[str, str]] = []

        # 系统提示
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # 组装用户消息
        user_content = ""
        if self.task_prompt:
            user_content += self.task_prompt + "\n\n"
        if self.profile_context:
            user_content += f"{self.profile_context}\n\n"
        if self.project_context:
            user_content += f"## 项目上下文\n{self.project_context}\n\n"
        if self.literature_context:
            user_content += f"## 文献上下文\n{self.literature_context}\n\n"
        if self.user_context:
            user_content += f"## 用户输入\n{self.user_context}\n"

        if user_content:
            messages.append({"role": "user", "content": user_content.strip()})

        # 历史消息
        messages.extend(self.history)

        return messages


class ContextEngine:
    """上下文引擎 - 管理和组装 Agent 的上下文.

    核心职责：
    1. 根据当前任务选择相关上下文
    2. 避免不相关上下文的污染
    3. 管理对话历史长度
    4. 协调短期记忆和长期记忆
    """

    # 最大历史消息轮数
    MAX_HISTORY_TURNS = 10

    def __init__(
        self,
        project_memory: ProjectMemory | None = None,
        researcher_profile: ResearcherProfile | None = None,
    ) -> None:
        """初始化上下文引擎.

        Args:
            project_memory: 项目记忆管理器（当前论文级）。
            researcher_profile: 研究者画像（跨论文长期记忆）。
                如不提供，会自动从默认路径 ~/.scholarpilot/profile.json 加载。
        """
        self.memory = project_memory or ProjectMemory()
        self.profile = researcher_profile or ResearcherProfile()

    def _get_profile_context(self) -> str:
        """获取研究者画像上下文字符串.

        如果画像为空（首次使用），返回空字符串以避免注入无意义内容。
        """
        prefs = self.profile.get_all_preferences()
        papers = self.profile.get_paper_records()
        if not prefs and not papers:
            return ""
        return self.profile.to_context_string()

    def build_topic_analysis_context(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建选题分析的上下文窗口."""
        from scholarpilot.context.prompts import TOPIC_ANALYSIS_PROMPT, get_role_prompt

        return ContextWindow(
            system_prompt=get_role_prompt(role or "topic_analysis", discipline=discipline),
            task_prompt=TOPIC_ANALYSIS_PROMPT.format(user_input=user_input, discipline=discipline),
            profile_context=self._get_profile_context(),
            user_context=user_input,
            history=self._trim_history(history or []),
        )

    def build_spec_generation_context(
        self,
        topic_info: dict[str, Any],
        research_type: str = "empirical",
        cnki_count: int = 0,
        ss_count: int = 0,
        arxiv_count: int = 0,
        core_ratio: float = 0.0,
        competition_level: str = "unknown",
        feasibility_result: str = "",
        key_papers: str = "",
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建论文规格生成的上下文窗口."""
        from scholarpilot.context.prompts import SPEC_GENERATION_PROMPT, get_role_prompt

        task = SPEC_GENERATION_PROMPT.format(
            topic_info=json.dumps(topic_info, ensure_ascii=False, indent=2),
            research_type=research_type,
            cnki_count=cnki_count,
            ss_count=ss_count,
            arxiv_count=arxiv_count,
            core_ratio=f"{core_ratio:.1%}",
            competition_level=competition_level,
            feasibility_result=feasibility_result,
            key_papers=key_papers,
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "spec_generation", discipline=discipline),
            task_prompt=task,
            profile_context=self._get_profile_context(),
            history=self._trim_history(history or []),
        )

    def build_outline_context(
        self,
        spec_content: str,
        research_type: str = "empirical",
        literature_summary: str = "",
        user_thoughts: str = "",
        target_journal: str = "CSSCI核心期刊",
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建大纲生成的上下文窗口."""
        from scholarpilot.context.prompts import OUTLINE_GENERATION_PROMPT, get_role_prompt

        task = OUTLINE_GENERATION_PROMPT.format(
            spec_content=spec_content,
            research_type=research_type,
            literature_summary=literature_summary or "暂无文献综述",
            user_thoughts=user_thoughts or "暂无用户补充",
            target_journal=target_journal,
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "outline", discipline=discipline),
            task_prompt=task,
            project_context=spec_content,
            history=self._trim_history(history or []),
        )

    def build_review_context(
        self,
        research_topic: str,
        papers_list: str,
        stats_result: str,
        research_gaps: str = "",
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建文献综述的上下文窗口."""
        from scholarpilot.context.prompts import REVIEW_WRITING_PROMPT, get_role_prompt

        task = REVIEW_WRITING_PROMPT.format(
            research_topic=research_topic,
            papers_list=papers_list,
            stats_result=stats_result,
            research_gaps=research_gaps or "暂无研究空白分析",
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "section_writing", discipline=discipline),
            task_prompt=task,
            literature_context=papers_list,
            history=self._trim_history(history or []),
        )

    def build_section_writing_context(
        self,
        paper_title: str,
        target_journal: str,
        language: str,
        outline: str,
        section_title: str,
        word_count: int,
        subsections: list[str],
        key_points: list[str],
        research_type: str = "empirical",
        relevant_papers: str = "",
        previous_sections: str = "",
        empirical_data: str = "",
        evidence_context: str = "",
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建章节撰写的上下文窗口.

        注意：outline 参数不再注入到 prompt 中（避免 prompt 过长导致 LLM 空响应）。
        保留参数签名是为了向后兼容。当前章节的小节和要点已足够指导撰写。

        Args:
            evidence_context: 证据矩阵上下文（Phase 2.5生成），注入到task prompt末尾。
                             为空时不注入（向后兼容旧项目）。
            role: 阶段角色key，默认 "section_writing"（学术作者角色卡）。
        """
        from scholarpilot.context.prompts import SECTION_WRITING_PROMPT, get_role_prompt

        task = SECTION_WRITING_PROMPT.format(
            paper_title=paper_title,
            target_journal=target_journal,
            language=language,
            research_type=research_type,
            section_title=section_title,
            word_count=word_count,
            subsections=", ".join(subsections),
            key_points="\n".join(f"- {p}" for p in key_points),
            relevant_papers=relevant_papers or "暂无相关文献",
            previous_sections=previous_sections or "这是第一章",
            empirical_data=empirical_data or "暂无",
        )

        # 注入证据矩阵上下文（如有）
        if evidence_context:
            task += f"\n\n## 本章论点与证据\n{evidence_context}"

        return ContextWindow(
            system_prompt=get_role_prompt(role or "section_writing", discipline=discipline),
            task_prompt=task,
            project_context=outline,
            history=self._trim_history(history or []),
        )

    def build_plan_context(
        self,
        user_input: str,
        project_state: dict[str, Any],
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建执行计划生成的上下文窗口."""
        from scholarpilot.context.prompts import PLAN_GENERATION_PROMPT, get_role_prompt

        task = PLAN_GENERATION_PROMPT.format(
            user_input=user_input,
            project_state=json.dumps(project_state, ensure_ascii=False, indent=2),
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role, discipline=discipline),
            task_prompt=task,
            user_context=user_input,
            history=self._trim_history(history or []),
        )

    def _trim_history(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        """裁剪历史消息，保留最近 N 轮."""
        if len(history) > self.MAX_HISTORY_TURNS * 2:
            return history[-(self.MAX_HISTORY_TURNS * 2):]
        return history

    def build_paragraph_edit_context(
        self,
        paper_title: str,
        section_title: str,
        full_section: str,
        paragraph_index: int,
        target_paragraph: str,
        edit_type: str,
        edit_instruction: str,
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建段落级编辑的上下文窗口."""
        from scholarpilot.context.prompts import PARAGRAPH_EDIT_PROMPT, get_role_prompt

        task = PARAGRAPH_EDIT_PROMPT.format(
            paper_title=paper_title,
            section_title=section_title,
            full_section=full_section[:8000],  # 截断避免超长
            paragraph_index=paragraph_index,
            target_paragraph=target_paragraph,
            edit_type=edit_type,
            edit_instruction=edit_instruction or "按上述操作类型修改",
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "section_writing", discipline=discipline),
            task_prompt=task,
            profile_context=self._get_profile_context(),
            history=self._trim_history(history or []),
        )

    def build_review_analysis_context(
        self,
        review_comments: str,
        paper_structure: str,
        paper_summary: str,
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建审稿意见解析的上下文窗口."""
        from scholarpilot.context.prompts import REVIEW_ANALYSIS_PROMPT, get_role_prompt

        task = REVIEW_ANALYSIS_PROMPT.format(
            review_comments=review_comments,
            paper_structure=paper_structure,
            paper_summary=paper_summary[:6000],
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "claim_calibration", discipline=discipline),
            task_prompt=task,
            profile_context=self._get_profile_context(),
            history=self._trim_history(history or []),
        )

    def build_review_response_context(
        self,
        review_records: str,
        diff_summary: str,
        history: list[dict[str, str]] | None = None,
        role: str | None = None,
        discipline: str = "学术研究",
    ) -> ContextWindow:
        """构建审稿意见回复函生成的上下文窗口."""
        from scholarpilot.context.prompts import REVIEW_RESPONSE_PROMPT, get_role_prompt

        task = REVIEW_RESPONSE_PROMPT.format(
            review_records=review_records,
            diff_summary=diff_summary or "暂无修改对比记录",
        )

        return ContextWindow(
            system_prompt=get_role_prompt(role or "claim_calibration", discipline=discipline),
            task_prompt=task,
            profile_context=self._get_profile_context(),
            history=self._trim_history(history or []),
        )
