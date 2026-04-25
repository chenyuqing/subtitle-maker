from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


@dataclass
class ChatResult:
    """OpenAI-compatible 聊天响应。"""

    content: str


class LlmClientError(RuntimeError):
    """统一包装 LLM provider 错误，避免上层泄露 SDK 细节。"""

    def __init__(self, message: str, *, status_code: int = 502, code: str = "E-AGENT-004") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class OpenAICompatibleChatClient:
    """OpenAI-compatible 聊天客户端，供 Agent 和后续翻译重构复用。"""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        api_key_env: str = "DEEPSEEK_API_KEY",
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: float = 30.0,
    ) -> None:
        # API key 只在内存中使用；调用方不得把它写入日志或 manifest。
        final_api_key = api_key or os.environ.get(api_key_env)
        if not final_api_key:
            raise LlmClientError(
                f"Missing API key. Provide api_key or set {api_key_env}.",
                status_code=400,
                code="E-AGENT-001",
            )
        self.model = model
        self.client = OpenAI(api_key=final_api_key, base_url=base_url, timeout=timeout)

    def chat(self, messages: List[Dict[str, str]], *, temperature: float = 0.2) -> ChatResult:
        """发送非流式聊天请求，并返回纯文本内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=False,
            )
            content = response.choices[0].message.content or ""
            return ChatResult(content=content.strip())
        except Exception as exc:  # pragma: no cover - SDK subclasses vary by version.
            # 不把原始请求内容或 API key 写入错误信息，只保留 provider 摘要。
            error_text = str(exc)
            lowered = error_text.lower()
            if "401" in error_text or "authentication" in lowered or "unauthorized" in lowered:
                raise LlmClientError("API Key 无效或无权限。", status_code=401, code="E-AGENT-002") from exc
            if "timeout" in lowered or "timed out" in lowered:
                raise LlmClientError("DeepSeek 请求超时。", status_code=504, code="E-AGENT-003") from exc
            raise LlmClientError("DeepSeek 返回错误。", status_code=502, code="E-AGENT-004") from exc
