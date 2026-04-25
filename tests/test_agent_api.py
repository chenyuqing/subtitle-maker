from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from subtitle_maker import agent_api, web
from subtitle_maker.core.llm_client import ChatResult, LlmClientError


class FakeAgentClient:
    """伪造 Agent LLM 客户端，避免单测访问真实 DeepSeek。"""

    instances = []

    def __init__(self, *, api_key=None, timeout=30.0, **kwargs):
        self.api_key = api_key
        self.timeout = timeout
        self.messages = None
        FakeAgentClient.instances.append(self)

    def chat(self, messages, *, temperature=0.2):
        self.messages = messages
        return ChatResult(
            content='{"reply":"请检查 Index-TTS 服务。", "suggested_actions":["打开 health endpoint", "确认端口 8010"]}'
        )


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web.app)
        FakeAgentClient.instances = []

    def test_agent_rejects_empty_message(self):
        response = self.client.post("/api/agent/chat", json={"message": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "E-AGENT-005")

    def test_agent_requires_api_key_or_env(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/api/agent/chat", json={"message": "怎么开始？"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "E-AGENT-001")
        self.assertNotIn("sk-", str(response.json()))

    def test_agent_returns_reply_and_suggested_actions(self):
        with patch.object(agent_api, "OpenAICompatibleChatClient", FakeAgentClient):
            response = self.client.post(
                "/api/agent/chat",
                json={"message": "Index-TTS 不可用怎么办？", "page": "panel-auto-dub-v2", "api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["conversation_id"].startswith("agent_"))
        self.assertEqual(payload["reply"], "请检查 Index-TTS 服务。")
        self.assertEqual(payload["suggested_actions"], ["打开 health endpoint", "确认端口 8010"])
        self.assertNotIn("secret-key", str(payload))

    def test_agent_prompt_forbids_execution(self):
        with patch.object(agent_api, "OpenAICompatibleChatClient", FakeAgentClient):
            response = self.client.post(
                "/api/agent/chat",
                json={"message": "帮我删除输出文件", "page": "panel-results", "api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(FakeAgentClient.instances)
        system_prompt = FakeAgentClient.instances[0].messages[0]["content"]
        self.assertIn("不能执行任务", system_prompt)
        self.assertIn("不能修改文件", system_prompt)
        self.assertIn("不能删除产物", system_prompt)

    def test_agent_maps_provider_error(self):
        class BrokenAgentClient(FakeAgentClient):
            def __init__(self, *, api_key=None, timeout=30.0, **kwargs):
                raise LlmClientError("API Key 无效或无权限。", status_code=401, code="E-AGENT-002")

        with patch.object(agent_api, "OpenAICompatibleChatClient", BrokenAgentClient):
            response = self.client.post(
                "/api/agent/chat",
                json={"message": "你好", "api_key": "bad-key"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "E-AGENT-002")
        self.assertNotIn("bad-key", str(response.json()))


if __name__ == "__main__":
    unittest.main()
