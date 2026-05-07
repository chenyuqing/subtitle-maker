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
        self._ensure_client = lambda: self.client

    def _parse_translated_lines(self, content: str, expected_len: int) -> List[str]:
        lines: List[str] = []
        for raw in str(content or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if "." in line:
                prefix, rest = line.split(".", 1)
                if prefix.strip().isdigit():
                    lines.append(rest.strip())
                    continue
            lines.append(line)
        if len(lines) < expected_len:
            lines.extend([""] * (expected_len - len(lines)))
        return lines[:expected_len]


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

    def test_resolve_grouped_synthesis_policy_keeps_grouping_for_source_short_merge(self) -> None:
        """source short merge 只做字幕重构，不应强制关闭 grouped synthesis。"""

        effective, reason = dub_pipeline.resolve_grouped_synthesis_policy(
            requested_enabled=True,
            input_srt_is_translated=False,
            translated_input_preserve_synthesis_mode=False,
            source_short_merge_enabled=True,
        )

        self.assertTrue(effective)
        self.assertEqual(reason, "user")

    def test_resolve_grouped_synthesis_policy_keeps_translated_strict_alignment_priority(self) -> None:
        """translated 直通模式仍应优先禁用 grouped synthesis。"""

        effective, reason = dub_pipeline.resolve_grouped_synthesis_policy(
            requested_enabled=True,
            input_srt_is_translated=True,
            translated_input_preserve_synthesis_mode=False,
            source_short_merge_enabled=False,
        )

        self.assertFalse(effective)
        self.assertEqual(reason, "input_translated_strict_alignment")

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

        self.assertEqual(selector(0).audio_path, short_ref)
        self.assertEqual(selector(0).reference_text, "短句一")
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

    def test_load_or_transcribe_subtitles_merges_uploaded_source_srt_without_asr_layout(self) -> None:
        """上传 source.srt 时，只做纯字幕级并句，不再触发 ASR/source-layout。"""
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
            self.assertTrue(any(record["event"] == "uploaded_source_subtitle_preprocessed" for record in logger.records))
            self.assertTrue(any(record["event"] == "srt_loaded" for record in logger.records))
            self.assertFalse(any(record["event"] == "source_layout_rebalanced" for record in logger.records))
            self.assertFalse(any(str(record["event"]).startswith("source_layout_llm_") for record in logger.records))

    def test_main_first_run_source_input_persists_uploaded_srt_for_rebalance(self) -> None:
        """首轮 source 输入且尚无 source.srt 时，主流程也必须走重构落盘分支。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_media = tmp_path / "demo.wav"
            input_media.write_bytes(b"fake-media")
            input_srt = tmp_path / "input.srt"
            input_srt.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nFirst short sentence.\n",
                encoding="utf-8",
            )
            out_dir = tmp_path / "out"
            seen: Dict[str, Any] = {}

            def fake_extract_audio(src: Path, dst: Path) -> None:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(b"fake-source-audio")

            def fake_load_or_transcribe_subtitles(**kwargs: Any) -> List[Dict[str, Any]]:
                seen.update(kwargs)
                raise RuntimeError("stop_after_load")

            with patch.object(dub_pipeline, "extract_audio", side_effect=fake_extract_audio), patch.object(
                dub_pipeline, "audio_duration", return_value=6.0
            ), patch.object(
                dub_pipeline, "load_or_transcribe_subtitles", side_effect=fake_load_or_transcribe_subtitles
            ), patch.object(
                sys,
                "argv",
                [
                    "dub_pipeline.py",
                    "--input-media",
                    str(input_media),
                    "--input-srt",
                    str(input_srt),
                    "--input-srt-kind",
                    "source",
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(out_dir),
                    "--source-short-merge-enabled",
                    "true",
                    "--source-short-merge-threshold",
                    "15",
                    "--index-tts-api-release-after-job",
                    "false",
                ],
            ):
                exit_code = dub_pipeline.main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(bool(seen))
            self.assertTrue(seen["persist_input_srt_to_source"])
            self.assertEqual(Path(seen["input_srt"]).resolve(), input_srt.resolve())

    def test_merge_short_source_subtitles_sentence_aware_prefers_complete_sentences(self) -> None:
        """句级重构应避免把一句话拆成多行。"""

        subtitles = [
            {"start": 0.0, "end": 2.0, "text": "First clause,"},
            {"start": 2.0, "end": 4.0, "text": "still same sentence."},
            {"start": 4.0, "end": 6.0, "text": "Second sentence starts,"},
            {"start": 6.0, "end": 8.0, "text": "and ends here."},
        ]

        merged, merged_pairs, sentence_blocks = dub_pipeline.merge_short_source_subtitles_sentence_aware(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged_pairs, 3)
        self.assertEqual(sentence_blocks, 2)
        self.assertEqual(
            merged[0]["text"],
            "First clause, still same sentence. Second sentence starts, and ends here.",
        )
        self.assertAlmostEqual(merged[0]["start"], 0.0, places=3)
        self.assertAlmostEqual(merged[0]["end"], 8.0, places=3)

    def test_merge_short_source_subtitles_sentence_aware_splits_oversized_sentence(self) -> None:
        """单句超过目标时长时应拆分，避免产生超长字幕块。"""

        subtitles = [
            {"start": 0.0, "end": 4.0, "text": "One long thought,"},
            {"start": 4.0, "end": 8.0, "text": "with another clause,"},
            {"start": 8.0, "end": 12.0, "text": "and it keeps extending."},
        ]

        merged, merged_pairs, sentence_blocks = dub_pipeline.merge_short_source_subtitles_sentence_aware(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(sentence_blocks, 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged_pairs, 2)
        self.assertEqual(
            [item["text"] for item in merged],
            ["One long thought, with another clause, and it keeps extending."],
        )
        self.assertAlmostEqual(merged[0]["start"], 0.0, places=3)
        self.assertAlmostEqual(merged[0]["end"], 12.0, places=3)
        self.assertGreater(merged[0]["end"] - merged[0]["start"], 10.0)

    def test_merge_short_source_subtitles_speaker_aware_does_not_cross_different_speakers(self) -> None:
        """source short merge 遇到不同 speaker 时，绝不能跨 speaker 合并。"""

        subtitles = [
            {"start": 0.0, "end": 2.0, "text": "第一句。", "speaker_id": "Speaker 1"},
            {"start": 2.0, "end": 4.0, "text": "第二句。", "speaker_id": "Speaker 1"},
            {"start": 4.0, "end": 6.0, "text": "第三句。", "speaker_id": "Speaker 2"},
            {"start": 6.0, "end": 8.0, "text": "第四句。", "speaker_id": "Speaker 2"},
        ]

        merged, merged_pairs, speaker_runs = dub_pipeline.merge_short_source_subtitles_speaker_aware(
            subtitles=subtitles,
            short_merge_target_seconds=10,
            gap_threshold_sec=1.5,
        )

        self.assertEqual(merged_pairs, 2)
        self.assertEqual(speaker_runs, 2)
        self.assertEqual(len(merged), 2)
        self.assertEqual([item["speaker_id"] for item in merged], ["Speaker 1", "Speaker 2"])
        self.assertEqual(
            [item["text"] for item in merged],
            ["第一句。第二句。", "第三句。第四句。"],
        )

    def test_rebalance_source_subtitles_short_merge_respects_speaker_prefix_boundaries(self) -> None:
        """上传 source.srt 含 Speaker 前缀时，短句合并也应先识别 speaker 边界。"""

        subtitles = [
            {"start": 0.0, "end": 2.0, "text": "Speaker 1: First short sentence."},
            {"start": 2.0, "end": 4.0, "text": "Speaker 1: Second short sentence."},
            {"start": 4.0, "end": 6.0, "text": "Speaker 2: Third short sentence."},
            {"start": 6.0, "end": 8.0, "text": "Speaker 2: Fourth short sentence."},
        ]

        result = dub_pipeline.rebalance_source_subtitles(
            subtitles=subtitles,
            max_gap_sec=0.5,
            max_line_width=40,
            source_short_merge_enabled=True,
            source_short_merge_threshold=10,
            logger=DummyLogger(),
        )

        self.assertEqual(len(result), 2)
        self.assertEqual([item.get("speaker_id") for item in result], ["Speaker 1", "Speaker 2"])
        self.assertEqual(
            [item["text"] for item in result],
            [
                "First short sentence. Second short sentence.",
                "Third short sentence. Fourth short sentence.",
            ],
        )

    def test_reflow_cluster_with_llm_uses_custom_translate_system_prompt(self) -> None:
        """翻译后重排调用 LLM 时应沿用用户自定义系统提示词。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Speaker 1: Andrew Main"},
            {"start": 1.0, "end": 2.0, "text": "Speaker 1: OpenAI Podcast"},
        ]
        translated_lines = ["安德鲁", "播客。"]
        fake_translator = FakeTranslator(["1. Andrew\n2. OpenAI Podcast"])
        custom_prompt = "这是 openai 的视频播客，翻译时名字保留英文。"

        output = dub_pipeline.reflow_cluster_with_llm(
            translator=fake_translator,
            subtitles=subtitles,
            translated_lines=translated_lines,
            indices=[0, 1],
            target_lang="Chinese",
            system_prompt=custom_prompt,
        )

        self.assertEqual(output, ["Andrew", "OpenAI Podcast"])
        self.assertEqual(len(fake_translator.completions.calls), 1)
        system_message = fake_translator.completions.calls[0]["messages"][0]["content"]
        self.assertEqual(system_message, custom_prompt)


if __name__ == "__main__":
    unittest.main()
