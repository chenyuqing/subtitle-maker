from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from subtitle_maker.manifests import BatchReplayOptions, build_batch_manifest, load_batch_manifest, load_segment_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
DUB_PIPELINE_PATH = REPO_ROOT / "tools" / "dub_pipeline.py"
DUB_LONG_VIDEO_PATH = REPO_ROOT / "tools" / "dub_long_video.py"

PIPELINE_SPEC = importlib.util.spec_from_file_location("test_manifest_dub_pipeline", DUB_PIPELINE_PATH)
assert PIPELINE_SPEC is not None and PIPELINE_SPEC.loader is not None
dub_pipeline = importlib.util.module_from_spec(PIPELINE_SPEC)
sys.modules[PIPELINE_SPEC.name] = dub_pipeline
PIPELINE_SPEC.loader.exec_module(dub_pipeline)

LONG_VIDEO_SPEC = importlib.util.spec_from_file_location("test_manifest_dub_long_video", DUB_LONG_VIDEO_PATH)
assert LONG_VIDEO_SPEC is not None and LONG_VIDEO_SPEC.loader is not None
dub_long_video = importlib.util.module_from_spec(LONG_VIDEO_SPEC)
sys.modules[LONG_VIDEO_SPEC.name] = dub_long_video
LONG_VIDEO_SPEC.loader.exec_module(dub_long_video)


class ManifestContractsTests(unittest.TestCase):
    """冻结当前 manifest 合约，避免后续重构把 replay 关键字段悄悄丢掉。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manifest_contract_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def build_args(self) -> argparse.Namespace:
        """构造最小但完整的参数快照，覆盖会影响重跑语义的字段。"""

        return argparse.Namespace(
            input_media=str((self.tmpdir / "demo.mp4").resolve()),
            target_lang="English",
            v2_mode="true",
            v2_rewrite_translation="false",
            input_srt_kind="translated",
            tts_backend="index-tts",
            fallback_tts_backend="omnivoice",
            omnivoice_root="/opt/omnivoice",
            omnivoice_python_bin="/opt/omnivoice/.venv/bin/python",
            omnivoice_model="k2-fsa/OmniVoice",
            omnivoice_device="mps",
            omnivoice_via_api="true",
            omnivoice_api_url="http://127.0.0.1:8020",
            index_tts_api_url="http://127.0.0.1:8010",
            timing_mode="balanced",
            grouping_strategy="sentence",
            source_short_merge_enabled="true",
            source_short_merge_threshold=12,
            translated_short_merge_enabled="true",
            translated_short_merge_threshold=10,
            dub_audio_leveling_enabled="true",
            dub_audio_leveling_target_rms=0.12,
            dub_audio_leveling_activity_threshold_db=-35.0,
            dub_audio_leveling_max_gain_db=8.0,
            dub_audio_leveling_peak_ceiling=0.95,
            grouped_synthesis="true",
            grouped_synthesis_effective=False,
            force_fit_timing="true",
            force_fit_timing_effective=False,
            auto_pick_ranges="true",
            range_strategy="manual",
            requested_time_ranges=[{"start_sec": 1.0, "end_sec": 9.0}],
            effective_time_ranges=[{"start_sec": 1.2, "end_sec": 8.7}],
        )

    def build_paths(self) -> Dict[str, Path | None]:
        """统一构造 manifest 里会被序列化的路径集合。"""

        base = self.tmpdir / "job"
        return {
            "source_audio": base / "audio" / "source.wav",
            "source_vocals": base / "audio" / "vocals.wav",
            "source_bgm": base / "audio" / "bgm.wav",
            "source_srt": base / "subtitles" / "source.srt",
            "translated_srt": base / "subtitles" / "translated.srt",
            "bilingual_srt": base / "subtitles" / "bilingual.srt",
            "dubbed_final_srt": base / "subtitles" / "dubbed_final.srt",
            "dubbed_vocals": base / "audio" / "dubbed_vocals.wav",
            "dubbed_mix": base / "audio" / "dubbed_mix.wav",
            "separation_report": base / "reports" / "separation.json",
            "log_jsonl": base / "logs" / "pipeline.jsonl",
        }

    def build_segment_records(self) -> list[dict[str, Any]]:
        """提供一组 done/failed 混合记录，便于校验 stats 聚合。"""

        return [
            {"id": "seg_0001", "status": "done"},
            {"id": "seg_0002", "status": "failed"},
        ]

    def test_build_manifest_contract_contains_replay_fields(self) -> None:
        """成功 manifest 必须保存 replay 关键字段，供 load-batch 和 redub 使用。"""

        args = self.build_args()
        paths = self.build_paths()
        separation = dub_pipeline.SeparationResult(
            source_audio=paths["source_audio"],
            vocals_audio=paths["source_vocals"],
            bgm_audio=paths["source_bgm"],
            separation_status="separated",
            separation_report=paths["separation_report"],
        )
        segment_records = self.build_segment_records()
        manual_review = [{"id": "seg_0002", "reason": "timing drift"}]

        manifest = dub_pipeline.build_manifest(
            job_id="job_001",
            args=args,
            separation=separation,
            paths=paths,
            segment_records=segment_records,
            manual_review=manual_review,
        )

        self.assertEqual(manifest["manifest_version"], "v1")
        self.assertEqual(manifest["job_id"], "job_001")
        self.assertEqual(manifest["target_lang"], "English")
        self.assertEqual(manifest["pipeline_version"], "v2")
        self.assertFalse(manifest["rewrite_translation"])
        self.assertEqual(manifest["input_srt_kind"], "translated")
        self.assertEqual(manifest["tts_backend"], "index-tts")
        self.assertEqual(manifest["fallback_tts_backend"], "omnivoice")
        self.assertEqual(manifest["omnivoice_root"], "/opt/omnivoice")
        self.assertEqual(manifest["omnivoice_python_bin"], "/opt/omnivoice/.venv/bin/python")
        self.assertEqual(manifest["omnivoice_model"], "k2-fsa/OmniVoice")
        self.assertEqual(manifest["omnivoice_device"], "mps")
        self.assertTrue(manifest["omnivoice_via_api"])
        self.assertEqual(manifest["omnivoice_api_url"], "http://127.0.0.1:8020")
        self.assertEqual(manifest["index_tts_api_url"], "http://127.0.0.1:8010")
        self.assertEqual(manifest["timing_mode"], "balanced")
        self.assertEqual(manifest["grouping_strategy"], "sentence")
        self.assertTrue(manifest["source_short_merge_enabled"])
        self.assertEqual(manifest["source_short_merge_threshold"], 12)
        self.assertEqual(manifest["source_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold"], 10)
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["dub_audio_leveling_enabled"])
        self.assertEqual(manifest["dub_audio_leveling_target_rms"], 0.12)
        self.assertEqual(manifest["dub_audio_leveling_activity_threshold_db"], -35.0)
        self.assertEqual(manifest["dub_audio_leveling_max_gain_db"], 8.0)
        self.assertEqual(manifest["dub_audio_leveling_peak_ceiling"], 0.95)
        self.assertFalse(manifest["grouped_synthesis"])
        self.assertFalse(manifest["force_fit_timing"])
        self.assertTrue(manifest["auto_pick_ranges"])
        self.assertEqual(manifest["range_strategy"], "manual")
        self.assertEqual(manifest["requested_time_ranges"], [{"start_sec": 1.0, "end_sec": 9.0}])
        self.assertEqual(manifest["effective_time_ranges"], [{"start_sec": 1.2, "end_sec": 8.7}])
        self.assertEqual(manifest["separation_status"], "separated")
        self.assertEqual(manifest["stats"], {"total": 2, "done": 1, "failed": 1, "manual_review": 1})
        self.assertEqual(manifest["segments"], segment_records)
        self.assertEqual(manifest["manual_review"], manual_review)
        self.assertEqual(
            set(manifest["paths"].keys()),
            {
                "source_audio",
                "source_vocals",
                "source_bgm",
                "source_srt",
                "translated_srt",
                "bilingual_srt",
                "dubbed_final_srt",
                "dubbed_vocals",
                "dubbed_mix",
                "separation_report",
                "log_jsonl",
            },
        )
        self.assertTrue(all(isinstance(value, str) for value in manifest["paths"].values()))

    def test_build_failure_manifest_contract_preserves_replay_fields(self) -> None:
        """失败 manifest 也必须保留重放配置，不能只剩 error 文本。"""

        args = self.build_args()
        paths = self.build_paths()
        segment_records = [{"id": "seg_0001", "status": "done"}]
        manual_review = [{"id": "seg_0009", "reason": "tts failure"}]

        manifest = dub_pipeline.build_failure_manifest(
            job_id="job_002",
            args=args,
            paths=paths,
            segment_records=segment_records,
            manual_review=manual_review,
            error_text="E-TTS-001 synth failed",
            separation_status="separated",
        )

        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["error"], "E-TTS-001 synth failed")
        self.assertEqual(manifest["target_lang"], "English")
        self.assertEqual(manifest["pipeline_version"], "v2")
        self.assertEqual(manifest["input_srt_kind"], "translated")
        self.assertEqual(manifest["tts_backend"], "index-tts")
        self.assertEqual(manifest["fallback_tts_backend"], "omnivoice")
        self.assertEqual(manifest["omnivoice_model"], "k2-fsa/OmniVoice")
        self.assertTrue(manifest["omnivoice_via_api"])
        self.assertEqual(manifest["omnivoice_api_url"], "http://127.0.0.1:8020")
        self.assertTrue(manifest["source_short_merge_enabled"])
        self.assertEqual(manifest["source_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold"], 10)
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["dub_audio_leveling_enabled"])
        self.assertEqual(manifest["dub_audio_leveling_target_rms"], 0.12)
        self.assertEqual(manifest["dub_audio_leveling_activity_threshold_db"], -35.0)
        self.assertEqual(manifest["dub_audio_leveling_max_gain_db"], 8.0)
        self.assertEqual(manifest["dub_audio_leveling_peak_ceiling"], 0.95)
        self.assertFalse(manifest["grouped_synthesis"])
        self.assertFalse(manifest["force_fit_timing"])
        self.assertEqual(manifest["stats"]["done"], 1)
        self.assertEqual(manifest["stats"]["failed"], 1)
        self.assertEqual(manifest["stats"]["manual_review"], 1)

    def test_write_skipped_segment_manifest_contract(self) -> None:
        """跳过分段也必须写出可合并、可扫描的最小 manifest。"""

        segment_audio = self.tmpdir / "segments" / "segment_0002.wav"
        segment_audio.parent.mkdir(parents=True, exist_ok=True)
        segment_audio.write_bytes(b"fake-audio")
        job_dir = self.tmpdir / "segment_jobs" / "segment_0002"

        manifest = dub_long_video.write_skipped_segment_manifest(
            segment_index=2,
            segment_audio=segment_audio,
            job_dir=job_dir,
            target_lang="Chinese",
            reason="no clipped subtitles",
        )

        manifest_path = job_dir / "manifest.json"
        self.assertTrue(manifest_path.exists())
        persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, persisted)
        self.assertEqual(persisted["manifest_version"], "v1")
        self.assertEqual(persisted["job_id"], "segment_0002")
        self.assertEqual(persisted["status"], "skipped")
        self.assertEqual(persisted["skip_reason"], "no clipped subtitles")
        self.assertEqual(persisted["target_lang"], "Chinese")
        self.assertEqual(persisted["stats"], {"total": 0, "done": 0, "failed": 0, "manual_review": 0})
        self.assertEqual(persisted["segments"], [])
        self.assertEqual(persisted["manual_review"], [])
        self.assertTrue((job_dir / "subtitles").exists())
        self.assertTrue(all(value is None for value in persisted["paths"].values()))

    def test_load_batch_manifest_normalizes_legacy_short_merge_units(self) -> None:
        """历史字数阈值 batch 应在 reader 中统一回退到新的秒数展示语义。"""

        manifest_path = self.tmpdir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "batch_legacy",
                    "input_media_path": "/tmp/demo.mp4",
                    "target_lang": "English",
                    "pipeline_version": "v1",
                    "rewrite_translation": True,
                    "input_srt_kind": "source",
                    "source_short_merge_enabled": True,
                    "source_short_merge_threshold": 64,
                    "requested_ranges": [{"start_sec": 1.0, "end_sec": 9.0}],
                    "paths": {"preferred_audio": "/tmp/final.wav"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manifest = load_batch_manifest(manifest_path)

        self.assertEqual(manifest.batch_id, "batch_legacy")
        self.assertEqual(manifest.options.target_lang, "English")
        self.assertEqual(manifest.options.pipeline_version, "v1")
        self.assertTrue(manifest.options.source_short_merge_enabled)
        self.assertEqual(manifest.options.source_short_merge_threshold, 15)
        self.assertFalse(manifest.options.translated_short_merge_enabled)
        self.assertEqual(manifest.options.translated_short_merge_threshold, 15)
        self.assertTrue(manifest.options.dub_audio_leveling_enabled)
        self.assertEqual(manifest.options.dub_audio_leveling_target_rms, 0.12)
        self.assertEqual(manifest.options.time_ranges, [{"start_sec": 1.0, "end_sec": 9.0}])
        self.assertEqual(manifest.paths["preferred_audio"], "/tmp/final.wav")

    def test_load_segment_manifest_infers_grouped_and_force_fit_compatibly(self) -> None:
        """segment reader 必须兼容旧 manifest 缺字段时的 grouped/force-fit 推断。"""

        manifest_path = self.tmpdir / "segment_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "job_id": "segment_0001",
                    "input_media_path": "/tmp/segment.wav",
                    "target_lang": "Chinese",
                    "pipeline_version": "v2",
                    "rewrite_translation": False,
                    "input_srt_kind": "translated",
                    "segments": [
                        {"id": "seg_0001", "group_id": "group_01", "skip_compose": False},
                        {"id": "seg_0002", "group_id": "group_01", "skip_compose": True},
                    ],
                    "paths": {"translated_srt": "/tmp/translated.srt"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manifest = load_segment_manifest(manifest_path)

        self.assertEqual(manifest.job_id, "segment_0001")
        self.assertEqual(manifest.input_media_path, "/tmp/segment.wav")
        self.assertEqual(manifest.options.pipeline_version, "v2")
        self.assertEqual(manifest.options.input_srt_kind, "translated")
        self.assertFalse(manifest.options.rewrite_translation)
        self.assertTrue(manifest.options.grouped_synthesis)
        self.assertFalse(manifest.options.force_fit_timing)
        self.assertFalse(manifest.options.translated_short_merge_enabled)
        self.assertEqual(manifest.options.translated_short_merge_threshold, 15)
        self.assertTrue(manifest.options.dub_audio_leveling_enabled)
        self.assertEqual(manifest.options.dub_audio_leveling_target_rms, 0.12)
        self.assertEqual(manifest.options.fallback_tts_backend, "none")
        self.assertEqual(len(manifest.segment_rows), 2)

    def test_build_batch_manifest_writes_legacy_and_normalized_range_keys(self) -> None:
        """batch writer 应同时保留旧 range 字段和新的标准字段。"""

        batch_dir = self.tmpdir / "batch"
        final_dir = batch_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "source_full.srt").write_text("", encoding="utf-8")

        manifest = build_batch_manifest(
            batch_id="batch_001",
            created_at="2026-04-24T00:00:00",
            input_media_path=self.tmpdir / "demo.mp4",
            options=BatchReplayOptions(
                target_lang="Chinese",
                pipeline_version="v1",
                rewrite_translation=True,
                timing_mode="strict",
                grouping_strategy="sentence",
                input_srt_kind="source",
                index_tts_api_url="http://127.0.0.1:8010",
                auto_pick_ranges=False,
            ),
            input_srt_path=None,
            segment_minutes=8.0,
            range_strategy="manual",
            requested_ranges=[(1.0, 9.0)],
            effective_ranges=[(1.5, 8.5)],
            batch_dir=batch_dir,
            preferred_audio=None,
            merged_vocals=None,
            merged_mix=None,
            merged_bgm=None,
            final_dir=final_dir,
            segments=[],
        )

        self.assertEqual(manifest["requested_ranges"], [{"start_sec": 1.0, "end_sec": 9.0}])
        self.assertEqual(manifest["requested_time_ranges"], manifest["requested_ranges"])
        self.assertEqual(manifest["effective_ranges"], [{"start_sec": 1.5, "end_sec": 8.5}])
        self.assertEqual(manifest["effective_time_ranges"], manifest["effective_ranges"])
        self.assertFalse(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold"], 15)
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["dub_audio_leveling_enabled"])
        self.assertEqual(manifest["dub_audio_leveling_target_rms"], 0.12)


if __name__ == "__main__":
    unittest.main()
