"""Scholar Agent 的 Prompt 模板 — 兼容性入口.

原 prompts.py 已重构为 prompts/ 包（按 10 阶段分类）。
本文件保留向后兼容：所有原有导入仍然有效。

新代码请直接从 prompts 包导入：
    from scholarpilot.context.prompts import XXX
"""

# 从重构后的 prompts 包重新导出所有内容
from scholarpilot.context.prompts import *  # noqa: F401,F403
from scholarpilot.context.prompts import __all__  # noqa: F401
