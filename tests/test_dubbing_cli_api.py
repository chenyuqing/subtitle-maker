from __future__ import annotations

import json
import os
import shutil
import subprocess
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
            patch.object(dubbing_cli_api.legacy_runtime, "UPLOAD_DIR", str(self.upload_root)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(dubbing_cli_api._tasks.clear)
        self.addCleanup(dubbing_cli_api.legacy_runtime.tasks.clear)
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
        self.assertFalse(task["source_short_merge_enabled"])
        self.assertEqual(task["source_short_merge_threshold"], 15)
        self.assertFalse(task["translated_short_merge_enabled"])
        self.assertEqual(task["translated_short_merge_threshold"], 15)
        self.assertTrue(task["dub_audio_leveling_enabled"])
        self.assertEqual(task["dub_audio_leveling_target_rms"], 0.12)
        self.assertEqual(task["dub_audio_leveling_activity_threshold_db"], -35.0)
        self.assertEqual(task["dub_audio_leveling_max_gain_db"], 8.0)
        self.assertEqual(task["dub_audio_leveling_peak_ceiling"], 0.95)
        self.assertIn("--asr-language", task["command"])
        self.assertIn("--timing-mode", task["command"])
        self.assertIn("strict", task["command"])
        self.assertIn("--grouping-strategy", task["command"])
        self.assertIn("sentence", task["command"])
        self.assertIn("--source-short-merge-enabled", task["command"])
        enabled_flag_index = task["command"].index("--source-short-merge-enabled")
        self.assertEqual(task["command"][enabled_flag_index + 1], "false")
        self.assertIn("--source-short-merge-threshold", task["command"])
        self.assertIn("15", task["command"])
        self.assertIn("--translated-short-merge-enabled", task["command"])
        translated_enabled_index = task["command"].index("--translated-short-merge-enabled")
        self.assertEqual(task["command"][translated_enabled_index + 1], "false")
        self.assertIn("--translated-short-merge-threshold", task["command"])
        self.assertIn("--dub-audio-leveling-enabled", task["command"])
        leveling_flag_index = task["command"].index("--dub-audio-leveling-enabled")
        self.assertEqual(task["command"][leveling_flag_index + 1], "true")
        self.assertIn("--dub-audio-leveling-target-rms", task["command"])
        self.assertIn("--fallback-tts-backend", task["command"])
        fallback_index = task["command"].index("--fallback-tts-backend")
        self.assertEqual(task["command"][fallback_index + 1], "none")
        self.assertIn("--auto-pick-ranges", task["command"])
        self.assertIn("false", task["command"])
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[0].started)
        self.assertEqual(FakeThread.instances[0].args[0], task_id)
        self.assertEqual(FakeThread.instances[0].args[2]["DEEPSEEK_API_KEY"], "secret-key")

    def test_start_auto_dubbing_from_project_reuses_existing_media_and_task_media_mapping(self):
        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        dubbing_cli_api.legacy_runtime.tasks["legacy-task"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": "demo.mp4",
        }

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "legacy-task",
                    "original_filename": "project-original.mp4",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "source",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project_filename"], "demo.mp4")
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        task_internal = dubbing_cli_api._tasks[payload["task_id"]]
        self.assertEqual(task["filename"], "project-original.mp4")
        self.assertEqual(Path(task_internal["input_path"]).read_bytes(), b"video-data")
        self.assertTrue(str(task_internal["input_srt"]).endswith("project_source.srt"))
        self.assertIn("--input-srt", task["command"])
        self.assertIn("source", task["command"])

    def test_start_auto_dubbing_from_project_accepts_translated_subtitles_without_api_key(self):
        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.0, "text": "你好"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["subtitle_mode"], "translated")
        self.assertIn("--input-srt-kind", task["command"])
        self.assertIn("translated", task["command"])

    def test_start_auto_dubbing_from_project_rejects_srt_only_project(self):
        dubbing_cli_api.legacy_runtime.tasks["srt-only"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": None,
        }

        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "srt-only",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no reusable media", response.json()["detail"])

    def test_start_auto_dubbing_accepts_enabled_short_merge_settings(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "short_merge_enabled": "true",
                    "short_merge_threshold": "12",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertTrue(task["source_short_merge_enabled"])
        self.assertEqual(task["source_short_merge_threshold"], 12)
        enabled_flag_index = task["command"].index("--source-short-merge-enabled")
        self.assertEqual(task["command"][enabled_flag_index + 1], "true")
        flag_index = task["command"].index("--source-short-merge-threshold")
        self.assertEqual(task["command"][flag_index + 1], "12")

    def test_start_auto_dubbing_accepts_translated_short_merge_settings(self):
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
                    "translated_short_merge_enabled": "true",
                    "translated_short_merge_threshold": "11",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertTrue(task["translated_short_merge_enabled"])
        self.assertEqual(task["translated_short_merge_threshold"], 11)
        enabled_flag_index = task["command"].index("--translated-short-merge-enabled")
        self.assertEqual(task["command"][enabled_flag_index + 1], "true")
        flag_index = task["command"].index("--translated-short-merge-threshold")
        self.assertEqual(task["command"][flag_index + 1], "11")

    def test_start_auto_dubbing_accepts_omnivoice_fallback_options(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ), patch.object(
            dubbing_cli_api,
            "_ensure_omnivoice_service",
            side_effect=AssertionError("fallback omnivoice should not auto-start"),
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "fallback_tts_backend": "omnivoice",
                    "omnivoice_root": "/opt/omnivoice",
                    "omnivoice_python_bin": "/opt/omnivoice/.venv/bin/python",
                    "omnivoice_model": "k2-fsa/OmniVoice",
                    "omnivoice_device": "mps",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["fallback_tts_backend"], "omnivoice")
        self.assertEqual(task["omnivoice_model"], "k2-fsa/OmniVoice")
        self.assertIn("--omnivoice-root", task["command"])
        omni_root_index = task["command"].index("--omnivoice-root")
        self.assertEqual(task["command"][omni_root_index + 1], "/opt/omnivoice")

    def test_start_auto_dubbing_accepts_omnivoice_primary_without_api_mode(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api,
            "_ensure_omnivoice_service",
            side_effect=AssertionError("omnivoice service should not be checked when api mode disabled"),
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "tts_backend": "omnivoice",
                    "omnivoice_via_api": "false",
                    "omnivoice_root": "/opt/omnivoice",
                    "omnivoice_python_bin": "/opt/omnivoice/.venv/bin/python",
                    "omnivoice_model": "k2-fsa/OmniVoice",
                    "omnivoice_device": "mps",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["tts_backend"], "omnivoice")
        self.assertFalse(task["omnivoice_via_api"])
        self.assertIn("--omnivoice-via-api", task["command"])
        via_api_index = task["command"].index("--omnivoice-via-api")
        self.assertEqual(task["command"][via_api_index + 1], "false")

    def test_start_auto_dubbing_accepts_omnivoice_primary_with_env_runtime(self):
        env_patch = {
            "OMNIVOICE_ROOT": "/opt/omnivoice",
            "OMNIVOICE_PYTHON_BIN": "/opt/omnivoice/.venv/bin/python",
            "OMNIVOICE_MODEL": "k2-fsa/OmniVoice",
            "OMNIVOICE_DEVICE": "mps",
        }
        with patch.dict(os.environ, env_patch, clear=False), patch.object(
            dubbing_cli_api.threading, "Thread", FakeThread
        ), patch.object(
            dubbing_cli_api,
            "_check_index_tts_service",
            side_effect=AssertionError("index-tts health check should not run for omnivoice"),
        ), patch.object(
            dubbing_cli_api,
            "_ensure_omnivoice_service",
            return_value=None,
        ) as ensure_omnivoice_mock:
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "tts_backend": "omnivoice",
                    "omnivoice_root": "",
                    "omnivoice_python_bin": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["tts_backend"], "omnivoice")
        self.assertEqual(task["omnivoice_root"], "/opt/omnivoice")
        self.assertEqual(task["omnivoice_python_bin"], "/opt/omnivoice/.venv/bin/python")
        self.assertTrue(task["omnivoice_via_api"])
        self.assertEqual(task["omnivoice_api_url"], dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)
        self.assertIn("--omnivoice-root", task["command"])
        self.assertIn("--omnivoice-python-bin", task["command"])
        self.assertIn("--omnivoice-via-api", task["command"])
        self.assertIn("--omnivoice-api-url", task["command"])
        ensure_omnivoice_mock.assert_called_once_with(dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)

    def test_start_auto_dubbing_rejects_omnivoice_primary_without_runtime_when_api_disabled(self):
        with patch.dict(
            os.environ,
            {
                "OMNIVOICE_ROOT": "",
                "OMNIVOICE_PYTHON_BIN": "",
                "OMNIVOICE_MODEL": "",
                "OMNIVOICE_DEVICE": "",
            },
            clear=False,
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "tts_backend": "omnivoice",
                    "omnivoice_via_api": "false",
                    "omnivoice_root": "",
                    "omnivoice_python_bin": "",
                    "omnivoice_api_url": "",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("omnivoice_root", response.json()["detail"])

    def test_start_auto_dubbing_rejects_invalid_short_merge_threshold(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            for bad_value in ("5", "21"):
                response = self.client.post(
                    "/dubbing/auto/start",
                    files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                    data={
                        "target_lang": "Chinese",
                        "api_key": "secret-key",
                        "short_merge_enabled": "true",
                        "short_merge_threshold": bad_value,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("short_merge_threshold", response.json()["detail"])

    def test_start_auto_dubbing_ignores_threshold_when_short_merge_disabled(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "short_merge_enabled": "false",
                    "short_merge_threshold": "21",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertFalse(task["source_short_merge_enabled"])
        self.assertEqual(task["source_short_merge_threshold"], 21)

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

    def test_start_auto_dubbing_rejects_invalid_pipeline_version(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "pipeline_version": "v3",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("pipeline_version", response.json()["detail"])

    def test_start_auto_dubbing_v2_passes_v2_mode(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "pipeline_version": "v2",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task.get("pipeline_version"), "v2")
        self.assertIn("--v2-mode", task["command"])
        self.assertIn("true", task["command"])
        self.assertIn("--v2-rewrite-translation", task["command"])
        self.assertTrue(task.get("rewrite_translation"))

    def test_start_auto_dubbing_v2_allows_disabling_rewrite_translation(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "pipeline_version": "v2",
                    "rewrite_translation": "false",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertIn("--v2-rewrite-translation", task["command"])
        self.assertIn("false", task["command"])
        self.assertFalse(task.get("rewrite_translation"))

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

    def test_start_auto_dubbing_accepts_vtt_subtitle_file(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": (
                        "manual.vtt",
                        (
                            "WEBVTT\n\n"
                            "00:00.000 --> 00:01.200\n"
                            "hello\n\n"
                            "00:01.300 --> 00:02.000\n"
                            "world\n"
                        ).encode("utf-8"),
                        "text/vtt",
                    ),
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
        self.assertTrue(str(task["input_srt"]).endswith(".srt"))

    def test_start_auto_dubbing_accepts_markdown_timeline_subtitle_file(self):
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": (
                        "manual.md",
                        (
                            "[0:04] Hello world\n"
                            "[0:11] second line\n"
                            "[02:17:39] long timeline line\n"
                        ).encode("utf-8"),
                        "text/markdown",
                    ),
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
        self.assertTrue(str(task["input_srt"]).endswith(".srt"))

    def test_start_auto_dubbing_rejects_invalid_markdown_timeline_subtitle_file(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": ("manual.md", b"just plain text without timeline\n", "text/markdown"),
                },
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Markdown timeline", response.json()["detail"])

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

    def test_start_auto_dubbing_rejects_unsupported_subtitle_extension(self):
        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={
                    "video": ("demo.mp4", b"video-data", "video/mp4"),
                    "subtitle_file": ("manual.ass", b"[Script Info]\n", "text/plain"),
                },
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(".srt, .vtt or .md", response.json()["detail"])

    def test_start_auto_dubbing_rejects_when_another_job_is_active(self):
        dubbing_cli_api._tasks["existing"] = {"status": "running"}

        with patch.object(dubbing_cli_api, "_check_index_tts_service", return_value=None):
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={"target_lang": "Chinese", "api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 409)

    def test_resume_auto_dubbing_requeues_failed_task_with_resume_batch_dir(self):
        media_path = self.upload_root / "resume-demo.mp4"
        media_path.write_bytes(b"video-data")
        out_root = self.output_root / "web_failed_demo"
        resume_batch_dir = out_root / "longdub_20260427_100000"
        (resume_batch_dir / "segment_jobs").mkdir(parents=True, exist_ok=True)
        out_root.mkdir(parents=True, exist_ok=True)

        dubbing_cli_api._tasks["failed-task"] = {
            "id": "failed-task",
            "status": "failed",
            "filename": "resume-demo.mp4",
            "input_path": str(media_path),
            "input_srt": None,
            "upload_dir": str(self.upload_root),
            "out_root": str(out_root),
            "target_lang": "Chinese",
            "source_lang": "auto",
            "subtitle_mode": "source",
            "segment_minutes": 8.0,
            "min_segment_minutes": 4.0,
            "translate_base_url": dubbing_cli_api.DEFAULT_TRANSLATE_BASE_URL,
            "translate_model": dubbing_cli_api.DEFAULT_TRANSLATE_MODEL,
            "tts_backend": "index-tts",
            "fallback_tts_backend": "none",
            "omnivoice_root": "",
            "omnivoice_python_bin": "",
            "omnivoice_model": dubbing_cli_api.DEFAULT_OMNIVOICE_MODEL,
            "omnivoice_device": "auto",
            "omnivoice_via_api": True,
            "omnivoice_api_url": dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL,
            "index_tts_api_url": dubbing_cli_api.DEFAULT_INDEX_TTS_API_URL,
            "timing_mode": "strict",
            "grouping_strategy": "sentence",
            "source_short_merge_enabled": False,
            "source_short_merge_threshold": 15,
            "time_ranges": [],
            "auto_pick_ranges": False,
            "auto_pick_min_silence_sec": 0.8,
            "auto_pick_min_speech_sec": 1.0,
            "pipeline_version": "v1",
            "rewrite_translation": True,
            "process": None,
        }

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            response = self.client.post(
                "/dubbing/auto/resume/failed-task",
                data={"api_key": "secret-key"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resumed_from_task_id"], "failed-task")
        self.assertEqual(payload["resume_batch_id"], "longdub_20260427_100000")
        resumed_task_id = payload["task_id"]
        self.assertNotEqual(resumed_task_id, "failed-task")
        task = self.client.get(f"/dubbing/auto/status/{resumed_task_id}").json()
        self.assertIn("--resume-batch-dir", task["command"])
        resume_index = task["command"].index("--resume-batch-dir")
        self.assertEqual(task["command"][resume_index + 1], str(resume_batch_dir.resolve()))
        self.assertEqual(dubbing_cli_api._tasks[resumed_task_id]["out_root"], str(out_root.resolve()))
        self.assertTrue(FakeThread.instances)
        self.assertEqual(FakeThread.instances[-1].args[2]["DEEPSEEK_API_KEY"], "secret-key")

    def test_resume_auto_dubbing_rejects_non_failed_task(self):
        dubbing_cli_api._tasks["done-task"] = {"id": "done-task", "status": "completed"}
        response = self.client.post("/dubbing/auto/resume/done-task")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Only failed/cancelled tasks", response.json()["detail"])

    def test_resume_auto_dubbing_requires_existing_batch_dir(self):
        dubbing_cli_api._tasks["failed-missing-batch"] = {
            "id": "failed-missing-batch",
            "status": "failed",
            "out_root": str(self.output_root / "web_missing"),
        }
        response = self.client.post("/dubbing/auto/resume/failed-missing-batch")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Resume batch directory not found", response.json()["detail"])

    def test_load_auto_dubbing_batch_restores_completed_task(self):
        batch_dir = self.output_root / "web_20260419_123000" / "longdub_20260419_102927"
        upload_dir = self.upload_root / "20260419_abc"
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
                    "segments_total": 1,
                    "input_media_path": str(media_path),
                    "target_lang": "English",
                    "pipeline_version": "v2",
                    "rewrite_translation": False,
                    "timing_mode": "balanced",
                    "grouping_strategy": "legacy",
                    "source_short_merge_enabled": True,
                    "source_short_merge_threshold": 12,
                    "source_short_merge_threshold_mode": "seconds",
                    "translated_short_merge_enabled": True,
                    "translated_short_merge_threshold": 10,
                    "translated_short_merge_threshold_mode": "seconds",
                    "dub_audio_leveling_enabled": True,
                    "dub_audio_leveling_target_rms": 0.12,
                    "dub_audio_leveling_activity_threshold_db": -35.0,
                    "dub_audio_leveling_max_gain_db": 8.0,
                    "dub_audio_leveling_peak_ceiling": 0.95,
                    "input_srt_kind": "translated",
                    "tts_backend": "index-tts",
                    "fallback_tts_backend": "omnivoice",
                    "omnivoice_root": "/opt/omnivoice",
                    "omnivoice_python_bin": "/opt/omnivoice/.venv/bin/python",
                    "omnivoice_model": "k2-fsa/OmniVoice",
                    "omnivoice_device": "mps",
                    "index_tts_api_url": "http://127.0.0.1:8011",
                    "auto_pick_ranges": True,
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

        response = self.client.post(
            "/dubbing/auto/load-batch",
            data={"batch_id": "longdub_20260419_102927"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["target_lang"], "English")
        self.assertEqual(payload["pipeline_version"], "v2")
        self.assertFalse(payload["rewrite_translation"])
        self.assertEqual(payload["timing_mode"], "balanced")
        self.assertEqual(payload["grouping_strategy"], "legacy")
        self.assertTrue(payload["source_short_merge_enabled"])
        self.assertEqual(payload["source_short_merge_threshold"], 12)
        self.assertTrue(payload["translated_short_merge_enabled"])
        self.assertEqual(payload["translated_short_merge_threshold"], 10)
        self.assertTrue(payload["dub_audio_leveling_enabled"])
        self.assertEqual(payload["dub_audio_leveling_target_rms"], 0.12)
        self.assertNotIn("speaker_mode", payload)
        self.assertEqual(payload["subtitle_mode"], "translated")
        self.assertEqual(payload["tts_backend"], "index-tts")
        self.assertEqual(payload["fallback_tts_backend"], "omnivoice")
        self.assertEqual(payload["omnivoice_model"], "k2-fsa/OmniVoice")
        self.assertEqual(payload["index_tts_api_url"], "http://127.0.0.1:8011")
        self.assertTrue(payload["auto_pick_ranges"])
        self.assertTrue(payload.get("artifacts"))
        self.assertTrue(payload.get("input_media_url"))

    def test_list_auto_dubbing_batches_includes_incomplete_batch_dir(self):
        batch_dir = self.output_root / "web_20260427_111111" / "longdub_20260427_211111"
        batch_dir.mkdir(parents=True, exist_ok=True)

        response = self.client.get("/dubbing/auto/batches")
        self.assertEqual(response.status_code, 200)
        batches = response.json().get("batches", [])
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_id"], "longdub_20260427_211111")
        self.assertFalse(batches[0]["has_manifest"])
        self.assertEqual(batches[0]["status"], "incomplete")

    def test_load_auto_dubbing_batch_loads_incomplete_batch_for_resume(self):
        batch_dir = self.output_root / "web_20260427_121212" / "longdub_20260427_221212"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        segment_dir.mkdir(parents=True, exist_ok=True)
        media_path = self.upload_root / "resume_incomplete.mp4"
        media_path.write_bytes(b"video-data")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "target_lang": "Chinese",
                    "pipeline_version": "v1",
                    "input_srt_kind": "source",
                    "input_media_path": str(media_path),
                    "translated_short_merge_enabled": True,
                    "translated_short_merge_threshold": 9,
                    "dub_audio_leveling_enabled": True,
                    "dub_audio_leveling_target_rms": 0.14,
                    "tts_backend": "index-tts",
                    "fallback_tts_backend": "none",
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post(
            "/dubbing/auto/load-batch",
            data={"batch_id": "longdub_20260427_221212"},
        )
        self.assertEqual(loaded.status_code, 200)
        payload = loaded.json()
        self.assertEqual(payload["status"], "failed")
        self.assertIn("interrupted job", payload.get("error", ""))
        self.assertTrue(payload["translated_short_merge_enabled"])
        self.assertEqual(payload["translated_short_merge_threshold"], 9)
        self.assertTrue(payload["dub_audio_leveling_enabled"])
        self.assertEqual(payload["dub_audio_leveling_target_rms"], 0.14)

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            resumed = self.client.post(f"/dubbing/auto/resume/{payload['id']}", data={"api_key": "secret-key"})
        self.assertEqual(resumed.status_code, 200)
        resumed_task = self.client.get(f"/dubbing/auto/status/{resumed.json()['task_id']}").json()
        self.assertIn("--resume-batch-dir", resumed_task["command"])
        resume_index = resumed_task["command"].index("--resume-batch-dir")
        self.assertEqual(resumed_task["command"][resume_index + 1], str(batch_dir.resolve()))

    def test_load_incomplete_batch_prefers_uploaded_video_over_segment_audio(self):
        batch_dir = self.output_root / "web_20260427_093752" / "longdub_20260427_173755"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        raw_segments_dir = batch_dir / "segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        raw_segments_dir.mkdir(parents=True, exist_ok=True)
        # 模拟错误写入：segment manifest 记录的是切片音频而不是原视频。
        segment_audio = raw_segments_dir / "segment_0001.wav"
        segment_audio.write_bytes(b"segment-audio")
        upload_dir = self.upload_root / "20260427_093752"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_video = upload_dir / "demo.mp4"
        uploaded_video.write_bytes(b"uploaded-video")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "target_lang": "Chinese",
                    "pipeline_version": "v1",
                    "input_srt_kind": "source",
                    "input_media_path": str(segment_audio),
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post(
            "/dubbing/auto/load-batch",
            data={"batch_id": "longdub_20260427_173755"},
        )
        self.assertEqual(loaded.status_code, 200)
        payload = loaded.json()
        self.assertEqual(payload["status"], "failed")
        # 关键断言：续跑命令应优先使用 uploads 里的原视频，而不是 segment 切片音频。
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), patch.object(
            dubbing_cli_api, "_check_index_tts_service", return_value=None
        ):
            resumed = self.client.post(f"/dubbing/auto/resume/{payload['id']}", data={"api_key": "secret-key"})
        self.assertEqual(resumed.status_code, 200)
        resumed_task = self.client.get(f"/dubbing/auto/status/{resumed.json()['task_id']}").json()
        self.assertIn(str(uploaded_video.resolve()), resumed_task["command"])
        self.assertNotIn(str(segment_audio.resolve()), resumed_task["command"])

    def test_load_auto_dubbing_batch_falls_back_from_legacy_short_merge_units(self):
        batch_dir = self.output_root / "web_20260419_123001" / "longdub_20260419_102928"
        upload_dir = self.upload_root / "20260419_abd"
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
                    "segments_total": 1,
                    "input_media_path": str(media_path),
                    "target_lang": "English",
                    "pipeline_version": "v1",
                    "source_short_merge_enabled": True,
                    "source_short_merge_threshold": 64,
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

        response = self.client.post(
            "/dubbing/auto/load-batch",
            data={"batch_id": "longdub_20260419_102928"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["source_short_merge_enabled"])
        self.assertEqual(payload["source_short_merge_threshold"], 15)

    def test_review_endpoints_load_and_save(self):
        batch_dir = self.output_root / "web_20260419_123000" / "longdub_20260419_102927"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        (segment_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nHello source\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nWorld source\n",
            encoding="utf-8",
        )
        translated_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界\n",
            encoding="utf-8",
        )
        bilingual_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好\nHello source\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界\nWorld source\n",
            encoding="utf-8",
        )
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "source_text": "Hello source", "translated_text": "你好", "status": "done"},
                        {"id": "seg_0002", "start_sec": 2.0, "end_sec": 4.0, "source_text": "World source", "translated_text": "世界", "status": "done"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "segments_total": 1,
                    "segments": [{"start_sec": 0.0, "summary": {"total": 2, "done": 2, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260419_102927"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        review = self.client.get(f"/dubbing/auto/review/{task_id}")
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["total"], 2)

        save = self.client.post(
            f"/dubbing/auto/review/{task_id}/save",
            data={"edits_json": json.dumps([{"index": 2, "translated_text": "世界（已改）"}], ensure_ascii=False)},
        )
        self.assertEqual(save.status_code, 200)
        updated_text = translated_srt.read_text(encoding="utf-8")
        self.assertIn("世界（已改）", updated_text)

    def test_review_load_prefers_translated_full_srt_over_segment_manifest_text(self):
        batch_dir = self.output_root / "web_20260419_223100" / "longdub_20260419_202930"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        (segment_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nHello source\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nWorld source\n\n",
            encoding="utf-8",
        )
        translated_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好翻译\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界翻译\n\n",
            encoding="utf-8",
        )
        bilingual_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好翻译\nHello source\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界翻译\nWorld source\n\n",
            encoding="utf-8",
        )
        # 故意把 segment manifest 中 translated_text 写成源字幕，模拟现场错读问题。
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [
                        {"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "source_text": "Hello source", "translated_text": "Hello source", "status": "done"},
                        {"id": "seg_0002", "start_sec": 2.0, "end_sec": 4.0, "source_text": "World source", "translated_text": "World source", "status": "done"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "segments_total": 1,
                    "segments": [{"start_sec": 0.0, "summary": {"total": 2, "done": 2, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "source_full_srt": str(source_srt),
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260419_202930"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        review = self.client.get(f"/dubbing/auto/review/{task_id}")
        self.assertEqual(review.status_code, 200)
        rows = review.json().get("lines", [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["translated_text"], "你好翻译")
        self.assertEqual(rows[1]["translated_text"], "世界翻译")

    def test_review_save_and_redub_runs_partial_pipeline(self):
        batch_dir = self.output_root / "web_20260419_223000" / "longdub_20260419_202927"
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
        stale_translated_srt = segment_dir / "translated_stale.srt"
        stale_dubbed_final_srt = segment_dir / "dubbed_final_stale.srt"
        stale_translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\n", encoding="utf-8")
        stale_dubbed_final_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\nHello\n", encoding="utf-8")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [{"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "translated_text": "你好", "status": "done"}],
                    "paths": {
                        "source_srt": str(segment_dir / "subtitles" / "source.srt"),
                        "translated_srt": str(stale_translated_srt),
                        "dubbed_final_srt": str(stale_dubbed_final_srt),
                    },
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
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

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260419_202927"})
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
        updated_manifest = json.loads((segment_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            updated_manifest["paths"]["translated_srt"],
            str((segment_dir / "subtitles" / "translated.srt").resolve()),
        )
        self.assertEqual(
            updated_manifest["paths"]["dubbed_final_srt"],
            str((segment_dir / "subtitles" / "dubbed_final.srt").resolve()),
        )

    def test_review_redub_failed_reuses_existing_translated_text(self):
        batch_dir = self.output_root / "web_20260427_220000" / "longdub_20260427_220000"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        dubbed_segments_dir = segment_dir / "dubbed_segments"
        subtitles_dir = segment_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        dubbed_segments_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nWorld\n",
            encoding="utf-8",
        )
        translated_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界\n",
            encoding="utf-8",
        )
        bilingual_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n你好\nHello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界\nWorld\n",
            encoding="utf-8",
        )
        (subtitles_dir / "source.srt").write_text(source_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "dubbed_final.srt").write_text(bilingual_srt.read_text(encoding="utf-8"), encoding="utf-8")
        real_audio = dubbed_segments_dir / "seg_0001.wav"
        missing_audio = dubbed_segments_dir / "seg_0002_missing.wav"
        real_audio.write_bytes(b"real")
        missing_audio.write_bytes(b"missing")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [
                        {
                            "id": "seg_0001",
                            "start_sec": 0.0,
                            "end_sec": 2.0,
                            "translated_text": "你好",
                            "status": "done",
                            "tts_audio_path": str(real_audio),
                        },
                        {
                            "id": "seg_0002",
                            "start_sec": 2.0,
                            "end_sec": 4.0,
                            "translated_text": "世界",
                            "status": "manual_review",
                            "tts_audio_path": str(missing_audio),
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "segments_total": 1,
                    "segments": [{"index": 1, "start_sec": 0.0, "summary": {"total": 2, "done": 1, "manual_review": 1}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260427_220000"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None) as rerun_mock, patch.object(
            dubbing_cli_api, "_rebuild_batch_outputs", return_value={"batch_rebuilt": True}
        ):
            response = self.client.post(f"/dubbing/auto/review/{task_id}/redub-failed")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "forced_redubbed")
        self.assertEqual(payload["forced_line_count"], 1)
        self.assertEqual(payload["redubbed_segments"], 1)
        rerun_mock.assert_called_once()
        self.assertEqual(rerun_mock.call_args.kwargs["redub_local_indices"], [2])
        self.assertIn("世界", translated_srt.read_text(encoding="utf-8"))

    def test_review_redub_failed_no_candidates_keeps_task_completed(self):
        batch_dir = self.output_root / "web_20260427_220010" / "longdub_20260427_220010"
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

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260427_220010"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None) as rerun_mock:
            response = self.client.post(f"/dubbing/auto/review/{task_id}/redub-failed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_candidates")
        rerun_mock.assert_not_called()
        status = self.client.get(f"/dubbing/auto/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")

    def test_rebuild_batch_outputs_updates_final_subtitles_when_some_segments_are_skipped(self):
        batch_dir = self.output_root / "web_20260427_100000" / "longdub_20260427_100000"
        final_dir = batch_dir / "final"
        segment_1_dir = batch_dir / "segment_jobs" / "segment_0001"
        segment_2_dir = batch_dir / "segment_jobs" / "segment_0002"
        (segment_1_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        segment_2_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = segment_1_dir / "subtitles" / "source.srt"
        translated_srt = segment_1_dir / "subtitles" / "translated.srt"
        dubbed_final_srt = segment_1_dir / "subtitles" / "dubbed_final.srt"
        stale_translated_srt = segment_1_dir / "translated_stale.srt"
        stale_dubbed_final_srt = segment_1_dir / "dubbed_final_stale.srt"
        source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（新）\n", encoding="utf-8")
        dubbed_final_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（新）\nHello\n", encoding="utf-8")
        stale_translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\n", encoding="utf-8")
        stale_dubbed_final_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\nHello\n", encoding="utf-8")

        (segment_1_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "paths": {
                        "source_srt": str(source_srt),
                        "translated_srt": str(stale_translated_srt),
                        "dubbed_final_srt": str(stale_dubbed_final_srt),
                    }
                }
            ),
            encoding="utf-8",
        )
        # segment_0002 模拟“跳过段”：存在 manifest 但没有字幕文件。
        (segment_2_dir / "manifest.json").write_text(json.dumps({"paths": {}}), encoding="utf-8")

        translated_full_srt = final_dir / "translated_full.srt"
        dubbed_final_full_srt = final_dir / "dubbed_final_full.srt"
        translated_full_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\n", encoding="utf-8")
        dubbed_final_full_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\nHello\n", encoding="utf-8")

        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {"index": 1, "start_sec": 0.0, "end_sec": 10.0, "job_dir": str(segment_1_dir)},
                        {"index": 2, "start_sec": 10.0, "end_sec": 20.0, "job_dir": str(segment_2_dir)},
                    ],
                    "paths": {
                        "source_full_srt": str(final_dir / "source_full.srt"),
                        "translated_full_srt": str(translated_full_srt),
                        "dubbed_final_full_srt": str(dubbed_final_full_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        rebuild = dubbing_cli_api._rebuild_batch_outputs(batch_dir)

        self.assertTrue(rebuild["batch_rebuilt"])
        self.assertEqual(rebuild["translated_srt_inputs"], 1)
        self.assertEqual(rebuild["dubbed_final_srt_inputs"], 1)
        self.assertIn("你好（新）", translated_full_srt.read_text(encoding="utf-8"))
        self.assertIn("你好（新）", dubbed_final_full_srt.read_text(encoding="utf-8"))

    def test_review_save_and_redub_no_changes_skips_rerun(self):
        batch_dir = self.output_root / "web_20260419_223010" / "longdub_20260419_202928"
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

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260419_202928"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None) as rerun_mock:
            response = self.client.post(
                f"/dubbing/auto/review/{task_id}/save-and-redub",
                data={"edits_json": json.dumps([{"index": 1, "translated_text": "你好"}], ensure_ascii=False)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_changes")
        rerun_mock.assert_not_called()
        status = self.client.get(f"/dubbing/auto/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")

    def test_review_save_and_redub_failure_sets_task_failed_and_returns_detail(self):
        batch_dir = self.output_root / "web_20260419_224000" / "longdub_20260419_203000"
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
                    "paths": {"source_srt": str(segment_dir / "subtitles" / "source.srt"), "translated_srt": str(segment_dir / "subtitles" / "translated.srt")},
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
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

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260419_203000"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(
            dubbing_cli_api,
            "_rerun_segment_with_translated_srt",
            side_effect=RuntimeError("segment re-dub failed [segment_0001] (1): Pipeline failed: DeepSeek API Key is required."),
        ):
            response = self.client.post(
                f"/dubbing/auto/review/{task_id}/save-and-redub",
                data={"edits_json": json.dumps([{"index": 1, "translated_text": "你好（重配）"}], ensure_ascii=False)},
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("DeepSeek API Key is required", response.json()["detail"])
        self.assertEqual(translated_srt.read_text(encoding="utf-8").strip(), "1\n00:00:00,000 --> 00:00:02,000\n你好")
        self.assertEqual((segment_dir / "subtitles" / "translated.srt").read_text(encoding="utf-8").strip(), "1\n00:00:00,000 --> 00:00:02,000\n你好")
        self.assertEqual((segment_dir / "subtitles" / "dubbed_final.srt").read_text(encoding="utf-8").strip(), "1\n00:00:00,000 --> 00:00:02,000\n你好\nHello")
        restored_manifest = json.loads((segment_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(restored_manifest["segments"][0]["translated_text"], "你好")

        status = self.client.get(f"/dubbing/auto/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "failed")
        self.assertIn("segment re-dub failed", status.json().get("error", ""))

    def test_rerun_segment_with_translated_srt_preserves_grouped_mode_and_full_rerun(self):
        segment_dir = self.tmpdir / "segment_job"
        subtitles_dir = segment_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        translated_srt = subtitles_dir / "translated.srt"
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        input_media = self.tmpdir / "segment.wav"
        input_media.write_bytes(b"fake-media")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(input_media),
                    "segments": [
                        {"id": "seg_0001", "translated_text": "你好", "group_id": "group_0001", "skip_compose": False},
                        {"id": "seg_0002", "translated_text": "世界", "group_id": "group_0001", "skip_compose": True},
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(dubbing_cli_api, "_switch_tts_runtime_on_demand", return_value=None), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = ""

            dubbing_cli_api._rerun_segment_with_translated_srt(
                segment_job_dir=segment_dir,
                target_lang="English",
                index_tts_api_url="http://127.0.0.1:8010",
                pipeline_version="v1",
                rewrite_translation=True,
                redub_local_indices=[2],
            )

        cmd = run_mock.call_args.args[0]
        self.assertIn("--grouped-synthesis", cmd)
        grouped_index = cmd.index("--grouped-synthesis")
        self.assertEqual(cmd[grouped_index + 1], "true")
        self.assertIn("--force-fit-timing", cmd)
        force_fit_index = cmd.index("--force-fit-timing")
        self.assertEqual(cmd[force_fit_index + 1], "true")
        self.assertIn("--translated-input-preserve-synthesis-mode", cmd)
        preserve_index = cmd.index("--translated-input-preserve-synthesis-mode")
        self.assertEqual(cmd[preserve_index + 1], "true")
        self.assertIn("--fallback-tts-backend", cmd)
        self.assertNotIn("--redub-line-indices-json", cmd)

    def test_rerun_segment_with_translated_srt_prefers_manifest_backend_and_api_url(self):
        segment_dir = self.tmpdir / "segment_job_custom_backend"
        subtitles_dir = segment_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        translated_srt = subtitles_dir / "translated.srt"
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        input_media = self.tmpdir / "segment-custom.wav"
        input_media.write_bytes(b"fake-media")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(input_media),
                    "tts_backend": "qwen-tts",
                    "fallback_tts_backend": "omnivoice",
                    "omnivoice_root": "/opt/omnivoice",
                    "omnivoice_python_bin": "/opt/omnivoice/.venv/bin/python",
                    "omnivoice_model": "k2-fsa/OmniVoice",
                    "omnivoice_device": "mps",
                    "index_tts_api_url": "http://127.0.0.1:19010",
                    "segments": [
                        {"id": "seg_0001", "translated_text": "你好"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(dubbing_cli_api, "_switch_tts_runtime_on_demand", return_value=None), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = ""

            dubbing_cli_api._rerun_segment_with_translated_srt(
                segment_job_dir=segment_dir,
                target_lang="English",
                index_tts_api_url="http://127.0.0.1:8010",
                pipeline_version="v1",
                rewrite_translation=True,
                redub_local_indices=[1],
            )

        cmd = run_mock.call_args.args[0]
        backend_index = cmd.index("--tts-backend")
        self.assertEqual(cmd[backend_index + 1], "qwen-tts")
        api_url_index = cmd.index("--index-tts-api-url")
        self.assertEqual(cmd[api_url_index + 1], "http://127.0.0.1:19010")
        fallback_index = cmd.index("--fallback-tts-backend")
        self.assertEqual(cmd[fallback_index + 1], "omnivoice")
        omnivoice_model_index = cmd.index("--omnivoice-model")
        self.assertEqual(cmd[omnivoice_model_index + 1], "k2-fsa/OmniVoice")
        self.assertIn("--omnivoice-via-api", cmd)
        via_api_index = cmd.index("--omnivoice-via-api")
        self.assertEqual(cmd[via_api_index + 1], "true")
        self.assertIn("--omnivoice-api-url", cmd)
        api_url_index = cmd.index("--omnivoice-api-url")
        self.assertEqual(cmd[api_url_index + 1], "http://127.0.0.1:8020")

    def test_compact_process_error_output_filters_flash_attn_noise(self):
        stdout = "[INFO] init:job_started - dubbing job started\nPipeline failed: DeepSeek API Key is required."
        stderr = "********\nWarning: flash-attn is not installed. Will only run the manual PyTorch version.\n********\n"
        detail = dubbing_cli_api._compact_process_error_output(stdout, stderr, keep_lines=20)
        self.assertIn("Pipeline failed: DeepSeek API Key is required.", detail)
        self.assertNotIn("flash-attn", detail)

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

    def test_ensure_omnivoice_service_autostarts_local_launcher(self):
        with patch.object(
            dubbing_cli_api,
            "_check_omnivoice_service",
            side_effect=[
                web.HTTPException(status_code=503, detail="down"),
                None,
            ],
        ) as check_mock, patch.object(dubbing_cli_api, "OMNIVOICE_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = "started"
            run_mock.return_value.stderr = ""

            dubbing_cli_api._ensure_omnivoice_service(dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)

        self.assertEqual(check_mock.call_count, 2)
        run_mock.assert_called_once()

    def test_ensure_omnivoice_service_raises_when_autostart_fails(self):
        with patch.object(
            dubbing_cli_api,
            "_check_omnivoice_service",
            side_effect=web.HTTPException(status_code=503, detail="down"),
        ), patch.object(dubbing_cli_api, "OMNIVOICE_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock:
            run_mock.return_value.returncode = 1
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = "boom"

            with self.assertRaises(web.HTTPException) as ctx:
                dubbing_cli_api._ensure_omnivoice_service(dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("auto-start failed", ctx.exception.detail)

    def test_auto_start_local_omnivoice_tolerates_nonzero_when_service_is_ready(self):
        with patch.object(dubbing_cli_api, "OMNIVOICE_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock, patch.object(dubbing_cli_api, "_check_omnivoice_service", return_value=None) as health_mock:
            run_mock.return_value.returncode = 1
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = "script aborted"

            dubbing_cli_api._auto_start_local_omnivoice(dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)

        run_mock.assert_called_once()
        health_mock.assert_called_once()

    def test_auto_start_local_omnivoice_tolerates_timeout_when_service_is_ready(self):
        with patch.object(dubbing_cli_api, "OMNIVOICE_START_SCRIPT", self.tool_path), patch.object(
            dubbing_cli_api.subprocess, "run"
        ) as run_mock, patch.object(dubbing_cli_api, "_check_omnivoice_service", return_value=None) as health_mock:
            run_mock.side_effect = subprocess.TimeoutExpired(cmd=str(self.tool_path), timeout=420)

            dubbing_cli_api._auto_start_local_omnivoice(dubbing_cli_api.DEFAULT_OMNIVOICE_API_URL)

        run_mock.assert_called_once()
        health_mock.assert_called_once()

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

    def test_input_media_artifact_prefers_uploaded_video_when_manifest_points_segment_audio(self):
        task_id = "task-input-media"
        out_root = self.output_root / "web_20260427_093752"
        batch_dir = out_root / "longdub_20260427_173755"
        final_dir = batch_dir / "final"
        segments_dir = batch_dir / "segments"
        final_dir.mkdir(parents=True, exist_ok=True)
        segments_dir.mkdir(parents=True, exist_ok=True)

        segment_audio = segments_dir / "segment_0001.wav"
        segment_audio.write_bytes(b"segment-audio")
        upload_dir = self.upload_root / "20260427_093752"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_video = upload_dir / "source.mp4"
        uploaded_video.write_bytes(b"source-video")
        mix_path = final_dir / "dubbed_mix_full.wav"
        mix_path.write_bytes(b"mix-bytes")
        bilingual_srt_path = final_dir / "dubbed_final_full.srt"
        bilingual_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "demo",
                    "input_media_path": str(segment_audio),
                    "segments_total": 1,
                    "paths": {
                        "batch_dir": str(batch_dir),
                        "preferred_audio": str(mix_path),
                        "dubbed_mix_full": str(mix_path),
                        "dubbed_final_full_srt": str(bilingual_srt_path),
                    },
                    "segments": [{"summary": {"manual_review": 0}}],
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

        download = self.client.get(f"/dubbing/auto/artifact/{task_id}/input_media")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"source-video")

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
