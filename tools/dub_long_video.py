#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.core.ffmpeg import (
    run_cmd as run_cmd_impl,
    run_cmd_checked as run_cmd_checked_impl,
    run_cmd_stream as run_cmd_stream_impl,
)
from subtitle_maker.domains.media import (
    build_full_timeline_bgm as build_full_timeline_bgm_impl,
    build_full_timeline_mix as build_full_timeline_mix_impl,
    build_full_timeline_vocals as build_full_timeline_vocals_impl,
    choose_boundaries as choose_boundaries_impl,
    concat_wav_files as concat_wav_files_impl,
    cut_audio_segment as cut_audio_segment_impl,
    detect_silence_endpoints as detect_silence_endpoints_impl,
    detect_speech_time_ranges as detect_speech_time_ranges_impl,
    extract_source_audio as extract_source_audio_impl,
    ffprobe_duration as ffprobe_duration_impl,
    load_mono_audio as load_mono_audio_impl,
    map_global_ranges_to_segment as map_global_ranges_to_segment_impl,
    merge_bilingual_srt_files as merge_bilingual_srt_files_impl,
    merge_srt_files as merge_srt_files_impl,
    mix_vocals_with_bgm as mix_vocals_with_bgm_impl,
    resample_mono_audio as resample_mono_audio_impl,
)
from subtitle_maker.manifests import (
    BatchReplayOptions,
    build_batch_manifest,
    build_skipped_segment_manifest,
    load_segment_manifest,
    write_manifest_json,
)

# Exit-code contract from tools/dub_pipeline.py
SEGMENT_EXIT_OK = 0
SEGMENT_EXIT_FAILED = 1
SEGMENT_EXIT_OK_WITH_MANUAL_REVIEW = 2
DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC = 15


def iso_now() -> str:
    return datetime.utcnow().isoformat()


def build_readable_batch_id(*, out_root: Path, time_tag: str) -> str:
    # 批次名仅使用时间戳，不追加 -001/-002 后缀。
    # 目录隔离由上层 web_<task_id> 保证（每次上传一个新 task 目录）。
    return time_tag


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """兼容旧入口：执行命令并返回退出码、stdout、stderr。"""
    return run_cmd_impl(cmd, cwd=cwd)


def run_cmd_checked(cmd: List[str], cwd: Optional[Path] = None) -> None:
    """兼容旧入口：执行命令，失败时抛出保留 stdout/stderr 的异常。"""
    return run_cmd_checked_impl(cmd, cwd=cwd)


def run_cmd_stream(cmd: List[str], cwd: Optional[Path] = None) -> int:
    """兼容旧入口：流式执行命令并把输出打印到终端。"""
    return run_cmd_stream_impl(cmd, cwd=cwd)


def read_bool(value: str) -> bool:
    # 统一解析布尔字符串参数。
    lowered = (value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def ffprobe_duration(path: Path) -> float:
    """兼容旧入口：通过 ffprobe 获取媒体时长。"""
    return ffprobe_duration_impl(path)


def extract_source_audio(input_media: Path, output_wav: Path) -> None:
    """兼容旧入口：从输入媒体抽取单声道 wav。"""
    return extract_source_audio_impl(input_media, output_wav)


def detect_silence_endpoints(
    source_audio: Path,
    *,
    noise_db: float,
    min_duration_sec: float,
) -> List[float]:
    """兼容旧入口：通过 ffmpeg silencedetect 获取静音结束点。"""
    return detect_silence_endpoints_impl(
        source_audio,
        noise_db=noise_db,
        min_duration_sec=min_duration_sec,
    )


def choose_boundaries(
    *,
    total_duration_sec: float,
    silence_ends: List[float],
    target_segment_sec: float,
    min_segment_sec: float,
    search_window_sec: float,
) -> List[float]:
    """兼容旧入口：围绕目标切段时长挑选更自然的边界。"""
    return choose_boundaries_impl(
        total_duration_sec=total_duration_sec,
        silence_ends=silence_ends,
        target_segment_sec=target_segment_sec,
        min_segment_sec=min_segment_sec,
        search_window_sec=search_window_sec,
    )


def normalize_time_ranges(ranges: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    # 合并重叠区间，避免重复处理。
    if not ranges:
        return []
    items = sorted(
        [(max(0.0, float(start_sec)), max(0.0, float(end_sec))) for start_sec, end_sec in ranges if end_sec > start_sec],
        key=lambda item: item[0],
    )
    merged: List[Tuple[float, float]] = []
    for start_sec, end_sec in items:
        if not merged:
            merged.append((start_sec, end_sec))
            continue
        prev_start, prev_end = merged[-1]
        if start_sec <= prev_end + 1e-6:
            merged[-1] = (prev_start, max(prev_end, end_sec))
        else:
            merged.append((start_sec, end_sec))
    return merged


def parse_time_ranges_json(raw: Optional[str]) -> List[Tuple[float, float]]:
    # 解析手动传入的时间区间 JSON。
    if not raw or not str(raw).strip():
        return []
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"invalid --time-ranges-json: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("--time-ranges-json must be a list")
    items: List[Tuple[float, float]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        start_sec = float(entry.get("start_sec", entry.get("start", 0.0)) or 0.0)
        end_sec = float(entry.get("end_sec", entry.get("end", start_sec)) or start_sec)
        if end_sec > start_sec:
            items.append((start_sec, end_sec))
    return normalize_time_ranges(items)


def detect_speech_time_ranges(
    *,
    source_audio: Path,
    min_silence_sec: float,
    min_speech_sec: float,
    energy_ratio: float = 0.16,
) -> List[Tuple[float, float]]:
    """兼容旧入口：基于短时能量检测语音活跃区间。"""
    return detect_speech_time_ranges_impl(
        source_audio=source_audio,
        min_silence_sec=min_silence_sec,
        min_speech_sec=min_speech_sec,
        energy_ratio=energy_ratio,
    )


def map_global_ranges_to_segment(
    *,
    global_ranges: List[Tuple[float, float]],
    segment_start_sec: float,
    segment_end_sec: float,
) -> List[Tuple[float, float]]:
    """兼容旧入口：把全局时间轴区间映射到分段局部时间轴。"""
    return map_global_ranges_to_segment_impl(
        global_ranges=global_ranges,
        segment_start_sec=segment_start_sec,
        segment_end_sec=segment_end_sec,
    )


def cut_audio_segment(
    *,
    source_audio: Path,
    output_audio: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    """兼容旧入口：按起止时间裁出单个音频分段。"""
    return cut_audio_segment_impl(
        source_audio=source_audio,
        output_audio=output_audio,
        start_sec=start_sec,
        end_sec=end_sec,
    )


def list_job_dirs(path: Path) -> List[Path]:
    if not path.exists():
        return []
    return sorted([item for item in path.iterdir() if item.is_dir()], key=lambda item: item.name)


def resolve_output_path(path_text: Optional[str]) -> Optional[Path]:
    if not path_text:
        return None
    raw = Path(path_text).expanduser()
    if raw.is_absolute():
        return raw
    return (REPO_ROOT / raw).resolve()


def concat_wav_files(inputs: List[Path], output_wav: Path) -> None:
    """兼容旧入口：拼接多个 wav 文件。"""
    return concat_wav_files_impl(inputs, output_wav, sample_rate=44100, error_on_empty=True)


def mix_vocals_with_bgm(*, vocals_wav: Path, bgm_wav: Path, output_wav: Path) -> None:
    """兼容旧入口：长视频全时轴场景的固定采样率混音封装。"""
    return mix_vocals_with_bgm_impl(vocals_wav=vocals_wav, bgm_wav=bgm_wav, output_wav=output_wav)


def _load_mono_audio(path: Path) -> Tuple[np.ndarray, int]:
    """兼容旧入口：读取音频并统一为单声道 float32。"""
    return load_mono_audio_impl(path)


def _resample_mono_audio(wav: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    """兼容旧入口：线性插值重采样单声道音频。"""
    return resample_mono_audio_impl(wav, source_sr, target_sr)


def build_full_timeline_vocals(
    *,
    results: List["SegmentResult"],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """兼容旧入口：生成全时轴 vocals。"""
    return build_full_timeline_vocals_impl(results=results, output_wav=output_wav, source_audio=source_audio)


def build_full_timeline_mix(
    *,
    results: List["SegmentResult"],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """兼容旧入口：生成全时轴 mix。"""
    return build_full_timeline_mix_impl(results=results, output_wav=output_wav, source_audio=source_audio)


def build_full_timeline_bgm(
    *,
    results: List["SegmentResult"],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """兼容旧入口：生成全时轴 bgm。"""
    return build_full_timeline_bgm_impl(results=results, output_wav=output_wav, source_audio=source_audio)


def merge_srt_files(
    *,
    inputs: List[Tuple[Path, float]],
    output_srt: Path,
) -> None:
    """兼容旧入口：把多段 SRT 按全局时间轴偏移拼接为完整字幕。"""
    return merge_srt_files_impl(inputs=inputs, output_srt=output_srt)


def merge_bilingual_srt_files(
    *,
    translated_inputs: List[Tuple[Path, float]],
    source_inputs: List[Tuple[Path, float]],
    output_srt: Path,
    translated_first: bool = True,
) -> None:
    """兼容旧入口：把原文和译文双轨字幕拼接为完整双语字幕。"""
    return merge_bilingual_srt_files_impl(
        translated_inputs=translated_inputs,
        source_inputs=source_inputs,
        output_srt=output_srt,
        translated_first=translated_first,
    )


@dataclass
class SegmentResult:
    index: int
    start_sec: float
    end_sec: float
    segment_audio: Path
    job_dir: Path
    manifest: Dict[str, Any]


def write_skipped_segment_manifest(
    *,
    segment_index: int,
    segment_audio: Path,
    job_dir: Path,
    target_lang: str,
    reason: str,
) -> Dict[str, Any]:
    # 当上传字幕只覆盖部分视频时，某些分段可能裁不出任何字幕。
    # 这类分段不应再送进 dub_pipeline，否则会因空 SRT 直接报 E-ASR-001。
    if job_dir.exists():
        shutil.rmtree(job_dir)
    (job_dir / "subtitles").mkdir(parents=True, exist_ok=True)
    manifest = build_skipped_segment_manifest(
        segment_index=segment_index,
        segment_audio=segment_audio,
        target_lang=target_lang,
        reason=reason,
        created_at=iso_now(),
    )
    return write_manifest_json(job_dir / "manifest.json", manifest)


def run_segment_job(
    *,
    segment_index: int,
    segment_audio: Path,
    target_lang: str,
    segment_jobs_dir: Path,
    shared_ref: Optional[Path],
    single_speaker_ref_seconds: float,
    api_key: Optional[str],
    extra_args: List[str],
    segment_time_ranges: Optional[List[Tuple[float, float]]] = None,
    input_srt_path: Optional[Path] = None,
    input_srt_kind: str = "source",
    resume_job_dir: Optional[Path] = None,
) -> Path:
    before = {item.name for item in list_job_dirs(segment_jobs_dir)}

    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "dub_pipeline.py"),
        "--input-media",
        str(segment_audio),
        "--target-lang",
        target_lang,
        "--out-dir",
        str(segment_jobs_dir),
    ]
    if resume_job_dir is not None:
        cmd.extend(["--resume-job-dir", str(resume_job_dir)])
    if shared_ref is not None:
        cmd.extend(["--single-speaker-ref", str(shared_ref)])
    else:
        cmd.extend(["--single-speaker-ref-seconds", str(single_speaker_ref_seconds)])
    if api_key:
        cmd.extend(["--api-key", api_key])
    if segment_time_ranges is not None:
        payload = [
            {"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
            for start_sec, end_sec in segment_time_ranges
        ]
        cmd.extend(["--time-ranges-json", json.dumps(payload, ensure_ascii=False)])
    if input_srt_path is not None:
        cmd.extend(["--input-srt", str(input_srt_path)])
        cmd.extend(["--input-srt-kind", (input_srt_kind or "source")])
    # 性能优化：分段阶段默认不导出 mix，避免“每段混音 + 最终再拼接”重复开销。
    if "--export-mix" not in extra_args:
        cmd.extend(["--export-mix", "false"])
    if extra_args:
        cmd.extend(extra_args)

    is_real_resume = bool(
        resume_job_dir is not None
        and resume_job_dir.exists()
        and (resume_job_dir / "manifest.json").exists()
    )
    if is_real_resume:
        print(f"\n===== Segment {segment_index:02d} resume in-place: {resume_job_dir.name} =====")
    else:
        print(f"\n===== Segment {segment_index:02d} start =====")
    code = run_cmd_stream(cmd, cwd=REPO_ROOT)
    if code not in (SEGMENT_EXIT_OK, SEGMENT_EXIT_OK_WITH_MANUAL_REVIEW):
        raise RuntimeError(f"command failed ({code}): {' '.join(cmd)}")
    if code == SEGMENT_EXIT_OK_WITH_MANUAL_REVIEW:
        print(f"===== Segment {segment_index:02d} done with manual_review =====\n")
    else:
        print(f"===== Segment {segment_index:02d} done =====\n")

    if resume_job_dir is not None:
        return resume_job_dir
    after = list_job_dirs(segment_jobs_dir)
    new_dirs = [item for item in after if item.name not in before]
    if not new_dirs:
        raise RuntimeError(f"cannot detect job directory for segment {segment_index}")
    return max(new_dirs, key=lambda item: item.stat().st_mtime)


def list_segment_audio_files(segments_dir: Path) -> List[Path]:
    files = sorted(segments_dir.glob("segment_*.wav"), key=lambda item: item.name)
    if not files:
        raise RuntimeError(f"no segment audio files found in: {segments_dir}")
    return files


def build_segments_from_existing_files(segments_dir: Path) -> List[Tuple[int, float, float, Path]]:
    segments: List[Tuple[int, float, float, Path]] = []
    cursor = 0.0
    files = list_segment_audio_files(segments_dir)
    for index, file_path in enumerate(files, start=1):
        duration = ffprobe_duration(file_path)
        start_sec = cursor
        end_sec = cursor + duration
        segments.append((index, start_sec, end_sec, file_path))
        cursor = end_sec
    return segments


def _manifest_output_exists(path_text: Optional[str]) -> bool:
    path = resolve_output_path(path_text)
    return bool(path and path.exists())


def is_segment_job_reusable(manifest: Dict[str, Any]) -> bool:
    stats = manifest.get("stats", {})
    total = int(stats.get("total", 0) or 0)
    done = int(stats.get("done", 0) or 0)
    failed = int(stats.get("failed", 0) or 0)
    paths = manifest.get("paths", {})
    required_ok = (
        _manifest_output_exists(paths.get("translated_srt"))
        and _manifest_output_exists(paths.get("dubbed_final_srt"))
        and _manifest_output_exists(paths.get("dubbed_vocals"))
    )
    if total > 0:
        return done >= total and failed == 0 and required_ok
    return required_ok


def collect_reusable_jobs_by_segment(
    *,
    segment_jobs_dir: Path,
    segments: List[Tuple[int, float, float, Path]],
) -> Dict[int, Tuple[Path, Dict[str, Any]]]:
    segment_path_to_index: Dict[Path, int] = {}
    for seg_index, _, _, seg_audio in segments:
        segment_path_to_index[seg_audio.resolve()] = seg_index

    candidates: Dict[int, Tuple[Path, Dict[str, Any], float]] = {}
    for job_dir in list_job_dirs(segment_jobs_dir):
        manifest_path = job_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest_view = load_segment_manifest(manifest_path)
            manifest = manifest_view.raw
        except Exception:
            continue
        input_media_path = manifest_view.input_media_path
        if not input_media_path:
            continue
        try:
            segment_audio = Path(input_media_path).expanduser().resolve()
        except Exception:
            continue
        seg_index = segment_path_to_index.get(segment_audio)
        if seg_index is None:
            continue
        if not is_segment_job_reusable(manifest):
            continue
        mtime = manifest_path.stat().st_mtime
        old = candidates.get(seg_index)
        if old is None or mtime > old[2]:
            candidates[seg_index] = (job_dir, manifest, mtime)

    output: Dict[int, Tuple[Path, Dict[str, Any]]] = {}
    for seg_index, (job_dir, manifest, _) in candidates.items():
        output[seg_index] = (job_dir, manifest)
    return output


def collect_latest_jobs_by_segment(
    *,
    segment_jobs_dir: Path,
    segments: List[Tuple[int, float, float, Path]],
) -> Dict[int, Path]:
    segment_path_to_index: Dict[Path, int] = {}
    duration_to_index: Dict[str, int] = {}
    for seg_index, start_sec, end_sec, seg_audio in segments:
        segment_path_to_index[seg_audio.resolve()] = seg_index
        duration_key = f"{(end_sec - start_sec):.3f}"
        duration_to_index[duration_key] = seg_index

    candidates: Dict[int, Tuple[Path, float]] = {}
    for job_dir in list_job_dirs(segment_jobs_dir):
        manifest_path = job_dir / "manifest.json"
        seg_index: Optional[int] = None

        if manifest_path.exists():
            try:
                manifest = load_segment_manifest(manifest_path)
                input_media_path = manifest.input_media_path
                if input_media_path:
                    seg_path = Path(input_media_path).expanduser().resolve()
                    seg_index = segment_path_to_index.get(seg_path)
            except Exception:
                seg_index = None

        if seg_index is None:
            stem_audio = job_dir / "stems" / "source_audio.wav"
            if stem_audio.exists():
                try:
                    stem_duration = ffprobe_duration(stem_audio)
                    seg_index = duration_to_index.get(f"{stem_duration:.3f}")
                except Exception:
                    seg_index = None

        if seg_index is None:
            continue

        marker = manifest_path if manifest_path.exists() else job_dir
        mtime = marker.stat().st_mtime
        old = candidates.get(seg_index)
        if old is None or mtime > old[1]:
            candidates[seg_index] = (job_dir, mtime)

    return {seg_index: pair[0] for seg_index, pair in candidates.items()}


def parse_args(argv: Optional[List[str]] = None) -> Tuple[argparse.Namespace, List[str]]:
    parser = argparse.ArgumentParser(
        description="Long-video batch dubbing orchestrator (split -> run dub_pipeline per segment -> merge)."
    )
    parser.add_argument("--input-media", required=True, help="Input media path")
    parser.add_argument("--target-lang", required=True, help="Target language")
    parser.add_argument("--out-dir", required=True, help="Output root directory for batch job")
    parser.add_argument("--input-srt", default=None, help="Optional external subtitle file to skip ASR")
    parser.add_argument(
        "--input-srt-kind",
        default="source",
        choices=["source", "translated"],
        help="Type of input srt: source(need translation) or translated(skip translation)",
    )
    parser.add_argument("--segment-minutes", type=float, default=8.0)
    parser.add_argument("--min-segment-minutes", type=float, default=4.0)
    parser.add_argument("--boundary-search-sec", type=float, default=45.0)
    parser.add_argument("--silence-noise-db", type=float, default=-35.0)
    parser.add_argument("--silence-min-dur-sec", type=float, default=0.3)
    parser.add_argument("--single-speaker-ref", default=None, help="Optional shared speaker ref wav")
    parser.add_argument("--single-speaker-ref-seconds", type=float, default=10.0)
    parser.add_argument("--api-key", default=None, help="Translation API key override")
    parser.add_argument("--merge-track", choices=["auto", "vocals", "mix"], default="auto")
    parser.add_argument("--time-ranges-json", default=None, help="Optional global time ranges JSON list")
    parser.add_argument("--auto-pick-ranges", default="false")
    parser.add_argument("--auto-pick-min-silence-sec", type=float, default=0.8)
    parser.add_argument("--auto-pick-min-speech-sec", type=float, default=1.0)
    parser.add_argument(
        "--resume-batch-dir",
        default=None,
        help="Resume from existing longdub batch dir (skip reusable completed segments).",
    )

    args, extra_args = parser.parse_known_args(argv)
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    return args, extra_args


def clip_subtitles_for_segment(
    *,
    subtitles: List[Dict[str, Any]],
    segment_start_sec: float,
    segment_end_sec: float,
) -> List[Dict[str, Any]]:
    # 将全局字幕裁到当前分段，并转换为分段局部时间轴（从 0 开始）。
    clipped: List[Dict[str, Any]] = []
    segment_duration = max(0.0, float(segment_end_sec) - float(segment_start_sec))
    if segment_duration <= 0:
        return clipped
    for item in subtitles:
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", start_sec) or start_sec)
        overlap_start = max(float(segment_start_sec), start_sec)
        overlap_end = min(float(segment_end_sec), end_sec)
        if overlap_end <= overlap_start:
            continue
        local_start = max(0.0, overlap_start - float(segment_start_sec))
        local_end = min(segment_duration, overlap_end - float(segment_start_sec))
        if local_end <= local_start:
            continue
        clipped.append(
            {
                "start": local_start,
                "end": local_end,
                "text": (item.get("text") or "").strip(),
            }
        )
    return clipped


def normalize_input_subtitles_for_segments(
    *,
    subtitles: List[Dict[str, Any]],
    media_duration_sec: float,
    min_duration_sec: float = 0.12,
) -> List[Dict[str, Any]]:
    # 在长视频分段前统一规整全局字幕时间轴，减少跨段裁剪时的断裂与零时长问题。
    if not subtitles:
        return []
    safe_media_duration = max(float(media_duration_sec), float(min_duration_sec))
    prepared: List[Dict[str, Any]] = []
    for item in subtitles:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        prepared.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", item.get("start", 0.0)) or item.get("start", 0.0) or 0.0),
                "text": text,
            }
        )
    if not prepared:
        return []

    prepared.sort(key=lambda x: float(x["start"]))
    output: List[Dict[str, Any]] = []
    cursor = 0.0
    total = len(prepared)
    for index, item in enumerate(prepared):
        start_sec = max(0.0, min(float(item["start"]), safe_media_duration))
        if start_sec < cursor:
            start_sec = cursor
        next_start = safe_media_duration
        if index + 1 < total:
            next_start = max(start_sec, min(float(prepared[index + 1]["start"]), safe_media_duration))
        raw_end = max(0.0, min(float(item["end"]), safe_media_duration))
        end_sec = min(raw_end, next_start) if raw_end > start_sec + 1e-6 else next_start
        if index == total - 1 and end_sec <= start_sec + 1e-6:
            end_sec = safe_media_duration
        if end_sec <= start_sec + 1e-6:
            end_sec = min(safe_media_duration, start_sec + float(min_duration_sec))
        if end_sec <= start_sec + 1e-6:
            continue
        output.append({"start": start_sec, "end": end_sec, "text": item["text"]})
        cursor = end_sec
    return output


def has_flag_enabled(extra_args: List[str], flag_name: str) -> bool:
    # 解析 parse_known_args 剩余参数中的布尔开关（例如 --v2-mode true）。
    for index, value in enumerate(extra_args):
        if value != flag_name:
            continue
        if index + 1 < len(extra_args):
            lowered = str(extra_args[index + 1]).strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return True
    return False


def find_flag_value(extra_args: List[str], flag_name: str) -> Optional[str]:
    # 提取剩余参数里的指定开关值（例如 --timing-mode balanced）。
    for index, value in enumerate(extra_args):
        if value != flag_name:
            continue
        if index + 1 < len(extra_args):
            next_value = str(extra_args[index + 1])
            if not next_value.startswith("--"):
                return next_value
        return None
    return None


def main(argv: Optional[List[str]] = None) -> int:
    args, extra_args = parse_args(argv)
    v2_mode = has_flag_enabled(extra_args, "--v2-mode")
    rewrite_translation = True
    if any(item == "--v2-rewrite-translation" for item in extra_args):
        rewrite_translation = has_flag_enabled(extra_args, "--v2-rewrite-translation")
    timing_mode = find_flag_value(extra_args, "--timing-mode") or "strict"
    grouping_strategy = find_flag_value(extra_args, "--grouping-strategy") or "sentence"
    source_short_merge_enabled = (
        has_flag_enabled(extra_args, "--source-short-merge-enabled")
        if any(item == "--source-short-merge-enabled" for item in extra_args)
        else False
    )
    source_short_merge_threshold = int(
        find_flag_value(extra_args, "--source-short-merge-threshold") or DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC
    )
    index_tts_api_url = find_flag_value(extra_args, "--index-tts-api-url")
    grouped_synthesis = (
        has_flag_enabled(extra_args, "--grouped-synthesis")
        if any(item == "--grouped-synthesis" for item in extra_args)
        else True
    )
    force_fit_timing = (
        has_flag_enabled(extra_args, "--force-fit-timing")
        if any(item == "--force-fit-timing" for item in extra_args)
        else True
    )

    input_media = Path(args.input_media).expanduser().resolve()
    if not input_media.exists():
        raise FileNotFoundError(f"input media not found: {input_media}")
    input_srt_path = Path(args.input_srt).expanduser().resolve() if args.input_srt else None
    input_subtitles: List[Dict[str, Any]] = []
    if input_srt_path is not None:
        if not input_srt_path.exists():
            raise FileNotFoundError(f"input srt not found: {input_srt_path}")
        input_subtitles = parse_srt(input_srt_path.read_text(encoding="utf-8"))
    if args.segment_minutes <= 0:
        raise ValueError("--segment-minutes must be > 0")
    if args.min_segment_minutes <= 0:
        raise ValueError("--min-segment-minutes must be > 0")
    if args.min_segment_minutes > args.segment_minutes:
        raise ValueError("--min-segment-minutes must be <= --segment-minutes")
    if args.auto_pick_min_silence_sec < 0.1 or args.auto_pick_min_silence_sec > 10.0:
        raise ValueError("--auto-pick-min-silence-sec must be in [0.1, 10.0]")
    if args.auto_pick_min_speech_sec < 0.1 or args.auto_pick_min_speech_sec > 30.0:
        raise ValueError("--auto-pick-min-speech-sec must be in [0.1, 30.0]")

    out_root = Path(args.out_dir).expanduser().resolve()
    resume_batch_dir = Path(args.resume_batch_dir).expanduser().resolve() if args.resume_batch_dir else None
    if resume_batch_dir is not None:
        batch_dir = resume_batch_dir
        batch_id = batch_dir.name.removeprefix("longdub_")
    else:
        batch_id = build_readable_batch_id(
            out_root=out_root,
            time_tag=datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        batch_dir = out_root / f"longdub_{batch_id}"
    segments_dir = batch_dir / "segments"
    segment_jobs_dir = batch_dir / "segment_jobs"
    final_dir = batch_dir / "final"
    for path in (segments_dir, segment_jobs_dir, final_dir):
        path.mkdir(parents=True, exist_ok=True)

    source_audio = batch_dir / "source_audio.wav"
    requested_ranges = parse_time_ranges_json(args.time_ranges_json)
    effective_ranges: List[Tuple[float, float]] = []
    range_strategy = "all"

    if source_audio.exists():
        print("Step 1/5: reuse existing source audio")
    else:
        print("Step 1/5: extract source audio")
        extract_source_audio(input_media, source_audio)
    total_duration_sec = ffprobe_duration(source_audio)
    print(f"Source duration: {total_duration_sec:.2f}s")
    if v2_mode and input_subtitles:
        input_subtitles = normalize_input_subtitles_for_segments(
            subtitles=input_subtitles,
            media_duration_sec=total_duration_sec,
        )

    if requested_ranges:
        effective_ranges = normalize_time_ranges(
            [
                (
                    max(0.0, min(start_sec, total_duration_sec)),
                    max(0.0, min(end_sec, total_duration_sec)),
                )
                for start_sec, end_sec in requested_ranges
                if end_sec > start_sec
            ]
        )
        range_strategy = "manual"
    elif read_bool(args.auto_pick_ranges):
        effective_ranges = detect_speech_time_ranges(
            source_audio=source_audio,
            min_silence_sec=float(args.auto_pick_min_silence_sec),
            min_speech_sec=float(args.auto_pick_min_speech_sec),
        )
        range_strategy = "auto"

    existing_segment_files = sorted(segments_dir.glob("segment_*.wav"), key=lambda item: item.name)
    if range_strategy != "all":
        print("Step 2/5: use selected time ranges as direct processing units")
        print(f"Planned segments: {len(effective_ranges)}")
        print("Step 3/5: cut selected range audio files")
        for old_file in existing_segment_files:
            old_file.unlink(missing_ok=True)
        segments = []
        for index, (start_sec, end_sec) in enumerate(effective_ranges, start=1):
            output_audio = segments_dir / f"segment_{index:04d}.wav"
            cut_audio_segment(
                source_audio=source_audio,
                output_audio=output_audio,
                start_sec=float(start_sec),
                end_sec=float(end_sec),
            )
            segments.append((index, float(start_sec), float(end_sec), output_audio))
    elif source_audio.exists() and existing_segment_files:
        print("Step 2/5: reuse existing segments")
        segments = build_segments_from_existing_files(segments_dir)
        print(f"Existing segments: {len(segments)}")
    else:
        print("Step 2/5: detect silence and build split plan")
        silences = detect_silence_endpoints(
            source_audio=source_audio,
            noise_db=float(args.silence_noise_db),
            min_duration_sec=float(args.silence_min_dur_sec),
        )
        boundaries = choose_boundaries(
            total_duration_sec=total_duration_sec,
            silence_ends=silences,
            target_segment_sec=float(args.segment_minutes) * 60.0,
            min_segment_sec=float(args.min_segment_minutes) * 60.0,
            search_window_sec=float(args.boundary_search_sec),
        )
        print(f"Planned segments: {len(boundaries) - 1}")

        print("Step 3/5: cut segment audio files")
        segments = []
        for index in range(len(boundaries) - 1):
            start_sec = float(boundaries[index])
            end_sec = float(boundaries[index + 1])
            output_audio = segments_dir / f"segment_{index + 1:04d}.wav"
            cut_audio_segment(
                source_audio=source_audio,
                output_audio=output_audio,
                start_sec=start_sec,
                end_sec=end_sec,
            )
            segments.append((index + 1, start_sec, end_sec, output_audio))
    if effective_ranges:
        print(f"Range strategy: {range_strategy}")
        print(f"Effective ranges: {len(effective_ranges)}")
    elif range_strategy != "all":
        print("Range strategy requested but no effective range found; fallback to all.")
        range_strategy = "all"

    shared_ref: Optional[Path] = None
    if args.single_speaker_ref:
        given_ref = Path(args.single_speaker_ref).expanduser().resolve()
        if not given_ref.exists():
            raise FileNotFoundError(f"--single-speaker-ref not found: {given_ref}")
        shared_ref = batch_dir / "shared_ref.wav"
        shared_ref.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(given_ref, shared_ref)

    reusable_jobs = (
        {}
        if (effective_ranges or input_srt_path is not None)
        else collect_reusable_jobs_by_segment(
            segment_jobs_dir=segment_jobs_dir,
            segments=segments,
        )
    )
    latest_jobs = collect_latest_jobs_by_segment(
        segment_jobs_dir=segment_jobs_dir,
        segments=segments,
    )

    print("Step 4/5: run dubbing per segment")
    results: List[SegmentResult] = []
    for seg_index, start_sec, end_sec, seg_audio in segments:
        segment_ranges = None
        segment_input_srt: Optional[Path] = None
        canonical_job_dir = segment_jobs_dir / f"segment_{seg_index:04d}"
        if range_strategy == "all" and effective_ranges:
            segment_ranges = map_global_ranges_to_segment(
                global_ranges=effective_ranges,
                segment_start_sec=start_sec,
                segment_end_sec=end_sec,
            )
        if input_srt_path is not None:
            segment_subtitles = clip_subtitles_for_segment(
                subtitles=input_subtitles,
                segment_start_sec=start_sec,
                segment_end_sec=end_sec,
            )
            if not segment_subtitles:
                print(f"===== Segment {seg_index:02d} skip: no clipped subtitles =====")
                manifest = write_skipped_segment_manifest(
                    segment_index=seg_index,
                    segment_audio=seg_audio,
                    job_dir=canonical_job_dir,
                    target_lang=args.target_lang,
                    reason="no subtitles overlap current segment",
                )
                results.append(
                    SegmentResult(
                        index=seg_index,
                        start_sec=start_sec,
                        end_sec=end_sec,
                        segment_audio=seg_audio,
                        job_dir=canonical_job_dir,
                        manifest=manifest,
                    )
                )
                continue
            segment_input_srt = segment_jobs_dir / f"segment_{seg_index:04d}" / "subtitles" / "_input_segment.srt"
            segment_input_srt.parent.mkdir(parents=True, exist_ok=True)
            segment_input_srt.write_text(format_srt(segment_subtitles), encoding="utf-8")
        if seg_index in reusable_jobs:
            job_dir, manifest = reusable_jobs[seg_index]
            print(f"===== Segment {seg_index:02d} reuse: {job_dir.name} =====")
        else:
            # 统一使用固定段目录，保证 segment_xxxx 与 segment_jobs/segment_xxxx 一一对应。
            # 注意：是否“真实续跑”由 run_segment_job 内部按 manifest 存在性判断。
            resume_job_dir = canonical_job_dir
            job_dir = run_segment_job(
                segment_index=seg_index,
                segment_audio=seg_audio,
                target_lang=args.target_lang,
                segment_jobs_dir=segment_jobs_dir,
                shared_ref=shared_ref,
                single_speaker_ref_seconds=float(args.single_speaker_ref_seconds),
                api_key=args.api_key,
                extra_args=extra_args,
                segment_time_ranges=segment_ranges,
                input_srt_path=segment_input_srt,
                input_srt_kind=args.input_srt_kind,
                resume_job_dir=resume_job_dir,
            )
            manifest_path = job_dir / "manifest.json"
            if not manifest_path.exists():
                raise RuntimeError(f"missing manifest for segment {seg_index}: {manifest_path}")
            manifest = load_segment_manifest(manifest_path).raw

        if shared_ref is None:
            auto_ref = job_dir / "refs" / "single_speaker_ref.wav"
            if auto_ref.exists():
                shared_ref = batch_dir / "shared_ref.wav"
                shared_ref.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(auto_ref, shared_ref)
        results.append(
            SegmentResult(
                index=seg_index,
                start_sec=start_sec,
                end_sec=end_sec,
                segment_audio=seg_audio,
                job_dir=job_dir,
                manifest=manifest,
            )
        )

    print("Step 5/5: merge outputs")
    all_vocals: List[Path] = []
    all_bgm: List[Path] = []
    source_srt_inputs: List[Tuple[Path, float]] = []
    translated_srt_inputs: List[Tuple[Path, float]] = []
    dubbed_final_srt_inputs: List[Tuple[Path, float]] = []

    for item in results:
        paths = item.manifest.get("paths", {})
        vocals_path = resolve_output_path(paths.get("dubbed_vocals"))
        bgm_path = resolve_output_path(paths.get("source_bgm"))
        source_srt = resolve_output_path(paths.get("source_srt"))
        translated_srt = resolve_output_path(paths.get("translated_srt"))
        dubbed_final_srt = resolve_output_path(paths.get("dubbed_final_srt"))

        fallback_source_srt = item.job_dir / "subtitles" / "source.srt"
        fallback_translated_srt = item.job_dir / "subtitles" / "translated.srt"
        fallback_dubbed_final_srt = item.job_dir / "subtitles" / "dubbed_final.srt"
        if (source_srt is None or not source_srt.exists()) and fallback_source_srt.exists():
            source_srt = fallback_source_srt
        if (translated_srt is None or not translated_srt.exists()) and fallback_translated_srt.exists():
            translated_srt = fallback_translated_srt
        if (dubbed_final_srt is None or not dubbed_final_srt.exists()) and fallback_dubbed_final_srt.exists():
            dubbed_final_srt = fallback_dubbed_final_srt

        if vocals_path and vocals_path.exists():
            all_vocals.append(vocals_path)
        if bgm_path and bgm_path.exists():
            all_bgm.append(bgm_path)
        if source_srt and source_srt.exists():
            source_srt_inputs.append((source_srt, item.start_sec))
        if translated_srt and translated_srt.exists():
            translated_srt_inputs.append((translated_srt, item.start_sec))
        if dubbed_final_srt and dubbed_final_srt.exists():
            dubbed_final_srt_inputs.append((dubbed_final_srt, item.start_sec))

    merged_vocals = None
    merged_mix = None
    merged_bgm = None
    if range_strategy != "all":
        # 指定区间模式：输出保持“完整时间轴”，仅替换区间内音频。
        merged_vocals = build_full_timeline_vocals(
            results=results,
            output_wav=final_dir / "dubbed_vocals_full.wav",
            source_audio=source_audio,
        )
        merged_bgm = build_full_timeline_bgm(
            results=results,
            output_wav=final_dir / "source_bgm_full.wav",
            source_audio=source_audio,
        )
        merged_mix = build_full_timeline_mix(
            results=results,
            output_wav=final_dir / "dubbed_mix_full.wav",
            source_audio=source_audio,
        )
    else:
        can_concat_vocals = bool(results) and len(all_vocals) == len(results)
        can_concat_bgm = bool(results) and len(all_bgm) == len(results)
        if can_concat_vocals:
            merged_vocals = final_dir / "dubbed_vocals_full.wav"
            concat_wav_files(all_vocals, merged_vocals)
        elif all_vocals:
            # 有分段被跳过或缺失产物时，退回全时轴拼接，空洞自动保持静音。
            merged_vocals = build_full_timeline_vocals(
                results=results,
                output_wav=final_dir / "dubbed_vocals_full.wav",
                source_audio=source_audio,
            )
        if can_concat_bgm:
            merged_bgm = final_dir / "source_bgm_full.wav"
            concat_wav_files(all_bgm, merged_bgm)
        elif all_bgm:
            merged_bgm = build_full_timeline_bgm(
                results=results,
                output_wav=final_dir / "source_bgm_full.wav",
                source_audio=source_audio,
            )
        # 全量模式改为“最终只混一次”：使用 full vocals + full bgm 生成 mix。
        if merged_vocals is not None and merged_bgm is not None:
            merged_mix = final_dir / "dubbed_mix_full.wav"
            mix_vocals_with_bgm(vocals_wav=merged_vocals, bgm_wav=merged_bgm, output_wav=merged_mix)

    if source_srt_inputs:
        merge_srt_files(
            inputs=source_srt_inputs,
            output_srt=final_dir / "source_full.srt",
        )
    if translated_srt_inputs:
        merge_srt_files(
            inputs=translated_srt_inputs,
            output_srt=final_dir / "translated_full.srt",
        )
    bilingual_translated_inputs = (
        dubbed_final_srt_inputs if len(dubbed_final_srt_inputs) == len(results) else translated_srt_inputs
    )
    if bilingual_translated_inputs and source_srt_inputs and len(bilingual_translated_inputs) == len(source_srt_inputs):
        merge_bilingual_srt_files(
            translated_inputs=bilingual_translated_inputs,
            source_inputs=source_srt_inputs,
            output_srt=final_dir / "dubbed_final_full.srt",
            translated_first=True,
        )

    preferred_audio = None
    if args.merge_track == "vocals":
        preferred_audio = merged_vocals
    elif args.merge_track == "mix":
        preferred_audio = merged_mix
    else:
        preferred_audio = merged_mix or merged_vocals

    batch_options = BatchReplayOptions(
        target_lang=args.target_lang,
        pipeline_version="v2" if v2_mode else "v1",
        rewrite_translation=bool(rewrite_translation),
        timing_mode=timing_mode,
        grouping_strategy=grouping_strategy,
        input_srt_kind=args.input_srt_kind,
        index_tts_api_url=index_tts_api_url,
        auto_pick_ranges=str(args.auto_pick_ranges).strip().lower() in {"1", "true", "yes", "on"},
        source_short_merge_enabled=bool(source_short_merge_enabled),
        source_short_merge_threshold=source_short_merge_threshold,
        source_short_merge_threshold_mode="seconds",
        grouped_synthesis=bool(grouped_synthesis),
        force_fit_timing=bool(force_fit_timing),
        tts_backend="index-tts",
    )
    batch_manifest = build_batch_manifest(
        batch_id=batch_id,
        created_at=iso_now(),
        input_media_path=input_media,
        options=batch_options,
        input_srt_path=input_srt_path,
        segment_minutes=args.segment_minutes,
        range_strategy=range_strategy,
        requested_ranges=requested_ranges,
        effective_ranges=effective_ranges,
        batch_dir=batch_dir,
        preferred_audio=preferred_audio,
        merged_vocals=merged_vocals,
        merged_mix=merged_mix,
        merged_bgm=merged_bgm,
        final_dir=final_dir,
        segments=[
            {
                "index": item.index,
                "start_sec": round(item.start_sec, 3),
                "end_sec": round(item.end_sec, 3),
                "duration_sec": round(item.end_sec - item.start_sec, 3),
                "segment_audio": str(item.segment_audio),
                "job_dir": str(item.job_dir),
                "summary": item.manifest.get("stats", {}),
            }
            for item in results
        ],
    )
    manifest_path = batch_dir / "batch_manifest.json"
    write_manifest_json(manifest_path, batch_manifest)

    print("\nBatch completed.")
    print(json.dumps(batch_manifest["paths"], ensure_ascii=False, indent=2))
    print(f"Batch manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
