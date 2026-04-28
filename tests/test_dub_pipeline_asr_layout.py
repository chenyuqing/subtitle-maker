from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import numpy as np
import soundfile as sf


REPO_ROOT = Path(__file__).resolve().parents[1]
DUB_PIPELINE_PATH = REPO_ROOT / "tools" / "dub_pipeline.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_dub_pipeline_module", DUB_PIPELINE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
dub_pipeline = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = dub_pipeline
MODULE_SPEC.loader.exec_module(dub_pipeline)


class DummyLogger:
    """收集日志事件，避免单测为 logger 落盘。"""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def log(
        self,
        level: str,
        stage: str,
        event: str,
        message: str,
        *,
        segment_id: Optional[str] = None,
        progress: Optional[float] = None,
        elapsed_ms: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.records.append(
            {
                "level": level,
                "stage": stage,
                "event": event,
                "message": message,
                "segment_id": segment_id,
                "progress": progress,
                "elapsed_ms": elapsed_ms,
                "data": data or {},
            }
        )


class FakeChatCompletions:
    """按预设响应返回假 LLM 结果，避免测试访问外网。"""

    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def create(self, *, model: str, messages: List[Dict[str, str]], stream: bool = False) -> Any:
        self.calls.append({"model": model, "messages": messages, "stream": stream})
        content = self._responses.pop(0) if self._responses else "1"
        message = type("FakeMessage", (), {"content": content})()
        choice = type("FakeChoice", (), {"message": message})()
        return type("FakeResponse", (), {"choices": [choice]})()


class FakeTranslator:
    """伪造 Translator，仅暴露 source layout 所需的 client/model。"""

    def __init__(self, responses: List[str]) -> None:
        self.model = "fake-deepseek"
        self.completions = FakeChatCompletions(responses)
        self.client = type("FakeClient", (), {})()
        self.client.chat = type("FakeChat", (), {})()
        self.client.chat.completions = self.completions


class DubPipelineAsrLayoutTests(unittest.TestCase):
    """验证 ASR 字幕会优先向句级布局收敛，而不是保留碎片 cue。"""

    def build_fragmented_sample(self) -> List[Dict[str, Any]]:
        """复用同一份英文碎片样例，便于比较 rule 与 hybrid。"""
        return [
            {"start": 0.080, "end": 1.360, "text": "I think it's extremely"},
            {"start": 1.360, "end": 2.160, "text": "clear"},
            {"start": 2.160, "end": 3.439, "text": "that we are going to have"},
            {"start": 3.439, "end": 6.480, "text": "AI within the next couple years in a way"},
            {"start": 6.480, "end": 8.960, "text": "that is still going to be jagged, but"},
            {"start": 8.960, "end": 12.240, "text": "that the the floor of task will just be"},
            {"start": 12.240, "end": 13.919, "text": "almost for any intellectual task of how"},
            {"start": 13.919, "end": 15.439, "text": "you use your computer."},
            {"start": 15.439, "end": 17.039, "text": "The AI will be able to do that."},
            {"start": 17.039, "end": 19.120, "text": "The scariest moment at OpenAI was"},
            {"start": 19.120, "end": 20.640, "text": "actually after we launched"},
            {"start": 20.640, "end": 22.879, "text": "ChatGPT, and I remember being at the"},
            {"start": 22.879, "end": 24.399, "text": "holiday party and just feeling this vibe"},
            {"start": 24.399, "end": 24.800, "text": "of we"},
            {"start": 24.800, "end": 25.760, "text": "won."},
            {"start": 25.760, "end": 27.120, "text": "I have never felt that."},
            {"start": 27.120, "end": 27.839, "text": "I was like,"},
            {"start": 27.839, "end": 29.839, "text": "no, that we we are the"},
            {"start": 29.839, "end": 29.960, "text": "underdog."},
        ]

    def test_rebalance_source_subtitles_merges_fragmented_sentence_sample(self) -> None:
        """坏样例应被压回更接近一句一行的布局，同时保留原始时间边界。"""
        subtitles = self.build_fragmented_sample()
        logger = DummyLogger()

        result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            logger=logger,
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            [item["text"] for item in result],
            [
                "I think it's extremely clear that we are going to have AI within the next couple years in a way that is still going to be jagged,",
                "but that the the floor of task will just be almost for any intellectual task of how you use your computer.",
                "The AI will be able to do that.",
                "The scariest moment at OpenAI was actually after we launched ChatGPT,",
                "and I remember being at the holiday party and just feeling this vibe of we won.",
                "I have never felt that.",
                "I was like, no, that we we are the underdog.",
            ],
        )
        self.assertAlmostEqual(result[0]["start"], 0.080, places=3)
        self.assertAlmostEqual(result[0]["end"], 8.710, places=3)
        self.assertAlmostEqual(result[1]["start"], 8.710, places=3)
        self.assertAlmostEqual(result[1]["end"], 15.439, places=3)
        self.assertEqual(
            [(round(item["start"], 3), round(item["end"], 3)) for item in result[2:]],
            [
                (15.439, 17.039),
                (17.039, 21.152),
                (21.152, 25.760),
                (25.760, 27.120),
                (27.120, 29.960),
            ],
        )
        self.assertFalse(any(item["text"] == "clear" for item in result))
        self.assertFalse(any(item["text"] == "won." for item in result))
        self.assertTrue(result[0]["text"].endswith("jagged,"))
        self.assertTrue(result[1]["text"].startswith("but "))
        self.assertTrue(all(dub_pipeline.ends_with_explicit_break(item["text"]) for item in result))
        self.assertTrue(any(record["event"] == "source_layout_rebalanced" for record in logger.records))

    def test_refine_source_layout_with_llm_uses_plan_when_better(self) -> None:
        """合法且更优的 LLM 计划应覆盖规则切点。"""
        block = [
            {"start": 0.000, "end": 0.600, "text": "This opening"},
            {"start": 0.600, "end": 1.200, "text": "segment is"},
            {"start": 1.200, "end": 3.600, "text": "much longer and carries most of the explanation"},
            {"start": 3.600, "end": 5.000, "text": "for the sentence."},
        ]
        rule_groups = [block[:1], block[1:]]
        logger = DummyLogger()
        fake_translator = FakeTranslator(["1-2\n3-4"])

        result = dub_pipeline.refine_source_layout_with_llm(
            block=block,
            rule_groups=rule_groups,
            max_line_width=40,
            llm_min_duration_sec=4.0,
            llm_min_text_units=80,
            llm_max_cues=8,
            translator_factory=lambda: fake_translator,
            logger=logger,
        )

        self.assertEqual(
            [dub_pipeline.subtitle_group_text(group, cjk_mode=False) for group in result],
            [
                "This opening segment is",
                "much longer and carries most of the explanation for the sentence.",
            ],
        )
        self.assertEqual(
            [dub_pipeline.describe_source_layout_groups(result)],
            ["1-2,3-4"],
        )
        self.assertTrue(any(record["event"] == "source_layout_llm_applied" for record in logger.records))
        self.assertEqual(len(fake_translator.completions.calls), 1)

    def test_rebalance_source_subtitles_hybrid_falls_back_on_invalid_plan(self) -> None:
        """LLM 返回非法计划时必须稳定回退到规则版。"""
        subtitles = self.build_fragmented_sample()
        rule_result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            logger=DummyLogger(),
        )
        logger = DummyLogger()
        fake_translator = FakeTranslator(["1-3\n5-8", "1-6"])

        hybrid_result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            source_layout_mode="hybrid",
            source_layout_llm_min_duration_sec=6.0,
            source_layout_llm_min_text_units=85,
            source_layout_llm_max_cues=12,
            translator_factory=lambda: fake_translator,
            logger=logger,
        )

        self.assertEqual(
            [item["text"] for item in hybrid_result],
            [item["text"] for item in rule_result],
        )
        self.assertTrue(any(record["event"] == "source_layout_llm_invalid_plan" for record in logger.records))

    def test_rebalance_source_subtitles_hybrid_rejects_plan_without_connector_improvement(self) -> None:
        """若 LLM 没减少连接词坏切点，即使总分更短也不能覆盖规则版。"""
        subtitles = self.build_fragmented_sample()
        rule_result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            logger=DummyLogger(),
        )
        logger = DummyLogger()
        fake_translator = FakeTranslator(["1-3\n4-5\n6-8", "1-3\n4-6"])

        hybrid_result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            source_layout_mode="hybrid",
            source_layout_llm_min_duration_sec=6.0,
            source_layout_llm_min_text_units=85,
            source_layout_llm_max_cues=12,
            translator_factory=lambda: fake_translator,
            logger=logger,
        )

        self.assertEqual(
            [item["text"] for item in hybrid_result],
            [item["text"] for item in rule_result],
        )
        self.assertTrue(any(record["event"] == "source_layout_llm_rejected" for record in logger.records))
        self.assertTrue(
            any(
                record["data"].get("llm_connector_issues", 0) > record["data"].get("rule_connector_issues", 0)
                for record in logger.records
                if record["event"] == "source_layout_llm_rejected"
            )
        )

    def test_rebalance_source_subtitles_does_not_cross_large_gap_clusters(self) -> None:
        """明显停顿后的新句子不应被并入前一簇。"""
        subtitles = [
            {"start": 0.000, "end": 0.600, "text": "This is"},
            {"start": 0.600, "end": 1.100, "text": "still one sentence"},
            {"start": 1.900, "end": 2.300, "text": "Another"},
            {"start": 2.300, "end": 3.000, "text": "sentence."},
        ]

        result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            logger=DummyLogger(),
        )

        self.assertEqual(
            [item["text"] for item in result],
            ["This is still one sentence", "Another sentence."],
        )
        self.assertEqual(
            [(round(item["start"], 3), round(item["end"], 3)) for item in result],
            [(0.000, 1.100), (1.900, 3.000)],
        )

    def test_merge_short_source_subtitles_prefers_natural_break_within_valid_window(self) -> None:
        """多个合法时长候选同时存在时，应优先选择更自然的句尾断点。"""
        subtitles = [
            {"start": 0.000, "end": 2.000, "text": "This opening thought,"},
            {"start": 2.000, "end": 5.000, "text": "keeps the sentence hanging,"},
            {"start": 5.000, "end": 9.000, "text": "until this clause closes cleanly."},
            {"start": 9.000, "end": 10.000, "text": "and then keeps going,"},
        ]

        result, merged_pairs = dub_pipeline.merge_short_source_subtitles(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(merged_pairs, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual(
            result[0]["text"],
            "This opening thought, keeps the sentence hanging, until this clause closes cleanly.",
        )
        self.assertAlmostEqual(result[0]["start"], 0.000, places=3)
        self.assertAlmostEqual(result[0]["end"], 9.000, places=3)
        self.assertEqual(result[1]["text"], "and then keeps going,")

    def test_rebalance_source_subtitles_short_merge_uses_independent_gap_window(self) -> None:
        """第 2 步短句合并应允许跨过 1.0s 停顿，不再受第 1 步 0.35s gap 限制。"""
        subtitles = [
            {"start": 0.000, "end": 2.000, "text": "First short sentence."},
            {"start": 3.000, "end": 6.000, "text": "Second short sentence."},
            {"start": 6.000, "end": 9.000, "text": "Third line closes cleanly."},
        ]

        result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.35,
            max_line_width=40,
            source_short_merge_enabled=True,
            source_short_merge_threshold=10,
            logger=DummyLogger(),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "First short sentence. Second short sentence. Third line closes cleanly.")
        self.assertAlmostEqual(result[0]["start"], 0.000, places=3)
        self.assertAlmostEqual(result[0]["end"], 9.000, places=3)

    def test_merge_short_source_subtitles_does_not_cross_large_gap(self) -> None:
        """相邻静默间隔超过 1.5s 时，应强制断开，不允许继续合并。"""
        subtitles = [
            {"start": 0.000, "end": 3.000, "text": "First thought,"},
            {"start": 4.600, "end": 7.000, "text": "second clause closes."},
            {"start": 7.000, "end": 10.000, "text": "Third line keeps going."},
        ]

        result, merged_pairs = dub_pipeline.merge_short_source_subtitles(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(merged_pairs, 1)
        self.assertEqual(result[0]["text"], "First thought,")
        self.assertAlmostEqual(result[0]["start"], 0.000, places=3)
        self.assertAlmostEqual(result[0]["end"], 3.000, places=3)
        self.assertEqual(result[1]["text"], "second clause closes. Third line keeps going.")

    def test_merge_short_source_subtitles_keeps_long_line_as_hard_boundary(self) -> None:
        """单条时长超过目标值时，应直接保留并阻止前后字幕跨越它合并。"""
        subtitles = [
            {"start": 0.000, "end": 3.000, "text": "Short opener."},
            {"start": 3.000, "end": 6.000, "text": "Short continuation."},
            {
                "start": 6.000,
                "end": 17.000,
                "text": "This long subtitle already exceeds the merge target duration and must stay alone.",
            },
            {"start": 17.000, "end": 20.000, "text": "Tail piece."},
            {"start": 20.000, "end": 23.000, "text": "Tail close."},
        ]

        result, merged_pairs = dub_pipeline.merge_short_source_subtitles(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(merged_pairs, 2)
        self.assertEqual([item["text"] for item in result], [
            "Short opener. Short continuation.",
            "This long subtitle already exceeds the merge target duration and must stay alone.",
            "Tail piece. Tail close.",
        ])

    def test_build_backend_reference_selector_prefers_shared_ref_for_short_omnivoice_refs(self) -> None:
        """OmniVoice 应优先使用共享参考音，仅在逐句参考音足够长时才启用。"""

        subtitles = [
            {"start": 0.000, "end": 0.600, "text": "短句一"},
            {"start": 0.600, "end": 2.600, "text": "短句二"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            default_ref = tmp_path / "shared.wav"
            short_ref = tmp_path / "subtitle_0001_ref.wav"
            long_ref = tmp_path / "subtitle_0002_ref.wav"
            sf.write(str(default_ref), np.zeros(32000, dtype=np.float32), 16000)
            sf.write(str(short_ref), np.zeros(9600, dtype=np.float32), 16000)
            sf.write(str(long_ref), np.zeros(24000, dtype=np.float32), 16000)

            selector, stats = dub_pipeline.build_backend_reference_selector(
                tts_backend="omnivoice",
                subtitles=subtitles,
                subtitle_ref_map={0: short_ref, 1: long_ref},
                default_ref=default_ref,
                omnivoice_min_subtitle_ref_sec=1.2,
            )

        self.assertEqual(selector(0), default_ref)
        self.assertEqual(selector(1), long_ref)
        self.assertEqual(stats["reference_strategy"], "shared_reference_preferred_for_omnivoice")
        self.assertEqual(stats["shared_reference_count"], 1)
        self.assertEqual(stats["subtitle_reference_count"], 1)
        self.assertEqual(stats["subtitle_reference_min_sec"], 1.2)

    def test_build_backend_reference_selector_keeps_per_subtitle_refs_for_index_tts(self) -> None:
        """非 OmniVoice 底座应保持现有逐句 reference 行为，不受新策略影响。"""

        subtitles = [{"start": 0.000, "end": 0.600, "text": "短句一"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            default_ref = tmp_path / "shared.wav"
            short_ref = tmp_path / "subtitle_0001_ref.wav"
            sf.write(str(default_ref), np.zeros(32000, dtype=np.float32), 16000)
            sf.write(str(short_ref), np.zeros(9600, dtype=np.float32), 16000)

            selector, stats = dub_pipeline.build_backend_reference_selector(
                tts_backend="index-tts",
                subtitles=subtitles,
                subtitle_ref_map={0: short_ref},
                default_ref=default_ref,
                omnivoice_min_subtitle_ref_sec=1.2,
            )

        self.assertEqual(selector(0), short_ref)
        self.assertEqual(stats["reference_strategy"], "sentence_original_audio_per_subtitle")
        self.assertEqual(stats["shared_reference_count"], 0)
        self.assertEqual(stats["subtitle_reference_count"], 1)

    def test_rebalance_source_subtitles_skips_short_merge_by_default(self) -> None:
        """默认关闭短句合并时，第二阶段不应自动并邻句。"""
        subtitles = [
            {"start": 0.000, "end": 0.700, "text": "This works."},
            {"start": 0.700, "end": 1.400, "text": "It stays concise."},
            {"start": 1.400, "end": 2.300, "text": "We merge the neighbor."},
        ]

        result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.35,
            max_line_width=40,
            source_short_merge_enabled=False,
            source_short_merge_threshold=15,
            logger=DummyLogger(),
        )

        self.assertEqual([item["text"] for item in result], [item["text"] for item in subtitles])

    def test_resolve_source_short_merge_policy_forces_omnivoice_when_user_disabled(self) -> None:
        """OmniVoice 链路即使未请求 source merge，也应在运行时强制开启。"""

        effective, reason = dub_pipeline.resolve_source_short_merge_policy(
            requested_enabled=False,
            tts_backend="omnivoice",
        )

        self.assertTrue(effective)
        self.assertEqual(reason, "omnivoice_policy")

    def test_load_or_transcribe_subtitles_applies_omnivoice_source_short_merge_policy_for_uploaded_source_srt(self) -> None:
        """上传 source.srt 时，OmniVoice 策略态也应触发短句合并并写出日志原因。"""

        subtitles = [
            {"start": 0.000, "end": 2.000, "text": "First short sentence."},
            {"start": 2.000, "end": 5.000, "text": "Second short sentence."},
            {"start": 5.000, "end": 9.000, "text": "Third line closes cleanly."},
        ]
        logger = DummyLogger()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_srt = tmp_path / "input.srt"
            source_srt = tmp_path / "source.srt"
            fake_audio = tmp_path / "audio.wav"
            input_srt.write_text(dub_pipeline.format_srt(subtitles), encoding="utf-8")

            with patch.object(dub_pipeline, "audio_duration", return_value=30.0):
                result = dub_pipeline.load_or_transcribe_subtitles(
                    input_srt=input_srt,
                    asr_audio=fake_audio,
                    source_srt_path=source_srt,
                    persist_input_srt_to_source=True,
                    asr_model_path="unused",
                    aligner_path="unused",
                    device="cpu",
                    language=None,
                    max_width=40,
                    asr_balance_lines=True,
                    asr_balance_gap_sec=0.5,
                    source_layout_mode="rule",
                    source_layout_llm_min_duration_sec=6.0,
                    source_layout_llm_min_text_units=85,
                    source_layout_llm_max_cues=12,
                    source_short_merge_enabled=True,
                    source_short_merge_threshold=10,
                    source_short_merge_requested=False,
                    source_short_merge_effective_reason="omnivoice_policy",
                    translator_factory=None,
                    logger=logger,
                )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "First short sentence. Second short sentence. Third line closes cleanly.")
        rebalanced_record = next(record for record in logger.records if record["event"] == "source_layout_rebalanced")
        self.assertFalse(rebalanced_record["data"]["short_merge_requested"])
        self.assertTrue(rebalanced_record["data"]["short_merge_effective"])
        self.assertEqual(rebalanced_record["data"]["short_merge_effective_reason"], "omnivoice_policy")

    def test_load_or_transcribe_subtitles_merges_uploaded_source_srt_by_time_window(self) -> None:
        """上传 source.srt 时，也应复用第 2 步时间窗合并逻辑。"""
        subtitles = [
            {"start": 0.000, "end": 2.000, "text": "First short sentence."},
            {"start": 2.000, "end": 5.000, "text": "Second short sentence."},
            {"start": 5.000, "end": 9.000, "text": "Third line closes cleanly."},
        ]
        logger = DummyLogger()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_srt = tmp_path / "input.srt"
            source_srt = tmp_path / "source.srt"
            fake_audio = tmp_path / "audio.wav"
            input_srt.write_text(dub_pipeline.format_srt(subtitles), encoding="utf-8")

            with patch.object(dub_pipeline, "audio_duration", return_value=30.0):
                result = dub_pipeline.load_or_transcribe_subtitles(
                    input_srt=input_srt,
                    asr_audio=fake_audio,
                    source_srt_path=source_srt,
                    persist_input_srt_to_source=True,
                    asr_model_path="unused",
                    aligner_path="unused",
                    device="cpu",
                    language=None,
                    max_width=40,
                    asr_balance_lines=True,
                    asr_balance_gap_sec=0.5,
                    source_layout_mode="rule",
                    source_layout_llm_min_duration_sec=6.0,
                    source_layout_llm_min_text_units=85,
                    source_layout_llm_max_cues=12,
                    source_short_merge_enabled=True,
                    source_short_merge_threshold=10,
                    source_short_merge_requested=True,
                    source_short_merge_effective_reason="user",
                    translator_factory=None,
                    logger=logger,
                )

            saved = dub_pipeline.parse_srt(source_srt.read_text(encoding="utf-8"))
            self.assertEqual([item["text"] for item in result], [item["text"] for item in saved])
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["text"], "First short sentence. Second short sentence. Third line closes cleanly.")
            self.assertAlmostEqual(saved[0]["start"], 0.000, places=3)
            self.assertAlmostEqual(saved[0]["end"], 9.000, places=3)
            self.assertTrue(all(dub_pipeline.ends_with_explicit_break(item["text"]) for item in saved))
            self.assertTrue(any(record["event"] == "source_layout_rebalanced" for record in logger.records))
            self.assertTrue(any(record["event"] == "srt_loaded" for record in logger.records))


if __name__ == "__main__":
    unittest.main()
