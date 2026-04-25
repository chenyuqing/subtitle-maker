from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import soundfile as sf


def _ensure_parent(path: Path) -> None:
    """确保输出文件的父目录存在。"""

    path.parent.mkdir(parents=True, exist_ok=True)


def _load_mono_audio(path: Path) -> tuple[np.ndarray, int]:
    """读取音频并统一转为单声道 float32。"""

    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    return np.asarray(wav, dtype=np.float32), int(sample_rate)


def extract_reference_audio(
    *,
    vocals_audio: Path,
    out_ref: Path,
    seconds: float,
) -> Path:
    """从整段人声中抽取第一段稳定参考音。"""

    audio, sample_rate = _load_mono_audio(vocals_audio)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    abs_audio = np.abs(audio.astype(np.float32))
    if abs_audio.size == 0:
        raise RuntimeError("E-REF-001 invalid vocals energy")

    kernel = max(1, int(sample_rate * 0.02))
    smoothed = np.convolve(abs_audio, np.ones(kernel, dtype=np.float32) / kernel, mode="same")
    threshold = max(1e-4, float(np.percentile(smoothed, 75) * 0.2))
    speech_indices = np.where(smoothed > threshold)[0]
    start_idx = int(speech_indices[0]) if speech_indices.size > 0 else 0
    end_idx = min(len(audio), start_idx + int(seconds * sample_rate))
    ref = audio[start_idx:end_idx]
    if len(ref) < int(0.8 * sample_rate):
        raise RuntimeError("E-REF-001 extracted reference too short")

    _ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sample_rate)
    return out_ref


def extract_reference_audio_from_offset(
    *,
    vocals_audio: Path,
    out_ref: Path,
    seconds: float,
    start_sec: float,
) -> Path:
    """按时间偏移抽取参考音，供多人场景使用。"""

    audio, sample_rate = _load_mono_audio(vocals_audio)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    start_sample = max(0, int(float(start_sec) * sample_rate))
    end_sample = min(len(audio), start_sample + int(max(0.8, float(seconds)) * sample_rate))
    ref = audio[start_sample:end_sample]
    if len(ref) < int(0.8 * sample_rate):
        raise RuntimeError("E-REF-001 extracted reference too short")

    _ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sample_rate)
    return out_ref


def extract_reference_audio_from_window(
    *,
    vocals_audio: Path,
    out_ref: Path,
    start_sec: float,
    end_sec: float,
    min_seconds: float = 0.8,
    pad_seconds: float = 0.15,
) -> Path:
    """按字幕时间窗抽取参考音，并在片段过短时自动扩窗。"""

    audio, sample_rate = _load_mono_audio(vocals_audio)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    total_sec = len(audio) / float(sample_rate)
    safe_start = max(0.0, float(start_sec) - float(pad_seconds))
    safe_end = min(total_sec, float(end_sec) + float(pad_seconds))
    if safe_end <= safe_start:
        safe_end = min(total_sec, safe_start + max(0.2, float(min_seconds)))

    start_sample = int(safe_start * sample_rate)
    end_sample = int(safe_end * sample_rate)
    ref = audio[start_sample:end_sample]

    min_len = int(max(0.2, float(min_seconds)) * sample_rate)
    if len(ref) < min_len:
        mid = (start_sample + end_sample) // 2
        half = min_len // 2
        new_start = max(0, mid - half)
        new_end = min(len(audio), new_start + min_len)
        new_start = max(0, new_end - min_len)
        ref = audio[new_start:new_end]

    if len(ref) < int(0.2 * sample_rate):
        raise RuntimeError("E-REF-001 extracted reference too short from subtitle window")

    _ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sample_rate)
    return out_ref


def build_subtitle_reference_map(
    *,
    subtitles: List[Dict[str, Any]],
    source_audio: Path,
    out_dir: Path,
    default_ref: Path,
) -> Dict[int, Path]:
    """按字幕时间窗为每一条字幕构造参考音映射。"""

    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: Dict[int, Path] = {}
    for index, subtitle in enumerate(subtitles):
        start_sec = float(subtitle.get("start", 0.0) or 0.0)
        end_sec = float(subtitle.get("end", start_sec) or start_sec)
        out_ref = out_dir / f"subtitle_{index + 1:04d}_ref.wav"
        try:
            ref_path = extract_reference_audio_from_window(
                vocals_audio=source_audio,
                out_ref=out_ref,
                start_sec=start_sec,
                end_sec=end_sec,
                min_seconds=0.35,
                pad_seconds=0.12,
            )
        except Exception:
            ref_path = default_ref
        mapping[index] = ref_path
    if not mapping:
        mapping[0] = default_ref
    return mapping
