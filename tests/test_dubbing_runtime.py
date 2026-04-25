from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from subtitle_maker.backends import split_text_for_index_tts
from subtitle_maker.domains.dubbing import (
    build_atempo_filter_chain,
    build_synthesis_groups,
    compute_effective_target_duration,
    resolve_segment_redub_runtime_options,
    synthesize_segments,
    synthesize_segments_grouped,
    synthesize_text_once,
)
from subtitle_maker.manifests import load_segment_manifest


class DubbingAlignmentTests(unittest.TestCase):
    def test_build_atempo_filter_chain_splits_large_ratio(self):
        self.assertEqual(build_atempo_filter_chain(6.0), "atempo=2.000000,atempo=2.000000,atempo=1.500000")

    def test_compute_effective_target_duration_borrows_future_gap(self):
        effective_target, borrowed_gap = compute_effective_target_duration(
            start_sec=1.0,
            end_sec=2.0,
            next_start_sec=3.0,
            gap_guard_sec=0.1,
        )
        self.assertAlmostEqual(effective_target, 1.9)
        self.assertAlmostEqual(borrowed_gap, 0.9)


class DubbingPipelineTests(unittest.TestCase):
    def test_build_synthesis_groups_sentence_strategy_prefers_sentence_end(self):
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello."},
            {"start": 1.1, "end": 2.0, "text": "How are"},
            {"start": 2.1, "end": 3.0, "text": "you"},
        ]
        groups = build_synthesis_groups(
            subtitles=subtitles,
            translated_lines=["你好。", "你", "好吗"],
            max_gap_sec=0.5,
            min_group_duration_sec=0.5,
            max_group_duration_sec=3.0,
            grouping_strategy="sentence",
        )
        self.assertEqual(groups, [[0], [1, 2]])

    def test_synthesize_text_once_dispatches_index_backend(self):
        with patch("subtitle_maker.domains.dubbing.pipeline.IndexTtsBackend") as backend_cls:
            backend = backend_cls.return_value
            synthesize_text_once(
                tts_backend="index-tts",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
                tts_qwen=None,
                qwen_prompt_items=None,
                tts_index=None,
                ref_audio_path=Path("/tmp/ref.wav"),
                index_emo_audio_prompt=Path("/tmp/emo.wav"),
                index_emo_alpha=0.7,
                index_use_emo_text=True,
                index_emo_text="calm",
                index_top_p=0.9,
                index_top_k=20,
                index_temperature=0.8,
                index_max_text_tokens=120,
                text="hello world",
                output_path=Path("/tmp/out.wav"),
            )

        backend_cls.assert_called_once_with(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        backend.synthesize.assert_called_once()
        request = backend.synthesize.call_args.args[0]
        self.assertEqual(request.text, "hello world")
        self.assertEqual(request.ref_audio_path, Path("/tmp/ref.wav"))
        self.assertEqual(request.output_path, Path("/tmp/out.wav"))
        self.assertEqual(request.emo_text, "calm")

    def test_synthesize_segments_reuses_existing_record_when_line_not_redubbed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reused_audio = tmp_path / "seg_0001.wav"
            reused_audio.write_bytes(b"fake-audio")
            records, manual_review = synthesize_segments(
                tts_backend="index-tts",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
                tts_qwen=None,
                qwen_prompt_items=None,
                tts_index=None,
                ref_audio_path=tmp_path / "ref.wav",
                ref_audio_selector=None,
                source_vocals_audio=tmp_path / "source.wav",
                source_media_duration_sec=None,
                index_emo_audio_prompt=None,
                index_emo_alpha=1.0,
                index_use_emo_text=False,
                index_emo_text=None,
                index_top_p=0.8,
                index_top_k=30,
                index_temperature=0.8,
                index_max_text_tokens=120,
                force_fit_timing=False,
                subtitles=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                translated_lines=["你好"],
                segment_dir=tmp_path / "segments",
                delta_pass_ms=120.0,
                delta_rewrite_ms=450.0,
                atempo_min=0.92,
                atempo_max=1.08,
                max_retry=0,
                translator=None,
                target_lang="Chinese",
                allow_rewrite_translation=False,
                prefer_translated_text=True,
                existing_records_by_id={
                    "seg_0001": {
                        "tts_audio_path": str(reused_audio),
                        "actual_duration_sec": 1.0,
                        "delta_sec": 0.0,
                        "status": "done",
                        "retry_count": 0,
                        "attempt_history": [],
                    }
                },
                redub_line_indices={2},
                v2_mode=False,
                logger=Mock(),
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["translated_text"], "你好")
        self.assertEqual(records[0]["tts_audio_path"], str(reused_audio))
        self.assertEqual(manual_review, [])

    def test_synthesize_segments_grouped_builds_silence_for_non_speech_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)
            records, manual_review = synthesize_segments_grouped(
                tts_backend="index-tts",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
                tts_qwen=None,
                qwen_prompt_items=None,
                tts_index=None,
                ref_audio_path=ref_audio,
                ref_audio_selector=None,
                source_media_duration_sec=None,
                index_emo_audio_prompt=None,
                index_emo_alpha=1.0,
                index_use_emo_text=False,
                index_emo_text=None,
                index_top_p=0.8,
                index_top_k=30,
                index_temperature=0.8,
                index_max_text_tokens=120,
                force_fit_timing=False,
                group_gap_sec=0.35,
                group_min_duration_sec=1.8,
                group_max_duration_sec=8.0,
                subtitles=[{"start": 0.0, "end": 1.0, "text": ""}],
                translated_lines=[""],
                segment_dir=tmp_path / "grouped",
                delta_pass_ms=120.0,
                timing_mode="strict",
                balanced_max_tempo_shift=0.08,
                balanced_min_line_sec=0.35,
                grouping_strategy="sentence",
                logger=Mock(),
                target_lang="Chinese",
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "done")
            self.assertTrue(Path(records[0]["tts_audio_path"]).exists())
            self.assertEqual(manual_review, [])


class DubbingBackendTests(unittest.TestCase):
    def test_split_text_for_index_tts_splits_cjk_on_punctuation(self):
        chunks = split_text_for_index_tts(
            "第一句很长，需要切开。第二句也很长，需要继续切开。",
            max_text_tokens=12,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("。"))


class DubbingReviewTests(unittest.TestCase):
    def test_resolve_segment_redub_runtime_options_prefers_manifest_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "input_media_path": str(Path(tmpdir) / "segment.wav"),
                        "pipeline_version": "v2",
                        "rewrite_translation": False,
                        "grouped_synthesis": True,
                        "force_fit_timing": True,
                        "tts_backend": "qwen-tts",
                        "index_tts_api_url": "http://127.0.0.1:19010",
                        "segments": [{"id": "seg_0001", "translated_text": "你好"}],
                    }
                ),
                encoding="utf-8",
            )
            manifest = load_segment_manifest(manifest_path)

        options = resolve_segment_redub_runtime_options(
            segment_manifest=manifest,
            fallback_pipeline_version="v1",
            fallback_rewrite_translation=True,
            fallback_index_tts_api_url="http://127.0.0.1:8010",
        )
        self.assertEqual(options.pipeline_version, "v2")
        self.assertFalse(options.rewrite_translation)
        self.assertTrue(options.grouped_synthesis)
        self.assertTrue(options.force_fit_timing)
        self.assertEqual(options.tts_backend, "qwen-tts")
        self.assertEqual(options.index_tts_api_url, "http://127.0.0.1:19010")


if __name__ == "__main__":
    unittest.main()
