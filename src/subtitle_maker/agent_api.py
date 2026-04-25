from __future__ import annotations

import json
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .core.llm_client import LlmClientError, OpenAICompatibleChatClient


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    """Agent V1 浮动抽屉聊天请求。"""

    message: str = Field(default="")
    conversation_id: Optional[str] = None
    page: Optional[str] = None
    api_key: Optional[str] = None


class AgentChatResponse(BaseModel):
    """Agent V1 回复，包含可选的短操作建议。"""

    conversation_id: str
    reply: str
    suggested_actions: List[str]


AGENT_SYSTEM_PROMPT = """你是 Subtitle Maker 的产品内使用助手。
你只能解释功能、排查错误、建议下一步。
你不能执行任务、不能修改文件、不能删除产物、不能声称已经完成任何操作。
如果用户要求你执行操作，你必须说明你只能提供手动操作建议。
如果用户没有提供足够错误信息，你必须要求用户粘贴错误文本或说明当前页面。
对常见问题给出短步骤，不输出大段架构解释。
优先使用项目实际术语：ASR、source.srt、translated.srt、Auto Dubbing V2、Index-TTS、DeepSeek、review、redub。

常见问题知识：
- DeepSeek API Key required：检查翻译/Agent key 或 DEEPSEEK_API_KEY。
- Index-TTS 服务不可用：检查本地服务和 http://127.0.0.1:8010/health。
- ASR 字幕很零散：检查智能分句和短句合并设置。
- 上传 translated 字幕：会跳过 ASR 和翻译，直接配音。
- 上传 source 字幕：会跳过 ASR，但仍需要翻译。
- redub 失败：不要覆盖已有产物，先查看错误摘要再重试。

请尽量返回 JSON：{"reply":"...", "suggested_actions":["..."]}。
如果无法返回 JSON，也可以直接回复正文。"""


def _build_agent_messages(*, message: str, page: Optional[str]) -> List[dict[str, str]]:
    """构造固定边界的 Agent 消息，确保 Agent 不越权执行。"""

    page_label = (page or "unknown").strip() or "unknown"
    user_content = f"当前页面: {page_label}\n用户问题:\n{message.strip()}"
    return [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _parse_agent_content(content: str) -> tuple[str, List[str]]:
    """解析模型返回；JSON 失败时回退为纯文本，避免一次格式漂移导致接口失败。"""

    text = (content or "").strip()
    if not text:
        return "没有收到有效回复，请重试。", []

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        payload = json.loads(candidate)
        reply = str(payload.get("reply") or "").strip() or text
        raw_actions = payload.get("suggested_actions") or []
        actions = [str(item).strip() for item in raw_actions if str(item).strip()]
        return reply, actions[:5]
    except Exception:
        return text, []


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(payload: AgentChatRequest) -> AgentChatResponse:
    """Agent V1 只提供使用建议，不读取本地任务状态，也不执行任何操作。"""

    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail={"code": "E-AGENT-005", "message": "请输入问题。"})

    client = None
    try:
        client = OpenAICompatibleChatClient(api_key=payload.api_key, timeout=30.0)
        result = client.chat(_build_agent_messages(message=message, page=payload.page), temperature=0.2)
        reply, actions = _parse_agent_content(result.content)
        conversation_id = payload.conversation_id or f"agent_{uuid.uuid4().hex[:12]}"
        return AgentChatResponse(conversation_id=conversation_id, reply=reply, suggested_actions=actions)
    except LlmClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    finally:
        # 明确不持久化 client 或 API key，减少泄露面。
        client = None
