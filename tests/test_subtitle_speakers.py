from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from subtitle_maker.domains.subtitles import (
    build_segment_speaker_metadata_from_subtitles,
    deepgram_json_to_subtitles,
    normalize_subtitles_with_speakers,
    parse_speaker_ref_map_json,
    strip_speaker_prefix,
)


class SubtitleSpeakerTests(unittest.TestCase):
    """覆盖多人字幕 speaker 前缀解析与参考音映射解析。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="subtitle_speakers_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_strip_speaker_prefix_extracts_speaker_and_text(self) -> None:
        speaker_id, text = strip_speaker_prefix("Speaker 1: Hello world")
        self.assertEqual(speaker_id, "Speaker 1")
        self.assertEqual(text, "Hello world")

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


if __name__ == "__main__":
    unittest.main()
