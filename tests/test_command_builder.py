from __future__ import annotations

import json
import unittest
from pathlib import Path

from subtitle_maker.jobs import (
    AutoDubbingCommandConfig,
    SegmentRedubCommandConfig,
    build_auto_dubbing_command,
    build_segment_redub_command,
)


class CommandBuilderTests(unittest.TestCase):
    def test_build_auto_dubbing_command_keeps_optional_replay_flags(self):
        cmd = build_auto_dubbing_command(
            AutoDubbingCommandConfig(
                python_executable="/usr/bin/python3",
                tool_path=Path("/repo/tools/dub_long_video.py"),
                input_media=Path("/tmp/input.mp4"),
                target_lang="Chinese",
                out_dir=Path("/tmp/out"),
                segment_minutes=8.0,
                min_segment_minutes=4.0,
                timing_mode="balanced",
                grouping_strategy="sentence",
                short_merge_enabled=True,
                short_merge_threshold=12,
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-chat",
                index_tts_api_url="http://127.0.0.1:8010",
                auto_pick_ranges=True,
                auto_pick_min_silence_sec=0.8,
                auto_pick_min_speech_sec=1.0,
                input_srt=Path("/tmp/manual.srt"),
                input_srt_kind="translated",
                time_ranges=[{"start_sec": 1.0, "end_sec": 5.5}],
                source_lang="English",
                pipeline_version="v2",
                rewrite_translation=False,
            )
        )

        self.assertEqual(cmd[:3], ["/usr/bin/python3", "-u", "/repo/tools/dub_long_video.py"])
        self.assertIn("--input-srt", cmd)
        self.assertIn("--input-srt-kind", cmd)
        self.assertIn("translated", cmd)
        self.assertIn("--time-ranges-json", cmd)
        ranges_index = cmd.index("--time-ranges-json")
        self.assertEqual(json.loads(cmd[ranges_index + 1]), [{"start_sec": 1.0, "end_sec": 5.5}])
        self.assertIn("--asr-language", cmd)
        self.assertIn("English", cmd)
        self.assertIn("--v2-mode", cmd)
        self.assertIn("--v2-rewrite-translation", cmd)
        rewrite_index = cmd.index("--v2-rewrite-translation")
        self.assertEqual(cmd[rewrite_index + 1], "false")

    def test_build_segment_redub_command_skips_line_indices_for_grouped_segments(self):
        cmd = build_segment_redub_command(
            SegmentRedubCommandConfig(
                python_executable="/usr/bin/python3",
                tool_path=Path("/repo/tools/dub_pipeline.py"),
                segment_job_dir=Path("/tmp/segment_0001"),
                out_dir=Path("/tmp"),
                input_media=Path("/tmp/segment.wav"),
                target_lang="English",
                translated_srt=Path("/tmp/segment_0001/subtitles/translated.srt"),
                index_tts_api_url="http://127.0.0.1:8010",
                pipeline_version="v2",
                rewrite_translation=False,
                grouped_synthesis=True,
                force_fit_timing=True,
                redub_local_indices=[2, 3],
            )
        )

        self.assertIn("--grouped-synthesis", cmd)
        grouped_index = cmd.index("--grouped-synthesis")
        self.assertEqual(cmd[grouped_index + 1], "true")
        self.assertIn("--force-fit-timing", cmd)
        force_fit_index = cmd.index("--force-fit-timing")
        self.assertEqual(cmd[force_fit_index + 1], "true")
        self.assertIn("--v2-mode", cmd)
        self.assertIn("--v2-rewrite-translation", cmd)
        self.assertNotIn("--redub-line-indices-json", cmd)

    def test_build_segment_redub_command_keeps_line_indices_for_non_grouped_segments(self):
        cmd = build_segment_redub_command(
            SegmentRedubCommandConfig(
                python_executable="/usr/bin/python3",
                tool_path=Path("/repo/tools/dub_pipeline.py"),
                segment_job_dir=Path("/tmp/segment_0001"),
                out_dir=Path("/tmp"),
                input_media=Path("/tmp/segment.wav"),
                target_lang="English",
                translated_srt=Path("/tmp/segment_0001/subtitles/translated.srt"),
                index_tts_api_url="http://127.0.0.1:8010",
                grouped_synthesis=False,
                force_fit_timing=False,
                redub_local_indices=[3, 1, 3, 0],
            )
        )

        self.assertIn("--redub-line-indices-json", cmd)
        indices_index = cmd.index("--redub-line-indices-json")
        self.assertEqual(json.loads(cmd[indices_index + 1]), [1, 3])


if __name__ == "__main__":
    unittest.main()
