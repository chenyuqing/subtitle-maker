from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

API_TEST_SKIP_REASON = ""
try:
    from subtitle_maker import dubbing_cli_api
    from subtitle_maker import web
except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
    dubbing_cli_api = None
    web = None
    API_TEST_SKIP_REASON = f"missing dependency {exc.name}"


class FakeThread:
    """替代后台线程，避免测试中真正启动 CLI。"""

    instances = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True

@unittest.skipIf(bool(API_TEST_SKIP_REASON), API_TEST_SKIP_REASON or "")
class DubbingCliApiTests(unittest.TestCase):
    """覆盖当前 auto dubbing API 主合同。"""

    def setUp(self):
        self.client = TestClient(web.app)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dub_api_test_"))
        self.upload_root = self.tmpdir / "uploads"
        self.output_root = self.tmpdir / "outputs"
        self.tool_path = self.tmpdir / "dub_long_video.py"
        self.tool_path.write_text("# fake tool\n", encoding="utf-8")
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

        dubbing_cli_api._tasks.clear()
        dubbing_cli_api.legacy_runtime.tasks.clear()
        FakeThread.instances = []

        self.patchers = [
            patch.object(dubbing_cli_api, "UPLOAD_ROOT", self.upload_root),
            patch.object(dubbing_cli_api, "OUTPUT_ROOT", self.output_root),
            patch.object(dubbing_cli_api, "TOOL_PATH", self.tool_path),
            patch.object(dubbing_cli_api.legacy_runtime, "UPLOAD_DIR", str(self.upload_root)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(dubbing_cli_api._tasks.clear)
        self.addCleanup(dubbing_cli_api.legacy_runtime.tasks.clear)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _patch_start_runtime(self):
        """统一屏蔽启动阶段的外部服务检查。"""

        return patch.object(dubbing_cli_api, "_switch_tts_runtime_on_demand", return_value=None)

    def test_start_auto_dubbing_creates_single_mode_task(self):
        """默认启动应走 single 模式，并生成当前主命令。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task_id = payload["task_id"]
        task = self.client.get(f"/dubbing/auto/status/{task_id}").json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["target_lang"], "Chinese")
        self.assertEqual(task["dubbing_mode"], "single")
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["speaker_ref_map"], [])
        self.assertIn("--dubbing-mode", task["command"])
        self.assertIn("single", task["command"])
        self.assertIn("--tts-backend", task["command"])
        self.assertIn("index-tts", task["command"])
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[0].started)
        self.assertEqual(FakeThread.instances[0].args[0], task_id)
        self.assertEqual(FakeThread.instances[0].args[2]["TRANSLATE_API_KEY"], "secret-key")
        runtime_brief = task.get("runtime_brief") or {}
        self.assertIn("index-tts(api=", runtime_brief.get("tts_base", ""))
        self.assertEqual(runtime_brief.get("dubbing_mode"), "single")
        self.assertIn("sentence(", runtime_brief.get("grouping", ""))
        self.assertEqual(runtime_brief.get("translation"), "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)")
        self.assertIn("source=off(", runtime_brief.get("merge", ""))
        self.assertIn("translated=off(", runtime_brief.get("merge", ""))
        self.assertEqual(runtime_brief.get("range"), "all(ranges=0)")
        self.assertEqual(runtime_brief.get("segment"), "8.0m/4.0m")
        self.assertEqual(task.get("translate_request_count"), 0)

    def test_start_auto_dubbing_requires_subtitle_file(self):
        """Auto dubbing 不再允许无字幕启动。"""

        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires subtitle_file", response.json()["detail"])

    def test_start_auto_dubbing_runtime_brief_keeps_grouped_for_source_short_merge(self):
        """开启 source short merge 后，index-tts 仍应保持 grouped synthesis。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "short_merge_enabled": "true",
                    "short_merge_threshold": "15",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        runtime_brief = task.get("runtime_brief") or {}
        self.assertIn("grouped=true", runtime_brief.get("grouping", ""))
        self.assertIn("force_fit=true", runtime_brief.get("grouping", ""))
        self.assertEqual(runtime_brief.get("translation"), "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)")
        self.assertIn("--index-max-text-tokens", task["command"])
        token_index = task["command"].index("--index-max-text-tokens")
        self.assertEqual(task["command"][token_index + 1], "40")

    def test_start_auto_dubbing_supports_custom_openai_compatible_provider(self):
        """自定义 OpenAI-compatible base_url/model 时，应透传到 CLI 并显示通用 provider 标签。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "custom-key",
                    "translate_base_url": "https://llm.example.com/v1",
                    "translate_model": "gpt-like-model",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["translate_base_url"], "https://llm.example.com/v1")
        self.assertEqual(task["translate_model"], "gpt-like-model")
        runtime_brief = task.get("runtime_brief") or {}
        self.assertEqual(
            runtime_brief.get("translation"),
            "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)",
        )
        self.assertEqual(FakeThread.instances[0].args[2]["TRANSLATE_API_KEY"], "custom-key")
        self.assertIn("--translate-base-url", task["command"])
        self.assertIn("https://llm.example.com/v1", task["command"])
        self.assertIn("--translate-model", task["command"])
        self.assertIn("gpt-like-model", task["command"])

    def test_start_auto_dubbing_accepts_multi_mode_with_uploaded_speaker_refs(self):
        """多人模式应按字幕 speaker 前缀收参考音映射。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "voxcpm-omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(len(task["speaker_ref_map"]), 2)
        self.assertEqual(task["speaker_ref_map"][0]["speaker_id"], "Speaker 1")
        self.assertIn("--speaker-ref-map-json", task["command"])
        self.assertNotIn("--voxcpm-api-url", task["command"])

    def test_start_auto_dubbing_with_speakers_and_zero_uploaded_refs_keeps_old_method(self):
        """有 speaker 但零上传参考音时，应自动推断 multi，并继续走旧方法。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["speaker_ref_map"], [])
        self.assertNotIn("--speaker-ref-map-json", task["command"])

    def test_update_from_stdout_counts_translate_requests(self):
        """运行日志里的翻译请求应累计到任务统计中。"""

        task_id = "task_translate_counter"
        dubbing_cli_api._task_store.create(
            task_id,
            {
                "id": task_id,
                "status": "running",
                "stage": "queued",
                "progress": 0.0,
                "stdout_tail": [],
                "translate_request_count": 0,
                "deepseek_request_count": 0,
                "runtime_brief": {"tts_base": "-", "dubbing_mode": "single", "grouping": "-", "timing_mode": "strict", "translation": "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)", "merge": "-", "range": "-", "segment": "-"},
            },
        )

        dubbing_cli_api._update_from_stdout(
            task_id,
            'HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"',
        )

        task = dubbing_cli_api._task_store.get_copy(task_id) or {}
        self.assertEqual(task.get("translate_request_count"), 1)
        self.assertNotIn("deepseek_request_count", task)

    def test_status_compatibly_exposes_translate_request_count_for_legacy_tasks(self):
        """旧任务若仍只有 legacy 翻译计数字段，状态接口也应统一暴露新字段。"""

        task_id = "task_legacy_translate_counter"
        dubbing_cli_api._task_store.create(
            task_id,
            {
                "id": task_id,
                "status": "running",
                "stage": "queued",
                "progress": 0.0,
                "stdout_tail": [],
                "deepseek_request_count": 3,
                "runtime_brief": {
                    "tts_base": "-",
                    "dubbing_mode": "single",
                    "grouping": "-",
                    "timing_mode": "strict",
                    "translation": "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)",
                "merge": "-",
                    "range": "-",
                    "segment": "-",
                },
            },
        )

        payload = self.client.get(f"/dubbing/auto/status/{task_id}").json()
        self.assertEqual(payload.get("translate_request_count"), 3)
        self.assertNotIn("deepseek_request_count", payload)

    def test_start_auto_dubbing_rejects_partial_speaker_reference_uploads(self):
        """有 speaker 时，只允许 0 上传或全上传；部分上传必须直接拒绝。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("zero uploaded references or a full set", response.json()["detail"])

    def test_start_auto_dubbing_ignores_legacy_omnivoice_backend_request(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "tts_backend": "omnivoice",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "single")

    def test_start_auto_dubbing_keeps_single_reference_audio_and_prompt_for_index_tts(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "Hello, this is the reference prompt.",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["single_ref_text"], "Hello, this is the reference prompt.")
        self.assertIn("--single-ref-text", task["command"])
        self.assertIn("--single-speaker-ref", task["command"])

    def test_start_from_project_legacy_omnivoice_request_normalizes_to_index_tts(self):
        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        subtitles_json = json.dumps(
            [
                {"start": 0.0, "end": 1.0, "text": "Speaker 1: hello", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "Speaker 2: world", "speaker_id": "Speaker 2"},
            ],
            ensure_ascii=False,
        )

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                files=[
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "subtitles_json": subtitles_json,
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "source",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_from_project_preserves_speaker_metadata_sidecar(self):
        """Current Project 启动时应把 speaker_id 额外写成 sidecar。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        subtitles_json = json.dumps(
            [
                {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "世界", "speaker_id": "Speaker 2"},
            ],
            ensure_ascii=False,
        )

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "subtitles_json": subtitles_json,
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        sidecar_path = Path(task["input_speaker_metadata"])
        self.assertTrue(sidecar_path.exists())
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(payload[0]["speaker_id"], "Speaker 1")
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_keeps_empty_single_ref_text_for_index_tts(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["single_ref_text"], "")
        self.assertNotIn("--single-ref-text", task["command"])

    def test_start_auto_dubbing_normalizes_voxcpm_backend_request_to_index_tts(self):
        """旧的 voxcpm-omnivoice 请求应被统一收敛到 index-tts。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "voxcpm-omnivoice",
                    "single_ref_text": "should be ignored",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_multi_with_legacy_voxcpm_request_still_uses_index_tts(self):
        """多人模式即便传旧 voxcpm 字段，也应统一收敛到 index-tts。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "dubbing_mode": "multi",
                    "tts_backend": "voxcpm-omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "multi")

    def test_start_auto_dubbing_multi_mode_with_legacy_omnivoice_request_uses_index_tts(self):
        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "dubbing_mode": "multi",
                    "tts_backend": "omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "multi")

    def test_start_auto_dubbing_rejects_invalid_dubbing_mode(self):
        """非法 dubbing_mode 应直接报错。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "dubbing_mode": "team",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("dubbing_mode", response.json()["detail"])

    def test_start_from_project_reuses_media_and_subtitles(self):
        """从当前项目启动时，应复用已有媒体和字幕。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        dubbing_cli_api.legacy_runtime.tasks["legacy-task"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": "demo.mp4",
        }

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "legacy-task",
                    "original_filename": "project-original.mp4",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project_filename"], "demo.mp4")
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["filename"], "demo.mp4")
        self.assertIn("--input-srt-kind", task["command"])
        self.assertIn("translated", task["command"])

    def test_start_from_project_passes_translate_system_prompt_into_command(self):
        """Current Project 启动时应透传自定义翻译系统提示词。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        dubbing_cli_api.legacy_runtime.tasks["legacy-task"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": "demo.mp4",
        }

        custom_prompt = "你是专业译者，优先保证专有名词一致。"
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "legacy-task",
                    "original_filename": "project-original.mp4",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "source",
                    "translate_system_prompt": custom_prompt,
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["translate_system_prompt"], custom_prompt)
        self.assertIn("--translate-system-prompt", task["command"])
        prompt_index = task["command"].index("--translate-system-prompt")
        self.assertEqual(task["command"][prompt_index + 1], custom_prompt)

    def test_start_from_project_does_not_duplicate_media_into_dubbing_upload_dir(self):
        """Current Project 启动不应再把媒体复制到 uploads/dubbing/<task_id>/。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "project-original.mp4",
                    "task_id": "legacy-task",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        private_task = dubbing_cli_api._tasks[task_id]
        # 任务输入媒体应直接指向原始上传路径，而不是 uploads/dubbing/<task_id>/project-original.mp4
        self.assertEqual(Path(private_task["input_path"]).resolve(), media_path.resolve())
        duplicated_media = Path(private_task["upload_dir"]) / "project-original.mp4"
        self.assertFalse(duplicated_media.exists())

    def test_load_batch_restores_completed_task_with_new_fields(self):
        """load-batch 应恢复新合同字段。"""

        batch_dir = self.output_root / "web_20260504_123000" / "longdub_20260504_123000"
        upload_dir = self.upload_root / "20260504_abc"
        upload_dir.mkdir(parents=True, exist_ok=True)
        media_path = upload_dir / "demo.mp4"
        media_path.write_bytes(b"fake-media")
        final_dir = batch_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        audio_path = final_dir / "dubbed_mix_full.wav"
        srt_path = final_dir / "dubbed_final_full.srt"
        audio_path.write_bytes(b"fake-audio")
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_123000",
                    "segments_total": 1,
                    "input_media_path": str(media_path),
                    "target_lang": "Chinese",
                    "pipeline_version": "auto-dubbing",
                    "dubbing_mode": "multi",
                    "rewrite_translation": False,
                    "input_srt_kind": "translated",
                    "tts_backend": "index-tts",
                    "speaker_ref_map": [{"speaker_id": "Speaker 1", "ref_audio_path": "/tmp/s1.wav"}],
                    "index_tts_api_url": "http://127.0.0.1:8011",
                    "segments": [{"summary": {"total": 1, "done": 1, "manual_review": 0}}],
                    "paths": {
                        "preferred_audio": str(audio_path),
                        "dubbed_mix_full": str(audio_path),
                        "dubbed_final_full_srt": str(srt_path),
                    },
                }
            ),
            encoding="utf-8",
        )

        response = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_123000"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["dubbing_mode"], "multi")
        self.assertEqual(payload["subtitle_mode"], "translated")
        self.assertEqual(payload["tts_backend"], "index-tts")
        self.assertEqual(payload["speaker_ref_map"][0]["speaker_id"], "Speaker 1")

    def test_load_batch_restores_incomplete_batch_for_resume(self):
        """无 batch manifest 时，应按 interrupted job 加载。"""

        batch_dir = self.output_root / "web_20260504_121212" / "longdub_20260504_221212"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        upload_dir = self.upload_root / "20260504_121212"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_video = upload_dir / "demo.mp4"
        uploaded_video.write_bytes(b"video-data")
        segment_dir.mkdir(parents=True, exist_ok=True)
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "target_lang": "Chinese",
                    "dubbing_mode": "single",
                    "input_srt_kind": "source",
                    "input_media_path": str(batch_dir / "segments" / "segment_0001.wav"),
                    "translated_short_merge_enabled": True,
                    "translated_short_merge_threshold": 9,
                    "tts_backend": "index-tts",
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_221212"})
        self.assertEqual(loaded.status_code, 200)
        payload = loaded.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["dubbing_mode"], "single")
        self.assertTrue(payload["translated_short_merge_enabled"])
        self.assertEqual(payload["translated_short_merge_threshold"], 9)
        self.assertIn("interrupted job", payload.get("error", ""))

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            resumed = self.client.post(f"/dubbing/auto/resume/{payload['id']}", data={"api_key": "secret-key"})
        self.assertEqual(resumed.status_code, 200)
        resumed_task = self.client.get(f"/dubbing/auto/status/{resumed.json()['task_id']}").json()
        self.assertIn("--resume-batch-dir", resumed_task["command"])
        self.assertIn(str(uploaded_video.resolve()), resumed_task["command"])

    def test_review_save_and_redub_runs_partial_pipeline(self):
        """save-and-redub 应更新字幕并调用局部重配。"""

        batch_dir = self.output_root / "web_20260504_223000" / "longdub_20260504_202927"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        (segment_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        bilingual_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\nHello\n", encoding="utf-8")
        (segment_dir / "subtitles" / "source.srt").write_text(source_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "subtitles" / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "subtitles" / "dubbed_final.srt").write_text(bilingual_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [{"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "translated_text": "你好", "status": "done"}],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_202927",
                    "segments_total": 1,
                    "segments": [{"index": 1, "start_sec": 0.0, "summary": {"total": 1, "done": 1, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_202927"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None), patch.object(
            dubbing_cli_api, "_rebuild_batch_outputs", return_value={"batch_rebuilt": True}
        ):
            response = self.client.post(
                f"/dubbing/auto/review/{task_id}/save-and-redub",
                data={"edits_json": json.dumps([{"index": 1, "translated_text": "你好（重配）"}], ensure_ascii=False)},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "saved_and_redubbed")
        self.assertEqual(payload["redubbed_segments"], 1)

    def test_review_redub_failed_no_candidates_keeps_task_completed(self):
        """没有 missing/manual_review 候选时，redub-failed 应返回 no_candidates。"""

        batch_dir = self.output_root / "web_20260504_220010" / "longdub_20260504_220010"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        subtitles_dir = segment_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        bilingual_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\nHello\n", encoding="utf-8")
        (subtitles_dir / "source.srt").write_text(source_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "dubbed_final.srt").write_text(bilingual_srt.read_text(encoding="utf-8"), encoding="utf-8")
        audio_path = segment_dir / "dubbed_segments" / "seg_0001.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"real")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [{"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "translated_text": "你好", "status": "done", "tts_audio_path": str(audio_path)}],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_220010",
                    "segments_total": 1,
                    "segments": [{"index": 1, "start_sec": 0.0, "summary": {"total": 1, "done": 1, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_220010"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None) as rerun_mock:
            response = self.client.post(f"/dubbing/auto/review/{task_id}/redub-failed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_candidates")
        rerun_mock.assert_not_called()

    def test_compact_process_error_output_filters_flash_attn_noise(self):
        """错误提炼应过滤 flash-attn 噪音。"""

        stdout = "[INFO] init:job_started - dubbing job started\nPipeline failed: Translation API key is required."
        stderr = "********\nWarning: flash-attn is not installed. Will only run the manual PyTorch version.\n********\n"
        detail = dubbing_cli_api._compact_process_error_output(stdout, stderr, keep_lines=20)
        self.assertIn("Pipeline failed: Translation API key is required.", detail)
        self.assertNotIn("flash-attn", detail)

    def test_switch_tts_runtime_on_demand_always_ensures_index_tts(self):
        """Auto Dubbing 收口后，运行时切换只应保证 index-tts 服务就绪。"""

        with patch.object(dubbing_cli_api, "_ensure_index_tts_service", return_value=None) as ensure_mock:
            dubbing_cli_api._switch_tts_runtime_on_demand(
                tts_backend="omnivoice",
                index_tts_api_url="http://127.0.0.1:8011",
            )

        ensure_mock.assert_called_once_with("http://127.0.0.1:8011")


@unittest.skipIf(bool(API_TEST_SKIP_REASON), API_TEST_SKIP_REASON or "")
class DubbingCliApiFailureParsingTests(unittest.TestCase):
    """覆盖 CLI 失败摘要提取规则。"""

    def test_extract_cli_failure_detail_prefers_pipeline_failed_line(self):
        stdout_tail = [
            "[INFO] translate:translation_started - translating subtitles",
            "[ERROR] finish:job_failed - pipeline failed",
            "Pipeline failed: Connection error.",
            "Traceback (most recent call last):",
            '  File "/tmp/a.py", line 1, in <module>',
            '    raise RuntimeError("command failed")',
            "RuntimeError: command failed (1): uv run python tools/dub_pipeline.py ...",
        ]

        detail = dubbing_cli_api._extract_cli_failure_detail(stdout_tail)
        self.assertEqual(detail, "Pipeline failed: Connection error.")

        message = dubbing_cli_api._build_cli_exit_error(1, stdout_tail)
        self.assertIn("Pipeline failed: Connection error.", message)
        self.assertNotIn("RuntimeError: command failed", message)


if __name__ == "__main__":
    unittest.main()
