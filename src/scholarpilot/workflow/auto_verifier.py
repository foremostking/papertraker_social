"""AutoVerifier — 角色自动校验器（Actor-Critic 双层架构）.

在每个阶段产出后，由不同职责的 Critic 角色自动校验质量。
校验通过则自动放行，不通过才升级到人工审核。

决策分级：
  score >= 80 且无 critical → "pass"  自动通过
  score 50-79 或有 critical 但可修复 → "fix"  记录问题后继续
  score < 50 或有不可修复 critical → "human"  升级人工审核

Usage::
    verifier = AutoVerifier(llm=agent.llm, callback=agent._callback)
    result = await verifier.verify(
        phase="topic_analysis",
        content="...",
        user_input="地方政府债务对经济增长的影响",
        discipline="经济学",
    )
    if result.decision == "pass":
        # 自动通过
        pass
    elif result.decision == "human":
        # 升级人工审核
        pass
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from scholarpilot.context.prompts.roles import get_role_prompt
from scholarpilot.context.prompts.verification import (
    ACTOR_CRITIC_MAP,
    VERIFICATION_PROMPTS,
)

logger = logging.getLogger(__name__)


@dataclass
class VerificationIssue:
    """校验发现的问题."""

    severity: str  # "critical" | "warning" | "info"
    location: str = ""
    description: str = ""
    suggestion: str = ""


@dataclass
class VerificationResult:
    """校验结果."""

    phase: str
    score: int = 0  # 0-100
    decision: str = "pass"  # "pass" | "fix" | "human"
    issues: list[VerificationIssue] = field(default_factory=list)
    summary: str = ""
    critic_name: str = ""
    raw_response: str = ""

    @property
    def passed(self) -> bool:
        """是否自动通过."""
        return self.decision == "pass"

    @property
    def needs_human(self) -> bool:
        """是否需要人工审核."""
        return self.decision == "human"

    @property
    def critical_issues(self) -> list[VerificationIssue]:
        """critical 级别的问题列表."""
        return [i for i in self.issues if i.severity == "critical"]

    def to_dict(self) -> dict[str, Any]:
        """转为字典."""
        return {
            "phase": self.phase,
            "score": self.score,
            "decision": self.decision,
            "critic": self.critic_name,
            "summary": self.summary,
            "issues": [
                {
                    "severity": i.severity,
                    "location": i.location,
                    "description": i.description,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }


class AutoVerifier:
    """角色自动校验器 — Actor-Critic 架构的 Critic 侧.

    在 ScholarAgent 完成某个阶段的产出后，由本类调用对应 Critic 角色
    的 LLM 来自动校验产出质量。
    """

    # 自动通过分数阈值
    PASS_THRESHOLD = 80
    # 升级人工审核分数阈值
    HUMAN_THRESHOLD = 50

    def __init__(
        self,
        llm: Any,
        callback: Any = None,
        pass_threshold: int = PASS_THRESHOLD,
        human_threshold: int = HUMAN_THRESHOLD,
    ) -> None:
        """初始化校验器.

        Args:
            llm: LLMGateway 实例，用于调用 LLM.
            callback: WorkflowCallback 实例，用于推送进度事件.
            pass_threshold: 自动通过分数阈值（默认80）.
            human_threshold: 升级人工审核分数阈值（默认50）.
        """
        self.llm = llm
        self.callback = callback
        self.pass_threshold = pass_threshold
        self.human_threshold = human_threshold

    async def verify(
        self,
        phase: str,
        content: str,
        user_input: str = "",
        discipline: str = "学术研究",
    ) -> VerificationResult:
        """校验指定阶段的产出.

        Args:
            phase: 阶段标识，如 "topic_analysis".
            content: 待校验的内容.
            user_input: 用户原始研究想法（部分校验需要）.
            discipline: 学科领域.

        Returns:
            VerificationResult 校验结果.
        """
        # 检查是否有对应的校验 Prompt
        prompt_template = VERIFICATION_PROMPTS.get(phase)
        if not prompt_template:
            logger.debug(f"阶段 {phase} 无校验 Prompt，跳过自动校验")
            return VerificationResult(
                phase=phase,
                score=100,
                decision="pass",
                summary="无校验 Prompt，默认通过",
            )

        # 获取 Critic 角色信息
        critic_info = ACTOR_CRITIC_MAP.get(phase, {})
        critic_role_key = critic_info.get("critic_role_key", "claim_calibration")
        critic_name = critic_info.get("critic_name", "审稿人")

        # 构建 Critic 的 system prompt
        system_prompt = get_role_prompt(critic_role_key, discipline=discipline)

        # 构建校验 prompt
        try:
            verification_prompt = prompt_template.format(
                content=content[:8000],  # 限制内容长度
                user_input=user_input[:500],
            )
        except KeyError:
            # 某些 prompt 可能不含 user_input 占位符
            verification_prompt = prompt_template.format(content=content[:8000])

        # 发出校验开始事件
        self._emit_progress(phase, "progress", f"{critic_name} 正在自动校验...")

        # 调用 LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": verification_prompt},
        ]

        try:
            response = await self.llm.chat(
                messages,
                temperature=0.2,  # 低温度保证一致性
            )
        except Exception as e:
            logger.error(f"自动校验 LLM 调用失败 [{phase}]: {e}")
            # LLM 调用失败，降级为人工审核
            return VerificationResult(
                phase=phase,
                score=0,
                decision="human",
                summary=f"校验 LLM 调用失败: {e}",
                critic_name=critic_name,
            )

        # 解析 LLM 返回的 JSON
        result = self._parse_verification_response(
            response, phase, critic_name
        )

        # 根据分数和 critical issues 确定最终决策
        result.decision = self._determine_decision(result)

        # 发出校验结果事件
        status_msg = (
            f"{critic_name} 校验完成: {result.score}分, 决策={result.decision}"
        )
        self._emit_progress(phase, "progress", status_msg)

        if result.passed:
            self._emit_progress(phase, "progress", f"✓ 自动校验通过: {result.summary}")
        elif result.needs_human:
            self._emit_progress(
                phase, "progress",
                f"⚠ 自动校验未通过，升级人工审核: {result.summary}",
            )
        else:
            # fix 模式：记录问题但继续
            for issue in result.critical_issues:
                self._emit_progress(
                    phase, "progress",
                    f"  ⚠ {issue.severity}: {issue.description}",
                )

        return result

    def _parse_verification_response(
        self,
        response: str,
        phase: str,
        critic_name: str,
    ) -> VerificationResult:
        """解析 LLM 返回的校验结果 JSON."""
        # 清洗 LLM 输出（移除思考标记等）
        from scholarpilot.llm.gateway import LLMGateway
        cleaned = LLMGateway._clean_llm_output(response)

        # 尝试提取 JSON
        json_data = None

        # 尝试直接解析
        try:
            json_data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        if not json_data:
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```",
                cleaned,
                re.DOTALL,
            )
            if json_match:
                try:
                    json_data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

        # 尝试从文本中提取第一个 JSON 对象
        if not json_data:
            json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
            if json_match:
                try:
                    json_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        if not json_data:
            logger.warning(f"无法解析校验结果 JSON [{phase}], 原始响应: {response[:200]}")
            return VerificationResult(
                phase=phase,
                score=0,
                decision="human",
                summary="校验结果解析失败，升级人工审核",
                critic_name=critic_name,
                raw_response=response,
            )

        # 解析 issues
        issues = []
        for issue_data in json_data.get("issues", []):
            issues.append(VerificationIssue(
                severity=issue_data.get("severity", "info"),
                location=issue_data.get("location", ""),
                description=issue_data.get("description", ""),
                suggestion=issue_data.get("suggestion", ""),
            ))

        return VerificationResult(
            phase=phase,
            score=int(json_data.get("score", 0)),
            decision=json_data.get("decision", "human"),
            issues=issues,
            summary=json_data.get("summary", ""),
            critic_name=critic_name,
            raw_response=response,
        )

    def _determine_decision(self, result: VerificationResult) -> str:
        """根据分数和 critical issues 确定最终决策.

        LLM 可能给出不准确的 decision，这里用规则覆盖：
        - score >= pass_threshold 且无 critical → "pass"
        - score >= human_threshold → "fix"
        - score < human_threshold → "human"
        """
        has_critical = bool(result.critical_issues)

        if result.score >= self.pass_threshold and not has_critical:
            return "pass"
        elif result.score >= self.human_threshold:
            return "fix"
        else:
            return "human"

    def _emit_progress(
        self, phase: str, status: str, message: str
    ) -> None:
        """发出进度事件."""
        if not self.callback:
            return
        try:
            from scholarpilot.events.types import ProgressEvent

            event = ProgressEvent(
                phase=phase,
                status=status,
                message=message,
            )
            self.callback.on_progress(event)
        except Exception as e:
            logger.debug(f"校验进度事件推送失败: {e}")
