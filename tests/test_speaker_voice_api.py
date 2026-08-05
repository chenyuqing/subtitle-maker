from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

API_TEST_SKIP_REASON = ""
try:
    from subtitle_maker import speaker_voice_api
    from subtitle_maker import web
except ModuleNotFoundError as exc:  # pragma: no cover
    speaker_voice_api = None
    web = None
    API_TEST_SKIP_REASON = f"missing dependency {exc.name}"


class FakeThread:
    """替代后台线程，避免测试中真正启动 Demucs 和裁音流程。"""

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
@pytest.mark.integration
class SpeakerVoiceApiTests(unittest.TestCase):
    """覆盖 Get Speaker Voice 独立接口主合同。"""

    def setUp(self):
        self.client = TestClient(web.app)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="speaker_voice_api_test_"))
        self.upload_root = self.tmpdir / "uploads"
        self.output_root = self.tmpdir / "outputs"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

        speaker_voice_api._task_store.clear()
        speaker_voice_api.legacy_runtime.tasks.clear()
        FakeThread.instances = []

        self.patchers = [
            patch.object(speaker_voice_api, "UPLOAD_ROOT", self.upload_root),
            patch.object(speaker_voice_api, "OUTPUT_ROOT", self.output_root),
            patch.object(speaker_voice_api.threading, "Thread", FakeThread),
            patch.object(speaker_voice_api.legacy_runtime, "UPLOAD_DIR", str(self.upload_root)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(speaker_voice_api._task_store.clear)
        self.addCleanup(speaker_voice_api.legacy_runtime.tasks.clear)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_start_requires_at_least_one_range(self):
        """Get Speaker Voice 没有 ranges 时必须阻止启动。"""

        response = self.client.post(
            "/speaker-voice/start",
            files={"media": ("demo.mp4", b"video-data", "video/mp4")},
            data={"time_ranges": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("at least one range", response.json()["detail"])

    def test_start_creates_standalone_task(self):
        """Standalone Upload 应创建独立 speaker voice 任务。"""

        response = self.client.post(
            "/speaker-voice/start",
            files={"media": ("demo.mp4", b"video-data", "video/mp4")},
            data={"time_ranges": '[{"start_sec": 10, "end_sec": 24}]'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task_id = payload["task_id"]
        task = self.client.get(f"/speaker-voice/status/{task_id}").json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["start_mode"], "standalone")
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[0].started)

    def test_start_from_project_reuses_current_project_media(self):
        """Current Project 模式应从当前项目媒体复制后启动任务。"""

        source_media = self.upload_root / "current.mp4"
        source_media.write_bytes(b"project-media")
        speaker_voice_api.legacy_runtime.tasks["task-1"] = {
            "video_filename": "current.mp4",
        }

        response = self.client.post(
            "/speaker-voice/start-from-project",
            data={
                "filename": "current.mp4",
                "original_filename": "current.mp4",
                "task_id": "task-1",
                "time_ranges": '[{"start_sec": 65, "end_sec": 78}]',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/speaker-voice/status/{payload['task_id']}").json()
        self.assertEqual(task["start_mode"], "project")
        self.assertEqual(payload["project_filename"], "current.mp4")

    def test_start_video_from_project_creates_video_slice_task(self):
        """Current Project 模式应支持按 ranges 启动视频切片任务。"""

        source_media = self.upload_root / "current.mp4"
        source_media.write_bytes(b"project-media")
        speaker_voice_api.legacy_runtime.tasks["task-2"] = {
            "video_filename": "current.mp4",
        }

        response = self.client.post(
            "/speaker-voice/start-video-from-project",
            data={
                "filename": "current.mp4",
                "original_filename": "current.mp4",
                "task_id": "task-2",
                "time_ranges": '[{"start_sec": 30, "end_sec": 45}]',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = self.client.get(f"/speaker-voice/status/{payload['task_id']}").json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["start_mode"], "project")
        self.assertEqual(task.get("slice_mode"), "video")
        self.assertEqual(payload["project_filename"], "current.mp4")
