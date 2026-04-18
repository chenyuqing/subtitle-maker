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

# Exit-code contract from tools/dub_pipeline.py
SEGMENT_EXIT_OK = 0
SEGMENT_EXIT_FAILED = 1
SEGMENT_EXIT_OK_WITH_MANUAL_REVIEW = 2


def iso_now() -> str:
    return datetime.utcnow().isoformat()


def build_readable_batch_id(*, out_root: Path, time_tag: str) -> str:
    # 生成可读批次名：固定三位序号后缀，格式如 20260417_192311-001。
    base = time_tag
    index = 1
    while True:
        candidate = f"{base}-{index:03d}"
        if not (out_root / f"longdub_{candidate}").exists():
            return candidate
        index += 1


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cmd_checked(cmd: List[str], cwd: Optional[Path] = None) -> None:
    code, out, err = run_cmd(cmd, cwd=cwd)
    if code != 0:
        raise RuntimeError(f"command failed ({code}): {' '.join(cmd)}\n{out}\n{err}")


def run_cmd_stream(cmd: List[str], cwd: Optional[Path] = None) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip())
    code = proc.wait()
    return code


def read_bool(value: str) -> bool:
    # 统一解析布尔字符串参数。
    lowered = (value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def ffprobe_duration(path: Path) -> float:
    code, out, err = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ]
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err.strip()}")
    try:
        return float(out.strip())
    except ValueError as exc:
        raise RuntimeError(f"invalid duration from ffprobe: {out!r}") from exc


def extract_source_audio(input_media: Path, output_wav: Path) -> None:
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_media),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            str(output_wav),
        ]
    )


def detect_silence_endpoints(
    source_audio: Path,
    *,
    noise_db: float,
    min_duration_sec: float,
) -> List[float]:
    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(source_audio),
            "-af",
            f"silencedetect=noise={noise_db:.1f}dB:d={min_duration_sec:.2f}",
            "-f",
            "null",
            "-",
        ]
    )
    if code != 0:
        raise RuntimeError(f"silence detect failed: {err.strip()}")
    pattern = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
    values = [float(match.group(1)) for match in pattern.finditer(err)]
    return sorted(set(values))


def choose_boundaries(
    *,
    total_duration_sec: float,
    silence_ends: List[float],
    target_segment_sec: float,
    min_segment_sec: float,
    search_window_sec: float,
) -> List[float]:
    if total_duration_sec <= target_segment_sec * 1.1:
        return [0.0, total_duration_sec]

    boundaries: List[float] = [0.0]
    cursor = 0.0
    while total_duration_sec - cursor > target_segment_sec:
        target = cursor + target_segment_sec
        min_cut = cursor + min_segment_sec
        max_cut = total_duration_sec - min_segment_sec

        window_start = max(min_cut, target - search_window_sec)
        window_end = min(max_cut, target + search_window_sec)
        candidate = None
        if window_end > window_start:
            window_points = [point for point in silence_ends if window_start <= point <= window_end]
            if window_points:
                candidate = min(window_points, key=lambda point: abs(point - target))

        cut = candidate if candidate is not None else min(target, max_cut)
        if cut <= cursor:
            break
        boundaries.append(round(cut, 3))
        cursor = cut

    if boundaries[-1] < total_duration_sec:
        boundaries.append(total_duration_sec)

    normalized: List[float] = [boundaries[0]]
    for value in boundaries[1:]:
        if value - normalized[-1] >= 0.2:
            normalized.append(value)
    if normalized[-1] < total_duration_sec:
        normalized[-1] = total_duration_sec
    return normalized


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
    # 基于短时能量自动识别有语音的区间，供自动配音使用。
    wav, sample_rate = sf.read(str(source_audio))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size == 0 or sample_rate <= 0:
        return []

    frame_hop = max(1, int(0.02 * sample_rate))
    window = max(1, int(0.03 * sample_rate))
    envelope = np.convolve(np.abs(mono), np.ones(window, dtype=np.float32) / window, mode="same")
    threshold = max(1e-5, float(np.percentile(envelope, 75) * float(energy_ratio)))

    active: List[Tuple[float, float]] = []
    in_active = False
    start_sample = 0
    for index in range(0, len(envelope), frame_hop):
        is_active = bool(envelope[index] >= threshold)
        if is_active and not in_active:
            in_active = True
            start_sample = index
        elif (not is_active) and in_active:
            in_active = False
            active.append((start_sample / sample_rate, index / sample_rate))
    if in_active:
        active.append((start_sample / sample_rate, len(envelope) / sample_rate))

    merged: List[Tuple[float, float]] = []
    for start_sec, end_sec in active:
        if not merged:
            merged.append((start_sec, end_sec))
            continue
        prev_start, prev_end = merged[-1]
        if start_sec - prev_end <= float(min_silence_sec):
            merged[-1] = (prev_start, end_sec)
        else:
            merged.append((start_sec, end_sec))
    return normalize_time_ranges(
        [(start_sec, end_sec) for start_sec, end_sec in merged if (end_sec - start_sec) >= float(min_speech_sec)]
    )


def map_global_ranges_to_segment(
    *,
    global_ranges: List[Tuple[float, float]],
    segment_start_sec: float,
    segment_end_sec: float,
) -> List[Tuple[float, float]]:
    # 将全局时间轴区间映射到分段局部时间轴。
    local: List[Tuple[float, float]] = []
    for global_start, global_end in global_ranges:
        overlap_start = max(float(segment_start_sec), float(global_start))
        overlap_end = min(float(segment_end_sec), float(global_end))
        if overlap_end <= overlap_start:
            continue
        local.append((overlap_start - float(segment_start_sec), overlap_end - float(segment_start_sec)))
    return normalize_time_ranges(local)


def cut_audio_segment(
    *,
    source_audio: Path,
    output_audio: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    duration_sec = max(0.05, end_sec - start_sec)
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_sec:.3f}",
            "-i",
            str(source_audio),
            "-t",
            f"{duration_sec:.3f}",
            "-ac",
            "1",
            "-ar",
            "44100",
            str(output_audio),
        ]
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
    if not inputs:
        raise RuntimeError("no inputs for concat")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    concat_list = output_wav.parent / f"{output_wav.stem}_concat.txt"
    lines = []
    for item in inputs:
        escaped = str(item.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(output_wav),
        ]
    )


def _load_mono_audio(path: Path) -> Tuple[np.ndarray, int]:
    # 读取音频并统一为单声道 float32，便于后续时间轴替换。
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    return mono, int(sample_rate)


def _resample_mono_audio(wav: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    # 线性插值重采样，避免区间配音与全时轴底轨采样率不一致时被跳过。
    if source_sr <= 0 or target_sr <= 0 or wav.size == 0:
        return np.asarray(wav, dtype=np.float32)
    if source_sr == target_sr:
        return np.asarray(wav, dtype=np.float32)
    source_len = int(len(wav))
    target_len = max(1, int(round(source_len * float(target_sr) / float(source_sr))))
    if source_len <= 1:
        return np.zeros(target_len, dtype=np.float32) + (float(wav[0]) if source_len == 1 else 0.0)
    source_x = np.linspace(0.0, 1.0, num=source_len, endpoint=True, dtype=np.float64)
    target_x = np.linspace(0.0, 1.0, num=target_len, endpoint=True, dtype=np.float64)
    resampled = np.interp(target_x, source_x, wav.astype(np.float64))
    return resampled.astype(np.float32)


def build_full_timeline_vocals(
    *,
    results: List["SegmentResult"],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    # 生成“全时轴 vocals”：区间内放配音，区间外保持静音。
    base_audio, sample_rate = _load_mono_audio(source_audio)
    if sample_rate <= 0:
        return None
    timeline = np.zeros(len(base_audio), dtype=np.float32)
    wrote_any = False
    for item in sorted(results, key=lambda x: x.start_sec):
        paths = item.manifest.get("paths", {})
        vocals_path = resolve_output_path(paths.get("dubbed_vocals"))
        if not (vocals_path and vocals_path.exists()):
            continue
        seg_wav, seg_sr = _load_mono_audio(vocals_path)
        if seg_wav.size == 0:
            continue
        if seg_sr != sample_rate:
            seg_wav = _resample_mono_audio(seg_wav, seg_sr, sample_rate)
        start_sample = max(0, int(float(item.start_sec) * sample_rate))
        if start_sample >= len(timeline):
            continue
        max_len = min(len(seg_wav), len(timeline) - start_sample)
        if max_len <= 0:
            continue
        timeline[start_sample : start_sample + max_len] = seg_wav[:max_len]
        wrote_any = True
    if not wrote_any:
        return None
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_wav), timeline, sample_rate)
    return output_wav


def build_full_timeline_mix(
    *,
    results: List["SegmentResult"],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    # 生成“全时轴 mix”：以原音频为底，仅替换指定区间为配音混音。
    base_audio, sample_rate = _load_mono_audio(source_audio)
    if sample_rate <= 0:
        return None
    timeline = base_audio.copy()
    wrote_any = False
    for item in sorted(results, key=lambda x: x.start_sec):
        paths = item.manifest.get("paths", {})
        mix_path = resolve_output_path(paths.get("dubbed_mix"))
        if not (mix_path and mix_path.exists()):
            mix_path = resolve_output_path(paths.get("dubbed_vocals"))
        if not (mix_path and mix_path.exists()):
            continue
        seg_wav, seg_sr = _load_mono_audio(mix_path)
        if seg_wav.size == 0:
            continue
        if seg_sr != sample_rate:
            seg_wav = _resample_mono_audio(seg_wav, seg_sr, sample_rate)
        start_sample = max(0, int(float(item.start_sec) * sample_rate))
        if start_sample >= len(timeline):
            continue
        max_len = min(len(seg_wav), len(timeline) - start_sample)
        if max_len <= 0:
            continue
        timeline[start_sample : start_sample + max_len] = seg_wav[:max_len]
        wrote_any = True
    if not wrote_any:
        return None
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_wav), timeline, sample_rate)
    return output_wav


def merge_srt_files(
    *,
    inputs: List[Tuple[Path, float]],
    output_srt: Path,
) -> None:
    merged: List[Dict[str, Any]] = []
    for path, offset_sec in inputs:
        text = path.read_text(encoding="utf-8")
        subtitles = parse_srt(text)
        for item in subtitles:
            merged.append(
                {
                    "start": float(item["start"]) + offset_sec,
                    "end": float(item["end"]) + offset_sec,
                    "text": item["text"],
                }
            )
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(format_srt(merged), encoding="utf-8")


def merge_bilingual_srt_files(
    *,
    translated_inputs: List[Tuple[Path, float]],
    source_inputs: List[Tuple[Path, float]],
    output_srt: Path,
    translated_first: bool = True,
) -> None:
    merged: List[Dict[str, Any]] = []
    for (translated_path, translated_offset), (source_path, source_offset) in zip(translated_inputs, source_inputs):
        if abs(float(translated_offset) - float(source_offset)) > 1e-6:
            raise RuntimeError("offset mismatch while building bilingual srt")
        translated_subs = parse_srt(translated_path.read_text(encoding="utf-8"))
        source_subs = parse_srt(source_path.read_text(encoding="utf-8"))
        if len(translated_subs) != len(source_subs):
            raise RuntimeError("line count mismatch while building bilingual srt")

        for translated, source in zip(translated_subs, source_subs):
            translated_text = (translated.get("text") or "").strip()
            source_text = (source.get("text") or "").strip()
            if translated_first:
                text = translated_text if not source_text else f"{translated_text}\n{source_text}"
            else:
                text = source_text if not translated_text else f"{source_text}\n{translated_text}"
            merged.append(
                {
                    "start": float(translated["start"]) + translated_offset,
                    "end": float(translated["end"]) + translated_offset,
                    "text": text,
                }
            )

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(format_srt(merged), encoding="utf-8")


@dataclass
class SegmentResult:
    index: int
    start_sec: float
    end_sec: float
    segment_audio: Path
    job_dir: Path
    manifest: Dict[str, Any]


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
    if extra_args:
        cmd.extend(extra_args)

    if resume_job_dir is not None and resume_job_dir.exists():
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
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        input_media_path = manifest.get("input_media_path")
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
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                input_media_path = manifest.get("input_media_path")
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


def main(argv: Optional[List[str]] = None) -> int:
    args, extra_args = parse_args(argv)

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
            segment_input_srt = segment_jobs_dir / f"segment_{seg_index:04d}" / "subtitles" / "_input_segment.srt"
            segment_input_srt.parent.mkdir(parents=True, exist_ok=True)
            segment_input_srt.write_text(format_srt(segment_subtitles), encoding="utf-8")
        canonical_job_dir = segment_jobs_dir / f"segment_{seg_index:04d}"
        if seg_index in reusable_jobs:
            job_dir, manifest = reusable_jobs[seg_index]
            print(f"===== Segment {seg_index:02d} reuse: {job_dir.name} =====")
        else:
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
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

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
    all_mix: List[Path] = []
    all_bgm: List[Path] = []
    source_srt_inputs: List[Tuple[Path, float]] = []
    translated_srt_inputs: List[Tuple[Path, float]] = []
    dubbed_final_srt_inputs: List[Tuple[Path, float]] = []

    for item in results:
        paths = item.manifest.get("paths", {})
        vocals_path = resolve_output_path(paths.get("dubbed_vocals"))
        mix_path = resolve_output_path(paths.get("dubbed_mix"))
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
        if mix_path and mix_path.exists():
            all_mix.append(mix_path)
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
        merged_mix = build_full_timeline_mix(
            results=results,
            output_wav=final_dir / "dubbed_mix_full.wav",
            source_audio=source_audio,
        )
    else:
        if all_vocals and len(all_vocals) == len(results):
            merged_vocals = final_dir / "dubbed_vocals_full.wav"
            concat_wav_files(all_vocals, merged_vocals)
        if all_mix and len(all_mix) == len(results):
            merged_mix = final_dir / "dubbed_mix_full.wav"
            concat_wav_files(all_mix, merged_mix)
        if all_bgm and len(all_bgm) == len(results):
            merged_bgm = final_dir / "source_bgm_full.wav"
            concat_wav_files(all_bgm, merged_bgm)

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
    if len(bilingual_translated_inputs) == len(results) and len(source_srt_inputs) == len(results):
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

    batch_manifest = {
        "batch_id": batch_id,
        "created_at": iso_now(),
        "input_media_path": str(input_media),
        "target_lang": args.target_lang,
        "input_srt": str(input_srt_path) if input_srt_path else None,
        "segment_minutes": args.segment_minutes,
        "range_strategy": range_strategy,
        "requested_ranges": [
            {"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
            for start_sec, end_sec in requested_ranges
        ],
        "effective_ranges": [
            {"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
            for start_sec, end_sec in effective_ranges
        ],
        "segments_total": len(results),
        "paths": {
            "batch_dir": str(batch_dir),
            "preferred_audio": str(preferred_audio) if preferred_audio else None,
            "dubbed_vocals_full": str(merged_vocals) if merged_vocals else None,
            "dubbed_mix_full": str(merged_mix) if merged_mix else None,
            "source_bgm_full": str(merged_bgm) if merged_bgm else None,
            "source_full_srt": str(final_dir / "source_full.srt")
            if (final_dir / "source_full.srt").exists()
            else None,
            "dubbed_final_full_srt": str(final_dir / "dubbed_final_full.srt")
            if (final_dir / "dubbed_final_full.srt").exists()
            else None,
            "translated_full_srt": str(final_dir / "translated_full.srt")
            if (final_dir / "translated_full.srt").exists()
            else None,
        },
        "segments": [
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
    }
    manifest_path = batch_dir / "batch_manifest.json"
    manifest_path.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nBatch completed.")
    print(json.dumps(batch_manifest["paths"], ensure_ascii=False, indent=2))
    print(f"Batch manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
