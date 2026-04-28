from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from subtitle_maker.jobs.recovery import (
    build_batch_task_updates,
    build_loaded_batch_task,
    find_batch_manifest_by_name,
    list_available_batches,
)


class JobRecoveryTests(unittest.TestCase):
    """冻结 Job Store 恢复层的最小行为。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="job_recovery_test_"))
        self.output_root = self.tmpdir / "outputs"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _artifact_url(self, task_id: str, key: str) -> str:
        """构造测试用 artifact URL。"""

        return f"/dubbing/auto/artifact/{task_id}/{key}"

    def test_build_batch_task_updates_preserves_replay_fields(self) -> None:
        """恢复层必须保留 load-batch 依赖的 replay 字段。"""

        batch_dir = self.output_root / "web_20260424_120000" / "longdub_20260424_120000"
        final_dir = batch_dir / "final"
        upload_dir = self.tmpdir / "uploads" / "20260424_120000"
        final_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)

        media_path = upload_dir / "demo.mp4"
        media_path.write_bytes(b"fake-media")
        audio_path = final_dir / "dubbed_mix_full.wav"
        audio_path.write_bytes(b"fake-audio")
        srt_path = final_dir / "dubbed_final_full.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260424_120000",
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
                    "index_tts_api_url": "http://127.0.0.1:8011",
                    "auto_pick_ranges": True,
                    "grouped_synthesis": True,
                    "force_fit_timing": False,
                    "tts_backend": "index-tts",
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

        updates = build_batch_task_updates(
            task_id="task_001",
            manifest_path=manifest_path,
            artifact_url_builder=self._artifact_url,
        )

        self.assertEqual(updates["status"], "completed")
        self.assertEqual(updates["target_lang"], "English")
        self.assertEqual(updates["pipeline_version"], "v2")
        self.assertFalse(updates["rewrite_translation"])
        self.assertEqual(updates["timing_mode"], "balanced")
        self.assertEqual(updates["grouping_strategy"], "legacy")
        self.assertTrue(updates["source_short_merge_enabled"])
        self.assertEqual(updates["source_short_merge_threshold"], 12)
        self.assertTrue(updates["translated_short_merge_enabled"])
        self.assertEqual(updates["translated_short_merge_threshold"], 10)
        self.assertTrue(updates["dub_audio_leveling_enabled"])
        self.assertEqual(updates["dub_audio_leveling_target_rms"], 0.12)
        self.assertEqual(updates["dub_audio_leveling_activity_threshold_db"], -35.0)
        self.assertEqual(updates["dub_audio_leveling_max_gain_db"], 8.0)
        self.assertEqual(updates["dub_audio_leveling_peak_ceiling"], 0.95)
        self.assertEqual(updates["subtitle_mode"], "translated")
        self.assertEqual(updates["index_tts_api_url"], "http://127.0.0.1:8011")
        self.assertTrue(updates["auto_pick_ranges"])
        self.assertTrue(updates["grouped_synthesis"])
        self.assertFalse(updates["force_fit_timing"])
        self.assertEqual(updates["tts_backend"], "index-tts")
        self.assertEqual(updates["result_audio"], "/dubbing/auto/artifact/task_001/preferred_audio")
        self.assertEqual(updates["result_srt"], "/dubbing/auto/artifact/task_001/bilingual_srt")
        artifact_keys = {item["key"] for item in updates["artifacts"]}
        self.assertIn("preferred_audio", artifact_keys)
        self.assertIn("bilingual_srt", artifact_keys)
        self.assertIn("input_media", artifact_keys)

    def test_build_loaded_batch_task_and_listing_cover_history_recovery(self) -> None:
        """恢复层应能列出批次，并生成 load-batch 所需完整任务记录。"""

        batch_dir = self.output_root / "web_20260424_130000" / "longdub_20260424_130000"
        final_dir = batch_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = batch_dir / "batch_manifest.json"
        srt_path = final_dir / "dubbed_final_full.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260424_130000",
                    "segments_total": 1,
                    "segments": [{"summary": {"total": 1, "done": 0, "manual_review": 1}}],
                    "paths": {"dubbed_final_full_srt": str(srt_path)},
                }
            ),
            encoding="utf-8",
        )

        found = find_batch_manifest_by_name(output_root=self.output_root, batch_id="longdub_20260424_130000")
        self.assertEqual(found, manifest_path)

        batches = list_available_batches(output_root=self.output_root, limit=10)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_id"], "longdub_20260424_130000")

        task = build_loaded_batch_task(
            task_id="20260424_130001",
            manifest_path=manifest_path,
            created_at="2026-04-24T13:00:01Z",
            default_short_merge_threshold=15,
            default_index_tts_api_url="http://127.0.0.1:8010",
            artifact_url_builder=self._artifact_url,
        )
        self.assertEqual(task["id"], "20260424_130001")
        self.assertEqual(task["short_id"], "20260424_130001")
        self.assertEqual(task["created_at"], "2026-04-24T13:00:01Z")
        self.assertEqual(task["out_root"], str(batch_dir.parent))
        self.assertEqual(task["status"], "failed")
        self.assertIn("manual_review", task["error"])


if __name__ == "__main__":
    unittest.main()
