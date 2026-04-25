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
    valid_segments = [
        segment
        for segment in segments
        if Path(segment["tts_audio_path"]).exists() and not bool(segment.get("skip_compose", False))
    ]
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
    first_audio, sr = sf.read(valid_segments[0]["tts_audio_path"])
    if isinstance(first_audio, np.ndarray) and first_audio.ndim > 1:
        first_audio = first_audio.mean(axis=1)

    max_len = 0
    cached: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for index, segment in enumerate(valid_segments):
        wav, cur_sr = sf.read(segment["tts_audio_path"])
        if isinstance(wav, np.ndarray) and wav.ndim > 1:
            wav = wav.mean(axis=1)
        if cur_sr != sr:
            raise RuntimeError("E-MIX-001 inconsistent segment sample rates")

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
