from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf

from subtitle_maker.core.ffmpeg import run_cmd
from subtitle_maker.domains.media import audio_duration


def _ensure_parent(path: Path) -> None:
    """确保输出文件的父目录存在。"""

    path.parent.mkdir(parents=True, exist_ok=True)


def apply_atempo(
    *,
    input_path: Path,
    output_path: Path,
    tempo: float,
) -> None:
    """对音频应用轻量变速，不改变音高。"""

    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            f"atempo={tempo:.6f}",
            "-vn",
            str(output_path),
        ]
    )
    if code != 0:
        raise RuntimeError(f"E-ALN-001 atempo failed: {err.strip()}")


def build_atempo_filter_chain(tempo: float) -> str:
    """把超出 ffmpeg 单段范围的 tempo 拆成可执行链条。"""

    value = max(1e-4, float(tempo))
    factors: List[float] = []
    while value > 2.0:
        factors.append(2.0)
        value /= 2.0
    while value < 0.5:
        factors.append(0.5)
        value /= 0.5
    factors.append(value)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def trim_silence_edges(
    *,
    input_path: Path,
    output_path: Path,
    threshold_db: float = -35.0,
    pad_sec: float = 0.03,
    min_keep_sec: float = 0.10,
) -> Tuple[float, float]:
    """裁掉音频首尾静音，并返回裁前/裁后时长。"""

    wav, sample_rate = sf.read(str(input_path))
    if sample_rate <= 0:
        raise RuntimeError("E-ALN-001 invalid sample rate")
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        mono = wav.mean(axis=1)
    else:
        mono = np.asarray(wav)
    mono = np.asarray(mono, dtype=np.float32)

    full_duration = float(len(mono) / sample_rate) if len(mono) > 0 else 0.0
    if mono.size == 0:
        shutil.copy2(input_path, output_path)
        return full_duration, full_duration

    threshold_amp = float(10 ** (threshold_db / 20.0))
    active = np.where(np.abs(mono) >= threshold_amp)[0]
    if active.size == 0:
        shutil.copy2(input_path, output_path)
        return full_duration, full_duration

    pad_samples = max(0, int(pad_sec * sample_rate))
    start = max(0, int(active[0]) - pad_samples)
    end = min(len(mono), int(active[-1]) + 1 + pad_samples)
    min_keep_samples = max(1, int(min_keep_sec * sample_rate))

    if end - start < min_keep_samples:
        center = int((start + end) / 2)
        half = int(min_keep_samples / 2)
        start = max(0, center - half)
        end = min(len(mono), start + min_keep_samples)

    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        trimmed = wav[start:end, :]
    else:
        trimmed = wav[start:end]

    _ensure_parent(output_path)
    sf.write(str(output_path), trimmed, sample_rate)
    trimmed_duration = float(max(0, end - start) / sample_rate)
    return full_duration, trimmed_duration


def fit_audio_to_duration(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> None:
    """把音频拟合到目标时长，超长时变速，过短时补齐静音。"""

    target = max(0.05, float(target_duration_sec))
    actual = max(0.01, audio_duration(input_path))
    if actual <= target:
        filter_expr = f"apad=pad_dur={target:.6f},atrim=0:{target:.6f}"
    else:
        tempo = actual / target
        atempo_chain = build_atempo_filter_chain(tempo)
        filter_expr = f"{atempo_chain},apad=pad_dur={target:.6f},atrim=0:{target:.6f}"
    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            filter_expr,
            "-vn",
            str(output_path),
        ]
    )
    if code != 0:
        raise RuntimeError(f"E-ALN-001 fit timing failed: {err.strip()}")


def trim_audio_to_max_duration(
    *,
    input_path: Path,
    output_path: Path,
    max_duration_sec: float,
) -> None:
    """只做时长上限裁剪，不做变速。"""

    target = max(0.05, float(max_duration_sec))
    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            f"atrim=0:{target:.6f}",
            "-vn",
            str(output_path),
        ]
    )
    if code != 0:
        raise RuntimeError(f"E-ALN-001 trim max duration failed: {err.strip()}")


def compute_effective_target_duration(
    *,
    start_sec: float,
    end_sec: float,
    next_start_sec: Optional[float],
    gap_guard_sec: float = 0.10,
) -> Tuple[float, float]:
    """计算可借后续静音后的有效目标时长。"""

    base_target_sec = max(0.05, float(end_sec) - float(start_sec))
    if next_start_sec is None:
        return base_target_sec, 0.0

    gap_sec = float(next_start_sec) - float(end_sec)
    if gap_sec <= 0:
        return base_target_sec, 0.0

    borrow_sec = max(0.0, gap_sec - max(0.0, float(gap_guard_sec)))
    effective_target_sec = max(base_target_sec, base_target_sec + borrow_sec)
    return effective_target_sec, borrow_sec


def apply_short_fade_edges(*, wav: np.ndarray, sample_rate: int, fade_ms: float = 10.0) -> np.ndarray:
    """给切分后的波形加短淡入淡出，减小爆音。"""

    audio = np.asarray(wav, dtype=np.float32).copy()
    if audio.size <= 2 or sample_rate <= 0:
        return audio
    fade_len = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    fade_len = min(fade_len, max(0, audio.size // 2))
    if fade_len <= 0:
        return audio
    fade_in = np.linspace(0.0, 1.0, fade_len, endpoint=True, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_len, endpoint=True, dtype=np.float32)
    audio[:fade_len] *= fade_in
    audio[-fade_len:] *= fade_out
    return audio


def split_waveform_by_durations(
    *,
    wav: np.ndarray,
    durations: List[float],
) -> List[np.ndarray]:
    """按目标时长比例把整段波形切成多句。"""

    count = len(durations)
    if count == 0:
        return []
    if count == 1:
        return [wav]

    total_samples = len(wav)
    if total_samples <= count:
        chunks: List[np.ndarray] = []
        for index in range(count):
            if index < total_samples:
                chunks.append(wav[index : index + 1].copy())
            else:
                chunks.append(np.zeros(1, dtype=np.float32))
        return chunks

    safe = [max(0.05, float(item)) for item in durations]
    sum_safe = sum(safe) or float(count)
    boundaries = [0]
    acc = 0.0
    for duration in safe[:-1]:
        acc += duration / sum_safe
        boundaries.append(int(round(acc * total_samples)))
    boundaries.append(total_samples)

    for index in range(1, len(boundaries) - 1):
        min_allowed = boundaries[index - 1] + 1
        if boundaries[index] < min_allowed:
            boundaries[index] = min_allowed
    for index in range(len(boundaries) - 2, 0, -1):
        max_allowed = boundaries[index + 1] - 1
        if boundaries[index] > max_allowed:
            boundaries[index] = max_allowed
    boundaries[0] = 0
    boundaries[-1] = total_samples

    chunks: List[np.ndarray] = []
    for index in range(count):
        start = boundaries[index]
        end = boundaries[index + 1]
        if end <= start:
            end = min(total_samples, start + 1)
        piece = wav[start:end]
        if piece.size == 0:
            piece = np.zeros(1, dtype=np.float32)
        chunks.append(piece.astype(np.float32))
    return chunks


def estimate_line_speech_weight(*, text: str, target_duration_sec: float, cjk_mode: bool) -> float:
    """估计单句语音负载，供 balanced 模式分配时长。"""

    content = (text or "").strip()
    if not content:
        return max(0.1, float(target_duration_sec))

    if cjk_mode:
        unit_count = len([char for char in content if not char.isspace()])
    else:
        unit_count = len([item for item in content.split(" ") if item.strip()])
    base = max(1.0, float(unit_count))

    punctuation_count = sum(1 for char in content if char in ",.;:!?，。；：！？、")
    digit_count = sum(1 for char in content if char.isdigit())
    structure_bonus = 1.0 + min(0.35, punctuation_count * 0.04 + digit_count * 0.02)

    duration_prior = max(0.2, float(target_duration_sec))
    return max(0.1, base * structure_bonus * (0.55 + 0.45 * duration_prior))


def allocate_balanced_durations(
    *,
    texts: List[str],
    target_durations: List[float],
    min_line_sec: float,
    cjk_mode: bool,
) -> List[float]:
    """在组总时长不变时，按文本负载重新分配每句时长。"""

    count = len(target_durations)
    if count == 0:
        return []
    if count == 1:
        return [max(0.05, float(target_durations[0]))]

    safe_targets = [max(0.05, float(item)) for item in target_durations]
    total_target = sum(safe_targets)
    if total_target <= 0:
        return [0.05 for _ in safe_targets]

    weights: List[float] = []
    for index in range(count):
        text = texts[index] if index < len(texts) else ""
        weights.append(
            estimate_line_speech_weight(
                text=text,
                target_duration_sec=safe_targets[index],
                cjk_mode=cjk_mode,
            )
        )
    sum_weights = sum(weights) or float(count)

    allocated = [total_target * (weight / sum_weights) for weight in weights]
    floor_value = max(0.05, float(min_line_sec))
    if floor_value * count <= total_target:
        deficit = 0.0
        for index, value in enumerate(allocated):
            if value < floor_value:
                deficit += floor_value - value
                allocated[index] = floor_value
        if deficit > 1e-9:
            donors = [index for index, value in enumerate(allocated) if value > floor_value + 1e-9]
            while deficit > 1e-9 and donors:
                donor_total = sum(allocated[index] - floor_value for index in donors)
                if donor_total <= 1e-9:
                    break
                used = 0.0
                for index in donors[:]:
                    room = allocated[index] - floor_value
                    take = min(room, deficit * (room / donor_total))
                    allocated[index] -= take
                    used += take
                    if allocated[index] <= floor_value + 1e-9:
                        donors.remove(index)
                if used <= 1e-9:
                    break
                deficit -= used

    corrected_sum = sum(allocated)
    if corrected_sum > 1e-9:
        scale = total_target / corrected_sum
        allocated = [max(0.05, value * scale) for value in allocated]

    tail_fix = total_target - sum(allocated)
    allocated[-1] = max(0.05, allocated[-1] + tail_fix)
    return allocated
