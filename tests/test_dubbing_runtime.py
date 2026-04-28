from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from subtitle_maker.backends import OmniVoiceBackend, TtsSynthesisRequest, split_text_for_index_tts
from subtitle_maker.domains.dubbing import (
    build_atempo_filter_chain,
    build_synthesis_groups,
    compute_effective_target_duration,
    resolve_segment_redub_runtime_options,
    synthesize_segments,
    synthesize_segments_grouped,
    synthesize_text_once,
)
from subtitle_maker.domains.media.compose import compose_vocals_master, normalize_speech_audio_level
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

    def test_compute_effective_target_duration_caps_huge_gap_for_short_line(self):
        effective_target, borrowed_gap = compute_effective_target_duration(
            start_sec=10.0,
            end_sec=10.5,
            next_start_sec=40.0,
            gap_guard_sec=0.1,
        )
        # 默认上限：最多借原句 1 倍（且不超过 2s），0.5s 句子最多借 0.5s。
        self.assertAlmostEqual(effective_target, 1.0)
        self.assertAlmostEqual(borrowed_gap, 0.5)

    def test_compose_vocals_master_resamples_mixed_sample_rates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            seg_a = tmp_path / "seg_a.wav"
            seg_b = tmp_path / "seg_b.wav"
            out = tmp_path / "master.wav"

            sf.write(str(seg_a), np.zeros(24000, dtype=np.float32), 24000)
            sf.write(str(seg_b), np.zeros(16000, dtype=np.float32), 16000)

            output_path, sample_rate = compose_vocals_master(
                segments=[
                    {"tts_audio_path": str(seg_a), "start_sec": 0.0, "end_sec": 1.0},
                    {"tts_audio_path": str(seg_b), "start_sec": 1.2, "end_sec": 2.2},
                ],
                output_path=out,
            )

            self.assertEqual(output_path, out)
            self.assertEqual(sample_rate, 24000)
            wav, sr = sf.read(str(out))
            self.assertEqual(sr, 24000)
            self.assertGreater(len(wav), 0)

    def test_compose_vocals_master_prefers_non_missing_audio_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            seg_dir = tmp_path / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)
            seg_real = seg_dir / "seg_0001.wav"
            seg_missing = seg_dir / "seg_0001_missing.wav"
            out = tmp_path / "master.wav"

            sf.write(str(seg_real), np.full(24000, 0.12, dtype=np.float32), 24000)
            sf.write(str(seg_missing), np.zeros(2400, dtype=np.float32), 24000)

            output_path, sample_rate = compose_vocals_master(
                segments=[
                    {"id": "seg_0001", "tts_audio_path": str(seg_missing), "start_sec": 0.0, "end_sec": 1.0},
                ],
                output_path=out,
            )

            self.assertEqual(output_path, out)
            self.assertEqual(sample_rate, 24000)
            wav, sr = sf.read(str(out))
            self.assertEqual(sr, 24000)
            # 若误用 missing，峰值会接近 0；正确应保留真实配音波形。
            self.assertGreater(float(np.max(np.abs(wav))), 0.05)

    def test_normalize_speech_audio_level_converges_active_rms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            quiet_path = tmp_path / "quiet.wav"
            loud_path = tmp_path / "loud.wav"
            quiet_audio = np.concatenate(
                [
                    np.zeros(1600, dtype=np.float32),
                    np.full(16000, 0.06, dtype=np.float32),
                    np.zeros(1600, dtype=np.float32),
                ]
            )
            loud_audio = np.concatenate(
                [
                    np.zeros(1600, dtype=np.float32),
                    np.full(16000, 0.24, dtype=np.float32),
                    np.zeros(1600, dtype=np.float32),
                ]
            )
            sf.write(str(quiet_path), quiet_audio, 16000)
            sf.write(str(loud_path), loud_audio, 16000)

            quiet_stats = normalize_speech_audio_level(input_path=quiet_path)
            loud_stats = normalize_speech_audio_level(input_path=loud_path)

            self.assertTrue(quiet_stats["applied"])
            self.assertTrue(loud_stats["applied"])
            self.assertAlmostEqual(float(quiet_stats["output_active_rms"]), 0.12, places=3)
            self.assertAlmostEqual(float(loud_stats["output_active_rms"]), 0.12, places=3)
            quiet_wav, _ = sf.read(str(quiet_path))
            loud_wav, _ = sf.read(str(loud_path))
            self.assertLessEqual(float(np.max(np.abs(quiet_wav))), 0.95)
            self.assertLessEqual(float(np.max(np.abs(loud_wav))), 0.95)

    def test_normalize_speech_audio_level_respects_gain_cap_and_peak_ceiling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            capped_path = tmp_path / "capped.wav"
            peak_limited_path = tmp_path / "peak_limited.wav"
            sf.write(str(capped_path), np.full(16000, 0.02, dtype=np.float32), 16000)
            sf.write(str(peak_limited_path), np.full(16000, 0.3, dtype=np.float32), 16000)

            capped_stats = normalize_speech_audio_level(
                input_path=capped_path,
                target_rms=0.12,
                max_gain_db=8.0,
            )
            peak_limited_stats = normalize_speech_audio_level(
                input_path=peak_limited_path,
                target_rms=0.8,
                max_gain_db=24.0,
                peak_ceiling=0.5,
            )

            self.assertAlmostEqual(float(capped_stats["applied_gain_db"]), 8.0, places=3)
            self.assertLess(float(capped_stats["output_active_rms"]), 0.12)
            self.assertTrue(peak_limited_stats["peak_limited"])
            self.assertLessEqual(float(peak_limited_stats["peak_after"]), 0.5)


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

    def test_synthesize_text_once_falls_back_to_omnivoice_when_primary_fails(self):
        with patch("subtitle_maker.domains.dubbing.pipeline.IndexTtsBackend") as index_cls, patch(
            "subtitle_maker.domains.dubbing.pipeline.OmniVoiceBackend"
        ) as omni_cls:
            index_backend = index_cls.return_value
            omni_backend = omni_cls.return_value
            index_backend.synthesize.side_effect = RuntimeError("primary failed")

            synthesize_text_once(
                tts_backend="index-tts",
                fallback_tts_backend="omnivoice",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
                tts_qwen=None,
                qwen_prompt_items=None,
                tts_index=None,
                ref_audio_path=Path("/tmp/ref.wav"),
                index_emo_audio_prompt=None,
                index_emo_alpha=1.0,
                index_use_emo_text=False,
                index_emo_text=None,
                index_top_p=0.8,
                index_top_k=30,
                index_temperature=0.8,
                index_max_text_tokens=120,
                text="hello world",
                output_path=Path("/tmp/out.wav"),
                omnivoice_root="/opt/omnivoice",
                omnivoice_python_bin="/opt/omnivoice/.venv/bin/python",
                omnivoice_model="k2-fsa/OmniVoice",
                omnivoice_device="mps",
                ref_text="hello",
                target_lang="English",
                target_duration_sec=1.9,
            )

        index_backend.synthesize.assert_called_once()
        omni_cls.assert_called_once()
        omni_backend.synthesize.assert_called_once()
        omni_request = omni_backend.synthesize.call_args.args[0]
        self.assertAlmostEqual(float(omni_request.target_duration_sec), 1.9, places=3)

    def test_synthesize_text_once_raises_when_primary_and_fallback_both_fail(self):
        with patch("subtitle_maker.domains.dubbing.pipeline.IndexTtsBackend") as index_cls, patch(
            "subtitle_maker.domains.dubbing.pipeline.OmniVoiceBackend"
        ) as omni_cls:
            index_cls.return_value.synthesize.side_effect = RuntimeError("index down")
            omni_cls.return_value.synthesize.side_effect = RuntimeError("omni down")

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_text_once(
                    tts_backend="index-tts",
                    fallback_tts_backend="omnivoice",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
                    tts_qwen=None,
                    qwen_prompt_items=None,
                    tts_index=None,
                    ref_audio_path=Path("/tmp/ref.wav"),
                    index_emo_audio_prompt=None,
                    index_emo_alpha=1.0,
                    index_use_emo_text=False,
                    index_emo_text=None,
                    index_top_p=0.8,
                    index_top_k=30,
                    index_temperature=0.8,
                    index_max_text_tokens=120,
                    text="hello world",
                    output_path=Path("/tmp/out.wav"),
                    omnivoice_root="/opt/omnivoice",
                    omnivoice_python_bin="/opt/omnivoice/.venv/bin/python",
                    omnivoice_model="k2-fsa/OmniVoice",
                    omnivoice_device="mps",
                    ref_text="hello",
                    target_lang="English",
                )

        self.assertIn("primary backend failed and fallback backend failed", str(ctx.exception))

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
            self.assertEqual(records[0]["tts_audio_path"], str((tmp_path / "segments" / "seg_0001.wav")))
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_resume_reuses_existing_record_without_redub_indices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reused_audio = tmp_path / "seg_0001.wav"
            reused_audio.write_bytes(b"fake-audio")

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
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
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

            synth_mock.assert_not_called()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["translated_text"], "你好")
            self.assertEqual(records[0]["tts_audio_path"], str((tmp_path / "segments" / "seg_0001.wav")))
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_normalizes_new_best_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                wav = np.concatenate(
                    [
                        np.zeros(1600, dtype=np.float32),
                        np.full(16000, 0.06, dtype=np.float32),
                        np.zeros(1600, dtype=np.float32),
                    ]
                )
                sf.write(str(output_path), wav, 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
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
                    existing_records_by_id=None,
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

            self.assertEqual(records[0]["status"], "done")
            self.assertTrue(records[0]["audio_leveling_applied"])
            self.assertAlmostEqual(float(records[0]["audio_leveling_output_rms"]), 0.12, places=3)
            wav, _ = sf.read(str(tmp_path / "segments" / "seg_0001.wav"))
            self.assertGreater(float(np.max(np.abs(wav))), 0.1)
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_resume_reuse_skips_releveling_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reused_audio = tmp_path / "reused.wav"
            sf.write(str(reused_audio), np.full(16000, 0.02, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
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
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

            synth_mock.assert_not_called()
            reused_wav, _ = sf.read(str(tmp_path / "segments" / "seg_0001.wav"))
            self.assertAlmostEqual(float(np.max(np.abs(reused_wav))), 0.02, places=3)
            self.assertFalse(records[0]["audio_leveling_applied"])
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_resume_prefers_real_audio_over_missing_record_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            seg_dir = tmp_path / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)
            real_audio = seg_dir / "seg_0001.wav"
            missing_audio = seg_dir / "seg_0001_missing.wav"
            real_audio.write_bytes(b"real-audio")
            missing_audio.write_bytes(b"missing-audio")

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
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
                    segment_dir=seg_dir,
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
                            "tts_audio_path": str(missing_audio),
                            "actual_duration_sec": 0.1,
                            "delta_sec": -0.9,
                            "status": "done",
                            "retry_count": 0,
                            "attempt_history": [],
                        }
                    },
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

            synth_mock.assert_not_called()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tts_audio_path"], str(real_audio))
            self.assertTrue(real_audio.exists())
            self.assertFalse(missing_audio.exists())
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_writes_missing_and_removes_stale_real_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            seg_dir = tmp_path / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)
            stale_real = seg_dir / "seg_0001.wav"
            stale_real.write_bytes(b"stale-real-audio")

            with patch(
                "subtitle_maker.domains.dubbing.pipeline.synthesize_text_once",
                side_effect=RuntimeError("tts failed"),
            ):
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
                    segment_dir=seg_dir,
                    delta_pass_ms=120.0,
                    delta_rewrite_ms=450.0,
                    atempo_min=0.92,
                    atempo_max=1.08,
                    max_retry=0,
                    translator=None,
                    target_lang="Chinese",
                    allow_rewrite_translation=False,
                    prefer_translated_text=True,
                    existing_records_by_id=None,
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "manual_review")
            self.assertTrue(records[0]["tts_audio_path"].endswith("_missing.wav"))
            self.assertFalse(stale_real.exists())
            self.assertTrue(Path(records[0]["tts_audio_path"]).exists())
            self.assertEqual(len(manual_review), 1)

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

    def test_synthesize_segments_omnivoice_precheck_rejects_too_short_effective_target_before_tts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            seg_dir = tmp_path / "segments"
            seg_dir.mkdir(parents=True, exist_ok=True)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
                records, manual_review = synthesize_segments(
                    tts_backend="omnivoice",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
                    tts_qwen=None,
                    qwen_prompt_items=None,
                    tts_index=None,
                    ref_audio_path=ref_audio,
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
                    subtitles=[{"start": 0.0, "end": 0.8, "text": "hello"}],
                    translated_lines=["你好"],
                    segment_dir=seg_dir,
                    delta_pass_ms=120.0,
                    delta_rewrite_ms=450.0,
                    atempo_min=0.92,
                    atempo_max=1.08,
                    max_retry=0,
                    translator=None,
                    target_lang="Chinese",
                    allow_rewrite_translation=False,
                    prefer_translated_text=True,
                    existing_records_by_id=None,
                    redub_line_indices=None,
                    v2_mode=False,
                    logger=Mock(),
                )

        synth_mock.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "manual_review")
        self.assertTrue(records[0]["tts_audio_path"].endswith("_missing.wav"))
        self.assertEqual(records[0]["attempt_history"][0]["action"], "omnivoice_duration_precheck")
        self.assertEqual(len(manual_review), 1)
        self.assertEqual(
            manual_review[0]["reason_code"],
            "omnivoice_target_duration_below_safe_floor",
        )
        self.assertEqual(manual_review[0]["error_stage"], "tts_precheck")

    def test_synthesize_segments_grouped_omnivoice_precheck_marks_all_short_group_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
                records, manual_review = synthesize_segments_grouped(
                    tts_backend="omnivoice",
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
                    subtitles=[
                        {"start": 0.0, "end": 0.4, "text": "Hello"},
                        {"start": 0.4, "end": 0.8, "text": "again"},
                    ],
                    translated_lines=["你", "好"],
                    segment_dir=tmp_path / "grouped_short",
                    delta_pass_ms=120.0,
                    timing_mode="strict",
                    balanced_max_tempo_shift=0.08,
                    balanced_min_line_sec=0.35,
                    grouping_strategy="sentence",
                    logger=Mock(),
                    target_lang="Chinese",
                )

        synth_mock.assert_not_called()
        self.assertEqual(len(records), 2)
        self.assertTrue(all(item["status"] == "manual_review" for item in records))
        self.assertTrue(all(item["tts_audio_path"].endswith("_missing.wav") for item in records))
        self.assertTrue(
            all(
                item["attempt_history"][0]["action"] == "group_omnivoice_duration_precheck"
                for item in records
            )
        )
        self.assertEqual(len(manual_review), 2)
        self.assertTrue(
            all(
                item["reason_code"] == "omnivoice_target_duration_below_safe_floor"
                for item in manual_review
            )
        )

    def test_synthesize_segments_grouped_omnivoice_non_speech_still_builds_silence_without_precheck(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once") as synth_mock:
                records, manual_review = synthesize_segments_grouped(
                    tts_backend="omnivoice",
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
                    subtitles=[{"start": 0.0, "end": 0.8, "text": ""}],
                    translated_lines=[""],
                    segment_dir=tmp_path / "grouped_non_speech",
                    delta_pass_ms=120.0,
                    timing_mode="strict",
                    balanced_max_tempo_shift=0.08,
                    balanced_min_line_sec=0.35,
                    grouping_strategy="sentence",
                    logger=Mock(),
                    target_lang="Chinese",
                )

        synth_mock.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "done")
        self.assertFalse(records[0]["tts_audio_path"].endswith("_missing.wav"))
        self.assertEqual(manual_review, [])

    def test_synthesize_segments_omnivoice_skips_fit_when_within_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 生成 1.25s 的稳定波形，确保高于 precheck 下限且进入“阈值内”分支。
                sf.write(str(output_path), np.full(20000, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                with patch("subtitle_maker.domains.dubbing.pipeline.fit_audio_to_duration") as fit_mock:
                    records, manual_review = synthesize_segments(
                        tts_backend="omnivoice",
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
                        force_fit_timing=True,
                        subtitles=[{"start": 0.0, "end": 1.25, "text": "hello"}],
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
                        existing_records_by_id=None,
                        redub_line_indices=None,
                        v2_mode=False,
                        logger=Mock(),
                    )

        fit_mock.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "done")
        actions = [item.get("action") for item in records[0].get("attempt_history", [])]
        self.assertIn("fit_timing_skip_tail_preserve", actions)
        self.assertEqual(manual_review, [])

    def test_synthesize_segments_omnivoice_avoids_atempo_to_preserve_sentence_head(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 目标 1.25s，实际 1.50s（超出 pass 阈值，但在 rewrite 阈值内）。
                sf.write(str(output_path), np.full(24000, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                with patch("subtitle_maker.domains.dubbing.pipeline.apply_atempo") as atempo_mock:
                    records, manual_review = synthesize_segments(
                        tts_backend="omnivoice",
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
                        subtitles=[{"start": 0.0, "end": 1.25, "text": "hello"}],
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
                        existing_records_by_id=None,
                        redub_line_indices=None,
                        v2_mode=False,
                        logger=Mock(),
                    )

        atempo_mock.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "done")
        actions = [item.get("action") for item in records[0].get("attempt_history", [])]
        self.assertIn("omnivoice_keep_natural_no_atempo", actions)
        self.assertEqual(manual_review, [])


class DubbingBackendTests(unittest.TestCase):
    def test_split_text_for_index_tts_splits_cjk_on_punctuation(self):
        chunks = split_text_for_index_tts(
            "第一句很长，需要切开。第二句也很长，需要继续切开。",
            max_text_tokens=12,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("。"))

    def test_omnivoice_backend_api_passes_duration(self):
        backend = OmniVoiceBackend(
            python_bin="/usr/bin/python3",
            root_dir="/tmp",
            model="k2-fsa/OmniVoice",
            via_api=True,
            api_url="http://127.0.0.1:8020",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)
            # 预建一个非空 wav 占位，避免 backend 的输出文件完整性校验失败。
            output.write_bytes(b"0" * 128)
            with patch("subtitle_maker.backends.omni_voice._http_json_request", return_value={"ok": True}) as request_mock:
                backend.synthesize(
                    TtsSynthesisRequest(
                        text="hello",
                        ref_audio_path=ref_audio,
                        output_path=output,
                        target_duration_sec=1.75,
                        language="English",
                    )
                )

            request_mock.assert_called_once()
            payload = request_mock.call_args.kwargs["payload"]
            self.assertAlmostEqual(float(payload["duration"]), 1.75, places=3)
            self.assertEqual(payload["language"], "en")

    def test_omnivoice_backend_rejects_too_short_target_duration_before_request(self):
        backend = OmniVoiceBackend(
            python_bin="/usr/bin/python3",
            root_dir="/tmp",
            model="k2-fsa/OmniVoice",
            via_api=True,
            api_url="http://127.0.0.1:8020",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)
            request = TtsSynthesisRequest(
                text="hello",
                ref_audio_path=ref_audio,
                output_path=output,
                target_duration_sec=0.8,
                language="English",
            )

            with patch("subtitle_maker.backends.omni_voice._http_json_request") as request_mock:
                with self.assertRaises(RuntimeError) as ctx:
                    backend.synthesize(request)

        request_mock.assert_not_called()
        self.assertIn("target duration below safe floor", str(ctx.exception))
        self.assertIn("0.800s", str(ctx.exception))

    def test_omnivoice_backend_api_restarts_local_service_after_connect_failure(self):
        backend = OmniVoiceBackend(
            python_bin="/usr/bin/python3",
            root_dir="/tmp",
            model="k2-fsa/OmniVoice",
            via_api=True,
            api_url="http://127.0.0.1:8020",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)
            request = TtsSynthesisRequest(
                text="hello",
                ref_audio_path=ref_audio,
                output_path=output,
                target_duration_sec=1.25,
                language="English",
            )

            with patch.object(
                backend,
                "_synthesize_via_api",
                side_effect=[
                    RuntimeError("E-TTS-001 omnivoice api connect failed: <urlopen error [Errno 61] Connection refused>"),
                    None,
                ],
            ) as synth_mock, patch.object(backend, "_release_api_model") as release_mock, patch(
                "subtitle_maker.backends.omni_voice._recover_local_omnivoice_service"
            ) as recover_mock:
                backend.synthesize(request)

        self.assertEqual(synth_mock.call_count, 2)
        release_mock.assert_called_once()
        recover_mock.assert_called_once_with("http://127.0.0.1:8020", timeout_sec=300.0)

    def test_omnivoice_backend_api_retries_conservative_profile_when_result_is_too_fast(self):
        backend = OmniVoiceBackend(
            python_bin="/usr/bin/python3",
            root_dir="/tmp",
            model="k2-fsa/OmniVoice",
            via_api=True,
            api_url="http://127.0.0.1:8020",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)
            request = TtsSynthesisRequest(
                text="hello",
                ref_audio_path=ref_audio,
                output_path=output,
                target_duration_sec=2.0,
                language="English",
            )

            with patch.object(
                backend,
                "_synthesize_via_api",
                side_effect=[
                    {"ok": True, "duration_sec": 0.8, "duration_ratio": 0.4, "retry_profile": "default"},
                    {"ok": True, "duration_sec": 1.8, "duration_ratio": 0.9, "retry_profile": "conservative"},
                ],
            ) as synth_mock:
                backend.synthesize(request)

        self.assertEqual(synth_mock.call_count, 2)
        self.assertEqual(synth_mock.call_args_list[0].kwargs["profile_name"], "default")
        self.assertEqual(synth_mock.call_args_list[1].kwargs["profile_name"], "conservative")
        self.assertEqual(
            synth_mock.call_args_list[1].kwargs["runtime_overrides"]["num_step"],
            48,
        )

    def test_omnivoice_backend_api_raises_quality_gate_failed_after_conservative_retry(self):
        backend = OmniVoiceBackend(
            python_bin="/usr/bin/python3",
            root_dir="/tmp",
            model="k2-fsa/OmniVoice",
            via_api=True,
            api_url="http://127.0.0.1:8020",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            output = tmp_path / "out.wav"
            sf.write(str(ref_audio), np.full(8000, 0.01, dtype=np.float32), 16000)
            request = TtsSynthesisRequest(
                text="hello",
                ref_audio_path=ref_audio,
                output_path=output,
                target_duration_sec=2.0,
                language="English",
            )

            with patch.object(
                backend,
                "_synthesize_via_api",
                side_effect=[
                    {"ok": True, "duration_sec": 0.8, "duration_ratio": 0.4, "retry_profile": "default"},
                    {"ok": True, "duration_sec": 0.9, "duration_ratio": 0.45, "retry_profile": "conservative"},
                ],
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    backend.synthesize(request)

        self.assertIn("quality gate failed", str(ctx.exception).lower())
        self.assertIn("conservative", str(ctx.exception))


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
                        "fallback_tts_backend": "omnivoice",
                        "omnivoice_root": "/opt/omnivoice",
                        "omnivoice_python_bin": "/opt/omnivoice/.venv/bin/python",
                        "omnivoice_model": "k2-fsa/OmniVoice",
                        "omnivoice_device": "mps",
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
        self.assertEqual(options.fallback_tts_backend, "omnivoice")
        self.assertEqual(options.omnivoice_model, "k2-fsa/OmniVoice")
        self.assertTrue(options.omnivoice_via_api)
        self.assertEqual(options.omnivoice_api_url, "http://127.0.0.1:8020")
        self.assertEqual(options.index_tts_api_url, "http://127.0.0.1:19010")


if __name__ == "__main__":
    unittest.main()
