from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import soundfile as sf

from subtitle_maker.core.ffmpeg import run_cmd


def audio_duration(path: Path) -> float:
    """读取音频文件元信息并返回时长秒数。"""
    return float(sf.info(str(path)).duration)


def ffprobe_duration(path: Path) -> float:
    """通过 ffprobe 获取媒体时长，保持对非 wav 输入的兼容性。"""
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


def load_mono_audio(path: Path) -> Tuple[np.ndarray, int]:
    """读取音频并统一为单声道 float32，便于后续时间轴处理。"""
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    return mono, int(sample_rate)


def resample_mono_audio(wav: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    """使用线性插值重采样单声道音频，避免不同采样率时被直接跳过。"""
    if source_sr <= 0 or target_sr <= 0 or wav.size == 0:
        return np.asarray(wav, dtype=np.float32)
    if source_sr == target_sr:
        return np.asarray(wav, dtype=np.float32)
    source_len = int(len(wav))
    target_len = max(1, int(round(source_len * float(target_sr) / float(source_sr))))
    if source_len <= 1:
        fill_value = float(wav[0]) if source_len == 1 else 0.0
        return np.zeros(target_len, dtype=np.float32) + fill_value
    source_x = np.linspace(0.0, 1.0, num=source_len, endpoint=True, dtype=np.float64)
    target_x = np.linspace(0.0, 1.0, num=target_len, endpoint=True, dtype=np.float64)
    resampled = np.interp(target_x, source_x, wav.astype(np.float64))
    return resampled.astype(np.float32)

