from __future__ import annotations

import json
import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from subtitle_maker import web
from subtitle_maker.app import legacy_runtime


class WebLegacyRouteTests(unittest.TestCase):
    """冻结 Phase 9 拆分后的 legacy web routes 兼容行为。"""

    def setUp(self):
        self.client = TestClient(web.app)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="web_legacy_routes_"))
        self.upload_dir = self.tmpdir / "uploads"
        self.output_dir = self.tmpdir / "outputs"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        legacy_runtime.tasks.clear()
        self.patchers = [
            patch.object(legacy_runtime, "UPLOAD_DIR", str(self.upload_dir)),
            patch.object(legacy_runtime, "OUTPUT_DIR", str(self.output_dir)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(legacy_runtime.tasks.clear)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_index_upload_and_stream_keep_working(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn('/static/app.js?v=', response.text)
        self.assertIn('id="global-translate-api-key"', response.text)
        self.assertIn('id="global-translate-base-url"', response.text)
        self.assertIn('id="global-translate-model"', response.text)
        self.assertIn('id="global-translate-save-key"', response.text)
        self.assertIn('id="global-translate-test-btn"', response.text)
        self.assertIn('id="global-translate-test-status"', response.text)
        self.assertIn('id="auto-dub-translate-system-prompt"', response.text)
        self.assertNotIn('id="agent-api-key"', response.text)
        self.assertNotIn('id="api-key"', response.text)
        self.assertNotIn('id="save-api-key"', response.text)

        upload = self.client.post(
            "/upload",
            files={"file": ("demo.mp4", b"video-bytes", "video/mp4")},
        )
        self.assertEqual(upload.status_code, 200)
        payload = upload.json()
        self.assertTrue((self.upload_dir / payload["filename"]).exists())

        streamed = self.client.get(payload["url"])
        self.assertEqual(streamed.status_code, 200)
        self.assertEqual(streamed.content, b"video-bytes")

    def test_upload_srt_and_status_keep_legacy_task_contract(self):
        response = self.client.post(
            "/upload_srt",
            files={"file": ("demo.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhello\n", "application/x-subrip")},
            data={"video_filename": "demo.mp4"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("task_id", payload)
        self.assertEqual(payload["filename"], "demo.srt")

        status = self.client.get(f"/status/{payload['task_id']}")
        self.assertEqual(status.status_code, 200)
        status_payload = status.json()
        self.assertEqual(status_payload["status"], "completed")
        self.assertEqual(status_payload["video_filename"], "demo.mp4")
        self.assertEqual(len(status_payload["subtitles"]), 1)

    def test_upload_srt_translated_kind_populates_translated_subtitles(self):
        response = self.client.post(
            "/upload_srt",
            files={"file": ("demo.srt", b"1\n00:00:00,000 --> 00:00:01,000\nni hao\n", "application/x-subrip")},
            data={"video_filename": "demo.mp4", "subtitle_kind": "translated"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subtitle_kind"], "translated")
        self.assertEqual(len(payload["translated_subtitles"]), 1)

        task = legacy_runtime.tasks[payload["task_id"]]
        self.assertIsInstance(task.get("translated_subtitles"), list)
        self.assertEqual(len(task["translated_subtitles"]), 1)

    def test_upload_srt_rejects_invalid_subtitle_kind(self):
        response = self.client.post(
            "/upload_srt",
            files={"file": ("demo.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhello\n", "application/x-subrip")},
            data={"video_filename": "demo.mp4", "subtitle_kind": "unknown"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("subtitle_kind", response.json()["detail"])

    def test_upload_srt_optimizes_same_speaker_short_turns(self):
        response = self.client.post(
            "/upload_srt",
            files={
                "file": (
                    "demo.srt",
                    (
                        "1\n00:00:00,000 --> 00:00:00,320\nSpeaker 1: No.\n\n"
                        "2\n00:00:00,320 --> 00:00:06,320\nSpeaker 1: But most guys are doing things in order not to ejaculate quite so quickly.\n"
                    ).encode("utf-8"),
                    "application/x-subrip",
                )
            },
            data={"video_filename": "demo.mp4", "subtitle_kind": "source"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["subtitles"]), 2)
        self.assertEqual(payload["subtitles"][0]["text"], "No.")
        self.assertEqual(payload["subtitles"][1]["text"], "But most guys are doing things in order not to ejaculate quite so quickly.")
        self.assertEqual(payload["subtitles"][0]["speaker_id"], "Speaker 1")
        self.assertEqual(payload["subtitles"][1]["speaker_id"], "Speaker 1")

    def test_upload_deepgram_json_and_status_keep_legacy_task_contract(self):
        deepgram_payload = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "paragraphs": {
                                    "paragraphs": [
                                        {
                                            "speaker": 0,
                                            "start": 0.0,
                                            "end": 1.0,
                                            "sentences": [
                                                {"text": "Hello there.", "start": 0.0, "end": 1.0},
                                            ],
                                        },
                                        {
                                            "speaker": 1,
                                            "start": 1.2,
                                            "end": 2.0,
                                            "sentences": [
                                                {"text": "General Kenobi.", "start": 1.2, "end": 2.0},
                                            ],
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }

        response = self.client.post(
            "/upload_deepgram_json",
            files={
                "file": (
                    "demo.json",
                    json.dumps(deepgram_payload, ensure_ascii=False).encode("utf-8"),
                    "application/json",
                )
            },
            data={"video_filename": "demo.mp4"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("task_id", payload)
        self.assertTrue(payload["filename"].endswith(".srt"))
        self.assertEqual(payload["subtitle_kind"], "source")
        self.assertEqual(len(payload["subtitles"]), 2)
        self.assertEqual(payload["subtitles"][0]["speaker_id"], "Speaker 1")

        status = self.client.get(f"/status/{payload['task_id']}")
        self.assertEqual(status.status_code, 200)
        status_payload = status.json()
        self.assertEqual(status_payload["status"], "completed")
        self.assertEqual(status_payload["video_filename"], "demo.mp4")
        self.assertEqual(len(status_payload["subtitles"]), 2)
        self.assertEqual(status_payload["subtitles"][1]["speaker_id"], "Speaker 2")

    def test_translation_connection_test_endpoint_returns_ok_for_valid_config(self):
        with patch("subtitle_maker.app.routes.translation.Translator.test_connection", return_value={"reply": "OK"}) as test_connection:
            response = self.client.post(
                "/translation/test",
                data={
                    "api_key": "dummy-key",
                    "translate_base_url": "https://llm.example.com/v1",
                    "translate_model": "demo-model",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "OpenAI-compatible")
        self.assertEqual(payload["provider_host"], "llm.example.com")
        self.assertEqual(payload["model"], "demo-model")
        self.assertEqual(payload["reply"], "OK")
        test_connection.assert_called_once()

    def test_async_transcribe_status_translate_and_export_still_work(self):
        media_path = self.upload_dir / "demo.mp4"
        media_path.write_bytes(b"video-bytes")

        def fake_transcribe_task(task_id, file_path, source_lang, max_width, time_ranges=None, existing_subtitles=None):
            self.assertEqual(file_path, str(media_path))
            legacy_runtime.tasks[task_id]["status"] = "completed"
            legacy_runtime.tasks[task_id]["subtitles"] = [
                {"start": 0.0, "end": 1.0, "text": "hello"},
            ]
            legacy_runtime.tasks[task_id]["srt_url"] = "/download/demo.srt"

        with patch.object(legacy_runtime, "transcribe_task", side_effect=fake_transcribe_task):
            response = self.client.post(
                "/transcribe",
                data={"filename": "demo.mp4", "language": "auto", "max_width": "40"},
            )
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]

        status = self.client.get(f"/status/{task_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")
        self.assertEqual(status.json()["subtitles"][0]["text"], "hello")

        with patch("subtitle_maker.app.routes.translation.Translator.translate_batch", return_value=["你好"]):
            translated = self.client.post(
                "/translate",
                data={
                    "task_id": task_id,
                    "target_lang": "Chinese",
                    "api_key": "dummy",
                    "translate_base_url": "https://llm.example.com/v1",
                    "translate_model": "demo-model",
                },
            )
        self.assertEqual(translated.status_code, 200)
        translated_payload = translated.json()
        self.assertEqual(translated_payload["translated_subtitles"][0]["text"], "你好")

        exported = self.client.post(
            "/export",
            data={"task_id": task_id, "format": "translated"},
        )
        self.assertEqual(exported.status_code, 200)
        self.assertIn("你好", exported.text)

    def test_project_reset_and_segment_route_exist(self):
        with patch("subtitle_maker.app.routes.projects.cancel_active_dubbing", return_value=2), patch.object(
            legacy_runtime,
            "clear_directory_contents",
            side_effect=[3, 4],
        ), patch.object(
            legacy_runtime,
            "prune_dubbing_uploads_keep_latest_videos",
            return_value={"video_candidates": 5, "kept_task_dirs": 3, "removed_entries": 2},
        ):
            reset = self.client.post("/project/reset")

        self.assertEqual(reset.status_code, 200)
        self.assertEqual(
            reset.json(),
            {
                "status": "reset",
                "cancelled_auto_tasks": 2,
                "uploads_removed": 3,
                "dubbing_pruned": {"video_candidates": 5, "kept_task_dirs": 3, "removed_entries": 2},
                "outputs_removed": 0,
            },
        )

        segment = self.client.post("/segment", data={"task_id": "missing", "max_duration": "30"})
        self.assertEqual(segment.status_code, 400)
        self.assertIn("No subtitles found", segment.json()["detail"])

    def test_polling_access_log_filter_suppresses_only_auto_dubbing_status_route(self):
        access_logger = logging.getLogger("uvicorn.access")
        original_filters = list(access_logger.filters)
        try:
            access_logger.filters[:] = []
            web._configure_access_log_filters()
            self.assertEqual(len(access_logger.filters), 1)

            polling_record = logging.LogRecord(
                name="uvicorn.access",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg='127.0.0.1 - "GET /dubbing/auto/status/demo HTTP/1.1" 200 OK',
                args=(),
                exc_info=None,
            )
            normal_record = logging.LogRecord(
                name="uvicorn.access",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg='127.0.0.1 - "POST /dubbing/auto/start HTTP/1.1" 200 OK',
                args=(),
                exc_info=None,
            )

            access_filter = access_logger.filters[0]
            self.assertFalse(access_filter.filter(polling_record))
            self.assertTrue(access_filter.filter(normal_record))

            web._configure_access_log_filters()
            self.assertEqual(len(access_logger.filters), 1)
        finally:
            access_logger.filters[:] = original_filters


if __name__ == "__main__":
    unittest.main()
