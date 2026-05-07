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
MANIFEST_TEST_SKIP_REASON = ""

PIPELINE_SPEC = importlib.util.spec_from_file_location("test_manifest_dub_pipeline", DUB_PIPELINE_PATH)
assert PIPELINE_SPEC is not None and PIPELINE_SPEC.loader is not None
dub_pipeline = importlib.util.module_from_spec(PIPELINE_SPEC)
sys.modules[PIPELINE_SPEC.name] = dub_pipeline
try:
    PIPELINE_SPEC.loader.exec_module(dub_pipeline)
except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
    MANIFEST_TEST_SKIP_REASON = f"missing dependency {exc.name}"
    dub_pipeline = None


@unittest.skipIf(bool(MANIFEST_TEST_SKIP_REASON), MANIFEST_TEST_SKIP_REASON or "")
class ManifestContractsTests(unittest.TestCase):
    """冻结当前 manifest 主合同，避免 replay 关键字段丢失。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manifest_contract_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def build_args(self) -> argparse.Namespace:
        """构造最小但完整的参数快照。"""

        return argparse.Namespace(
            input_media=str((self.tmpdir / "demo.mp4").resolve()),
            target_lang="Chinese",
            dubbing_mode="multi",
            input_srt_kind="translated",
            tts_backend="index-tts",
            single_speaker_ref="",
            single_ref_text="",
            speaker_ref_map_json=json.dumps(
                [
                    {"speaker_id": "Speaker 1", "ref_audio_path": "/tmp/s1.wav", "ref_text": "hello one"},
                    {"speaker_id": "Speaker 2", "ref_audio_path": "/tmp/s2.wav", "ref_text": "hello two"},
                ],
                ensure_ascii=False,
            ),
            tts_model_path="/models/index",
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

    def test_build_manifest_contract_contains_new_replay_fields(self) -> None:
        """成功 manifest 必须保存新的 replay 字段。"""

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
        self.assertEqual(manifest["target_lang"], "Chinese")
        self.assertEqual(manifest["pipeline_version"], "auto-dubbing")
        self.assertEqual(manifest["dubbing_mode"], "multi")
        self.assertTrue(manifest["rewrite_translation"])
        self.assertEqual(manifest["input_srt_kind"], "translated")
        self.assertEqual(manifest["tts_backend"], "index-tts")
        self.assertEqual(manifest["speaker_ref_map"][0]["speaker_id"], "Speaker 1")
        self.assertEqual(manifest["speaker_ref_map"][0]["ref_text"], "hello one")
        self.assertEqual(manifest["tts_model_path"], "/models/index")
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
        self.assertEqual(manifest["range_strategy"], "manual")
        self.assertEqual(manifest["requested_time_ranges"], [{"start_sec": 1.0, "end_sec": 9.0}])
        self.assertEqual(manifest["effective_time_ranges"], [{"start_sec": 1.2, "end_sec": 8.7}])
        self.assertEqual(manifest["separation_status"], "separated")
        self.assertEqual(manifest["stats"], {"total": 2, "done": 1, "failed": 1, "manual_review": 1})
        self.assertEqual(manifest["segments"], segment_records)
        self.assertEqual(manifest["manual_review"], manual_review)

    def test_build_failure_manifest_contract_preserves_new_replay_fields(self) -> None:
        """失败 manifest 也必须保留新的 replay 字段。"""

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
        self.assertEqual(manifest["target_lang"], "Chinese")
        self.assertEqual(manifest["pipeline_version"], "auto-dubbing")
        self.assertEqual(manifest["dubbing_mode"], "multi")
        self.assertEqual(manifest["tts_backend"], "index-tts")
        self.assertEqual(manifest["speaker_ref_map"][1]["speaker_id"], "Speaker 2")
        self.assertEqual(manifest["speaker_ref_map"][1]["ref_text"], "hello two")
        self.assertTrue(manifest["source_short_merge_enabled"])
        self.assertEqual(manifest["source_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")
        self.assertEqual(manifest["stats"]["done"], 1)
        self.assertEqual(manifest["stats"]["failed"], 1)
        self.assertEqual(manifest["stats"]["manual_review"], 1)

    def test_batch_replay_options_round_trip_preserves_new_fields(self) -> None:
        """batch manifest round-trip 必须保留 single/multi 与 speaker refs。"""

        options = BatchReplayOptions(
            target_lang="Chinese",
            pipeline_version="auto-dubbing",
            dubbing_mode="multi",
            rewrite_translation=True,
            timing_mode="strict",
            grouping_strategy="sentence",
            input_srt_kind="translated",
            index_tts_api_url="http://127.0.0.1:8010",
            tts_backend="index-tts",
            single_ref_audio="",
            single_ref_text="",
            speaker_ref_map=[{"speaker_id": "Speaker 1", "ref_audio_path": "/tmp/s1.wav", "ref_text": "hello one"}],
            tts_model_path="/models/index",
        )
        manifest = build_batch_manifest(
            batch_id="batch_001",
            created_at="2026-05-03T00:00:00",
            input_media_path=self.tmpdir / "demo.mp4",
            options=options,
            batch_dir=self.tmpdir / "batch_001",
            preferred_audio=None,
            merged_vocals=None,
            merged_mix=None,
            merged_bgm=None,
            final_dir=self.tmpdir / "batch_001" / "final",
            input_srt_path=None,
            segment_minutes=8.0,
            range_strategy="all",
            requested_ranges=[],
            effective_ranges=[],
            segments=[],
        )
        manifest_path = self.tmpdir / "batch_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        loaded = load_batch_manifest(manifest_path)
        self.assertEqual(loaded.options.pipeline_version, "auto-dubbing")
        self.assertEqual(loaded.options.dubbing_mode, "multi")
        self.assertEqual(loaded.options.tts_backend, "index-tts")
        self.assertEqual(loaded.options.speaker_ref_map[0]["speaker_id"], "Speaker 1")
        self.assertEqual(loaded.options.speaker_ref_map[0]["ref_text"], "hello one")
        self.assertEqual(loaded.options.tts_model_path, "/models/index")

    def test_segment_manifest_reader_infers_defaults_for_new_contract(self) -> None:
        """segment manifest reader 在字段缺失时仍应回到当前默认合同。"""

        manifest_path = self.tmpdir / "segment_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "input_media_path": str(self.tmpdir / "segment.wav"),
                    "target_lang": "Chinese",
                    "segments": [{"id": "seg_0001", "translated_text": "你好"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = load_segment_manifest(manifest_path)
        self.assertEqual(loaded.options.pipeline_version, "auto-dubbing")
        self.assertEqual(loaded.options.dubbing_mode, "single")
        self.assertEqual(loaded.options.tts_backend, "index-tts")


if __name__ == "__main__":
    unittest.main()
