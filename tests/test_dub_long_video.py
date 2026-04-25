from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
DUB_LONG_VIDEO_PATH = REPO_ROOT / "tools" / "dub_long_video.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_dub_long_video_module", DUB_LONG_VIDEO_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
dub_long_video = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = dub_long_video
MODULE_SPEC.loader.exec_module(dub_long_video)


class DubLongVideoTests(unittest.TestCase):
    """覆盖长视频编排中的边界分段行为。"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dub_long_video_test_"))
        self.input_media = self.tmpdir / "demo.mp4"
        self.input_media.write_bytes(b"fake-media")
        self.input_srt = self.tmpdir / "manual.srt"
        self.input_srt.write_text(
            "1\n00:00:01,000 --> 00:00:09,000\n第一段有字幕\n",
            encoding="utf-8",
        )
        self.out_dir = self.tmpdir / "outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_main_skips_segment_when_uploaded_srt_has_no_overlap(self) -> None:
        """上传字幕只覆盖部分视频时，空字幕分段应跳过而不是整批失败。"""

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 20.0

        def fake_detect_silence_endpoints(*, source_audio: Path, noise_db: float, min_duration_sec: float) -> list[float]:
            return [10.0]

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(f"{start_sec:.3f}-{end_sec:.3f}".encode("utf-8"))

        run_calls: list[int] = []

        def fake_run_segment_job(
            *,
            segment_index: int,
            segment_audio: Path,
            target_lang: str,
            segment_jobs_dir: Path,
            shared_ref: Path | None,
            single_speaker_ref_seconds: float,
            api_key: str | None,
            extra_args: list[str],
            segment_time_ranges: list[tuple[float, float]] | None = None,
            input_srt_path: Path | None = None,
            input_srt_kind: str = "source",
            resume_job_dir: Path | None = None,
        ) -> Path:
            run_calls.append(segment_index)
            self.assertEqual(segment_index, 1)
            self.assertIsNotNone(input_srt_path)
            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            source_srt = subtitles_dir / "source.srt"
            translated_srt = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"

            source_srt.write_text(
                "1\n00:00:01,000 --> 00:00:09,000\n第一段有字幕\n",
                encoding="utf-8",
            )
            translated_srt.write_text(
                "1\n00:00:01,000 --> 00:00:09,000\n第一段译文\n",
                encoding="utf-8",
            )
            dubbed_final_srt.write_text(
                "1\n00:00:01,000 --> 00:00:09,000\n第一段译文\n第一段有字幕\n",
                encoding="utf-8",
            )
            dubbed_vocals.write_bytes(b"fake-vocals")

            manifest = {
                "manifest_version": "v1",
                "job_id": f"segment_{segment_index:04d}",
                "input_media_path": str(segment_audio),
                "target_lang": target_lang,
                "paths": {
                    "source_srt": str(source_srt),
                    "translated_srt": str(translated_srt),
                    "dubbed_final_srt": str(dubbed_final_srt),
                    "dubbed_vocals": str(dubbed_vocals),
                    "source_bgm": None,
                    "dubbed_mix": None,
                },
                "stats": {
                    "total": 1,
                    "done": 1,
                    "failed": 0,
                    "manual_review": 0,
                },
                "segments": [
                    {
                        "id": "seg_0001",
                        "status": "done",
                    }
                ],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return job_dir

        def fake_build_full_timeline_vocals(*, results, output_wav: Path, source_audio: Path) -> Path:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"full-vocals")
            return output_wav

        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchtest"), patch.object(
            dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio
        ), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ), patch.object(
            dub_long_video, "detect_silence_endpoints", side_effect=fake_detect_silence_endpoints
        ), patch.object(
            dub_long_video, "cut_audio_segment", side_effect=fake_cut_audio_segment
        ), patch.object(
            dub_long_video, "collect_reusable_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "collect_latest_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "run_segment_job", side_effect=fake_run_segment_job
        ), patch.object(
            dub_long_video, "build_full_timeline_vocals", side_effect=fake_build_full_timeline_vocals
        ) as build_vocals_mock, patch.object(
            dub_long_video, "build_full_timeline_bgm", return_value=None
        ):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(self.input_srt),
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(run_calls, [1])
        self.assertEqual(build_vocals_mock.call_count, 1)

        batch_dir = self.out_dir / "longdub_batchtest"
        manifest = json.loads((batch_dir / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["segments_total"], 2)
        self.assertEqual(len(manifest["segments"]), 2)
        self.assertEqual(manifest["pipeline_version"], "v1")
        self.assertFalse(manifest["source_short_merge_enabled"])
        self.assertEqual(manifest["source_short_merge_threshold"], 15)
        self.assertEqual(manifest["source_short_merge_threshold_mode"], "seconds")
        self.assertTrue(manifest["grouped_synthesis"])
        self.assertTrue(manifest["force_fit_timing"])
        self.assertEqual(manifest["requested_time_ranges"], manifest["requested_ranges"])
        self.assertEqual(manifest["effective_time_ranges"], manifest["effective_ranges"])
        self.assertEqual(manifest["segments"][0]["summary"]["total"], 1)
        self.assertEqual(manifest["segments"][1]["summary"]["total"], 0)
        self.assertTrue((batch_dir / "final" / "source_full.srt").exists())
        self.assertTrue((batch_dir / "final" / "translated_full.srt").exists())
        self.assertTrue((batch_dir / "final" / "dubbed_final_full.srt").exists())


if __name__ == "__main__":
    unittest.main()
