from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from subtitle_maker.domains.subtitles import (
    build_segment_speaker_metadata_from_subtitles,
    deepgram_json_to_subtitles,
    optimize_srt_import_subtitles,
    normalize_subtitles_with_speakers,
    parse_speaker_ref_map_json,
    subtitle_group_text,
    strip_speaker_prefix,
)


@pytest.mark.unit
class SubtitleSpeakerTests(unittest.TestCase):
    """覆盖多人字幕 speaker 前缀解析与参考音映射解析。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="subtitle_speakers_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_strip_speaker_prefix_extracts_speaker_and_text(self) -> None:
        speaker_id, text = strip_speaker_prefix("Speaker 1: Hello world")
        self.assertEqual(speaker_id, "Speaker 1")
        self.assertEqual(text, "Hello world")

    def test_strip_speaker_prefix_does_not_treat_normal_english_colon_text_as_speaker(self) -> None:
        speaker_id, text = strip_speaker_prefix("Ideas are everywhere: they're worthless.")
        self.assertIsNone(speaker_id)
        self.assertEqual(text, "Ideas are everywhere: they're worthless.")

    def test_normalize_subtitles_with_speakers_keeps_order_and_removes_prefix(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Speaker 1: Hello"},
            {"start": 1.0, "end": 2.0, "text": "Speaker 2: Hi"},
            {"start": 2.0, "end": 3.0, "text": "No prefix here"},
        ]
        normalized, speaker_ids = normalize_subtitles_with_speakers(subtitles)
        self.assertEqual(speaker_ids, ["Speaker 1", "Speaker 2"])
        self.assertEqual(normalized[0]["text"], "Hello")
        self.assertEqual(normalized[0]["speaker_id"], "Speaker 1")
        self.assertEqual(normalized[1]["text"], "Hi")
        self.assertEqual(normalized[1]["speaker_id"], "Speaker 2")
        self.assertEqual(normalized[2]["text"], "No prefix here")
        self.assertNotIn("speaker_id", normalized[2])

    def test_normalize_subtitles_with_speakers_keeps_existing_sidecar_speaker_id(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Hi", "speaker_id": "Speaker 2"},
        ]
        normalized, speaker_ids = normalize_subtitles_with_speakers(subtitles)
        self.assertEqual(speaker_ids, ["Speaker 1", "Speaker 2"])
        self.assertEqual(normalized[0]["speaker_id"], "Speaker 1")
        self.assertEqual(normalized[1]["speaker_id"], "Speaker 2")

    def test_normalize_subtitles_with_speakers_does_not_trim_normal_colon_text_when_sidecar_exists(self) -> None:
        subtitles = [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "我今天想聊一个事实。哈佛创新实验室的导师在课上说了一句话，原话是：Ideas are everywhere.",
                "speaker_id": "Larei",
            }
        ]

        normalized, speaker_ids = normalize_subtitles_with_speakers(subtitles)

        self.assertEqual(speaker_ids, ["Larei"])
        self.assertEqual(normalized[0]["speaker_id"], "Larei")
        self.assertEqual(
            normalized[0]["text"],
            "我今天想聊一个事实。哈佛创新实验室的导师在课上说了一句话，原话是：Ideas are everywhere.",
        )

    def test_build_segment_speaker_metadata_from_subtitles_only_keeps_tagged_rows(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "No speaker"},
        ]
        metadata = build_segment_speaker_metadata_from_subtitles(subtitles)
        self.assertEqual(
            metadata,
            [
                {
                    "subtitle_index": 1,
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "Hello",
                    "speaker_id": "Speaker 1",
                }
            ],
        )

    def test_parse_speaker_ref_map_json_returns_resolved_paths(self) -> None:
        ref_audio = self.tmpdir / "speaker1.wav"
        ref_audio.write_bytes(b"wav")
        payload = json.dumps(
            [{"speaker_id": "Speaker 1", "ref_audio_path": str(ref_audio)}],
            ensure_ascii=False,
        )
        mapping = parse_speaker_ref_map_json(payload)
        self.assertEqual(mapping["Speaker 1"], ref_audio.resolve())

    def test_deepgram_json_to_subtitles_merges_speaker_turns_from_paragraphs(self) -> None:
        payload = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "paragraphs": {
                                    "paragraphs": [
                                        {
                                            "speaker": 0,
                                            "start": 0,
                                            "end": 4.88,
                                            "sentences": [
                                                {
                                                    "text": "During sex, the average man lasts two point five minutes to six minutes.",
                                                    "start": 0,
                                                    "end": 4.88,
                                                }
                                            ],
                                        },
                                        {
                                            "speaker": 1,
                                            "start": 4.88,
                                            "end": 12.24,
                                            "sentences": [
                                                {
                                                    "text": "And I know this because I'm a sex therapist.",
                                                    "start": 4.88,
                                                    "end": 6.64,
                                                },
                                                {
                                                    "text": "They've done studies in colleges, and something like ninety five percent of guys were worried about climaxing too soon.",
                                                    "start": 6.64,
                                                    "end": 12.24,
                                                },
                                            ],
                                        },
                                        {
                                            "speaker": 0,
                                            "start": 12.365,
                                            "end": 30.28,
                                            "sentences": [
                                                {
                                                    "text": "If this is what's actually happening, it's like the public facing message of what a sexual encounter is actually happening and what's actually happening in a private encounter is like very different.",
                                                    "start": 12.365,
                                                    "end": 22.925,
                                                },
                                                {
                                                    "text": "Like, if you're had a hookup and you're in a locker room talking about it with the boys you're not going to be saying, Oh, it lasted two minutes.",
                                                    "start": 22.925,
                                                    "end": 30.28,
                                                },
                                            ],
                                        },
                                        {
                                            "speaker": 1,
                                            "start": 30.28,
                                            "end": 47.615,
                                            "sentences": [
                                                {"text": "No.", "start": 30.28, "end": 30.68},
                                                {
                                                    "text": "But most guys are doing things in order not to ejaculate quite so quickly.",
                                                    "start": 30.68,
                                                    "end": 36.28,
                                                },
                                                {
                                                    "text": "Most guys are doing some degree of stopping and starting, or they're kinda staying below the speed limit and trying not to get too excited.",
                                                    "start": 36.84,
                                                    "end": 43.775,
                                                },
                                                {
                                                    "text": "They have to kind of almost create bad sex in order not to come too fast.",
                                                    "start": 43.775,
                                                    "end": 47.615,
                                                },
                                            ],
                                        },
                                        {
                                            "speaker": 0,
                                            "start": 47.934998,
                                            "end": 51.135,
                                            "sentences": [
                                                {
                                                    "text": "you feel like this is a a trivial conversation or",
                                                    "start": 47.934998,
                                                    "end": 51.135,
                                                }
                                            ],
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }

        subtitles = deepgram_json_to_subtitles(payload)
        self.assertEqual(len(subtitles), 8)
        self.assertEqual(
            [item["speaker_id"] for item in subtitles],
            [
                "Speaker 1",
                "Speaker 2",
                "Speaker 1",
                "Speaker 1",
                "Speaker 2",
                "Speaker 2",
                "Speaker 2",
                "Speaker 1",
            ],
        )
        self.assertEqual(subtitles[0]["text"], "During sex, the average man lasts two point five minutes to six minutes.")
        self.assertIn("And I know this because I'm a sex therapist.", subtitles[1]["text"])
        self.assertIn("They've done studies in colleges", subtitles[1]["text"])
        self.assertEqual(subtitles[4]["text"], "No.\nBut most guys are doing things in order not to ejaculate quite so quickly.")
        self.assertEqual(subtitles[-1]["text"], "you feel like this is a a trivial conversation or")

    def test_deepgram_json_to_subtitles_falls_back_to_words_when_paragraphs_missing(self) -> None:
        payload = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "words": [
                                    {
                                        "word": "hello",
                                        "punctuated_word": "Hello,",
                                        "start": 0.0,
                                        "end": 0.4,
                                        "speaker": 0,
                                    },
                                    {
                                        "word": "world",
                                        "punctuated_word": "world.",
                                        "start": 0.4,
                                        "end": 0.9,
                                        "speaker": 0,
                                    },
                                    {
                                        "word": "second",
                                        "punctuated_word": "Second",
                                        "start": 1.5,
                                        "end": 1.9,
                                        "speaker": 1,
                                    },
                                    {
                                        "word": "speaker",
                                        "punctuated_word": "speaker.",
                                        "start": 1.9,
                                        "end": 2.2,
                                        "speaker": 1,
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }

        subtitles = deepgram_json_to_subtitles(payload)
        self.assertEqual(len(subtitles), 2)
        self.assertEqual(subtitles[0]["speaker_id"], "Speaker 1")
        self.assertEqual(subtitles[1]["speaker_id"], "Speaker 2")
        self.assertEqual(subtitles[0]["text"], "Hello, world.")
        self.assertEqual(subtitles[1]["text"], "Second speaker.")

    def test_optimize_srt_import_subtitles_merges_same_speaker_short_turns(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 0.32, "text": "No.", "speaker_id": "Speaker 1"},
            {
                "start": 0.32,
                "end": 6.32,
                "text": "But most guys are doing things in order not to ejaculate quite so quickly.",
                "speaker_id": "Speaker 1",
            },
        ]

        optimized = optimize_srt_import_subtitles(subtitles)
        self.assertEqual(len(optimized), 2)
        self.assertEqual(optimized[0]["start"], 0.0)
        self.assertGreater(optimized[0]["end"], optimized[0]["start"])
        self.assertEqual(optimized[0]["text"], "No.")
        self.assertEqual(optimized[1]["text"], "But most guys are doing things in order not to ejaculate quite so quickly.")
        self.assertEqual(optimized[0]["speaker_id"], "Speaker 1")
        self.assertEqual(optimized[1]["speaker_id"], "Speaker 1")

    def test_optimize_srt_import_subtitles_keeps_different_speakers_separate(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 0.32, "text": "No.", "speaker_id": "Speaker 1"},
            {"start": 0.32, "end": 1.0, "text": "Okay.", "speaker_id": "Speaker 2"},
        ]

        optimized = optimize_srt_import_subtitles(subtitles)
        self.assertEqual(len(optimized), 2)
        self.assertEqual(optimized[0]["speaker_id"], "Speaker 1")
        self.assertEqual(optimized[1]["speaker_id"], "Speaker 2")

    def test_optimize_srt_import_subtitles_single_speaker_collapses_across_speaker_switches(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 0.32, "text": "但", "speaker_id": "Speaker 1"},
            {"start": 0.32, "end": 1.4, "text": "失败模式六呢？", "speaker_id": "Speaker 2"},
            {
                "start": 1.4,
                "end": 9.4,
                "text": "那就是，好吧，假设你的反馈循环正常工作，一切开始运转起来，你能够比以前发布更多代码，但你的大脑跟不上",
                "speaker_id": "Speaker 2",
            },
            {"start": 9.4, "end": 9.72, "text": "了。", "speaker_id": "Speaker 2"},
            {"start": 9.72, "end": 10.0, "text": "对吧？", "speaker_id": "Speaker 2"},
        ]

        # gap==0 的相邻块不再自动合并，每个块保持独立
        optimized = optimize_srt_import_subtitles(subtitles, speaker_mode="single")
        self.assertEqual(len(optimized), 5)
        self.assertEqual(optimized[0]["text"], "但")
        self.assertEqual(optimized[1]["text"], "失败模式六呢？")
        self.assertIn("跟不上", optimized[2]["text"])
        self.assertEqual(optimized[3]["text"], "了。")
        self.assertEqual(optimized[4]["text"], "对吧？")

    def test_optimize_srt_import_subtitles_keeps_complete_sentences_together(self) -> None:
        subtitles = [
            {"start": 0.0, "end": 0.32, "text": "但", "speaker_id": "Speaker 1"},
            {"start": 0.32, "end": 1.4, "text": "失败模式六呢？", "speaker_id": "Speaker 1"},
            {
                "start": 1.4,
                "end": 9.4,
                "text": "那就是，好吧，假设你的反馈循环正常工作，一切开始运转起来，你能够比以前发布更多代码，但你的大脑跟不上",
                "speaker_id": "Speaker 1",
            },
            {"start": 9.4, "end": 9.72, "text": "了。", "speaker_id": "Speaker 1"},
            {"start": 9.72, "end": 10.0, "text": "对吧？", "speaker_id": "Speaker 1"},
        ]

        optimized = optimize_srt_import_subtitles(subtitles)
        self.assertEqual(len(optimized), 5)
        self.assertEqual(optimized[0]["text"], "但")
        self.assertEqual(optimized[1]["text"], "失败模式六呢？")
        self.assertIn("跟不上", optimized[2]["text"])
        self.assertEqual(optimized[3]["text"], "了。")
        self.assertEqual(optimized[4]["text"], "对吧？")

    def test_optimize_srt_import_subtitles_splits_overlong_runs_without_sentence_punctuation(self) -> None:
        subtitles = [
            {"start": 879.120, "end": 882.240, "text": "Um and and so training training the models to be better at", "speaker_id": "Speaker 3"},
            {"start": 882.240, "end": 884.960, "text": "that, which I think will also make the models better at at", "speaker_id": "Speaker 3"},
            {"start": 885.280, "end": 888.160, "text": "other things where they haven't made progress as fast as coding, like", "speaker_id": "Speaker 3"},
            {"start": 888.160, "end": 891.200, "text": "their ability to write or their ability to kind of do do", "speaker_id": "Speaker 3"},
            {"start": 891.280, "end": 894.800, "text": "do do you know to to do uh you know less less", "speaker_id": "Speaker 3"},
            {"start": 894.800, "end": 896.640, "text": "objective scientific tasks.", "speaker_id": "Speaker 3"},
            {"start": 896.640, "end": 899.440, "text": "So I think it's gonna have benefits in many in many other", "speaker_id": "Speaker 3"},
            {"start": 899.440, "end": 903.120, "text": "areas, but you know I think we find even within software engineering", "speaker_id": "Speaker 3"},
            {"start": 903.280, "end": 907.040, "text": "this uh you know this these these kind of um uh uh", "speaker_id": "Speaker 3"},
            {"start": 907.280, "end": 912.800, "text": "soft or somewhat subjective um uh skills and abilities are become surprisingly", "speaker_id": "Speaker 3"},
        ]

        optimized = optimize_srt_import_subtitles(
            subtitles,
            speaker_mode="multi",
            enforce_merge_duration_guard=True,
        )

        self.assertGreater(len(optimized), 1)
        max_duration = max(float(item["end"]) - float(item["start"]) for item in optimized)
        self.assertLessEqual(max_duration, 12.0)
        self.assertTrue(all((item.get("speaker_id") == "Speaker 3") for item in optimized))

    def test_optimize_srt_import_subtitles_default_does_not_enforce_merge_duration_guard(self) -> None:
        subtitles = [
            {"start": 888.160, "end": 891.200, "text": "their ability to write or their ability to kind of do do", "speaker_id": "Speaker 3"},
            {"start": 891.280, "end": 894.800, "text": "do do you know to to do uh you know less less", "speaker_id": "Speaker 3"},
            {"start": 894.800, "end": 896.640, "text": "objective scientific tasks.", "speaker_id": "Speaker 3"},
            {"start": 896.640, "end": 899.440, "text": "So I think it's gonna have benefits in many in many other", "speaker_id": "Speaker 3"},
            {"start": 899.440, "end": 903.120, "text": "areas, but you know I think we find even within software engineering", "speaker_id": "Speaker 3"},
            {"start": 903.280, "end": 907.040, "text": "this uh you know this these these kind of um uh uh", "speaker_id": "Speaker 3"},
            {"start": 907.280, "end": 912.800, "text": "soft or somewhat subjective um uh skills and abilities are become surprisingly", "speaker_id": "Speaker 3"},
        ]

        optimized = optimize_srt_import_subtitles(subtitles, speaker_mode="multi")
        max_duration = max(float(item["end"]) - float(item["start"]) for item in optimized)
        self.assertGreater(max_duration, 12.0)

    def test_optimize_srt_import_subtitles_can_enforce_merge_duration_guard(self) -> None:
        subtitles = [
            {"start": 888.160, "end": 891.200, "text": "their ability to write or their ability to kind of do do", "speaker_id": "Speaker 3"},
            {"start": 891.280, "end": 894.800, "text": "do do you know to to do uh you know less less", "speaker_id": "Speaker 3"},
            {"start": 894.800, "end": 896.640, "text": "objective scientific tasks.", "speaker_id": "Speaker 3"},
            {"start": 896.640, "end": 899.440, "text": "So I think it's gonna have benefits in many in many other", "speaker_id": "Speaker 3"},
            {"start": 899.440, "end": 903.120, "text": "areas, but you know I think we find even within software engineering", "speaker_id": "Speaker 3"},
            {"start": 903.280, "end": 907.040, "text": "this uh you know this these these kind of um uh uh", "speaker_id": "Speaker 3"},
            {"start": 907.280, "end": 912.800, "text": "soft or somewhat subjective um uh skills and abilities are become surprisingly", "speaker_id": "Speaker 3"},
        ]

        optimized = optimize_srt_import_subtitles(
            subtitles,
            speaker_mode="multi",
            enforce_merge_duration_guard=True,
        )
        max_duration = max(float(item["end"]) - float(item["start"]) for item in optimized)
        self.assertLessEqual(max_duration, 12.0)

    def test_subtitle_group_text_keeps_english_spacing_in_cjk_mode(self) -> None:
        """CJK 合并时要保留英文词间空格，例如 Claude Code。"""

        merged = subtitle_group_text(
            [
                {"text": "我在用 Claude"},
                {"text": "Code 开发"},
            ],
            cjk_mode=True,
        )
        self.assertIn("Claude Code", merged)


if __name__ == "__main__":
    unittest.main()
