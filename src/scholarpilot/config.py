"""ScholarPilot 配置管理模块.

使用 pydantic-settings 管理所有配置项，支持 .env 文件和环境变量。
.env 文件从包的根目录（scholarpilot/）加载，确保无论从哪个工作目录
启动命令都能正确读取配置。
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


def _find_env_file() -> Path:
    """从包根目录向上查找 .env 文件.

    查找顺序：
    1. 包源码目录的父目录（开发模式：scholarpilot/src/scholarpilot/config.py -> scholarpilot/）
    2. 当前工作目录（兼容在项目根目录下运行）
    """
    # 开发模式：当前文件在 src/scholarpilot/config.py，.env 在项目根目录
    config_file = Path(__file__).resolve()
    # src/scholarpilot/config.py -> src/ -> scholarpilot/
    pkg_root = config_file.parent.parent.parent
    candidate = pkg_root / ".env"
    if candidate.exists():
        return candidate
    # 回退到当前工作目录
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    # 默认返回包根目录的 .env（即使不存在，pydantic-settings 会静默跳过）
    return candidate


class Settings(BaseSettings):
    """ScholarPilot 全局配置.

    所有配置项均可通过环境变量覆盖，环境变量前缀为 SCHOLAR_。
    例如: SCHOLAR_CLAUDE_API_KEY=xxx
    """

    # ── LLM API Keys ──────────────────────────────────────
    claude_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""

    # ── 火山方舟（Volcano Ark / 豆包）─────────────────────
    # OpenAI 兼容 API，通过 LiteLLM 的 openai/ 前缀 + api_base 调用
    ark_api_key: str = ""
    ark_api_base: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 默认模型（填入火山方舟的 endpoint ID，如 ep-2024xxxx-xxxxx）
    ark_default_model: str = ""

    # ── 学术检索 API Keys ────────────────────────────────
    ss_api_key: str = ""  # Semantic Scholar API Key
    arxiv_enabled: bool = True  # 是否启用 arXiv 检索

    # ── 默认模型配置 ──────────────────────────────────────
    default_writing_model: str = "claude-sonnet-4-20250514"
    default_analysis_model: str = "gpt-4o"
    default_casual_model: str = "deepseek/deepseek-chat"

    # ── 目录配置 ──────────────────────────────────────────
    projects_dir: Path = Path("./projects")
    mcp_servers_dir: Path = Path("./mcp-servers")

    # 全局用户目录（跨论文共享：研究者画像、全局文献库等）
    # 默认 ~/.scholarpilot，可通过 SCHOLAR_USER_HOME 覆盖
    user_home_dir: Path = Path.home() / ".scholarpilot"

    # ── 文献订阅（Feed）配置 ─────────────────────────────
    # 每次推送推荐文献的默认数量，按相关度排序
    feed_max_recommendations: int = 20
    # 是否生成 LLM 推荐理由（有任意 LLM API Key 时自动启用，无则跳过）
    feed_enable_llm_reasons: bool = True
    # 启用的订阅策略: citation=反向引用追踪, author=同作者追踪, topic=主题增量
    feed_strategies: str = "citation,author,topic"
    # 种子论文自动选取数量（从全局文献库中按引用数选取）
    feed_auto_seed_count: int = 5
    # OpenAlex polite pool 邮箱（可选，提高速率限制）
    openalex_mailto: str = ""

    model_config = {"env_file": _find_env_file(), "env_prefix": "SCHOLAR_"}


# 全局配置单例
_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局配置单例."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """重置配置单例（主要用于测试）."""
    global _settings
    _settings = None
