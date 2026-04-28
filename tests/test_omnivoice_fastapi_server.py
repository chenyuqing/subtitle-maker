from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
import torch


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "tools" / "omnivoice_fastapi_server.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_omnivoice_fastapi_server_module", SERVER_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
omnivoice_fastapi_server = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = omnivoice_fastapi_server
MODULE_SPEC.loader.exec_module(omnivoice_fastapi_server)


class DummyOmniVoiceModel:
    """轻量假模型：返回固定波形，避免真实加载 OmniVoice 权重。"""

    sampling_rate = 24000

    def generate(self, **kwargs):
        return [torch.zeros(1, 24000)]


class OmniVoiceFastApiServerTests(unittest.TestCase):
    """覆盖 OmniVoice 服务端的运行参数与时长元数据。"""

    def test_resolve_runtime_params_prefers_request_overrides(self) -> None:
        cfg = {
            "num_step": 32,
            "guidance_scale": 2.0,
            "speed": 1.0,
            "t_shift": 0.1,
            "denoise": True,
            "postprocess_output": True,
            "layer_penalty_factor": 5.0,
            "position_temperature": 5.0,
            "class_temperature": 0.0,
        }

        params = omnivoice_fastapi_server._resolve_runtime_params(
            {
                "speed": 0.9,
                "num_step": 48,
                "guidance_scale": 2.5,
                "denoise": False,
                "postprocess_output": True,
            },
            cfg,
        )

        self.assertEqual(params["speed"], 0.9)
        self.assertEqual(params["num_step"], 48)
        self.assertEqual(params["guidance_scale"], 2.5)
        self.assertFalse(params["denoise"])
        self.assertTrue(params["postprocess_output"])

    def test_server_state_synthesize_returns_duration_ratio_and_runtime_metadata(self) -> None:
        state = omnivoice_fastapi_server.ServerState.__new__(omnivoice_fastapi_server.ServerState)
        state.cfg = {
            "num_step": 32,
            "guidance_scale": 2.0,
            "speed": 1.0,
            "t_shift": 0.1,
            "denoise": True,
            "postprocess_output": True,
            "layer_penalty_factor": 5.0,
            "position_temperature": 5.0,
            "class_temperature": 0.0,
        }
        state.model = DummyOmniVoiceModel()
        state.ensure_loaded = lambda: state.model

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output_path = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)

            def fake_save(path: str, audio, sample_rate: int) -> None:
                Path(path).write_bytes(b"RIFF")

            with patch.object(omnivoice_fastapi_server.torchaudio, "save", side_effect=fake_save), patch.object(
                omnivoice_fastapi_server.sf,
                "info",
                return_value=type("Info", (), {"duration": 1.0, "samplerate": 24000})(),
            ):
                result = omnivoice_fastapi_server.ServerState.synthesize(
                    state,
                    {
                        "text": "hello",
                        "output_path": str(output_path),
                        "ref_audio": str(ref_audio),
                        "duration": 2.0,
                        "retry_profile": "conservative",
                        "speed": 0.9,
                        "num_step": 48,
                        "guidance_scale": 2.5,
                    },
                )

        self.assertEqual(result["target_duration_sec"], 2.0)
        self.assertEqual(result["actual_duration_sec"], 1.0)
        self.assertAlmostEqual(float(result["duration_ratio"]), 0.5, places=3)
        self.assertEqual(result["retry_profile"], "conservative")
        self.assertEqual(result["speed"], 0.9)
        self.assertEqual(result["num_step"], 48)
        self.assertEqual(result["guidance_scale"], 2.5)


if __name__ == "__main__":
    unittest.main()
