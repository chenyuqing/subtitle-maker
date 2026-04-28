from __future__ import annotations

import io
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_main_merges_translated_subtitles_once_per_segment_before_writing_input_srt(self) -> None:
        """translated merge 应只在初始编排阶段按 segment 执行一次，并写入分段输入字幕。"""

        translated_srt = self.tmpdir / "translated_manual.srt"
        translated_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n第一句\n\n"
            "2\n00:00:02,000 --> 00:00:05,000\n第二句\n\n"
            "3\n00:00:05,000 --> 00:00:09,000\n第三句。\n",
            encoding="utf-8",
        )

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 12.0

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(f"{start_sec:.3f}-{end_sec:.3f}".encode("utf-8"))

        seen_segment_texts: list[list[str]] = []

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
            self.assertEqual(input_srt_kind, "translated")
            self.assertIsNotNone(input_srt_path)
            input_srt_text = input_srt_path.read_text(encoding="utf-8")
            clipped = dub_long_video.parse_srt(input_srt_text)
            seen_segment_texts.append([str(item.get("text") or "") for item in clipped])

            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)
            source_srt = subtitles_dir / "source.srt"
            translated_out = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"
            # 这里保持 source/translated 行数一致，模拟真实批处理产物，避免双语合并阶段被行数保护拦下。
            source_srt.write_text(input_srt_text, encoding="utf-8")
            translated_out.write_text(input_srt_text, encoding="utf-8")
            dubbed_final_srt.write_text(input_srt_text, encoding="utf-8")
            dubbed_vocals.write_bytes(b"fake-vocals")
            manifest = {
                "manifest_version": "v1",
                "job_id": f"segment_{segment_index:04d}",
                "input_media_path": str(segment_audio),
                "target_lang": target_lang,
                "translated_short_merge_enabled": True,
                "translated_short_merge_threshold": 10,
                "paths": {
                    "source_srt": str(source_srt),
                    "translated_srt": str(translated_out),
                    "dubbed_final_srt": str(dubbed_final_srt),
                    "dubbed_vocals": str(dubbed_vocals),
                    "source_bgm": None,
                    "dubbed_mix": None,
                },
                "stats": {"total": len(clipped), "done": len(clipped), "failed": 0, "manual_review": 0},
                "segments": [{"id": f"seg_{idx + 1:04d}", "status": "done"} for idx in range(len(clipped))],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return job_dir

        def fake_concat_wav_files(inputs: list[Path], output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"concat-audio")

        stdout_buffer = io.StringIO()
        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchmerge"), patch.object(
            dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio
        ), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ), patch.object(
            dub_long_video, "detect_silence_endpoints", return_value=[]
        ), patch.object(
            dub_long_video, "cut_audio_segment", side_effect=fake_cut_audio_segment
        ), patch.object(
            dub_long_video, "collect_reusable_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "collect_latest_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "run_segment_job", side_effect=fake_run_segment_job
        ), patch.object(
            dub_long_video, "concat_wav_files", side_effect=fake_concat_wav_files
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), redirect_stdout(stdout_buffer):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(translated_srt),
                    "--input-srt-kind",
                    "translated",
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                    "--translated-short-merge-enabled",
                    "true",
                    "--translated-short-merge-threshold",
                    "10",
                    "--grouped-synthesis",
                    "false",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen_segment_texts, [["第一句第二句第三句。"]])
        self.assertIn(
            "translated merge: status=applied requested=True effective=True reason=user before=3 after=1 merged_pairs=2 target=10s",
            stdout_buffer.getvalue(),
        )

        batch_dir = self.out_dir / "longdub_batchmerge"
        manifest = json.loads((batch_dir / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold"], 10)
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")

    def test_main_forces_translated_merge_for_omnivoice_even_when_user_flag_disabled(self) -> None:
        """OmniVoice 链路即使未请求 translated merge，也应在初始编排阶段强制并句。"""

        translated_srt = self.tmpdir / "translated_omnivoice.srt"
        translated_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n第一句\n\n"
            "2\n00:00:02,000 --> 00:00:05,000\n第二句\n\n"
            "3\n00:00:05,000 --> 00:00:09,000\n第三句。\n",
            encoding="utf-8",
        )

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 12.0

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(f"{start_sec:.3f}-{end_sec:.3f}".encode("utf-8"))

        seen_segment_texts: list[list[str]] = []

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
            self.assertEqual(input_srt_kind, "translated")
            self.assertIn("--tts-backend", extra_args)
            self.assertIn("omnivoice", extra_args)
            self.assertNotIn("--translated-short-merge-enabled", extra_args)
            self.assertIsNotNone(input_srt_path)
            input_srt_text = input_srt_path.read_text(encoding="utf-8")
            clipped = dub_long_video.parse_srt(input_srt_text)
            seen_segment_texts.append([str(item.get("text") or "") for item in clipped])

            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            source_srt = subtitles_dir / "source.srt"
            translated_out = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"
            source_srt.write_text(input_srt_text, encoding="utf-8")
            translated_out.write_text(input_srt_text, encoding="utf-8")
            dubbed_final_srt.write_text(input_srt_text, encoding="utf-8")
            dubbed_vocals.write_bytes(b"fake-vocals")
            manifest = {
                "manifest_version": "v1",
                "job_id": f"segment_{segment_index:04d}",
                "input_media_path": str(segment_audio),
                "target_lang": target_lang,
                "translated_short_merge_enabled": False,
                "translated_short_merge_threshold": 15,
                "paths": {
                    "source_srt": str(source_srt),
                    "translated_srt": str(translated_out),
                    "dubbed_final_srt": str(dubbed_final_srt),
                    "dubbed_vocals": str(dubbed_vocals),
                    "source_bgm": None,
                    "dubbed_mix": None,
                },
                "stats": {"total": len(clipped), "done": len(clipped), "failed": 0, "manual_review": 0},
                "segments": [{"id": f"seg_{idx + 1:04d}", "status": "done"} for idx in range(len(clipped))],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return job_dir

        def fake_concat_wav_files(inputs: list[Path], output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"concat-audio")

        stdout_buffer = io.StringIO()
        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchomnimerge"), patch.object(
            dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio
        ), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ), patch.object(
            dub_long_video, "detect_silence_endpoints", return_value=[]
        ), patch.object(
            dub_long_video, "cut_audio_segment", side_effect=fake_cut_audio_segment
        ), patch.object(
            dub_long_video, "collect_reusable_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "collect_latest_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "run_segment_job", side_effect=fake_run_segment_job
        ), patch.object(
            dub_long_video, "concat_wav_files", side_effect=fake_concat_wav_files
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), redirect_stdout(stdout_buffer):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(translated_srt),
                    "--input-srt-kind",
                    "translated",
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                    "--grouped-synthesis",
                    "false",
                    "--tts-backend",
                    "omnivoice",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen_segment_texts, [["第一句第二句第三句。"]])
        self.assertIn(
            "translated merge: status=applied requested=False effective=True reason=omnivoice_policy before=3 after=1 merged_pairs=2 target=15s",
            stdout_buffer.getvalue(),
        )

        batch_dir = self.out_dir / "longdub_batchomnimerge"
        manifest = json.loads((batch_dir / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["translated_short_merge_enabled"])
        self.assertEqual(manifest["translated_short_merge_threshold"], 15)
        self.assertEqual(manifest["translated_short_merge_threshold_mode"], "seconds")

    def test_resolve_translated_short_merge_policy_skips_resume_even_for_omnivoice(self) -> None:
        """resume 场景应跳过 translated merge，避免再次漂移分段句边界。"""

        effective, reason = dub_long_video.resolve_translated_short_merge_policy(
            requested_enabled=False,
            tts_backend="omnivoice",
            resume_batch_dir=Path("/tmp/existing-batch"),
        )

        self.assertFalse(effective)
        self.assertEqual(reason, "resume_skipped")

    def test_main_merge_outputs_prefers_canonical_segment_subtitles_over_stale_manifest_paths(self) -> None:
        """任务自然结束时，最终 merge 必须优先使用 segment/subtitles 下的新字幕。"""

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 10.0

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(f"{start_sec:.3f}-{end_sec:.3f}".encode("utf-8"))

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
            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            source_srt = subtitles_dir / "source.srt"
            translated_srt = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            stale_translated_srt = job_dir / "translated_stale.srt"
            stale_dubbed_final_srt = job_dir / "dubbed_final_stale.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"

            source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
            translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（新）\n", encoding="utf-8")
            dubbed_final_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（新）\nHello\n", encoding="utf-8")
            stale_translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\n", encoding="utf-8")
            stale_dubbed_final_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好（旧）\nHello\n", encoding="utf-8")
            dubbed_vocals.write_bytes(b"fake-vocals")

            manifest = {
                "manifest_version": "v1",
                "job_id": f"segment_{segment_index:04d}",
                "input_media_path": str(segment_audio),
                "target_lang": target_lang,
                "paths": {
                    "source_srt": str(source_srt),
                    "translated_srt": str(stale_translated_srt),
                    "dubbed_final_srt": str(stale_dubbed_final_srt),
                    "dubbed_vocals": str(dubbed_vocals),
                    "source_bgm": None,
                    "dubbed_mix": None,
                },
                "stats": {"total": 1, "done": 1, "failed": 0, "manual_review": 0},
                "segments": [{"id": "seg_0001", "status": "done"}],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return job_dir

        def fake_concat_wav_files(inputs: list[Path], output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"concat-audio")

        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchstale"), patch.object(
            dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio
        ), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ), patch.object(
            dub_long_video, "detect_silence_endpoints", return_value=[]
        ), patch.object(
            dub_long_video, "cut_audio_segment", side_effect=fake_cut_audio_segment
        ), patch.object(
            dub_long_video, "collect_reusable_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "collect_latest_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "run_segment_job", side_effect=fake_run_segment_job
        ), patch.object(
            dub_long_video, "concat_wav_files", side_effect=fake_concat_wav_files
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
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
        batch_dir = self.out_dir / "longdub_batchstale"
        translated_full_srt = batch_dir / "final" / "translated_full.srt"
        dubbed_final_full_srt = batch_dir / "final" / "dubbed_final_full.srt"
        self.assertIn("你好（新）", translated_full_srt.read_text(encoding="utf-8"))
        self.assertNotIn("你好（旧）", translated_full_srt.read_text(encoding="utf-8"))
        self.assertIn("你好（新）", dubbed_final_full_srt.read_text(encoding="utf-8"))
        self.assertNotIn("你好（旧）", dubbed_final_full_srt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
