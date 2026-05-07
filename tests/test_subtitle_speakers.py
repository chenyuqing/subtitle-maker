from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from subtitle_maker.domains.subtitles import (
    build_segment_speaker_metadata_from_subtitles,
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


if __name__ == "__main__":
    unittest.main()
