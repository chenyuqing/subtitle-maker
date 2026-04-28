from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

from subtitle_maker.core.ffmpeg import run_cmd, run_cmd_checked
from subtitle_maker.domains.media.probe import load_mono_audio, resample_mono_audio
from subtitle_maker.transcriber import format_srt, parse_srt


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS = 0.12
DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB = -35.0
DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB = 8.0
DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING = 0.95


def _to_mono_float32(wav: np.ndarray) -> np.ndarray:
    """把任意 shape 的波形统一成单声道 float32，供分析使用。"""

    audio = np.asarray(wav, dtype=np.float32)
    if audio.ndim > 1:
        return np.mean(audio, axis=1, dtype=np.float32)
    return audio


def _build_active_sample_mask(
    *,
    mono_audio: np.ndarray,
    sample_rate: int,
    threshold_db: float,
    frame_sec: float = 0.05,
    hop_sec: float = 0.01,
) -> np.ndarray:
    """基于短窗 RMS 估计活动语音区域，避免整条静音把 RMS 拉低。"""

    if mono_audio.size == 0 or sample_rate <= 0:
        return np.zeros(0, dtype=bool)

    frame_samples = max(1, int(sample_rate * max(0.005, frame_sec)))
    hop_samples = max(1, int(sample_rate * max(0.005, hop_sec)))
    threshold_rms = float(10 ** (float(threshold_db) / 20.0))
    mask = np.zeros(mono_audio.shape[0], dtype=bool)
    last_start = max(0, mono_audio.shape[0] - frame_samples)

    for start in range(0, last_start + 1, hop_samples):
        frame = mono_audio[start : start + frame_samples]
        if frame.size == 0:
            continue
        frame_rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        if frame_rms >= threshold_rms:
            mask[start : start + frame_samples] = True

    if mask.any():
        return mask

    # 极短句可能凑不满有效窗，这里退回逐样本阈值，避免误判为全静音。
    return np.abs(mono_audio) >= threshold_rms


def normalize_speech_audio_level(
    *,
    input_path: Path,
    output_path: Optional[Path] = None,
    target_rms: float = DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS,
    activity_threshold_db: float = DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB,
    max_gain_db: float = DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB,
    peak_ceiling: float = DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING,
) -> Dict[str, Any]:
    """按活动语音 RMS 统一句级音量，并返回归一化统计。"""

    source_path = Path(input_path).expanduser()
    target_path = Path(output_path).expanduser() if output_path is not None else source_path
    wav, sample_rate = sf.read(str(source_path))
    mono_audio = _to_mono_float32(wav)
    peak_before = float(np.max(np.abs(mono_audio))) if mono_audio.size > 0 else 0.0

    result: Dict[str, Any] = {
        "applied": False,
        "input_active_rms": None,
        "output_active_rms": None,
        "applied_gain_db": 0.0,
        "peak_before": round(peak_before, 6),
        "peak_after": round(peak_before, 6),
        "active_duration_sec": 0.0,
        "peak_limited": False,
    }
    if mono_audio.size == 0 or sample_rate <= 0:
        if target_path != source_path:
            shutil.copy2(source_path, target_path)
        return result

    active_mask = _build_active_sample_mask(
        mono_audio=mono_audio,
        sample_rate=sample_rate,
        threshold_db=activity_threshold_db,
    )
    if active_mask.size == 0 or not active_mask.any():
        if target_path != source_path:
            shutil.copy2(source_path, target_path)
        return result

    active_audio = mono_audio[active_mask]
    active_rms = float(np.sqrt(np.mean(np.square(active_audio), dtype=np.float64)))
    result["input_active_rms"] = round(active_rms, 6)
    result["active_duration_sec"] = round(float(active_audio.size / sample_rate), 6)
    if active_rms <= 1e-6:
        if target_path != source_path:
            shutil.copy2(source_path, target_path)
        return result

    safe_target_rms = max(1e-4, float(target_rms))
    safe_peak_ceiling = max(0.05, min(0.99, float(peak_ceiling)))
    linear_gain = safe_target_rms / active_rms
    gain_db = 20.0 * float(np.log10(max(linear_gain, 1e-8)))
    if gain_db > float(max_gain_db):
        gain_db = float(max_gain_db)
        linear_gain = float(10 ** (gain_db / 20.0))

    scaled = np.asarray(wav, dtype=np.float32) * linear_gain
    peak_after_gain = float(np.max(np.abs(scaled))) if scaled.size > 0 else 0.0
    peak_limited = False
    if peak_after_gain > safe_peak_ceiling:
        peak_limited = True
        peak_ratio = safe_peak_ceiling / max(peak_after_gain, 1e-8)
        scaled *= peak_ratio
        linear_gain *= peak_ratio
        gain_db = 20.0 * float(np.log10(max(linear_gain, 1e-8)))

    peak_after = float(np.max(np.abs(scaled))) if scaled.size > 0 else 0.0
    result["output_active_rms"] = round(active_rms * linear_gain, 6)
    result["applied_gain_db"] = round(gain_db, 4)
    result["peak_after"] = round(peak_after, 6)
    result["peak_limited"] = peak_limited

    needs_write = abs(gain_db) >= 0.1 or peak_limited or target_path != source_path
    if not needs_write:
        if target_path != source_path:
            shutil.copy2(source_path, target_path)
        return result

    target_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target_path), scaled, sample_rate)
    result["applied"] = True
    return result


def _resolve_output_path(path_text: Optional[str]) -> Optional[Path]:
    """把 manifest 中的相对或绝对路径解析为真实文件路径。"""
    if not path_text:
        return None
    raw = Path(path_text).expanduser()
    if raw.is_absolute():
        return raw
    return (REPO_ROOT / raw).resolve()


def _raise_command_error(
    *,
    cmd: List[str],
    code: int,
    out: str,
    err: str,
    error_prefix: Optional[str],
) -> None:
    """统一处理 ffmpeg 失败，并按旧脚本需要保留不同错误格式。"""
    if error_prefix:
        raise RuntimeError(f"{error_prefix}: {err.strip()}")
    raise RuntimeError(f"command failed ({code}): {' '.join(cmd)}\n{out}\n{err}")


def concat_wav_files(
    inputs: List[Path],
    output_wav: Path,
    *,
    sample_rate: int = 44100,
    error_on_empty: bool = False,
    error_prefix: Optional[str] = None,
) -> None:
    """使用 ffmpeg concat 拼接多个 wav；空输入时可选报错或直接返回。"""
    if not inputs:
        if error_on_empty:
            raise RuntimeError("no inputs for concat")
        return
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    concat_list = output_wav.parent / f"{output_wav.stem}_concat.txt"
    lines = []
    for item in inputs:
        escaped = str(item.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
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
        str(sample_rate),
        str(output_wav),
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        _raise_command_error(cmd=cmd, code=code, out=out, err=err, error_prefix=error_prefix)


def concat_generated_wavs(inputs: List[Path], output_wav: Path) -> None:
    """拼接单句 TTS 分片，保持 `dub_pipeline.py` 的旧错误语义。"""
    if not inputs:
        raise RuntimeError("E-TTS-001 no generated parts to concat")
    if len(inputs) == 1:
        shutil.copy2(inputs[0], output_wav)
        return
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    concat_list = output_wav.parent / f"{output_wav.stem}_parts_concat.txt"
    lines = []
    for item in inputs:
        escaped = str(item.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
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
        "22050",
        str(output_wav),
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"E-TTS-001 concat generated parts failed: {out}\n{err}")


def mix_with_bgm(
    *,
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    target_sr: int,
    error_prefix: Optional[str] = None,
) -> None:
    """混合配音人声和背景音，并允许旧脚本保留各自错误格式。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(vocals_path),
        "-i",
        str(bgm_path),
        "-filter_complex",
        "[0:a]volume=1.0[v];[1:a]volume=1.0[b];[v][b]amix=inputs=2:duration=longest:dropout_transition=0[m]",
        "-map",
        "[m]",
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        str(output_path),
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        _raise_command_error(cmd=cmd, code=code, out=out, err=err, error_prefix=error_prefix)


def mix_vocals_with_bgm(*, vocals_wav: Path, bgm_wav: Path, output_wav: Path) -> None:
    """长视频全时轴场景的固定采样率混音封装。"""
    mix_with_bgm(
        vocals_path=vocals_wav,
        bgm_path=bgm_wav,
        output_path=output_wav,
        target_sr=44100,
        error_prefix=None,
    )


def compose_vocals_master(
    *,
    segments: List[Dict[str, Any]],
    output_path: Path,
    source_audio_fallback: Optional[Path] = None,
) -> Tuple[Path, int]:
    """把逐句或逐段配音按时间轴回填为一条 master vocals。"""

    def resolve_compose_audio_path(segment: Dict[str, Any]) -> Optional[Path]:
        """解析用于混音的音频路径，优先 `seg_xxxx.wav`，避免误用 `*_missing.wav`。"""

        raw_text = str(segment.get("tts_audio_path") or "").strip()
        if not raw_text:
            return None
        raw_path = Path(raw_text).expanduser()
        seg_id = str(segment.get("id") or "").strip()
        if seg_id:
            canonical_path = raw_path.parent / f"{seg_id}.wav"
            if canonical_path.exists():
                return canonical_path
        if raw_path.exists():
            return raw_path
        return None

    valid_segments: List[Dict[str, Any]] = []
    for segment in segments:
        if bool(segment.get("skip_compose", False)):
            continue
        resolved_audio = resolve_compose_audio_path(segment)
        if resolved_audio is None:
            continue
        segment_for_compose = dict(segment)
        segment_for_compose["_compose_audio_path"] = str(resolved_audio)
        valid_segments.append(segment_for_compose)

    if not valid_segments:
        if source_audio_fallback is None:
            raise RuntimeError("E-TTS-001 no segment audio produced")
        wav, sr = sf.read(str(source_audio_fallback))
        if isinstance(wav, np.ndarray) and wav.ndim > 1:
            wav = wav.mean(axis=1)
        silence = np.zeros(len(wav), dtype=np.float32)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), silence, sr)
        return output_path, sr

    valid_segments.sort(key=lambda item: float(item["start_sec"]))
    first_audio, sr = sf.read(valid_segments[0]["_compose_audio_path"])
    if isinstance(first_audio, np.ndarray) and first_audio.ndim > 1:
        first_audio = first_audio.mean(axis=1)

    max_len = 0
    cached: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for index, segment in enumerate(valid_segments):
        wav, cur_sr = sf.read(segment["_compose_audio_path"])
        if isinstance(wav, np.ndarray) and wav.ndim > 1:
            wav = wav.mean(axis=1)
        if cur_sr != sr:
            # 容错：不同后端或失败占位音频可能出现采样率不一致，这里统一重采样到首段采样率再拼接。
            wav = resample_mono_audio(np.asarray(wav, dtype=np.float32), cur_sr, sr)

        start_sample = int(float(segment["start_sec"]) * sr)
        # 若存在“借静音后”的有效目标时长，合成窗口也要同步扩展，
        # 否则后续拼轨会再次截断尾音。
        if segment.get("effective_target_duration_sec") is not None:
            own_end_sec = float(segment["start_sec"]) + max(
                0.05, float(segment.get("effective_target_duration_sec", 0.0) or 0.0)
            )
        else:
            own_end_sec = float(segment.get("group_anchor_end_sec", segment["end_sec"]))
        own_end_sample = max(start_sample + 1, int(own_end_sec * sr))

        if index + 1 < len(valid_segments):
            next_start_sample = int(float(valid_segments[index + 1]["start_sec"]) * sr)
            if next_start_sample > start_sample:
                window_end_sample = min(own_end_sample, next_start_sample)
            else:
                window_end_sample = own_end_sample
        else:
            window_end_sample = own_end_sample

        max_allowed_len = max(1, window_end_sample - start_sample)
        clipped = np.asarray(wav, dtype=np.float32)[:max_allowed_len]
        cached.append((segment, clipped))
        max_len = max(max_len, start_sample + len(clipped))

    master = np.zeros(max_len, dtype=np.float32)
    for segment, wav in cached:
        start_sample = int(float(segment["start_sec"]) * sr)
        end_sample = start_sample + len(wav)
        master[start_sample:end_sample] = wav

    peak = float(np.max(np.abs(master))) if master.size > 0 else 1.0
    if peak > 0.99:
        master = master / peak * 0.99

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), master, sr)
    return output_path, sr


def build_full_timeline_vocals(
    *,
    results: List[Any],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """生成全时轴 vocals：命中的区间放配音，其他区间保持静音。"""
    base_audio, sample_rate = load_mono_audio(source_audio)
    if sample_rate <= 0:
        return None
    timeline = np.zeros(len(base_audio), dtype=np.float32)
    wrote_any = False
    for item in sorted(results, key=lambda x: x.start_sec):
        paths = item.manifest.get("paths", {})
        vocals_path = _resolve_output_path(paths.get("dubbed_vocals"))
        if not (vocals_path and vocals_path.exists()):
            continue
        seg_wav, seg_sr = load_mono_audio(vocals_path)
        if seg_wav.size == 0:
            continue
        if seg_sr != sample_rate:
            seg_wav = resample_mono_audio(seg_wav, seg_sr, sample_rate)
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
    results: List[Any],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """生成全时轴 mix：区间内优先放段内 mix，其次在线重建混音。"""
    base_audio, sample_rate = load_mono_audio(source_audio)
    if sample_rate <= 0:
        return None
    timeline = base_audio.copy()
    wrote_any = False
    for item in sorted(results, key=lambda x: x.start_sec):
        paths = item.manifest.get("paths", {})
        mix_path = _resolve_output_path(paths.get("dubbed_mix"))
        vocals_path = _resolve_output_path(paths.get("dubbed_vocals"))
        bgm_path = _resolve_output_path(paths.get("source_bgm"))

        seg_wav: Optional[np.ndarray] = None
        if mix_path and mix_path.exists():
            loaded_wav, loaded_sr = load_mono_audio(mix_path)
            if loaded_wav.size > 0:
                if loaded_sr != sample_rate:
                    loaded_wav = resample_mono_audio(loaded_wav, loaded_sr, sample_rate)
                seg_wav = loaded_wav

        # 性能优化场景可能关闭段内 mix 导出，此时在线用人声+BGM重建。
        if seg_wav is None and vocals_path and vocals_path.exists() and bgm_path and bgm_path.exists():
            vocals_wav, vocals_sr = load_mono_audio(vocals_path)
            bgm_wav, bgm_sr = load_mono_audio(bgm_path)
            if vocals_wav.size > 0 and bgm_wav.size > 0:
                if vocals_sr != sample_rate:
                    vocals_wav = resample_mono_audio(vocals_wav, vocals_sr, sample_rate)
                if bgm_sr != sample_rate:
                    bgm_wav = resample_mono_audio(bgm_wav, bgm_sr, sample_rate)
                min_len = min(len(vocals_wav), len(bgm_wav))
                if min_len > 0:
                    rebuilt_mix = vocals_wav[:min_len] + bgm_wav[:min_len]
                    peak = float(np.max(np.abs(rebuilt_mix))) if rebuilt_mix.size > 0 else 0.0
                    if peak > 0.99:
                        rebuilt_mix = rebuilt_mix / peak * 0.99
                    seg_wav = rebuilt_mix.astype(np.float32)

        # 最后兜底仍允许只放纯人声，避免整个区间丢失。
        if seg_wav is None and vocals_path and vocals_path.exists():
            loaded_wav, loaded_sr = load_mono_audio(vocals_path)
            if loaded_wav.size > 0:
                if loaded_sr != sample_rate:
                    loaded_wav = resample_mono_audio(loaded_wav, loaded_sr, sample_rate)
                seg_wav = loaded_wav

        if seg_wav is None or seg_wav.size == 0:
            continue

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


def build_full_timeline_bgm(
    *,
    results: List[Any],
    output_wav: Path,
    source_audio: Path,
) -> Optional[Path]:
    """生成全时轴 bgm：命中的区间放段内背景音，其余区间保持静音。"""
    base_audio, sample_rate = load_mono_audio(source_audio)
    if sample_rate <= 0:
        return None
    timeline = np.zeros(len(base_audio), dtype=np.float32)
    wrote_any = False
    for item in sorted(results, key=lambda x: x.start_sec):
        paths = item.manifest.get("paths", {})
        bgm_path = _resolve_output_path(paths.get("source_bgm"))
        if not (bgm_path and bgm_path.exists()):
            continue
        seg_wav, seg_sr = load_mono_audio(bgm_path)
        if seg_wav.size == 0:
            continue
        if seg_sr != sample_rate:
            seg_wav = resample_mono_audio(seg_wav, seg_sr, sample_rate)
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
    """把多段 SRT 按全局时间轴偏移拼接回一份完整字幕。"""
    merged: List[Dict[str, Any]] = []
    for path, offset_sec in inputs:
        subtitles = parse_srt(path.read_text(encoding="utf-8"))
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
    """把译文和原文双轨字幕按相同偏移拼接为双语字幕。"""
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
