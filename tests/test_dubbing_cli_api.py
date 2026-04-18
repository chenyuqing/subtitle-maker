from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from subtitle_maker import dubbing_cli_api
from subtitle_maker import web


class FakeThread:
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


class FakeProc:
    def __init__(self, pid: int = 12345):
        self.pid = pid
        self.wait_called = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.wait_called = True
        return 0


class FakeStreamProc:
    def __init__(self, lines: list[str], returncode: int, pid: int = 56789):
        self.pid = pid
        self.stdout = iter(lines)
        self._returncode = returncode

    def wait(self, timeout=None):
        return self._returncode

    def poll(self):
        return None


class DubbingCliApiTests(unittest.TestCase):
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
        FakeThread.instances = []

        self.patchers = [
            patch.object(dubbing_cli_api, "UPLOAD_ROOT", self.upload_root),
            patch.object(dubbing_cli_api, "OUTPUT_ROOT", self.output_root),
            patch.object(dubbing_cli_api, "TOOL_PATH", self.tool_path),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(dubbing_cli_api._tasks.clear)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_start_auto_dubbing_creates_isolated_task(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task_id = payload["task_id"]

        status = self.client.get(f"/dubbing/auto/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        task = status.json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["target_lang"], "Chinese")
        self.assertEqual(task["source_lang"], "English")
        self.assertEqual(task["timing_mode"], "strict")
        self.assertEqual(task["grouping_strategy"], "sentence")
        self.assertIn("--asr-language", task["command"])
        self.assertIn("--timing-mode", task["command"])
        self.assertIn("strict", task["command"])
        self.assertIn("--grouping-strategy", task["command"])
        self.assertIn("sentence", task["command"])
        self.assertIn("--auto-pick-ranges", task["command"])
        self.assertIn("false", task["command"])
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[0].started)
        self.assertEqual(FakeThread.instances[0].args[0], task_id)
        self.assertEqual(FakeThread.instances[0].args[2]["DEEPSEEK_API_KEY"], "secret-key")

    def test_start_auto_dubbing_rejects_invalid_timing_mode(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "timing_mode": "fast-and-loose",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("timing_mode", response.json()["detail"])

    def test_start_auto_dubbing_rejects_invalid_grouping_strategy(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "grouping_strategy": "bad-strategy",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("grouping_strategy", response.json()["detail"])

    def test_start_auto_dubbing_accepts_manual_time_ranges(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "time_ranges": '[{"start_sec": 12, "end_sec": 38}]',
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertIn("--time-ranges-json", task["command"])
        self.assertEqual(task["time_ranges"], [{"start_sec": 12.0, "end_sec": 38.0}])

    def test_start_auto_dubbing_rejects_invalid_time_ranges_json(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "time_ranges": "{bad json",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("time_ranges", response.json()["detail"])

    def test_start_auto_dubbing_accepts_manual_time_ranges_shorthand(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "time_ranges": "00:10-00:45, 01:20-02:00",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(
            task["time_ranges"],
            [
                {"start_sec": 10.0, "end_sec": 45.0},
                {"start_sec": 80.0, "end_sec": 120.0},
            ],
        )

    def test_start_auto_dubbing_accepts_optional_subtitle_file(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": ("manual.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhi\n", "application/x-subrip"),
                },
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertIn("--input-srt", task["command"])
        self.assertTrue(task.get("input_srt"))

    def test_start_auto_dubbing_forces_auto_pick_off_when_subtitle_uploaded(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": ("manual.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhi\n", "application/x-subrip"),
                },
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "auto_pick_ranges": "true",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["auto_pick_ranges"], False)
        self.assertIn("--auto-pick-ranges", task["command"])
        auto_pick_index = task["command"].index("--auto-pick-ranges")
        self.assertEqual(task["command"][auto_pick_index + 1], "false")

    def test_start_auto_dubbing_accepts_translated_subtitle_without_api_key(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": (
                        "manual.srt",
                        "1\n00:00:00,000 --> 00:00:01,000\n你好\n".encode("utf-8"),
                        "application/x-subrip",
                    ),
                },
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["subtitle_mode"], "translated")
        self.assertIn("--input-srt", task["command"])
        self.assertIn("--input-srt-kind", task["command"])
        self.assertIn("translated", task["command"])

    def test_start_auto_dubbing_rejects_invalid_subtitle_mode(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": ("manual.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhi\n", "application/x-subrip"),
                },
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "bad-mode",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("subtitle_mode", response.json()["detail"])

    def test_start_auto_dubbing_rejects_when_another_job_is_active(self):
        dubbing_cli_api._tasks["existing"] = {"status": "running"}

        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={"target_lang": "Chinese", "api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("already running", response.json()["detail"])

    def test_start_auto_dubbing_requires_api_key_for_default_translate_backend(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={"target_lang": "Chinese"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("API key", response.json()["detail"])

    def test_start_auto_dubbing_surfaces_index_tts_health_error(self):
        with patch.object(
            dubbing_cli_api,
            "_ensure_index_tts_service",
            side_effect=web.HTTPException(status_code=503, detail="index-tts service unavailable"),
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={"target_lang": "Chinese", "api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("index-tts", response.json()["detail"])

    def test_ensure_index_tts_service_autostarts_local_launcher(self):
        with patch.object(
            dubbing_cli_api,
            "_check_index_tts_service",
            side_effect=[
                web.HTTPException(status_code=503, detail="down"),
                None,
            ],
        ) as check_mock, patch.object(dubbing_cli_api, "INDEX_TTS_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = "started"
            run_mock.return_value.stderr = ""

            dubbing_cli_api._ensure_index_tts_service(dubbing_cli_api.DEFAULT_INDEX_TTS_API_URL)

        self.assertEqual(check_mock.call_count, 2)
        run_mock.assert_called_once()

    def test_ensure_index_tts_service_raises_when_autostart_fails(self):
        with patch.object(
            dubbing_cli_api,
            "_check_index_tts_service",
            side_effect=web.HTTPException(status_code=503, detail="down"),
        ), patch.object(dubbing_cli_api, "INDEX_TTS_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 1
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = "boom"

            with self.assertRaises(web.HTTPException) as ctx:
                dubbing_cli_api._ensure_index_tts_service(dubbing_cli_api.DEFAULT_INDEX_TTS_API_URL)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("auto-start failed", ctx.exception.detail)

    def test_completed_task_exposes_artifacts_and_download(self):
        task_id = "task-artifacts"
        out_root = self.output_root / f"web_{task_id}"
        batch_dir = out_root / "longdub_demo"
        final_dir = batch_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)

        mix_path = final_dir / "dubbed_mix_full.wav"
        mix_path.write_bytes(b"mix-bytes")
        bilingual_srt_path = final_dir / "dubbed_final_full.srt"
        bilingual_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "demo",
                    "segments_total": 2,
                    "paths": {
                        "batch_dir": str(batch_dir),
                        "preferred_audio": str(mix_path),
                        "dubbed_mix_full": str(mix_path),
                        "dubbed_final_full_srt": str(bilingual_srt_path),
                    },
                    "segments": [
                        {"summary": {"manual_review": 1}},
                        {"summary": {"manual_review": 0}},
                    ],
                }
            ),
            encoding="utf-8",
        )

        dubbing_cli_api._tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "out_root": str(out_root),
            "artifacts": [],
        }
        dubbing_cli_api._complete_task_from_manifest(task_id, manifest_path)

        status = self.client.get(f"/dubbing/auto/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["manual_review_segments"], 1)
        artifact_keys = {item["key"] for item in payload["artifacts"]}
        self.assertIn("preferred_audio", artifact_keys)
        self.assertIn("bilingual_srt", artifact_keys)

        download = self.client.get(f"/dubbing/auto/artifact/{task_id}/preferred_audio")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"mix-bytes")

    def test_run_cli_task_surfaces_downstream_failure_detail(self):
        task_id = "task-failed-detail"
        out_root = self.output_root / f"web_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        dubbing_cli_api._tasks[task_id] = {
            "id": task_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "out_root": str(out_root),
            "artifacts": [],
            "stdout_tail": [],
        }
        lines = [
            "[INFO] translate:translation_started - translating subtitles\n",
            'HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 401 Authorization Required"\n',
            "[ERROR] finish:job_failed - pipeline failed\n",
            "Pipeline failed: Error code: 401 - {'error': {'message': 'Authentication Fails'}}\n",
            "RuntimeError: command failed (1): /path/to/dub_pipeline.py\n",
        ]

        with patch.object(
            dubbing_cli_api.subprocess,
            "Popen",
            return_value=FakeStreamProc(lines=lines, returncode=1),
        ):
            dubbing_cli_api._run_cli_task(task_id, ["python", "fake"], {}, out_root)

        task = dubbing_cli_api._tasks[task_id]
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["exit_code"], 1)
        self.assertIn("dub_long_video.py exited with code 1", task["error"])
        self.assertIn("Pipeline failed: Error code: 401", task["error"])
        self.assertNotIn("RuntimeError: command failed", task["error"])

    def test_cancel_auto_dubbing_marks_task_and_kills_process_group(self):
        proc = FakeProc(pid=43210)
        dubbing_cli_api._tasks["cancel-me"] = {
            "id": "cancel-me",
            "status": "running",
            "stage": "dubbing",
            "process": proc,
            "out_root": str(self.output_root / "web_cancel-me"),
        }

        with patch.object(dubbing_cli_api.os, "killpg") as killpg:
            response = self.client.post("/dubbing/auto/cancel/cancel-me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(dubbing_cli_api._tasks["cancel-me"]["status"], "cancelled")
        killpg.assert_called_once_with(proc.pid, dubbing_cli_api.signal.SIGTERM)
        self.assertTrue(proc.wait_called)

    def test_model_all_release_reports_auto_task_count(self):
        with patch.object(web, "cancel_active_transcriptions", return_value=1), patch.object(
            web, "cancel_active_dubbing", return_value=2
        ), patch.object(web, "release_generator", return_value=None), patch.object(
            web, "release_index_tts_model", return_value={"ok": True}
        ):
            response = self.client.post("/model/all/release")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "all models released",
                "cancelled_transcriptions": 1,
                "cancelled_auto_tasks": 2,
                "index_tts_release": {"ok": True},
            },
        )

    def test_index_tts_management_endpoints_proxy_service_helpers(self):
        with patch.object(web, "get_index_tts_status", return_value={"ok": True, "status": "idle"}), patch.object(
            web, "start_index_tts_service", return_value={"ok": True, "returncode": 0}
        ), patch.object(web, "release_index_tts_model", return_value={"ok": True, "payload": {"released": True}}), patch.object(
            web, "stop_index_tts_service", return_value={"ok": True, "returncode": 0}
        ):
            self.assertEqual(self.client.get("/model/index-tts/status").json(), {"ok": True, "status": "idle"})
            self.assertEqual(self.client.post("/model/index-tts/start").json(), {"ok": True, "returncode": 0})
            self.assertEqual(
                self.client.post("/model/index-tts/release").json(),
                {"ok": True, "payload": {"released": True}},
            )
            self.assertEqual(self.client.post("/model/index-tts/stop").json(), {"ok": True, "returncode": 0})


if __name__ == "__main__":
    unittest.main()
