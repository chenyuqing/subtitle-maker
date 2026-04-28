from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "tools" / "index_tts_fastapi_server.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_index_tts_fastapi_server_module", SERVER_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
index_tts_fastapi_server = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = index_tts_fastapi_server
MODULE_SPEC.loader.exec_module(index_tts_fastapi_server)


class IndexTTSFastApiServerTests(unittest.TestCase):
    """覆盖 Index-TTS 服务启动时的设备兜底逻辑。"""

    def test_resolve_runtime_device_falls_back_to_cpu_when_accelerators_unavailable(self) -> None:
        """auto 模式在没有 CUDA/MPS 时应稳定回退到 CPU。"""

        fake_mps = SimpleNamespace(is_available=lambda: False)
        with patch.object(index_tts_fastapi_server.torch.cuda, "is_available", return_value=False), patch.object(
            index_tts_fastapi_server.torch.backends, "mps", fake_mps
        ):
            self.assertEqual(index_tts_fastapi_server._resolve_runtime_device("auto"), "cpu")

    def test_resolve_runtime_device_keeps_explicit_choice(self) -> None:
        """显式设备参数应保持原样，避免覆盖用户手动指定。"""

        self.assertEqual(index_tts_fastapi_server._resolve_runtime_device("mps"), "mps")
        self.assertEqual(index_tts_fastapi_server._resolve_runtime_device("cpu"), "cpu")

    def test_record_successful_synthesis_respects_zero_threshold(self) -> None:
        """自动轮换阈值为 0 时，应保持当前常驻行为。"""

        state = index_tts_fastapi_server.ServerState.__new__(index_tts_fastapi_server.ServerState)
        state.requests_served = 0
        state.restart_after_requests = 0
        state.restart_pending = False

        should_restart = index_tts_fastapi_server.ServerState.record_successful_synthesis(state)

        self.assertFalse(should_restart)
        self.assertEqual(state.requests_served, 1)
        self.assertFalse(state.restart_pending)

    def test_record_successful_synthesis_marks_restart_pending_at_threshold(self) -> None:
        """达到阈值后只标记 pending，交给响应返回后的 shutdown 处理。"""

        state = index_tts_fastapi_server.ServerState.__new__(index_tts_fastapi_server.ServerState)
        state.requests_served = 0
        state.restart_after_requests = 2
        state.restart_pending = False

        first = index_tts_fastapi_server.ServerState.record_successful_synthesis(state)
        second = index_tts_fastapi_server.ServerState.record_successful_synthesis(state)

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(state.requests_served, 2)
        self.assertTrue(state.restart_pending)

    def test_health_payload_exposes_restart_counters(self) -> None:
        """健康检查应暴露请求计数与轮换状态，便于后台观察。"""

        state = index_tts_fastapi_server.ServerState.__new__(index_tts_fastapi_server.ServerState)
        state.requests_served = 7
        state.restart_after_requests = 50
        state.restart_pending = True

        payload = index_tts_fastapi_server.ServerState.health_payload(state)

        self.assertEqual(payload["requests_served"], 7)
        self.assertEqual(payload["restart_after_requests"], 50)
        self.assertTrue(payload["restart_pending"])


if __name__ == "__main__":
    unittest.main()
