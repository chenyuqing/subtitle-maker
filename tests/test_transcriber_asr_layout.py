from __future__ import annotations

import unittest

from subtitle_maker.transcriber import (
    SubtitleGenerator,
    format_srt,
    merge_chunk_subtitles,
    normalize_subtitle_timeline,
)


def _build_time_stamps(tokens: list[str], start: float = 0.0, token_dur: float = 0.20, gap: float = 0.03) -> list[dict]:
    """按给定 token 生成简化时间戳，便于构造 ASR 单元测试输入。"""

    stamps: list[dict] = []
    cursor = float(start)
    for token in tokens:
        end = cursor + token_dur
        stamps.append({
            "text": token,
            "start_time": cursor,
            "end_time": end,
        })
        cursor = end + gap
    return stamps


class TranscriberAsrLayoutTests(unittest.TestCase):
    """覆盖 ASR 前置修复的核心行为：分句、边界去重、时间轴兜底。"""

    def setUp(self) -> None:
        # lazy_load=True 避免测试期加载真实 ASR 模型。
        self.generator = SubtitleGenerator(lazy_load=True)

    def test_normalize_timeline_removes_overlap(self) -> None:
        """时间轴兜底应保证输出单调，禁止相邻重叠。"""

        raw = [
            {"start": 14.800, "end": 17.760, "text": "first line"},
            {"start": 17.199, "end": 19.600, "text": "second line"},
            {"start": 19.200, "end": 21.679, "text": "third line"},
        ]
        cleaned = normalize_subtitle_timeline(raw)
        self.assertGreaterEqual(len(cleaned), 2)
        for idx in range(1, len(cleaned)):
            self.assertGreater(cleaned[idx]["start"], cleaned[idx - 1]["end"])

    def test_normalize_timeline_merges_too_short_fragment(self) -> None:
        """过短孤立片段（如单词行）应优先并入邻句。"""

        raw = [
            {"start": 0.00, "end": 0.90, "text": "harness"},
            {"start": 0.95, "end": 2.10, "text": "engineering"},
        ]
        cleaned = normalize_subtitle_timeline(raw)
        self.assertEqual(len(cleaned), 1)
        self.assertIn("harness", cleaned[0]["text"])
        self.assertIn("engineering", cleaned[0]["text"])

    def test_generate_subtitles_avoids_connector_tail_break(self) -> None:
        """句尾连接词（and/but/is 等）不应被切成独立片段。"""

        text = "we design and build systems for humans."
        tokens = ["we", "design", "and", "build", "systems", "for", "humans"]
        results = [{
            "text": text,
            "time_stamps": _build_time_stamps(tokens, token_dur=0.18, gap=0.04),
        }]
        subtitles = self.generator.generate_subtitles(results, max_len=10)
        self.assertGreaterEqual(len(subtitles), 1)
        for row in subtitles:
            tail = row["text"].strip().lower()
            self.assertFalse(tail.endswith("and"))
            self.assertNotEqual(tail, "is")

    def test_generate_subtitles_does_not_split_moderate_pause_into_is_line(self) -> None:
        """中等停顿（~0.55s）不应把 'is' 强行拆成单独一条。"""

        results = [{
            "text": "what that means is we ship fast.",
            "time_stamps": [
                {"text": "what", "start_time": 0.00, "end_time": 0.20},
                {"text": "that", "start_time": 0.23, "end_time": 0.43},
                {"text": "means", "start_time": 0.46, "end_time": 0.66},
                # 0.55 秒停顿：旧策略（0.5）会切断，新策略应保持连贯。
                {"text": "is", "start_time": 1.21, "end_time": 1.36},
                {"text": "we", "start_time": 1.39, "end_time": 1.54},
                {"text": "ship", "start_time": 1.57, "end_time": 1.77},
                {"text": "fast", "start_time": 1.80, "end_time": 2.00},
            ],
        }]
        subtitles = self.generator.generate_subtitles(results, max_len=40)
        self.assertGreaterEqual(len(subtitles), 1)
        self.assertFalse(any(item["text"].strip().lower() == "is" for item in subtitles))

    def test_merge_chunk_subtitles_dedupes_boundary_overlap(self) -> None:
        """chunk 首尾重叠时应去重合并，避免重复词覆盖。"""

        existing = [
            {"start": 1.00, "end": 2.20, "text": "what that means is"},
        ]
        incoming = [
            {"start": 2.10, "end": 3.20, "text": "means is we ship fast"},
            {"start": 3.25, "end": 3.90, "text": "next sentence"},
        ]
        merged = merge_chunk_subtitles(existing, incoming)
        self.assertEqual(len(merged), 2)
        self.assertIn("we ship fast", merged[0]["text"])
        self.assertNotIn("means is means is", merged[0]["text"].lower())

    def test_normalize_timeline_merges_connector_head_row(self) -> None:
        """弱连接词起句应并回前句，避免“..., and / 下一行”割裂。"""

        raw = [
            {"start": 10.00, "end": 12.60, "text": "we changed our workflow"},
            {"start": 12.70, "end": 14.90, "text": "and this becomes important for teams"},
        ]
        cleaned = normalize_subtitle_timeline(raw)
        self.assertEqual(len(cleaned), 1)
        self.assertIn("workflow and this becomes important", cleaned[0]["text"])

    def test_normalize_timeline_splits_overlong_row(self) -> None:
        """超长时长（>6s）应自动拆分，降低阅读峰值。"""

        raw = [{
            "start": 0.0,
            "end": 8.4,
            "text": "we now have a different kind of job, and this requires better delegation and better systems thinking",
        }]
        cleaned = normalize_subtitle_timeline(raw)
        self.assertGreaterEqual(len(cleaned), 2)
        self.assertTrue(all((item["end"] - item["start"]) <= 6.05 for item in cleaned))

    def test_normalize_timeline_repairs_leading_punctuation(self) -> None:
        """句首孤立标点应修复，不再出现“. And / , and”开头。"""

        raw = [
            {"start": 0.0, "end": 2.8, "text": "we can ship faster"},
            {"start": 2.9, "end": 4.9, "text": ", and keep quality high"},
        ]
        cleaned = normalize_subtitle_timeline(raw)
        self.assertEqual(len(cleaned), 1)
        self.assertFalse(cleaned[0]["text"].strip().startswith(","))

    def test_format_srt_wraps_lines_by_width(self) -> None:
        """SRT 输出应按 42 字符规则换行，优先控制在两行内。"""

        subtitles = [{
            "start": 0.0,
            "end": 4.0,
            "text": "This sentence verifies subtitle wrapping keeps lines readable and balanced.",
        }]
        srt = format_srt(subtitles)
        lines = srt.strip().splitlines()
        text_lines = lines[2:]
        self.assertLessEqual(len(text_lines), 2)
        self.assertTrue(all(len(line) <= 42 for line in text_lines))


if __name__ == "__main__":
    unittest.main()
