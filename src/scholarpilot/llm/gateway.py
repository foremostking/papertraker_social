"""LLM Gateway - 基于 LiteLLM 的统一 LLM 调用网关.

封装 LiteLLM，提供统一的调用接口，自动根据模型名称选择对应的 API Key 和端点。
支持 Claude (Anthropic)、GPT (OpenAI)、DeepSeek、智谱 (Zhipu)、火山方舟 (Ark) 等多种模型。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

import litellm

# 禁用 litellm 远程模型价格表获取（避免 SSL 证书警告）
# 必须在 import litellm 后立即设置，在任何 LLM 调用之前生效
litellm.model_cost_default_url = ""

from scholarpilot.config import Settings

logger = logging.getLogger(__name__)

# 模型前缀到 API Key 配置字段的映射
_MODEL_KEY_MAP: dict[str, str] = {
    "claude": "claude_api_key",
    "anthropic": "claude_api_key",
    "gpt": "openai_api_key",
    "openai": "openai_api_key",
    "o1": "openai_api_key",
    "o3": "openai_api_key",
    "deepseek": "deepseek_api_key",
    "glm": "zhipu_api_key",
    "zhipu": "zhipu_api_key",
    "ark": "ark_api_key",          # 火山方舟（自定义前缀）
    "ep-": "ark_api_key",          # 火山方舟 endpoint ID（ep-xxx）
    "doubao": "ark_api_key",       # 豆包模型
}


class LLMGateway:
    """统一 LLM 调用网关.

    通过 LiteLLM 实现多模型统一调用，自动路由到正确的 API 端点。

    Usage:
        config = Settings()
        gateway = LLMGateway(config)
        response = await gateway.chat([{"role": "user", "content": "Hello"}])
    """

    def __init__(self, config: Settings) -> None:
        """初始化 LLM Gateway.

        Args:
            config: ScholarPilot 配置对象。
        """
        self.config = config
        # 禁用 litellm 远程模型价格表获取（避免 SSL 证书警告）
        litellm.model_cost_default_url = ""
        self._setup_api_keys()

    def _setup_api_keys(self) -> None:
        """根据配置设置各模型的 API Key."""
        api_keys = {
            "claude_api_key": self.config.claude_api_key,
            "openai_api_key": self.config.openai_api_key,
            "deepseek_api_key": self.config.deepseek_api_key,
            "zhipu_api_key": self.config.zhipu_api_key,
            "ark_api_key": self.config.ark_api_key,
        }
        for key_name, key_value in api_keys.items():
            if key_value:
                litellm.api_key = key_value
                # 同时设置环境变量供 litellm 使用
                import os

                env_name = key_name.upper()
                os.environ.setdefault(env_name, key_value)

        # 设置 NO_PROXY：国内 API 地址不走代理
        # 避免系统代理拦截国内服务（如火山方舟、CNKI 等）
        import os

        no_proxy_domains = [
            "ark.cn-beijing.volces.com",
            "open.bigmodel.cn",  # 智谱 AI
            "kns.cnki.net",
            "navi.cnki.net",
            "gwz.cass.org.cn",
            "www.ncpssd.cn",
        ]
        existing_no_proxy = os.environ.get("NO_PROXY", "")
        all_no_proxy = ",".join(d for d in no_proxy_domains if d not in existing_no_proxy)
        if all_no_proxy:
            os.environ["NO_PROXY"] = f"{existing_no_proxy},{all_no_proxy}" if existing_no_proxy else all_no_proxy
            os.environ["no_proxy"] = os.environ["NO_PROXY"]

    def _is_ark_model(self, model: str) -> bool:
        """判断是否为火山方舟模型."""
        model_lower = model.lower()
        return (
            model_lower.startswith("ark")
            or model_lower.startswith("ep-")
            or model_lower.startswith("doubao")
        )

    def _is_zhipu_model(self, model: str) -> bool:
        """判断是否为智谱 GLM 模型.

        智谱 GLM 系列模型名：glm-4、glm-4-plus、glm-4.5、glm-4-flash 等。
        LiteLLM 1.89 不原生支持 zhipu/ 前缀，需走 OpenAI 兼容模式。
        """
        model_lower = model.lower()
        return (
            model_lower.startswith("glm")
            or model_lower.startswith("zhipu")
        )

    def _select_api_key(self, model: str) -> Optional[str]:
        """根据模型名称选择合适的 API Key.

        Args:
            model: 模型名称（如 "claude-sonnet-4-20250514"、"gpt-4o" 等）。

        Returns:
            对应的 API Key，如果没有匹配则返回 None。
        """
        model_lower = model.lower()
        for prefix, key_field in _MODEL_KEY_MAP.items():
            if model_lower.startswith(prefix):
                return getattr(self.config, key_field, None) or None
        return None

    @staticmethod
    def _clean_llm_output(content: str) -> str:
        """清洗 LLM 输出，去除思考过程前缀和 markdown 代码块包裹.

        某些模型（如 DeepSeek V3 通过火山方舟）会在正式内容前添加
        思考过程标记（如 [💭 思考]、[🔧 执行]），以及用 ```markdown
        包裹正文。本方法去除这些多余内容，只保留正文。

        Args:
            content: LLM 原始返回内容。

        Returns:
            清洗后的内容。
        """
        import re

        lines = content.split("\n")
        cleaned_lines: list[str] = []
        in_code_block = False
        skip_until_content = True

        for line in lines:
            stripped = line.strip()

            # 跳过思考过程标记行（如 [💭 思考] xxx、[🔧 执行] xxx）
            if re.match(r"^\[(💭|🔧|✅|❌|📝|📋|🔍|📊|💡|⚠️|🎯|✨|📚|🏗️|🔧)\s*", stripped):
                skip_until_content = True
                continue

            # 跳过 ```markdown 开头行
            if stripped.lower().startswith("```markdown"):
                in_code_block = True
                skip_until_content = False
                continue

            # 跳过 ``` 开头行（非 markdown 的代码块）
            if stripped == "```" and in_code_block:
                in_code_block = False
                continue

            # 如果还在跳过阶段，跳过空行
            if skip_until_content:
                if not stripped:
                    continue
                # 遇到第一个实际内容行，停止跳过
                skip_until_content = False

            cleaned_lines.append(line)

        result = "\n".join(cleaned_lines).strip()

        # 如果整个内容被 ``` 包裹但没有 markdown 标记，提取内部内容
        if result.startswith("```") and result.endswith("```"):
            lines = result.split("\n")
            if len(lines) >= 3:
                result = "\n".join(lines[1:-1]).strip()

        return result

    # 空响应最大重试次数
    MAX_EMPTY_RETRIES = 3

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """调用 LLM，自动选择模型和 API Key.

        空响应自动重试：当 LLM 返回空内容时，自动重试最多 MAX_EMPTY_RETRIES 次。
        重试时逐步降低 temperature 并添加 max_tokens 参数。

        Args:
            messages: 对话消息列表，格式为 [{"role": "...", "content": "..."}, ...]。
            model: 模型名称，默认使用 default_casual_model。
            **kwargs: 传递给 litellm.acompletion 的额外参数。

        Returns:
            LLM 返回的文本内容。

        Raises:
            RuntimeError: 当所有重试均返回空响应时。
        """
        model = model or self.config.default_casual_model
        temperature = kwargs.pop("temperature", 0.7)

        # 火山方舟特殊处理：OpenAI 兼容 API + 自定义 api_base
        is_ark = self._is_ark_model(model)
        # 智谱 GLM 特殊处理：OpenAI 兼容 API + 自定义 api_base
        is_zhipu = self._is_zhipu_model(model)
        if is_ark:
            litellm_model = model if model.startswith("openai/") else f"openai/{model}"
            api_base = self.config.ark_api_base
            api_key = self.config.ark_api_key
        elif is_zhipu:
            # 智谱 GLM 走 OpenAI 兼容模式：openai/glm-4 + api_base
            # LiteLLM 不原生支持 zhipu/ 前缀，必须用 openai/ 前缀 + api_base
            litellm_model = model if model.startswith("openai/") else f"openai/{model}"
            api_base = self.config.zhipu_api_base
            api_key = self.config.zhipu_api_key
        else:
            litellm_model = model
            api_base = None
            api_key = self._select_api_key(model)

        last_error_info = ""
        for attempt in range(1, self.MAX_EMPTY_RETRIES + 1):
            call_kwargs = {**kwargs, "temperature": temperature}
            # 始终显式设置 max_tokens，避免 Ark API 默认值过小导致空响应
            call_kwargs.setdefault("max_tokens", 16384)

            try:
                if is_ark or is_zhipu:
                    response = await litellm.acompletion(
                        model=litellm_model,
                        messages=messages,
                        api_key=api_key,
                        api_base=api_base,
                        **call_kwargs,
                    )
                else:
                    response = await litellm.acompletion(
                        model=litellm_model,
                        messages=messages,
                        api_key=api_key,
                        **call_kwargs,
                    )

                content = response.choices[0].message.content
                if content and content.strip():
                    # 清洗 LLM 输出：去除思考过程前缀（如 [💭 思考]、[🔧 执行] 等）
                    content = self._clean_llm_output(content)
                    if content.strip():
                        return content

                # 空响应 — 记录并重试
                last_error_info = (
                    f"finish_reason={response.choices[0].finish_reason}, "
                    f"usage={response.usage}"
                )
                logger.warning(
                    f"LLM 返回空响应 (attempt {attempt}/{self.MAX_EMPTY_RETRIES}): "
                    f"model={model}, {last_error_info}"
                )
                # 重试时降低 temperature
                temperature = max(0.1, temperature - 0.2)

            except Exception as e:
                logger.warning(
                    f"LLM 调用异常 (attempt {attempt}/{self.MAX_EMPTY_RETRIES}): "
                    f"model={model}, error={e}"
                )
                last_error_info = str(e)
                if attempt == self.MAX_EMPTY_RETRIES:
                    raise

            # 重试前等待
            if attempt < self.MAX_EMPTY_RETRIES:
                import asyncio
                await asyncio.sleep(2 * attempt)

        raise RuntimeError(
            f"LLM 在 {self.MAX_EMPTY_RETRIES} 次重试后仍返回空响应: "
            f"model={model}, {last_error_info}"
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式调用 LLM.

        Args:
            messages: 对话消息列表。
            model: 模型名称，默认使用 default_casual_model。
            **kwargs: 传递给 litellm.acompletion 的额外参数。

        Yields:
            LLM 返回的文本片段。
        """
        model = model or self.config.default_casual_model

        # 火山方舟特殊处理
        if self._is_ark_model(model):
            litellm_model = model if model.startswith("openai/") else f"openai/{model}"
            api_base = self.config.ark_api_base
            api_key = self.config.ark_api_key

            async for chunk in litellm.acompletion(
                model=litellm_model,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                stream=True,
                **kwargs,
            ):
                content = chunk.choices[0].delta.content if chunk.choices else None
                if content:
                    yield content
            return

        # 智谱 GLM 特殊处理（OpenAI 兼容模式）
        if self._is_zhipu_model(model):
            litellm_model = model if model.startswith("openai/") else f"openai/{model}"
            api_base = self.config.zhipu_api_base
            api_key = self.config.zhipu_api_key

            async for chunk in litellm.acompletion(
                model=litellm_model,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                stream=True,
                **kwargs,
            ):
                content = chunk.choices[0].delta.content if chunk.choices else None
                if content:
                    yield content
            return

        # 标准模型路由
        api_key = self._select_api_key(model)
        async for chunk in litellm.acompletion(
            model=model,
            messages=messages,
            api_key=api_key,
            stream=True,
            **kwargs,
        ):
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content
