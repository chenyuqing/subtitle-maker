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
                translate_model="deepseek-v4-flash",
                tts_backend="index-tts",
                fallback_tts_backend="omnivoice",
                omnivoice_root="/opt/omnivoice",
                omnivoice_python_bin="/opt/omnivoice/.venv/bin/python",
                omnivoice_model="k2-fsa/OmniVoice",
                omnivoice_device="mps",
                index_tts_api_url="http://127.0.0.1:8010",
                auto_pick_ranges=True,
                auto_pick_min_silence_sec=0.8,
                auto_pick_min_speech_sec=1.0,
                translated_short_merge_enabled=True,
                translated_short_merge_threshold=11,
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
        self.assertIn("--translated-short-merge-enabled", cmd)
        translated_merge_index = cmd.index("--translated-short-merge-enabled")
        self.assertEqual(cmd[translated_merge_index + 1], "true")
        self.assertIn("--translated-short-merge-threshold", cmd)
        translated_threshold_index = cmd.index("--translated-short-merge-threshold")
        self.assertEqual(cmd[translated_threshold_index + 1], "11")
        self.assertIn("--dub-audio-leveling-enabled", cmd)
        leveling_enabled_index = cmd.index("--dub-audio-leveling-enabled")
        self.assertEqual(cmd[leveling_enabled_index + 1], "true")
        self.assertIn("--dub-audio-leveling-target-rms", cmd)
        target_rms_index = cmd.index("--dub-audio-leveling-target-rms")
        self.assertEqual(cmd[target_rms_index + 1], "0.12")
        self.assertIn("--dub-audio-leveling-peak-ceiling", cmd)
        peak_ceiling_index = cmd.index("--dub-audio-leveling-peak-ceiling")
        self.assertEqual(cmd[peak_ceiling_index + 1], "0.95")
        self.assertIn("--time-ranges-json", cmd)
        ranges_index = cmd.index("--time-ranges-json")
        self.assertEqual(json.loads(cmd[ranges_index + 1]), [{"start_sec": 1.0, "end_sec": 5.5}])
        self.assertIn("--asr-language", cmd)
        self.assertIn("English", cmd)
        self.assertIn("--v2-mode", cmd)
        self.assertIn("--v2-rewrite-translation", cmd)
        rewrite_index = cmd.index("--v2-rewrite-translation")
        self.assertEqual(cmd[rewrite_index + 1], "false")
        self.assertIn("--fallback-tts-backend", cmd)
        fallback_index = cmd.index("--fallback-tts-backend")
        self.assertEqual(cmd[fallback_index + 1], "omnivoice")
        self.assertIn("--omnivoice-root", cmd)
        omni_root_index = cmd.index("--omnivoice-root")
        self.assertEqual(cmd[omni_root_index + 1], "/opt/omnivoice")
        self.assertIn("--omnivoice-via-api", cmd)
        via_api_index = cmd.index("--omnivoice-via-api")
        self.assertEqual(cmd[via_api_index + 1], "true")
        self.assertIn("--omnivoice-api-url", cmd)
        api_url_index = cmd.index("--omnivoice-api-url")
        self.assertEqual(cmd[api_url_index + 1], "http://127.0.0.1:8020")

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
                fallback_tts_backend="none",
                omnivoice_root="",
                omnivoice_python_bin="",
                omnivoice_model="",
                omnivoice_device="auto",
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
        self.assertIn("--fallback-tts-backend", cmd)
        self.assertNotIn("--redub-line-indices-json", cmd)
        self.assertNotIn("--translated-short-merge-enabled", cmd)

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
                fallback_tts_backend="none",
                omnivoice_root="",
                omnivoice_python_bin="",
                omnivoice_model="",
                omnivoice_device="auto",
                grouped_synthesis=False,
                force_fit_timing=False,
                redub_local_indices=[3, 1, 3, 0],
            )
        )

        self.assertIn("--redub-line-indices-json", cmd)
        self.assertIn("--fallback-tts-backend", cmd)
        indices_index = cmd.index("--redub-line-indices-json")
        self.assertEqual(json.loads(cmd[indices_index + 1]), [1, 3])

    def test_build_auto_dubbing_command_keeps_omnivoice_runtime_flags_for_primary_backend(self):
        cmd = build_auto_dubbing_command(
            AutoDubbingCommandConfig(
                python_executable="/usr/bin/python3",
                tool_path=Path("/repo/tools/dub_long_video.py"),
                input_media=Path("/tmp/input.mp4"),
                target_lang="Chinese",
                out_dir=Path("/tmp/out"),
                segment_minutes=8.0,
                min_segment_minutes=4.0,
                timing_mode="strict",
                grouping_strategy="sentence",
                short_merge_enabled=False,
                short_merge_threshold=15,
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                tts_backend="omnivoice",
                fallback_tts_backend="none",
                omnivoice_root="/opt/omnivoice",
                omnivoice_python_bin="/opt/omnivoice/.venv/bin/python",
                omnivoice_model="k2-fsa/OmniVoice",
                omnivoice_device="mps",
                index_tts_api_url="http://127.0.0.1:8010",
                auto_pick_ranges=False,
                auto_pick_min_silence_sec=0.8,
                auto_pick_min_speech_sec=1.0,
            )
        )

        self.assertIn("--tts-backend", cmd)
        backend_index = cmd.index("--tts-backend")
        self.assertEqual(cmd[backend_index + 1], "omnivoice")
        self.assertIn("--omnivoice-root", cmd)
        self.assertIn("--omnivoice-python-bin", cmd)
        self.assertIn("--omnivoice-via-api", cmd)
        self.assertIn("--omnivoice-api-url", cmd)

    def test_build_auto_dubbing_command_includes_resume_batch_dir_when_provided(self):
        cmd = build_auto_dubbing_command(
            AutoDubbingCommandConfig(
                python_executable="/usr/bin/python3",
                tool_path=Path("/repo/tools/dub_long_video.py"),
                input_media=Path("/tmp/input.mp4"),
                target_lang="Chinese",
                out_dir=Path("/tmp/out"),
                segment_minutes=8.0,
                min_segment_minutes=4.0,
                timing_mode="strict",
                grouping_strategy="sentence",
                short_merge_enabled=False,
                short_merge_threshold=15,
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                tts_backend="index-tts",
                fallback_tts_backend="none",
                omnivoice_root="",
                omnivoice_python_bin="",
                omnivoice_model="",
                omnivoice_device="auto",
                index_tts_api_url="http://127.0.0.1:8010",
                auto_pick_ranges=False,
                auto_pick_min_silence_sec=0.8,
                auto_pick_min_speech_sec=1.0,
                resume_batch_dir=Path("/tmp/out/longdub_20260427_123000"),
            )
        )

        self.assertIn("--resume-batch-dir", cmd)
        resume_index = cmd.index("--resume-batch-dir")
        self.assertEqual(cmd[resume_index + 1], "/tmp/out/longdub_20260427_123000")


if __name__ == "__main__":
    unittest.main()
