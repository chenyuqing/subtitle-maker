from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
DUB_LONG_VIDEO_PATH = REPO_ROOT / "tools" / "dub_long_video.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_dub_long_video_module", DUB_LONG_VIDEO_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
dub_long_video = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = dub_long_video
sys.modules.setdefault(
    "torch",
    SimpleNamespace(
        float16="float16",
        bfloat16="bfloat16",
        float32="float32",
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
        mps=SimpleNamespace(empty_cache=lambda: None),
        cuda=SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None),
    ),
)
sys.modules.setdefault("ffmpeg", SimpleNamespace())
sys.modules.setdefault("openai", SimpleNamespace(OpenAI=object))
sys.modules.setdefault("librosa", SimpleNamespace())
sys.modules.setdefault("transformers", SimpleNamespace(AutoModelForCausalLM=object, AutoTokenizer=object))
sys.modules.setdefault("qwen_asr", SimpleNamespace(Qwen3ASRModel=object, Qwen3ForcedAligner=object))
sys.modules.setdefault(
    "qwen_asr.core.transformers_backend.processing_qwen3_asr",
    SimpleNamespace(Qwen3ASRProcessor=object),
)
sys.modules.setdefault("soundfile", SimpleNamespace())
MODULE_SPEC.loader.exec_module(dub_long_video)


class DubLongVideoTests(unittest.TestCase):
    """覆盖当前 long-video 主编排合同。"""

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

    def test_filter_segment_extra_args_removes_long_video_only_flags(self) -> None:
        """segment 子任务不应收到 long-video 专属字段。"""

        filtered = dub_long_video.filter_segment_extra_args(
            [
                "--dubbing-mode",
                "multi",
                "--speaker-ref-map-json",
                '[{"speaker_id":"Speaker 1","ref_audio_path":"/tmp/ref.wav"}]',
                "--grouped-synthesis",
                "false",
                "--tts-backend",
                "index-tts",
            ]
        )

        self.assertEqual(
            filtered,
            [
                "--grouped-synthesis",
                "false",
                "--tts-backend",
                "index-tts",
            ],
        )

    def test_clip_subtitles_for_segment_preserves_speaker_metadata(self) -> None:
        """切分局部字幕时应保留 speaker_id 等元数据。"""

        subtitles = [
            {"start": 10.0, "end": 12.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 12.0, "end": 14.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]

        clipped = dub_long_video.clip_subtitles_for_segment(
            subtitles=subtitles,
            segment_start_sec=11.0,
            segment_end_sec=13.0,
        )

        self.assertEqual(
            clipped,
            [
                {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
            ],
        )

    def test_normalize_input_subtitles_for_segments_preserves_speaker_metadata(self) -> None:
        """长视频分段前的时间轴规整不应丢失 speaker_id。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]

        normalized = dub_long_video.normalize_input_subtitles_for_segments(
            subtitles=subtitles,
            media_duration_sec=2.0,
        )

        self.assertEqual([item["speaker_id"] for item in normalized], ["Speaker 1", "Speaker 2"])

    def test_build_segment_speaker_metadata_from_subtitles_preserves_speaker_ids(self) -> None:
        """分段 sidecar 应保留每条字幕的 speaker_id。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]

        metadata = dub_long_video.build_segment_speaker_metadata_from_subtitles(subtitles)

        self.assertEqual([item["speaker_id"] for item in metadata], ["Speaker 1", "Speaker 2"])

    def test_resolve_translated_short_merge_policy_skips_resume(self) -> None:
        """resume 场景应关闭 translated merge，避免重复漂移。"""

        effective, reason = dub_long_video.resolve_translated_short_merge_policy(
            requested_enabled=True,
            tts_backend="index-tts",
            resume_batch_dir=Path("/tmp/existing-batch"),
        )

        self.assertFalse(effective)
        self.assertEqual(reason, "resume_skipped")

    def test_speaker_aware_merge_does_not_cross_speaker_boundaries(self) -> None:
        """speaker-aware 重构时，交替 speaker 不能跨 speaker 合并。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "世界", "speaker_id": "Speaker 2"},
            {"start": 2.0, "end": 3.0, "text": "再次你好", "speaker_id": "Speaker 1"},
        ]

        merged, merged_pairs, run_count = dub_long_video.maybe_merge_translated_input_subtitles_speaker_aware(
            subtitles=subtitles,
            translated_short_merge_enabled=True,
            translated_short_merge_threshold=10,
        )

        self.assertEqual(len(merged), 3)
        self.assertEqual(merged_pairs, 0)
        self.assertEqual(run_count, 3)
        self.assertEqual([str(item.get("speaker_id")) for item in merged], ["Speaker 1", "Speaker 2", "Speaker 1"])

    def test_speaker_aware_merge_merges_same_speaker_and_rebuilds_timestamps(self) -> None:
        """同 speaker 连续短句应被真实合并，且新行时间覆盖原区间。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句。", "speaker_id": "Speaker 1"},
        ]

        merged, merged_pairs, run_count = dub_long_video.maybe_merge_translated_input_subtitles_speaker_aware(
            subtitles=subtitles,
            translated_short_merge_enabled=True,
            translated_short_merge_threshold=10,
        )

        self.assertEqual(run_count, 1)
        self.assertEqual(merged_pairs, 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual(float(merged[0]["start"]), 0.0)
        self.assertEqual(float(merged[0]["end"]), 2.0)
        self.assertEqual(str(merged[0].get("speaker_id") or ""), "Speaker 1")

    def test_speaker_aware_merge_requires_speaker_id_in_every_row(self) -> None:
        """speaker-aware 重构下，缺失 speaker_id 必须直接失败。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句"},
        ]

        with self.assertRaisesRegex(RuntimeError, "requires speaker_id on every subtitle row"):
            dub_long_video.maybe_merge_translated_input_subtitles_speaker_aware(
                subtitles=subtitles,
                translated_short_merge_enabled=True,
                translated_short_merge_threshold=10,
            )

    def test_speaker_aware_merge_keeps_clean_text_without_speaker_prefix(self) -> None:
        """重构后文本保持纯正文，不拼回 Speaker 前缀，同时保留 speaker_id 元数据。"""

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "很高兴见到你。", "speaker_id": "Speaker 1"},
        ]

        merged, _, _ = dub_long_video.maybe_merge_translated_input_subtitles_speaker_aware(
            subtitles=subtitles,
            translated_short_merge_enabled=True,
            translated_short_merge_threshold=10,
        )

        self.assertEqual(len(merged), 1)
        merged_text = str(merged[0].get("text") or "")
        self.assertFalse(merged_text.startswith("Speaker 1:"))
        self.assertEqual(str(merged[0].get("speaker_id") or ""), "Speaker 1")

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
            dubbing_mode: str = "single",
            speaker_ref_map_json: str = "",
            speaker_metadata_path: Path | None = None,
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
                "segments": [{"id": "seg_0001", "status": "done"}],
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
        ), patch.object(
            dub_long_video, "build_full_timeline_mix", return_value=None
        ), patch.object(
            dub_long_video, "build_dubbed_video_two_step", return_value={"status": "skipped", "reason": "input_has_no_video_stream"}
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
        self.assertEqual(manifest["pipeline_version"], "auto-dubbing")
        self.assertEqual(manifest["dubbing_mode"], "single")
        self.assertEqual(manifest["segments"][0]["summary"]["total"], 1)
        self.assertEqual(manifest["segments"][1]["summary"]["total"], 0)

    def test_main_merges_translated_subtitles_once_per_segment_before_writing_input_srt(self) -> None:
        """translated merge 应只在初始编排阶段按 segment 执行一次。"""

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
            dubbing_mode: str = "single",
            speaker_ref_map_json: str = "",
            speaker_metadata_path: Path | None = None,
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
            dub_long_video, "build_full_timeline_vocals", return_value=self.out_dir / "dubbed_vocals_full.wav"
        ), patch.object(
            dub_long_video, "build_full_timeline_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_mix", return_value=None
        ), patch.object(
            dub_long_video, "concat_wav_files", side_effect=fake_concat_wav_files
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_dubbed_video_two_step", return_value={"status": "skipped", "reason": "input_has_no_video_stream"}
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
            "translated merge: status=applied requested=True effective=True reason=user "
            "before=3 after=1 merged_pairs=2 speaker_run_count=0 target=10s",
            stdout_buffer.getvalue(),
        )

    def test_main_multi_mode_legacy_backend_request_still_requires_complete_speaker_ref_map(self) -> None:
        """即便传旧 backend，请求也应按 index-tts 严格 speaker 映射校验。"""

        multi_srt = self.tmpdir / "multi.srt"
        multi_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nSpeaker 1: Hello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nSpeaker 2: World\n",
            encoding="utf-8",
        )
        speaker1_ref = self.tmpdir / "speaker1.wav"
        speaker1_ref.write_bytes(b"fake-ref")

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 4.0

        with patch.object(dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ):
            with self.assertRaisesRegex(RuntimeError, "index-tts strict speaker mapping missing reference audio for: Speaker 2"):
                dub_long_video.main(
                    [
                        "--input-media",
                        str(self.input_media),
                        "--input-srt",
                        str(multi_srt),
                        "--target-lang",
                        "Chinese",
                        "--out-dir",
                        str(self.out_dir),
                        "--dubbing-mode",
                        "multi",
                        "--tts-backend",
                        "index-tts",
                        "--speaker-ref-map-json",
                        json.dumps(
                            [{"speaker_id": "Speaker 1", "ref_audio_path": str(speaker1_ref)}],
                            ensure_ascii=False,
                        ),
                    ]
                )

    def test_main_index_tts_multi_without_speaker_map_allows_start(self) -> None:
        """index-tts 多人模式未传 speaker_ref_map 时，不应在 long-video 层被强制拦截。"""

        multi_srt = self.tmpdir / "multi_no_map_ok.srt"
        multi_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nSpeaker 1: Hello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nSpeaker 2: World\n",
            encoding="utf-8",
        )

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 4.0

        with patch.object(dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ), patch.object(
            dub_long_video, "detect_silence_endpoints", return_value=[]
        ), patch.object(
            dub_long_video, "cut_audio_segment", return_value=None
        ), patch.object(
            dub_long_video, "collect_reusable_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "collect_latest_jobs_by_segment", return_value={}
        ), patch.object(
            dub_long_video, "run_segment_job", side_effect=RuntimeError("stop_after_validation")
        ):
            with self.assertRaisesRegex(RuntimeError, "stop_after_validation"):
                dub_long_video.main(
                    [
                        "--input-media",
                        str(self.input_media),
                        "--input-srt",
                        str(multi_srt),
                        "--target-lang",
                        "Chinese",
                        "--out-dir",
                        str(self.out_dir),
                        "--dubbing-mode",
                        "multi",
                        "--tts-backend",
                        "index-tts",
                    ]
                )

    def test_main_index_tts_multi_with_speaker_map_requires_complete_mapping(self) -> None:
        """index-tts 多人模式传入 speaker_ref_map 后，应启用严格映射校验。"""

        multi_srt = self.tmpdir / "multi_index_strict.srt"
        multi_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nSpeaker 1: Hello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nSpeaker 2: World\n",
            encoding="utf-8",
        )
        speaker1_ref = self.tmpdir / "speaker1_only.wav"
        speaker1_ref.write_bytes(b"fake-ref")

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 4.0

        with patch.object(dub_long_video, "extract_source_audio", side_effect=fake_extract_source_audio), patch.object(
            dub_long_video, "ffprobe_duration", side_effect=fake_ffprobe_duration
        ):
            with self.assertRaisesRegex(RuntimeError, "index-tts strict speaker mapping missing reference audio for: Speaker 2"):
                dub_long_video.main(
                    [
                        "--input-media",
                        str(self.input_media),
                        "--input-srt",
                        str(multi_srt),
                        "--target-lang",
                        "Chinese",
                        "--out-dir",
                        str(self.out_dir),
                        "--dubbing-mode",
                        "multi",
                        "--tts-backend",
                        "index-tts",
                        "--speaker-ref-map-json",
                        json.dumps(
                            [{"speaker_id": "Speaker 1", "ref_audio_path": str(speaker1_ref)}],
                            ensure_ascii=False,
                        ),
                    ]
                )

    def test_main_multi_mode_accepts_sidecar_speaker_metadata_without_text_prefixes(self) -> None:
        """多人模式应优先读取 speaker sidecar，而不是强依赖字幕正文前缀。"""

        plain_srt = self.tmpdir / "plain.srt"
        plain_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nWorld\n",
            encoding="utf-8",
        )
        speaker_metadata_path = self.tmpdir / "_input_project.speakers.json"
        speaker_metadata_path.write_text(
            json.dumps(
                [
                    {"subtitle_index": 1, "speaker_id": "Speaker 1"},
                    {"subtitle_index": 2, "speaker_id": "Speaker 2"},
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        speaker1_ref = self.tmpdir / "speaker1.wav"
        speaker2_ref = self.tmpdir / "speaker2.wav"
        speaker1_ref.write_bytes(b"fake-ref-1")
        speaker2_ref.write_bytes(b"fake-ref-2")
        speaker_ref_map_json = json.dumps(
            [
                {"speaker_id": "Speaker 1", "ref_audio_path": str(speaker1_ref)},
                {"speaker_id": "Speaker 2", "ref_audio_path": str(speaker2_ref)},
            ],
            ensure_ascii=False,
        )

        seen_speaker_ids: list[list[str]] = []

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 4.0

        def fake_detect_silence_endpoints(*, source_audio: Path, noise_db: float, min_duration_sec: float) -> list[float]:
            return []

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(b"segment-audio")

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
            dubbing_mode: str = "single",
            speaker_ref_map_json: str = "",
            speaker_metadata_path: Path | None = None,
        ) -> Path:
            self.assertIsNotNone(speaker_metadata_path)
            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            source_srt = subtitles_dir / "source.srt"
            translated_srt = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"
            text = input_srt_path.read_text(encoding="utf-8") if input_srt_path is not None else ""
            source_srt.write_text(text, encoding="utf-8")
            translated_srt.write_text(text, encoding="utf-8")
            dubbed_final_srt.write_text(text, encoding="utf-8")
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
                "stats": {"total": 2, "done": 2, "failed": 0, "manual_review": 0},
                "segments": [{"id": "seg_0001", "status": "done"}, {"id": "seg_0002", "status": "done"}],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            seen_speaker_ids.append(
                [item["speaker_id"] for item in json.loads(speaker_metadata_path.read_text(encoding="utf-8"))]
            )
            return job_dir

        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchsidecar"), patch.object(
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
            dub_long_video, "concat_wav_files", return_value=None
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_vocals", return_value=self.out_dir / "dubbed_vocals_full.wav"
        ), patch.object(
            dub_long_video, "build_full_timeline_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_mix", return_value=None
        ), patch.object(
            dub_long_video, "build_dubbed_video_two_step", return_value={"status": "skipped", "reason": "input_has_no_video_stream"}
        ):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(plain_srt),
                    "--speaker-metadata-path",
                    str(speaker_metadata_path),
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--dubbing-mode",
                    "multi",
                    "--speaker-ref-map-json",
                    speaker_ref_map_json,
                    "--tts-backend",
                    "index-tts",
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen_speaker_ids, [["Speaker 1", "Speaker 2"]])

    def test_main_multi_mode_passes_speaker_ref_map_to_segment_job_and_manifest(self) -> None:
        """多人模式应把 speaker_ref_map 透传给 segment job，并写入 batch manifest。"""

        multi_srt = self.tmpdir / "multi_ok.srt"
        multi_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nSpeaker 1: Hello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nSpeaker 2: World\n",
            encoding="utf-8",
        )
        speaker1_ref = self.tmpdir / "speaker1.wav"
        speaker2_ref = self.tmpdir / "speaker2.wav"
        speaker1_ref.write_bytes(b"fake-ref-1")
        speaker2_ref.write_bytes(b"fake-ref-2")
        speaker_ref_map_json = json.dumps(
            [
                {"speaker_id": "Speaker 1", "ref_audio_path": str(speaker1_ref)},
                {"speaker_id": "Speaker 2", "ref_audio_path": str(speaker2_ref)},
            ],
            ensure_ascii=False,
        )

        seen_dubbing_modes: list[str] = []
        seen_ref_maps: list[str] = []
        seen_speaker_metadata: list[list[dict[str, object]]] = []

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 4.0

        def fake_detect_silence_endpoints(*, source_audio: Path, noise_db: float, min_duration_sec: float) -> list[float]:
            return []

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(b"segment-audio")

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
            dubbing_mode: str = "single",
            speaker_ref_map_json: str = "",
            speaker_metadata_path: Path | None = None,
        ) -> Path:
            seen_dubbing_modes.append(dubbing_mode)
            seen_ref_maps.append(speaker_ref_map_json)
            self.assertIsNotNone(speaker_metadata_path)
            seen_speaker_metadata.append(json.loads(speaker_metadata_path.read_text(encoding="utf-8")))

            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            source_srt = subtitles_dir / "source.srt"
            translated_srt = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"
            text = input_srt_path.read_text(encoding="utf-8") if input_srt_path is not None else ""
            source_srt.write_text(text, encoding="utf-8")
            translated_srt.write_text(text, encoding="utf-8")
            dubbed_final_srt.write_text(text, encoding="utf-8")
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
                "stats": {"total": 2, "done": 2, "failed": 0, "manual_review": 0},
                "segments": [{"id": "seg_0001", "status": "done"}, {"id": "seg_0002", "status": "done"}],
                "manual_review": [],
            }
            (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return job_dir

        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchmulti"), patch.object(
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
            dub_long_video, "concat_wav_files", return_value=None
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_vocals", return_value=self.out_dir / "dubbed_vocals_full.wav"
        ), patch.object(
            dub_long_video, "build_full_timeline_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_mix", return_value=None
        ), patch.object(
            dub_long_video, "build_dubbed_video_two_step", return_value={"status": "skipped", "reason": "input_has_no_video_stream"}
        ):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(multi_srt),
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--dubbing-mode",
                    "multi",
                    "--speaker-ref-map-json",
                    speaker_ref_map_json,
                    "--tts-backend",
                    "index-tts",
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen_dubbing_modes, ["multi"])
        self.assertEqual(seen_ref_maps, [speaker_ref_map_json])
        self.assertEqual(
            [item["speaker_id"] for item in seen_speaker_metadata[0]],
            ["Speaker 1", "Speaker 2"],
        )

        batch_dir = self.out_dir / "longdub_batchmulti"
        manifest = json.loads((batch_dir / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pipeline_version"], "auto-dubbing")
        self.assertEqual(manifest["dubbing_mode"], "multi")
        self.assertEqual(manifest["tts_backend"], "index-tts")
        self.assertEqual(
            manifest["speaker_ref_map"],
            [
                {"speaker_id": "Speaker 1", "ref_audio_path": str(speaker1_ref.resolve())},
                {"speaker_id": "Speaker 2", "ref_audio_path": str(speaker2_ref.resolve())},
            ],
        )

    def test_main_source_input_snapshot_is_rewritten_to_rebalanced_source_srt(self) -> None:
        """开启 source short merge 后，段级 `_input_segment.srt` 应同步成真实生效的重构结果。"""

        source_srt = self.tmpdir / "source_merge.srt"
        source_srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nFirst short sentence.\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nSecond short sentence.\n\n"
            "3\n00:00:04,000 --> 00:00:06,000\nThird line closes cleanly.\n",
            encoding="utf-8",
        )

        def fake_extract_source_audio(input_media: Path, output_wav: Path) -> None:
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            output_wav.write_bytes(b"fake-source-audio")

        def fake_ffprobe_duration(path: Path) -> float:
            return 6.0

        def fake_detect_silence_endpoints(*, source_audio: Path, noise_db: float, min_duration_sec: float) -> list[float]:
            return []

        def fake_cut_audio_segment(*, source_audio: Path, output_audio: Path, start_sec: float, end_sec: float) -> None:
            output_audio.parent.mkdir(parents=True, exist_ok=True)
            output_audio.write_bytes(b"segment-audio")

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
            dubbing_mode: str = "single",
            speaker_ref_map_json: str = "",
            speaker_metadata_path: Path | None = None,
        ) -> Path:
            self.assertIsNotNone(input_srt_path)
            job_dir = resume_job_dir or (segment_jobs_dir / f"segment_{segment_index:04d}")
            subtitles_dir = job_dir / "subtitles"
            subtitles_dir.mkdir(parents=True, exist_ok=True)

            merged_subtitles = [
                {
                    "start": 0.0,
                    "end": 6.0,
                    "text": "First short sentence. Second short sentence. Third line closes cleanly.",
                }
            ]
            source_output_srt = subtitles_dir / "source.srt"
            translated_srt = subtitles_dir / "translated.srt"
            dubbed_final_srt = subtitles_dir / "dubbed_final.srt"
            dubbed_vocals = job_dir / "dubbed_vocals.wav"
            merged_text = dub_long_video.format_srt(merged_subtitles)
            source_output_srt.write_text(merged_text, encoding="utf-8")
            translated_srt.write_text(merged_text, encoding="utf-8")
            dubbed_final_srt.write_text(merged_text, encoding="utf-8")
            dubbed_vocals.write_bytes(b"fake-vocals")

            manifest = {
                "manifest_version": "v1",
                "job_id": f"segment_{segment_index:04d}",
                "input_media_path": str(segment_audio),
                "target_lang": target_lang,
                "paths": {
                    "source_srt": str(source_output_srt),
                    "translated_srt": str(translated_srt),
                    "dubbed_final_srt": str(dubbed_final_srt),
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

        with patch.object(dub_long_video, "build_readable_batch_id", return_value="batchsync"), patch.object(
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
            dub_long_video, "concat_wav_files", return_value=None
        ), patch.object(
            dub_long_video, "mix_vocals_with_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_vocals", return_value=self.out_dir / "dubbed_vocals_full.wav"
        ), patch.object(
            dub_long_video, "build_full_timeline_bgm", return_value=None
        ), patch.object(
            dub_long_video, "build_full_timeline_mix", return_value=None
        ), patch.object(
            dub_long_video, "build_dubbed_video_two_step", return_value={"status": "skipped", "reason": "input_has_no_video_stream"}
        ):
            code = dub_long_video.main(
                [
                    "--input-media",
                    str(self.input_media),
                    "--input-srt",
                    str(source_srt),
                    "--target-lang",
                    "Chinese",
                    "--out-dir",
                    str(self.out_dir),
                    "--segment-minutes",
                    "0.2",
                    "--min-segment-minutes",
                    "0.1",
                    "--source-short-merge-enabled",
                    "true",
                    "--source-short-merge-threshold",
                    "15",
                ]
            )

        self.assertEqual(code, 0)
        snapshot_srt = self.out_dir / "longdub_batchsync" / "segment_jobs" / "segment_0001" / "subtitles" / "_input_segment.srt"
        snapshot_items = dub_long_video.parse_srt(snapshot_srt.read_text(encoding="utf-8"))
        self.assertEqual(len(snapshot_items), 1)
        self.assertEqual(
            snapshot_items[0]["text"],
            "First short sentence. Second short sentence. Third line closes cleanly.",
        )
        self.assertAlmostEqual(float(snapshot_items[0]["start"]), 0.0, places=3)
        self.assertAlmostEqual(float(snapshot_items[0]["end"]), 6.0, places=3)


if __name__ == "__main__":
    unittest.main()
