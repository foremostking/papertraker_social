"""ScholarPilot 共享枚举定义.

ADR-007 P4: 收敛 evidence_matrix.py 的 EvidenceStrength 和
anti_hallucination.py 的 EvidenceLevel 两个重复枚举。
"""

from __future__ import annotations

from enum import Enum


class EvidenceStrength(str, Enum):
    """证据强度枚举（统一定义）.

    遵循保守策略：宁可标 WEAK 不标 STRONG。

    Attributes:
        STRONG: 强证据——有 DOI + 权威期刊 + 大样本 + 因果识别.
        MODERATE: 中等证据——同行评议 + 样本有限.
        WEAK: 弱证据——预印本/小样本/仅相关性.
        UNVERIFIED: 未验证——信息不足或 AI 生成的可能虚构引用.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNVERIFIED = "unverified"
