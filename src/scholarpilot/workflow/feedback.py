"""FeedbackHandler — 处理用户划词反馈，调用 LLM 重新生成章节.

支持用户在预览面板中选中文字，提出修改意见，
由 LLM 根据反馈重写指定章节内容。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from scholarpilot.config import get_settings
from scholarpilot.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class FeedbackHandler:
    """处理用户对章节内容的反馈，调用 LLM 重新生成.

    Usage:
        handler = FeedbackHandler(project_dir)
        new_content = await handler.rewrite_section(
            section_title="第4章 实证结果与讨论",
            original_content="...",
            feedback="请增加对控制变量选择的理论依据说明",
        )
    """

    # 重写 Prompt 模板
    REWRITE_PROMPT = """你是一位学术论文修改专家。请根据用户的修改意见，重写以下章节内容。

## 原文

{original_content}

## 用户修改意见

{feedback}

## 上下文信息（大纲和前置章节摘要）

{context}

## 要求

1. 严格按照用户修改意见进行修改，不要改变未提及的内容
2. 保持学术论文的严谨风格和专业术语
3. 确保修改后的内容与上下文衔接自然
4. 保持原文的引用格式和编号体系
5. 输出完整的章节内容（不要只输出修改部分）

## 重写结果

"""

    def __init__(
        self,
        project_dir: Path,
        config: Any = None,
    ) -> None:
        """初始化反馈处理器.

        Args:
            project_dir: 项目目录路径
            config: 配置对象（可选）
        """
        self.project_dir = Path(project_dir)
        self.config = config or get_settings()
        self.llm = LLMGateway(self.config)

    async def rewrite_section(
        self,
        section_title: str,
        original_content: str,
        feedback: str,
        selected_text: str = "",
    ) -> str:
        """根据用户反馈重写章节.

        Args:
            section_title: 章节标题
            original_content: 原始章节内容
            feedback: 用户的修改意见
            selected_text: 用户选中的文字（可选，用于精确定位修改范围）

        Returns:
            重写后的章节内容
        """
        # 构建上下文：加载大纲和前置章节摘要
        context = self._build_context(section_title)

        # 如果用户选中了文字，在反馈中标注
        full_feedback = feedback
        if selected_text:
            full_feedback = (
                f"用户选中的文字：\n「{selected_text}」\n\n"
                f"修改意见：\n{feedback}"
            )

        prompt = self.REWRITE_PROMPT.format(
            original_content=original_content,
            feedback=full_feedback,
            context=context,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            result = await self.llm.chat(
                messages=messages,
                model=self.config.default_writing_model,
                temperature=0.5,
            )
            return result.strip()
        except Exception as e:
            logger.error(f"章节重写失败: {e}", exc_info=True)
            raise

    def _build_context(self, section_title: str) -> str:
        """构建重写上下文（大纲 + 前置章节摘要）.

        Args:
            section_title: 当前章节标题

        Returns:
            上下文字符串
        """
        parts = []

        # 加载大纲
        outline_path = self.project_dir / "outline.md"
        if outline_path.exists():
            outline = outline_path.read_text(encoding="utf-8")
            # 只取大纲的前2000字，避免 prompt 过长
            parts.append(f"## 论文大纲\n{outline[:2000]}")

        # 加载 SPEC 中的研究主题
        spec_path = self.project_dir / "SPEC.md"
        if spec_path.exists():
            spec = spec_path.read_text(encoding="utf-8")
            # 提取研究主题部分
            parts.append(f"## 研究规格摘要\n{spec[:1000]}")

        return "\n\n".join(parts) if parts else "（无可用上下文）"

    def save_rewritten_section(
        self,
        section_name: str,
        new_content: str,
        feedback: str,
    ) -> Path:
        """保存重写后的章节（创建版本快照）.

        Args:
            section_name: 章节标识，如 "chapter4"
            new_content: 重写后的内容
            feedback: 用户的修改意见（记录到版本备注）

        Returns:
            保存的文件路径
        """
        from scholarpilot.utils.file_manager import FileManager

        fm = FileManager(self.config.projects_dir)
        section_path = fm.save_section_with_version(
            self.project_dir,
            section_name,
            new_content,
            label="用户修改",
            note=f"基于反馈重写: {feedback[:100]}",
        )

        # 更新步骤输出
        steps_dir = self.project_dir / ".scholar" / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)

        from scholarpilot.events.types import StepOutput

        output = StepOutput(
            phase="section_writing",
            content=self._load_all_chapters(),
            content_type="markdown",
            metadata={"char_count": len(new_content), "rewritten": section_name},
        )
        (steps_dir / "section_writing.json").write_text(
            output.to_json(), encoding="utf-8"
        )

        return section_path

    def _load_all_chapters(self) -> str:
        """加载所有章节内容合并为一个字符串."""
        draft_dir = self.project_dir / "draft"
        if not draft_dir.exists():
            return ""
        parts = []
        for md_file in sorted(draft_dir.glob("chapter*.md")):
            parts.append(md_file.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(parts)

    def load_comments(self) -> list[dict[str, Any]]:
        """加载项目的所有评论.

        Returns:
            评论列表
        """
        comments_path = self.project_dir / ".scholar" / "comments.json"
        if comments_path.exists():
            try:
                return json.loads(comments_path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def add_comment(
        self,
        quote: str,
        text: str,
        section: str = "",
        position: int = 0,
    ) -> dict[str, Any]:
        """添加一条评论.

        Args:
            quote: 被选中的原文
            text: 评论内容
            section: 所在章节
            position: 字符偏移量

        Returns:
            新建的评论对象
        """
        from datetime import datetime, timezone

        comments = self.load_comments()
        comment = {
            "id": f"comment_{len(comments) + 1}",
            "quote": quote,
            "text": text,
            "section": section,
            "position": position,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved": False,
        }
        comments.append(comment)

        comments_path = self.project_dir / ".scholar" / "comments.json"
        comments_path.parent.mkdir(parents=True, exist_ok=True)
        comments_path.write_text(
            json.dumps(comments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return comment

    def resolve_comment(self, comment_id: str) -> bool:
        """标记评论为已解决.

        Args:
            comment_id: 评论 ID

        Returns:
            是否成功标记
        """
        comments = self.load_comments()
        for c in comments:
            if c.get("id") == comment_id:
                c["resolved"] = True
                comments_path = self.project_dir / ".scholar" / "comments.json"
                comments_path.write_text(
                    json.dumps(comments, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
        return False
