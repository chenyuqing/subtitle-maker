from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from types import SimpleNamespace
RUNTIME_TEST_SKIP_REASON = ""
try:
    import soundfile as sf
except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
    sf = None
    RUNTIME_TEST_SKIP_REASON = f"missing dependency {exc.name}"

if not RUNTIME_TEST_SKIP_REASON:
    try:
        from subtitle_maker.backends import IndexTtsBackend, TtsSynthesisRequest, split_text_for_index_tts
        from subtitle_maker.domains.dubbing import (
            build_atempo_filter_chain,
            build_synthesis_groups,
            compute_effective_target_duration,
            resolve_segment_redub_runtime_options,
            synthesize_segments,
            synthesize_segments_grouped,
            synthesize_text_once,
            trim_leading_silence_conservative,
            trim_silence_edges,
        )
        from subtitle_maker.domains.media.compose import (
            build_dubbed_video_two_step,
            compose_vocals_master,
            normalize_speech_audio_level,
        )
        from subtitle_maker.manifests import load_segment_manifest
    except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
        RUNTIME_TEST_SKIP_REASON = f"missing dependency {exc.name}"


@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
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

    def test_trim_silence_edges_keeps_wider_default_padding_for_quiet_tails(self):
        """默认 padding 提升到 80ms 后，应保留更多轻声首尾。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.wav"
            output_path = tmp_path / "output.wav"
            sample_rate = 1000
            wav = np.concatenate(
                [
                    np.zeros(120, dtype=np.float32),
                    np.full(200, 0.2, dtype=np.float32),
                    np.zeros(120, dtype=np.float32),
                ]
            )
            sf.write(str(input_path), wav, sample_rate)

            before_trim, after_trim = trim_silence_edges(
                input_path=input_path,
                output_path=output_path,
            )

        self.assertAlmostEqual(before_trim, 0.44, places=2)
        # 0.20s 主体 + 前后各 0.08s padding = 0.36s。
        self.assertAlmostEqual(after_trim, 0.36, places=2)

    def test_trim_leading_silence_conservative_only_trims_front(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.wav"
            output_path = tmp_path / "output.wav"
            sample_rate = 1000
            wav = np.concatenate(
                [
                    np.zeros(220, dtype=np.float32),
                    np.full(200, 0.2, dtype=np.float32),
                    np.zeros(180, dtype=np.float32),
                ]
            )
            sf.write(str(input_path), wav, sample_rate)

            before_trim, after_trim = trim_leading_silence_conservative(
                input_path=input_path,
                output_path=output_path,
                max_trim_sec=0.35,
            )

            trimmed, _ = sf.read(str(output_path))

        self.assertAlmostEqual(before_trim, 0.60, places=2)
        self.assertAlmostEqual(after_trim, 0.46, places=2)
        self.assertEqual(len(trimmed), 460)

    def test_trim_leading_silence_conservative_respects_max_trim_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.wav"
            output_path = tmp_path / "output.wav"
            sample_rate = 1000
            wav = np.concatenate(
                [
                    np.zeros(600, dtype=np.float32),
                    np.full(200, 0.2, dtype=np.float32),
                ]
            )
            sf.write(str(input_path), wav, sample_rate)

            _, after_trim = trim_leading_silence_conservative(
                input_path=input_path,
                output_path=output_path,
                max_trim_sec=0.35,
            )

        self.assertAlmostEqual(after_trim, 0.45, places=2)

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

    def test_build_dubbed_video_two_step_runs_copy_path(self):
        """two-step 成功路径应先准备音频，再走视频 copy 合并。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_media = tmp_path / "demo.mp4"
            preferred_audio = tmp_path / "dubbed_mix_full.wav"
            output_video = tmp_path / "dubbed_video_full.mp4"
            output_audio = tmp_path / "dubbed_audio_for_video.m4a"
            input_media.write_bytes(b"fake-video")
            preferred_audio.write_bytes(b"fake-audio")

            with patch("subtitle_maker.domains.media.compose.run_cmd") as run_cmd_mock:
                run_cmd_mock.side_effect = [
                    (0, "video\n", ""),
                    (0, "", ""),
                    (0, "", ""),
                ]
                result = build_dubbed_video_two_step(
                    input_media_path=input_media,
                    preferred_audio_path=preferred_audio,
                    output_video_path=output_video,
                    output_audio_path=output_audio,
                    target_duration_sec=12.34,
                )

            self.assertEqual(result["status"], "done")
            self.assertEqual(result["mux_mode"], "copy")
            self.assertEqual(run_cmd_mock.call_count, 3)
            first_cmd = run_cmd_mock.call_args_list[0].args[0]
            second_cmd = run_cmd_mock.call_args_list[1].args[0]
            third_cmd = run_cmd_mock.call_args_list[2].args[0]
            self.assertEqual(first_cmd[0], "ffprobe")
            self.assertTrue(any("apad,atrim=0:12.340000" in token for token in second_cmd))
            self.assertIn("-c:v", third_cmd)
            self.assertIn("copy", third_cmd)

    def test_build_dubbed_video_two_step_falls_back_to_reencode(self):
        """视频 copy 失败时应自动回退到重编码，保证 mp4 产物可输出。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_media = tmp_path / "demo.mp4"
            preferred_audio = tmp_path / "dubbed_mix_full.wav"
            output_video = tmp_path / "dubbed_video_full.mp4"
            output_audio = tmp_path / "dubbed_audio_for_video.m4a"
            input_media.write_bytes(b"fake-video")
            preferred_audio.write_bytes(b"fake-audio")

            with patch("subtitle_maker.domains.media.compose.run_cmd") as run_cmd_mock:
                run_cmd_mock.side_effect = [
                    (0, "video\n", ""),
                    (0, "", ""),
                    (1, "", "copy failed"),
                    (0, "", ""),
                ]
                result = build_dubbed_video_two_step(
                    input_media_path=input_media,
                    preferred_audio_path=preferred_audio,
                    output_video_path=output_video,
                    output_audio_path=output_audio,
                    target_duration_sec=9.5,
                )

            self.assertEqual(result["status"], "done")
            self.assertEqual(result["mux_mode"], "reencode")
            self.assertEqual(run_cmd_mock.call_count, 4)
            third_cmd = run_cmd_mock.call_args_list[2].args[0]
            fourth_cmd = run_cmd_mock.call_args_list[3].args[0]
            self.assertIn("-c:v", third_cmd)
            self.assertIn("copy", third_cmd)
            self.assertIn("libx264", fourth_cmd)

    def test_build_dubbed_video_two_step_skips_when_no_video_stream(self):
        """输入媒体没有视频流时应跳过后处理，不影响主任务成功。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_media = tmp_path / "demo.wav"
            preferred_audio = tmp_path / "dubbed_mix_full.wav"
            output_video = tmp_path / "dubbed_video_full.mp4"
            output_audio = tmp_path / "dubbed_audio_for_video.m4a"
            input_media.write_bytes(b"fake-audio-media")
            preferred_audio.write_bytes(b"fake-audio")

            with patch("subtitle_maker.domains.media.compose.run_cmd", return_value=(0, "", "")) as run_cmd_mock:
                result = build_dubbed_video_two_step(
                    input_media_path=input_media,
                    preferred_audio_path=preferred_audio,
                    output_video_path=output_video,
                    output_audio_path=output_audio,
                    target_duration_sec=4.0,
                )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "input_has_no_video_stream")
            self.assertEqual(run_cmd_mock.call_count, 1)


@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
class DubbingPipelineTests(unittest.TestCase):
    @dataclass(frozen=True)
    class _TestVoiceReference:
        audio_path: Path
        reference_text: str

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

    def test_build_speaker_aware_synthesis_groups_keeps_same_speaker_together(self):
        from subtitle_maker.domains.dubbing.pipeline import build_speaker_aware_synthesis_groups

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "World", "speaker_id": "Speaker 1"},
            {"start": 2.0, "end": 3.0, "text": "Hi", "speaker_id": "Speaker 2"},
            {"start": 3.0, "end": 4.0, "text": "There", "speaker_id": "Speaker 2"},
        ]
        groups = build_speaker_aware_synthesis_groups(
            subtitles=subtitles,
            translated_lines=["你", "好", "啊", "呀"],
            max_gap_sec=0.35,
            min_group_duration_sec=0.5,
            max_group_duration_sec=8.0,
        )

        self.assertEqual(groups, [[0, 1], [2, 3]])

    def test_build_speaker_aware_synthesis_groups_splits_overlong_runs(self):
        from subtitle_maker.domains.dubbing.pipeline import build_speaker_aware_synthesis_groups

        subtitles = [
            {"start": 0.0, "end": 3.0, "text": "A", "speaker_id": "Speaker 1"},
            {"start": 3.0, "end": 6.0, "text": "B", "speaker_id": "Speaker 1"},
            {"start": 6.0, "end": 9.5, "text": "C", "speaker_id": "Speaker 1"},
        ]
        groups = build_speaker_aware_synthesis_groups(
            subtitles=subtitles,
            translated_lines=["甲", "乙", "丙"],
            max_gap_sec=0.35,
            min_group_duration_sec=0.5,
            max_group_duration_sec=5.0,
        )

        self.assertTrue(all((subtitles[g[-1]]["end"] - subtitles[g[0]]["start"]) <= 5.0 for g in groups))

    def test_synthesize_text_once_dispatches_index_backend(self):
        with patch("subtitle_maker.domains.dubbing.pipeline.IndexTtsBackend") as backend_cls:
            backend = backend_cls.return_value
            synthesize_text_once(
                tts_backend="index-tts",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
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

    def test_translate_batch_with_budget_lazy_initializes_translator_client(self):
        from subtitle_maker.translator import Translator
        from tools.dub_pipeline import translate_batch_with_budget

        class FakeClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=Mock(
                            return_value=SimpleNamespace(
                                choices=[SimpleNamespace(message=SimpleNamespace(content="1. 你好"))]
                            )
                        )
                    )
                )

        translator = Translator(api_key="test-key", base_url="http://example.com", model="demo-model")
        translator.client = None

        with patch.object(Translator, "_ensure_client", return_value=FakeClient()) as ensure_client:
            translated = translate_batch_with_budget(
                translator=translator,
                lines=["hello"],
                durations=[1.0],
                target_lang="Chinese",
                system_prompt=None,
                chunk_size=1,
            )

        self.assertEqual(translated, ["你好"])
        ensure_client.assert_called_once()
        system_message = ensure_client.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("50 翻译成五十", system_message)
        self.assertIn("不要出现冒号", system_message)
        self.assertIn("AI 的发展", system_message)

    def test_translator_translate_batch_merges_default_and_custom_system_prompt(self):
        from subtitle_maker.translator import Translator

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="1. 你好"))]
                        )
                    )
                )
            )
        )
        translator = Translator(api_key="test-key", base_url="http://example.com", model="demo-model")
        translator.client = fake_client

        translated = translator.translate_batch(
            ["hello"],
            target_lang="Chinese",
            system_prompt="名字保留英文。",
            chunk_size=1,
        )

        self.assertEqual(translated, ["你好"])
        system_message = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("50 翻译成五十", system_message)
        self.assertIn("不要出现冒号", system_message)
        self.assertIn("AI 的发展", system_message)
        self.assertIn("名字保留英文。", system_message)

    def test_translator_translate_batch_flattens_internal_newlines_in_one_cue(self):
        from subtitle_maker.translator import Translator

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="1. 不"))]
                        )
                    )
                )
            )
        )
        translator = Translator(api_key="test-key", base_url="http://example.com", model="demo-model")
        translator.client = fake_client

        translated = translator.translate_batch(
            ["No.\nBut most guys are doing things in order not to ejaculate quite so quickly."],
            target_lang="Chinese",
            system_prompt=None,
            chunk_size=1,
        )

        self.assertEqual(translated, ["不"])
        user_message = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("1. No. But most guys are doing things in order not to ejaculate quite so quickly.", user_message)
        self.assertNotIn("No.\nBut most guys", user_message)

    def test_resolve_translation_api_key_prefers_generic_env_then_legacy_env(self):
        from subtitle_maker.translator import resolve_translation_api_key

        with patch.dict(
            "os.environ",
            {"TRANSLATE_API_KEY": "generic-key", "DEEPSEEK_API_KEY": "legacy-key"},
            clear=False,
        ):
            self.assertEqual(resolve_translation_api_key(), "generic-key")
            self.assertEqual(resolve_translation_api_key(api_key="explicit-key"), "explicit-key")

    def test_get_translate_provider_label_defaults_to_openai_compatible_for_custom_host(self):
        from subtitle_maker.translator import get_translate_provider_label

        self.assertEqual(get_translate_provider_label("https://api.deepseek.com"), "OpenAI-compatible")
        self.assertEqual(get_translate_provider_label("https://llm.example.com/v1"), "OpenAI-compatible")

    def test_default_translation_provider_config_keeps_compat_aliases_in_sync(self):
        from subtitle_maker.translator import (
            DEFAULT_TRANSLATE_BASE_URL,
            DEFAULT_TRANSLATE_MODEL,
            DEFAULT_TRANSLATION_PROVIDER,
        )

        self.assertEqual(DEFAULT_TRANSLATION_PROVIDER.base_url, DEFAULT_TRANSLATE_BASE_URL)
        self.assertEqual(DEFAULT_TRANSLATION_PROVIDER.model, DEFAULT_TRANSLATE_MODEL)

    def test_repair_punctuation_only_translations_inherits_merged_system_prompt(self):
        from subtitle_maker.translator import Translator
        from tools.dub_pipeline import JsonlLogger, repair_punctuation_only_translations

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="1. 人工智能 的发展"))]
                        )
                    )
                )
            )
        )
        translator = Translator(api_key="test-key", base_url="http://example.com", model="demo-model")
        translator.client = fake_client

        repaired = repair_punctuation_only_translations(
            subtitles=[{"text": "AI: 50", "start": 0.0, "end": 1.0}],
            translated_lines=["..."],
            translator=translator,
            target_lang="Chinese",
            logger=JsonlLogger(Path(tempfile.mkdtemp()) / "repair.jsonl", "test-repair"),
            system_prompt="名字保留英文。",
        )

        self.assertEqual(repaired, ["人工智能 的发展"])
        system_message = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("50 翻译成五十", system_message)
        self.assertIn("不要出现冒号", system_message)
        self.assertIn("AI 的发展", system_message)
        self.assertIn("名字保留英文。", system_message)
        self.assertIn("Never output only punctuation or ellipsis.", system_message)

    def test_synthesize_text_once_rejects_removed_fallback_backend(self):
        """Auto Dubbing 收口后，不再允许通过 fallback_tts_backend 切到其他底座。"""

        with self.assertRaises(RuntimeError) as ctx:
            synthesize_text_once(
                tts_backend="index-tts",
                fallback_tts_backend="omnivoice",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
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
                ref_text="hello",
                target_lang="English",
                target_duration_sec=1.9,
            )

        self.assertIn("Unsupported fallback_tts_backend", str(ctx.exception))


    def test_synthesize_text_once_primary_failure_surfaces_original_error_without_fallback(self):
        with patch("subtitle_maker.domains.dubbing.pipeline.IndexTtsBackend") as index_cls:
            index_cls.return_value.synthesize.side_effect = RuntimeError("index down")

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_text_once(
                    tts_backend="index-tts",
                    fallback_tts_backend="none",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
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
                    ref_text="hello",
                    target_lang="English",
                )

        self.assertIn("index down", str(ctx.exception))

    def test_synthesize_text_once_rejects_removed_voxcpm_backend(self):
        """Auto Dubbing 收口后，旧的 voxcpm-omnivoice backend 不再是有效合同。"""

        with self.assertRaises(RuntimeError) as ctx:
            synthesize_text_once(
                tts_backend="voxcpm-omnivoice",
                fallback_tts_backend="none",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
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
                text="这是 VoxCPM anchor 测试。",
                output_path=Path("/tmp/out.wav"),
                ref_text="This is the source prompt text.",
                target_lang="Chinese",
                target_duration_sec=2.0,
            )

        self.assertIn("Unsupported tts backend", str(ctx.exception))

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
                        np.zeros(160, dtype=np.float32),
                        np.full(16000, 0.06, dtype=np.float32),
                        np.zeros(160, dtype=np.float32),
                    ]
                )
                sf.write(str(output_path), wav, 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                records, manual_review = synthesize_segments(
                    tts_backend="index-tts",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
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

    def test_synthesize_segments_short_index_tts_line_skips_leveling_and_edge_fade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(output_path), np.full(6400, 0.2, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once), patch(
                "subtitle_maker.domains.dubbing.pipeline.normalize_speech_audio_level"
            ) as level_mock, patch(
                "subtitle_maker.domains.dubbing.pipeline._apply_final_edge_fade"
            ) as fade_mock:
                records, manual_review = synthesize_segments(
                    tts_backend="index-tts",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
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
                    subtitles=[{"start": 0.0, "end": 0.4, "text": "hello"}],
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

            level_mock.assert_not_called()
            fade_mock.assert_not_called()
            self.assertEqual(records[0]["status"], "done")
            self.assertFalse(records[0]["audio_leveling_applied"])
            self.assertEqual(manual_review, [])

    def test_synthesize_segments_trims_edges_before_selecting_best(self):
        """逐句链路应先做 trim_edges，避免句首瞬态杂音直接进入最终候选。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 前后各 100ms 静音，中间 400ms 有效语音
                wav = np.concatenate(
                    [
                        np.zeros(1600, dtype=np.float32),
                        np.full(6400, 0.2, dtype=np.float32),
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
                    subtitles=[{"start": 0.0, "end": 0.6, "text": "hello"}],
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
                    fallback_tts_backend="none",
                        dub_audio_leveling_enabled=False,
                )

            self.assertEqual(manual_review, [])
            self.assertEqual(records[0]["status"], "done")
            actions = [str(item.get("action") or "") for item in records[0].get("attempt_history", [])]
            self.assertIn("trim_edges", actions)

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
                dubbing_mode="single",
                index_tts_via_api=True,
                index_tts_api_url="http://127.0.0.1:8010",
                index_tts_api_timeout_sec=12.0,
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

    def test_synthesize_text_once_rejects_removed_voxcpm_backend_even_with_reference_prompt(self):
        """即便传入旧的 VoxCPM 参考文案字段，也应直接报 backend 不支持。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.full(16000, 0.05, dtype=np.float32), 16000)

            with self.assertRaises(RuntimeError) as ctx:
                synthesize_text_once(
                    tts_backend="voxcpm-omnivoice",
                    fallback_tts_backend="none",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
                    tts_index=None,
                    ref_audio_path=ref_audio,
                    index_emo_audio_prompt=None,
                    index_emo_alpha=1.0,
                    index_use_emo_text=False,
                    index_emo_text=None,
                    index_top_p=0.8,
                    index_top_k=30,
                    index_temperature=0.8,
                    index_max_text_tokens=120,
                    text="这是要配音的字幕正文",
                    output_path=tmp_path / "out.wav",
                    target_duration_sec=1.8,
                    ref_text="这是参考音频对应文本",
                    target_lang="Chinese",
                    anchor_output_path=tmp_path / "anchor.wav",
                )

        self.assertIn("Unsupported tts backend", str(ctx.exception))






    def test_synthesize_segments_index_tts_skips_fit_when_within_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(output_path), np.full(17120, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                with patch("subtitle_maker.domains.dubbing.pipeline.fit_audio_to_duration") as fit_mock:
                    records, manual_review = synthesize_segments(
                        tts_backend="index-tts",
                        index_tts_via_api=True,
                        index_tts_api_url="http://127.0.0.1:8010",
                        index_tts_api_timeout_sec=12.0,
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
                        subtitles=[{"start": 0.0, "end": 1.1, "text": "hello"}],
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

    def test_synthesize_segments_index_tts_marks_manual_review_on_compose_window_overrun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 目标窗口 1.0s，实际 1.08s；虽然在 pass 阈值内，但不应进入 compose。
                sf.write(str(output_path), np.full(17280, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                records, manual_review = synthesize_segments(
                    tts_backend="index-tts",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
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
                    segment_dir=tmp_path / "segments_guard",
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
        actions = [item.get("action") for item in records[0].get("attempt_history", [])]
        self.assertIn("compose_window_overrun_guard", actions)
        self.assertEqual(len(manual_review), 1)
        self.assertEqual(manual_review[0]["reason_code"], "compose_window_overrun")

    def test_synthesize_segments_grouped_index_tts_marks_manual_review_on_compose_window_overrun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 目标窗口 1.0s，实际 1.08s；在 120ms pass 阈值内，但应被 compose guard 拦下。
                sf.write(str(output_path), np.full(17280, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                records, manual_review = synthesize_segments_grouped(
                    tts_backend="index-tts",
                    dubbing_mode="single",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
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
                    subtitles=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                    translated_lines=["你好"],
                    segment_dir=tmp_path / "grouped_guard",
                    delta_pass_ms=120.0,
                    timing_mode="strict",
                    balanced_max_tempo_shift=0.08,
                    balanced_min_line_sec=0.35,
                    grouping_strategy="sentence",
                    logger=Mock(),
                    target_lang="Chinese",
                )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "manual_review")
        actions = [item.get("action") for item in records[0].get("attempt_history", [])]
        self.assertIn("group_compose_window_overrun_guard", actions)
        self.assertEqual(len(manual_review), 1)
        self.assertEqual(manual_review[0]["reason_code"], "compose_window_overrun")

    def test_synthesize_segments_grouped_index_tts_uses_anchor_window_for_status(self):
        """grouped 判定应按本组窗口，不因 borrowed gap 未填满而误判 manual_review。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "ref.wav"
            sf.write(str(ref_audio), np.zeros(16000, dtype=np.float32), 16000)

            def fake_synthesize_text_once(**kwargs):
                output_path = Path(kwargs["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # 输出 1.75s：接近本组 target(1.8s)，但显著短于 effective_target(≈3.7s)。
                sf.write(str(output_path), np.full(28000, 0.05, dtype=np.float32), 16000)

            with patch("subtitle_maker.domains.dubbing.pipeline.synthesize_text_once", side_effect=fake_synthesize_text_once):
                records, manual_review = synthesize_segments_grouped(
                    tts_backend="index-tts",
                    dubbing_mode="single",
                    index_tts_via_api=True,
                    index_tts_api_url="http://127.0.0.1:8010",
                    index_tts_api_timeout_sec=12.0,
                    tts_index=None,
                    ref_audio_path=ref_audio,
                    ref_audio_selector=None,
                    source_media_duration_sec=10.0,
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
                    group_min_duration_sec=0.5,
                    group_max_duration_sec=8.0,
                    subtitles=[{"start": 0.0, "end": 1.8, "text": "hello"}],
                    translated_lines=["你好世界"],
                    segment_dir=tmp_path / "grouped_anchor_window",
                    delta_pass_ms=120.0,
                    timing_mode="strict",
                    balanced_max_tempo_shift=0.08,
                    balanced_min_line_sec=0.35,
                    grouping_strategy="sentence",
                    logger=Mock(),
                    target_lang="Chinese",
                    fallback_tts_backend="none",
                )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "done")
        self.assertEqual(manual_review, [])
        self.assertAlmostEqual(records[0]["anchor_target_duration_sec"], 1.8, places=2)
        self.assertAlmostEqual(records[0]["borrowed_gap_sec"], 1.8, places=2)






@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
class DubbingBackendTests(unittest.TestCase):
    def test_split_text_for_index_tts_splits_cjk_on_punctuation(self):
        chunks = split_text_for_index_tts(
            "第一句很长，需要切开。第二句也很长，需要继续切开。",
            max_text_tokens=12,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("。"))







@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
class DubbingReviewTests(unittest.TestCase):
    def test_resolve_segment_redub_runtime_options_prefers_manifest_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "input_media_path": str(Path(tmpdir) / "segment.wav"),
                        "rewrite_translation": False,
                        "grouped_synthesis": True,
                        "force_fit_timing": True,
                        "tts_backend": "index-tts",
                        "index_tts_api_url": "http://127.0.0.1:19010",
                        "segments": [{"id": "seg_0001", "translated_text": "你好"}],
                    }
                ),
                encoding="utf-8",
            )
            manifest = load_segment_manifest(manifest_path)

        options = resolve_segment_redub_runtime_options(
            segment_manifest=manifest,
            fallback_rewrite_translation=True,
            fallback_index_tts_api_url="http://127.0.0.1:8010",
        )
        self.assertFalse(options.rewrite_translation)
        self.assertTrue(options.grouped_synthesis)
        self.assertTrue(options.force_fit_timing)
        self.assertEqual(options.tts_backend, "index-tts")
        self.assertEqual(options.index_tts_api_url, "http://127.0.0.1:19010")


@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
class IndexTtsBackendRecoveryTests(unittest.TestCase):
    def _build_request(self, tmpdir: str) -> TtsSynthesisRequest:
        """构造最小化请求对象，供 Index-TTS API 重试逻辑测试复用。"""

        base = Path(tmpdir)
        return TtsSynthesisRequest(
            text="hello world",
            ref_audio_path=base / "ref.wav",
            output_path=base / "out.wav",
        )

    def test_index_tts_backend_waits_for_restart_pending_before_next_call(self):
        """当服务返回 restart_pending 时，应先等待健康恢复，避免下一句打到 503。"""

        backend = IndexTtsBackend(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            request = self._build_request(tmpdir)
            with patch(
                "subtitle_maker.backends.index_tts.synthesize_via_index_tts_api",
                return_value={"ok": True, "restart_pending": True},
            ) as synth_mock, patch(
                "subtitle_maker.backends.index_tts._wait_index_tts_service_ready",
                return_value={"ok": True, "status": "ok"},
            ) as wait_mock, patch(
                "subtitle_maker.backends.index_tts.release_index_tts_api_model"
            ) as release_mock:
                backend._synthesize_api(request)

        self.assertEqual(synth_mock.call_count, 1)
        wait_mock.assert_called_once_with(api_url="http://127.0.0.1:8010", timeout_sec=12.0)
        release_mock.assert_not_called()

    def test_index_tts_backend_retries_after_transient_503_and_recovers(self):
        """遇到 503/断连等短暂故障时，应等待恢复后重试而非直接判 missing。"""

        backend = IndexTtsBackend(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            request = self._build_request(tmpdir)
            with patch(
                "subtitle_maker.backends.index_tts.synthesize_via_index_tts_api",
                side_effect=[
                    RuntimeError("E-TTS-001 index-tts api http 503: "),
                    {"ok": True, "restart_pending": False},
                ],
            ) as synth_mock, patch(
                "subtitle_maker.backends.index_tts._wait_index_tts_service_ready",
                return_value={"ok": True, "status": "ok"},
            ) as wait_mock, patch(
                "subtitle_maker.backends.index_tts.release_index_tts_api_model",
                return_value={"ok": True},
            ) as release_mock:
                backend._synthesize_api(request)

        self.assertEqual(synth_mock.call_count, 2)
        wait_mock.assert_called_once_with(api_url="http://127.0.0.1:8010", timeout_sec=12.0)
        release_mock.assert_called_once_with(api_url="http://127.0.0.1:8010", timeout_sec=12.0)


@unittest.skipIf(bool(RUNTIME_TEST_SKIP_REASON), RUNTIME_TEST_SKIP_REASON or "")
class IndexTtsBackendQualityTests(unittest.TestCase):
    def _build_request(
        self,
        tmpdir: str,
        *,
        target_duration_sec: float = 2.0,
        text: str = "hello world",
    ) -> TtsSynthesisRequest:
        """构造带目标时长的请求，供质量反馈测试复用。"""

        base = Path(tmpdir)
        ref_audio = base / "ref.wav"
        sf.write(str(ref_audio), np.full(1600, 0.01, dtype=np.float32), 16000)
        return TtsSynthesisRequest(
            text=text,
            ref_audio_path=ref_audio,
            output_path=base / "out.wav",
            target_duration_sec=target_duration_sec,
        )

    def test_index_tts_backend_retries_once_when_api_duration_is_too_short(self):
        """API 返回明显偏短时，应先做一次内部质量重试。"""

        backend = IndexTtsBackend(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            request = self._build_request(
                tmpdir,
                text="hello world this sentence is long enough for a guarded retry",
            )
            durations = iter([1.0, 1.82])
            current_duration = {"sec": 0.0}

            def fake_synthesize_one(chunk_request: TtsSynthesisRequest) -> dict[str, float | bool]:
                duration_sec = float(next(durations))
                current_duration["sec"] = duration_sec
                sf.write(
                    str(chunk_request.output_path),
                    np.full(max(1, int(duration_sec * 16000)), 0.01, dtype=np.float32),
                    16000,
                )
                return {"ok": True, "duration_sec": duration_sec}

            def fake_concat(part_paths: list[Path], output_path: Path) -> None:
                del part_paths
                sf.write(
                    str(output_path),
                    np.full(max(1, int(current_duration["sec"] * 16000)), 0.01, dtype=np.float32),
                    16000,
                )

            with patch.object(backend, "_synthesize_one", side_effect=fake_synthesize_one) as synth_mock, patch(
                "subtitle_maker.backends.index_tts.concat_generated_wavs",
                side_effect=fake_concat,
            ):
                backend.synthesize(request)

        self.assertEqual(synth_mock.call_count, 2)
        self.assertEqual(backend.last_synthesis_meta["quality_attempt_no"], 2)
        self.assertIsNone(backend.last_synthesis_meta["quality_retry_reason"])
        self.assertAlmostEqual(float(backend.last_synthesis_meta["api_duration_sec"]), 1.82, places=2)
        self.assertIsNone(backend.last_synthesis_meta["output_duration_sec"])

    def test_index_tts_backend_retries_once_when_api_duration_is_too_long(self):
        """API 返回明显偏长时，也应先在后端内部做一次保守重试。"""

        backend = IndexTtsBackend(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            request = self._build_request(
                tmpdir,
                text="hello world this sentence is long enough for a guarded retry",
            )
            durations = iter([2.7, 2.04])
            current_duration = {"sec": 0.0}

            def fake_synthesize_one(chunk_request: TtsSynthesisRequest) -> dict[str, float | bool]:
                duration_sec = float(next(durations))
                current_duration["sec"] = duration_sec
                sf.write(
                    str(chunk_request.output_path),
                    np.full(max(1, int(duration_sec * 16000)), 0.01, dtype=np.float32),
                    16000,
                )
                return {"ok": True, "duration_sec": duration_sec}

            def fake_concat(part_paths: list[Path], output_path: Path) -> None:
                del part_paths
                sf.write(
                    str(output_path),
                    np.full(max(1, int(current_duration["sec"] * 16000)), 0.01, dtype=np.float32),
                    16000,
                )

            with patch.object(backend, "_synthesize_one", side_effect=fake_synthesize_one) as synth_mock, patch(
                "subtitle_maker.backends.index_tts.concat_generated_wavs",
                side_effect=fake_concat,
            ):
                backend.synthesize(request)

        self.assertEqual(synth_mock.call_count, 2)
        self.assertEqual(backend.last_synthesis_meta["quality_attempt_no"], 2)
        self.assertIsNone(backend.last_synthesis_meta["quality_retry_reason"])
        self.assertAlmostEqual(float(backend.last_synthesis_meta["api_duration_sec"]), 2.04, places=2)
        self.assertIsNone(backend.last_synthesis_meta["output_duration_sec"])

    def test_index_tts_backend_short_sentence_skips_second_quality_retry(self):
        """短句即使明显偏短，也不应触发第二轮整句质量重试。"""

        backend = IndexTtsBackend(
            via_api=True,
            api_url="http://127.0.0.1:8010",
            timeout_sec=12.0,
            local_model=None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            request = self._build_request(tmpdir, target_duration_sec=1.2, text="hello")

            def fake_synthesize_one(chunk_request: TtsSynthesisRequest) -> dict[str, float | bool]:
                sf.write(
                    str(chunk_request.output_path),
                    np.full(int(0.5 * 16000), 0.01, dtype=np.float32),
                    16000,
                )
                return {"ok": True, "duration_sec": 0.5}

            def fake_concat(part_paths: list[Path], output_path: Path) -> None:
                del part_paths
                sf.write(
                    str(output_path),
                    np.full(int(0.5 * 16000), 0.01, dtype=np.float32),
                    16000,
                )

            with patch.object(backend, "_synthesize_one", side_effect=fake_synthesize_one) as synth_mock, patch(
                "subtitle_maker.backends.index_tts.concat_generated_wavs",
                side_effect=fake_concat,
            ):
                backend.synthesize(request)

        self.assertEqual(synth_mock.call_count, 1)
        self.assertEqual(backend.last_synthesis_meta["quality_attempt_no"], 1)
        self.assertEqual(backend.last_synthesis_meta["quality_retry_reason"], "too_short")


if __name__ == "__main__":
    unittest.main()
