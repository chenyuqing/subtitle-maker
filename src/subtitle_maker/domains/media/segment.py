from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import numpy as np
import soundfile as sf

from subtitle_maker.core.ffmpeg import run_cmd, run_cmd_checked


def extract_source_audio(input_media: Path, output_wav: Path) -> None:
    """从输入媒体抽取单声道 wav，供后续长视频切段与检测复用。"""
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
    """通过 ffmpeg silencedetect 获取静音结束点，用于长视频自动切段。"""
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
    """围绕目标切段时长，在静音结束点附近挑选更自然的边界。"""
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
    """合并重叠区间，避免重复处理同一段时间。"""
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


def detect_speech_time_ranges(
    *,
    source_audio: Path,
    min_silence_sec: float,
    min_speech_sec: float,
    energy_ratio: float = 0.16,
) -> List[Tuple[float, float]]:
    """基于短时能量检测语音活跃区间，供自动配音选择时间段。"""
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
    """把全局时间轴区间映射到分段局部时间轴。"""
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
    """按起止时间裁出单个音频分段。"""
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

