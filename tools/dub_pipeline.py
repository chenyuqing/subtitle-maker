#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import html
import json
import os
import re
import glob
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from sklearn.cluster import KMeans
import librosa

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from subtitle_maker.transcriber import SubtitleGenerator, format_srt, parse_srt
from subtitle_maker.translator import Translator
from subtitle_maker.qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel

# Exit-code contract for callers (e.g. dub_long_video.py)
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_OK_WITH_MANUAL_REVIEW = 2


def iso_now() -> str:
    return datetime.utcnow().isoformat()


def build_readable_run_id(*, root_dir: Path, time_tag: str) -> str:
    # 生成可读 ID：时间戳优先，冲突时追加递增序号，不使用随机串。
    base = time_tag
    candidate = base
    index = 2
    while (root_dir / candidate).exists():
        candidate = f"{base}_{index:02d}"
        index += 1
    return candidate


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def audio_duration(path: Path) -> float:
    return float(sf.info(str(path)).duration)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


class JsonlLogger:
    def __init__(self, path: Path, job_id: str):
        self.path = path
        self.job_id = job_id
        ensure_parent(path)

    def log(
        self,
        level: str,
        stage: str,
        event: str,
        message: str,
        *,
        segment_id: Optional[str] = None,
        progress: Optional[float] = None,
        elapsed_ms: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        item: Dict[str, Any] = {
            "ts": iso_now(),
            "level": level,
            "job_id": self.job_id,
            "stage": stage,
            "event": event,
            "message": message,
        }
        if segment_id is not None:
            item["segment_id"] = segment_id
        if progress is not None:
            item["progress"] = float(progress)
        if elapsed_ms is not None:
            item["elapsed_ms"] = int(elapsed_ms)
        if data is not None:
            item["data"] = data
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[{level}] {stage}:{event} - {message}")


@dataclass
class SeparationResult:
    source_audio: Path
    vocals_audio: Path
    bgm_audio: Optional[Path]
    separation_status: str
    separation_report: Path


def extract_audio(input_media: Path, source_audio: Path) -> None:
    ensure_parent(source_audio)
    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_media),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(source_audio),
        ]
    )
    if code != 0:
        raise RuntimeError(f"E-IO-001 ffmpeg extract failed: {err.strip()}")


def _find_demucs_stems(demucs_out: Path, model_name: str) -> Tuple[Optional[Path], Optional[Path]]:
    model_root = demucs_out / model_name
    vocals = list(model_root.glob("**/vocals.wav"))
    no_vocals = list(model_root.glob("**/no_vocals.wav"))
    vocals_path = vocals[0] if vocals else None
    no_vocals_path = no_vocals[0] if no_vocals else None
    return vocals_path, no_vocals_path


def run_demucs(
    input_audio: Path,
    out_root: Path,
    model_name: str,
    *,
    device: str,
) -> Tuple[Optional[Path], Optional[Path], str]:
    demucs_out = out_root / "demucs_tmp"
    demucs_out.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        model_name,
        "--two-stems=vocals",
        "-o",
        str(demucs_out),
        str(input_audio),
    ]
    if device and device != "auto":
        cmd.insert(6, "-d")
        cmd.insert(7, device)

    code, _, err = run_cmd(cmd)
    if code != 0:
        return None, None, err.strip() or "demucs failed"

    vocals, bgm = _find_demucs_stems(demucs_out, model_name)
    if vocals is None:
        return None, None, "vocals stem not found"
    return vocals, bgm, ""


def separate_audio(
    *,
    source_audio: Path,
    source_vocals: Path,
    source_bgm: Path,
    out_dir: Path,
    primary_model: str,
    fallback_model: str,
    separator_device: str,
    logger: JsonlLogger,
) -> SeparationResult:
    report: Dict[str, Any] = {
        "ts": iso_now(),
        "primary_model": primary_model,
        "fallback_model": fallback_model,
        "separator_device": separator_device,
        "status": "unknown",
        "attempts": [],
    }
    report_path = out_dir / "separation_report.json"

    logger.log("INFO", "separate_vocals", "separation_primary_started", "running primary separation model")
    primary_v, primary_b, primary_err = run_demucs(
        source_audio,
        out_dir,
        primary_model,
        device=separator_device,
    )
    report["attempts"].append(
        {
            "model": primary_model,
            "ok": primary_v is not None,
            "error": primary_err if primary_v is None else "",
        }
    )

    if primary_v is not None:
        ensure_parent(source_vocals)
        shutil.copy2(primary_v, source_vocals)
        if primary_b is not None:
            ensure_parent(source_bgm)
            shutil.copy2(primary_b, source_bgm)
        report["status"] = "ok"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return SeparationResult(
            source_audio=source_audio,
            vocals_audio=source_vocals,
            bgm_audio=source_bgm if source_bgm.exists() else None,
            separation_status="ok",
            separation_report=report_path,
        )

    logger.log(
        "WARN",
        "separate_vocals",
        "separation_primary_failed",
        "primary separator failed, trying fallback",
        data={"error": primary_err},
    )
    logger.log("INFO", "separate_vocals", "separation_fallback_started", "running fallback separation model")
    fallback_v, fallback_b, fallback_err = run_demucs(
        source_audio,
        out_dir,
        fallback_model,
        device=separator_device,
    )
    report["attempts"].append(
        {
            "model": fallback_model,
            "ok": fallback_v is not None,
            "error": fallback_err if fallback_v is None else "",
        }
    )

    if fallback_v is not None:
        ensure_parent(source_vocals)
        shutil.copy2(fallback_v, source_vocals)
        if fallback_b is not None:
            ensure_parent(source_bgm)
            shutil.copy2(fallback_b, source_bgm)
        report["status"] = "ok"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return SeparationResult(
            source_audio=source_audio,
            vocals_audio=source_vocals,
            bgm_audio=source_bgm if source_bgm.exists() else None,
            separation_status="ok",
            separation_report=report_path,
        )

    logger.log(
        "WARN",
        "separate_vocals",
        "separation_degraded_to_vocals_only",
        "all separator models failed, fallback to vocals-only mode",
        data={"error": fallback_err or primary_err},
    )
    ensure_parent(source_vocals)
    shutil.copy2(source_audio, source_vocals)
    report["status"] = "failed_fallback_vocals_only"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return SeparationResult(
        source_audio=source_audio,
        vocals_audio=source_vocals,
        bgm_audio=None,
        separation_status="failed_fallback_vocals_only",
        separation_report=report_path,
    )


def save_srt(subtitles: List[Dict[str, Any]], path: Path) -> None:
    ensure_parent(path)
    path.write_text(format_srt(subtitles), encoding="utf-8")


def analyze_subtitle_timestamps(
    subtitles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    # 统计字幕时间戳健康度：用于判定是否存在零时长/逆序/重叠等上游问题。
    total = len(subtitles)
    zero_or_negative = 0
    non_monotonic = 0
    overlap = 0
    previous_end = 0.0
    min_duration = None
    max_duration = 0.0
    for index, item in enumerate(subtitles):
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", start_sec) or start_sec)
        duration_sec = end_sec - start_sec
        if duration_sec <= 1e-6:
            zero_or_negative += 1
        if duration_sec > max_duration:
            max_duration = duration_sec
        if min_duration is None or duration_sec < min_duration:
            min_duration = duration_sec
        if index > 0 and start_sec < previous_end - 1e-6:
            overlap += 1
        if end_sec < start_sec - 1e-6:
            non_monotonic += 1
        previous_end = max(previous_end, end_sec)
    zero_ratio = (zero_or_negative / total) if total > 0 else 0.0
    return {
        "total": total,
        "zero_or_negative": zero_or_negative,
        "zero_ratio": round(zero_ratio, 4),
        "overlap": overlap,
        "non_monotonic": non_monotonic,
        "min_duration_sec": round(float(min_duration or 0.0), 4),
        "max_duration_sec": round(float(max_duration), 4),
    }


def trim_leading_silence_for_asr(
    *,
    input_audio: Path,
    output_audio: Path,
    min_silence_sec: float = 0.35,
    energy_ratio: float = 0.18,
) -> Tuple[Path, float]:
    # 裁掉前导静音，降低“长静音 + 短词”导致的 ASR 时间戳塌缩风险。
    wav, sample_rate = sf.read(str(input_audio))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size == 0 or sample_rate <= 0:
        return input_audio, 0.0

    window = max(1, int(0.02 * sample_rate))
    envelope = np.convolve(np.abs(mono), np.ones(window, dtype=np.float32) / window, mode="same")
    threshold = max(1e-5, float(np.percentile(envelope, 75) * float(energy_ratio)))
    active = np.where(envelope > threshold)[0]
    if active.size == 0:
        return input_audio, 0.0

    first_active_sample = int(active[0])
    leading_sec = float(first_active_sample / sample_rate)
    if leading_sec < float(min_silence_sec):
        return input_audio, 0.0

    trimmed = mono[first_active_sample:]
    if trimmed.size < int(0.5 * sample_rate):
        return input_audio, 0.0
    ensure_parent(output_audio)
    sf.write(str(output_audio), trimmed, sample_rate)
    return output_audio, leading_sec


def enforce_subtitle_timestamps(
    *,
    subtitles: List[Dict[str, Any]],
    media_duration_sec: float,
    min_duration_sec: float = 0.12,
) -> List[Dict[str, Any]]:
    # 时间戳守卫：确保每条字幕满足 end > start、整体单调、并限制在媒体时长内。
    if not subtitles:
        return subtitles
    safe_media_duration = max(float(media_duration_sec), float(min_duration_sec))
    output: List[Dict[str, Any]] = []
    cursor = 0.0
    for item in subtitles:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", start_sec) or start_sec)
        start_sec = max(0.0, min(start_sec, safe_media_duration))
        end_sec = max(0.0, min(end_sec, safe_media_duration))
        if start_sec < cursor:
            start_sec = cursor
        if end_sec <= start_sec:
            end_sec = min(safe_media_duration, start_sec + float(min_duration_sec))
        if end_sec <= start_sec:
            continue
        output.append(
            {
                "start": start_sec,
                "end": end_sec,
                "text": text,
            }
        )
        cursor = end_sec
        if cursor >= safe_media_duration - 1e-6:
            break
    return output


def parse_time_ranges_json(raw: Optional[str]) -> List[Tuple[float, float]]:
    # 解析时间区间 JSON，并标准化为不重叠有序区间。
    if not raw or not str(raw).strip():
        return []
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"invalid --time-ranges-json: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("--time-ranges-json must be a list")
    parsed: List[Tuple[float, float]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("--time-ranges-json item must be an object")
        start_sec = float(item.get("start_sec", item.get("start", 0.0)) or 0.0)
        end_sec = float(item.get("end_sec", item.get("end", start_sec)) or start_sec)
        if end_sec <= start_sec:
            continue
        parsed.append((start_sec, end_sec))
    return normalize_time_ranges(parsed)


def normalize_time_ranges(ranges: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    # 合并重叠时间区间，避免重复处理同一段时间。
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
    input_audio: Path,
    min_silence_sec: float,
    min_speech_sec: float,
    energy_ratio: float = 0.16,
) -> List[Tuple[float, float]]:
    # 基于短时能量检测语音活跃区间，用于自动选择要配音的时间段。
    wav, sample_rate = sf.read(str(input_audio))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size == 0 or sample_rate <= 0:
        return []

    frame_hop = max(1, int(0.02 * sample_rate))
    window = max(1, int(0.03 * sample_rate))
    envelope = np.convolve(np.abs(mono), np.ones(window, dtype=np.float32) / window, mode="same")
    threshold = max(1e-5, float(np.percentile(envelope, 75) * float(energy_ratio)))

    active_ranges: List[Tuple[float, float]] = []
    in_active = False
    start_sample = 0
    for index in range(0, len(envelope), frame_hop):
        is_active = bool(envelope[index] >= threshold)
        if is_active and not in_active:
            in_active = True
            start_sample = index
        elif (not is_active) and in_active:
            end_sample = index
            in_active = False
            active_ranges.append((start_sample / sample_rate, end_sample / sample_rate))
    if in_active:
        active_ranges.append((start_sample / sample_rate, len(envelope) / sample_rate))

    if not active_ranges:
        return []
    merged = []
    for start_sec, end_sec in active_ranges:
        if not merged:
            merged.append((start_sec, end_sec))
            continue
        prev_start, prev_end = merged[-1]
        if start_sec - prev_end <= float(min_silence_sec):
            merged[-1] = (prev_start, end_sec)
        else:
            merged.append((start_sec, end_sec))
    filtered = [(start_sec, end_sec) for start_sec, end_sec in merged if (end_sec - start_sec) >= float(min_speech_sec)]
    return normalize_time_ranges(filtered)


def filter_subtitles_by_time_ranges(
    *,
    subtitles: List[Dict[str, Any]],
    time_ranges: List[Tuple[float, float]],
    boundary_pad_sec: float = 0.20,
) -> List[Dict[str, Any]]:
    # 只保留与目标时间区间重叠的字幕，边界加少量缓冲避免句子被硬切。
    if not subtitles or not time_ranges:
        return subtitles
    output: List[Dict[str, Any]] = []
    for item in subtitles:
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", start_sec) or start_sec)
        for range_start, range_end in time_ranges:
            if min(end_sec, range_end + boundary_pad_sec) - max(start_sec, range_start - boundary_pad_sec) > 1e-6:
                output.append(item)
                break
    return output


def load_or_transcribe_subtitles(
    *,
    input_srt: Optional[Path],
    asr_audio: Path,
    source_srt_path: Path,
    asr_model_path: str,
    aligner_path: str,
    device: str,
    language: Optional[str],
    max_width: int,
    asr_balance_lines: bool,
    asr_balance_gap_sec: float,
    logger: JsonlLogger,
) -> List[Dict[str, Any]]:
    if input_srt is not None:
        text = input_srt.read_text(encoding="utf-8")
        subtitles = parse_srt(text)
        # 上传字幕统一做文本清洗：去 HTML 标签与括号说明，避免生成无效音。
        subtitles, changed_count = sanitize_subtitles_for_tts(subtitles)
        media_duration_sec = audio_duration(asr_audio)
        subtitles = enforce_subtitle_timestamps(
            subtitles=subtitles,
            media_duration_sec=media_duration_sec,
        )
        save_srt(subtitles, source_srt_path)
        logger.log(
            "INFO",
            "asr_align",
            "srt_loaded",
            "loaded existing srt input",
            data={"count": len(subtitles), "sanitized_lines": int(changed_count)},
        )
        return subtitles

    logger.log("INFO", "asr_align", "asr_started", "transcribing source audio")
    generator = SubtitleGenerator(
        model_path=asr_model_path,
        aligner_path=aligner_path,
        device=device,
        lazy_load=True,
    )
    try:
        asr_input_audio = asr_audio
        asr_offset_sec = 0.0
        trimmed_for_asr = source_srt_path.parent / "_asr_trimmed.wav"
        asr_input_audio, asr_offset_sec = trim_leading_silence_for_asr(
            input_audio=asr_audio,
            output_audio=trimmed_for_asr,
        )
        logger.log(
            "INFO",
            "asr_align",
            "asr_input_prepared",
            "prepared asr input audio (leading silence check)",
            data={
                "input_audio": str(asr_audio),
                "asr_audio": str(asr_input_audio),
                "leading_silence_trim_sec": round(float(asr_offset_sec), 3),
            },
        )

        generator.load_model()
        subtitles: List[Dict[str, Any]] = []
        # 参考 2. Generate Subtitles：使用分块识别降低长音频时间戳退化概率。
        for chunk_results in generator.transcribe_iter(
            str(asr_input_audio),
            language=language,
            chunk_size=30,
            preprocessed=False,
        ):
            subtitles.extend(generator.generate_subtitles(chunk_results, max_len=max_width))
        # ASR 结果也走相同清洗规则，统一后续 TTS 输入规范。
        subtitles, changed_count = sanitize_subtitles_for_tts(subtitles)
        if asr_offset_sec > 0.0:
            for item in subtitles:
                item["start"] = float(item.get("start", 0.0) or 0.0) + asr_offset_sec
                item["end"] = float(item.get("end", 0.0) or 0.0) + asr_offset_sec
        if asr_balance_lines:
            subtitles = rebalance_source_subtitles(
                subtitles=subtitles,
                max_gap_sec=asr_balance_gap_sec,
                logger=logger,
            )
        media_duration_sec = audio_duration(asr_audio)
        before_health = analyze_subtitle_timestamps(subtitles)
        subtitles = enforce_subtitle_timestamps(
            subtitles=subtitles,
            media_duration_sec=media_duration_sec,
        )
        after_health = analyze_subtitle_timestamps(subtitles)
        logger.log(
            "INFO",
            "asr_align",
            "asr_timestamp_health",
            "subtitle timestamp health checked",
            data={"before": before_health, "after": after_health, "sanitized_lines": int(changed_count)},
        )
        save_srt(subtitles, source_srt_path)
        logger.log("INFO", "asr_align", "asr_completed", "transcription completed", data={"count": len(subtitles)})
        return subtitles
    finally:
        try:
            trimmed_for_asr = source_srt_path.parent / "_asr_trimmed.wav"
            if trimmed_for_asr.exists():
                trimmed_for_asr.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            generator.unload_model()
            logger.log("INFO", "asr_align", "asr_released", "asr model released")
        except Exception:
            logger.log("WARN", "asr_align", "asr_release_failed", "asr model release failed")


def is_cjk_target_lang(target_lang: str) -> bool:
    lowered = (target_lang or "").strip().lower()
    markers = ["chinese", "中文", "mandarin", "cantonese", "zh", "japanese", "korean", "日文", "韩文"]
    return any(marker in lowered for marker in markers)


def is_sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?。！？][\"')\]]*\s*$", (text or "").strip()))


def is_orphan_like_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", (text or ""))
    if not compact:
        return True
    if len(compact) <= 1:
        return True
    if re.fullmatch(r"[,.;:!?，。！？、；：…]+", compact):
        return True
    orphan_words = {
        "of",
        "to",
        "the",
        "a",
        "an",
        "and",
        "or",
        "is",
        "are",
        "in",
        "on",
        "at",
        "的",
        "了",
        "吗",
        "呢",
        "啊",
        "吧",
    }
    return compact.lower() in orphan_words


def has_speakable_content(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    return any(char.isalnum() for char in compact)


def audio_is_effectively_silent(
    path: Path,
    *,
    rms_threshold: float = 0.005,
    peak_threshold: float = 0.02,
    min_duration_sec: float = 0.20,
) -> bool:
    if not path.exists():
        return True
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size == 0 or sample_rate <= 0:
        return True
    duration = float(mono.size / sample_rate)
    if duration < min_duration_sec:
        return True
    rms = float(np.sqrt(np.mean(mono * mono)))
    peak = float(np.max(np.abs(mono)))
    return rms < rms_threshold and peak < peak_threshold


def group_subtitle_is_empty(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    indices: List[int],
) -> bool:
    for index in indices:
        src = (subtitles[index].get("text") or "").strip()
        tgt = (translated_lines[index] if index < len(translated_lines) else "").strip()
        if has_speakable_content(src) or has_speakable_content(tgt):
            return False
    return True


def is_punctuation_only_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    return bool(re.fullmatch(r"[,.;:!?，。！？、；：…\"'`~\-—_(){}\[\]<>/|\\]+", compact))


def sanitize_subtitle_text(text: str) -> str:
    """清洗字幕文本，移除 HTML 与括号内情绪/舞台说明。"""
    # 先反转 HTML 实体，再去掉标签（如 <b>...</b>）。
    cleaned = html.unescape(text or "")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    # 递归移除常见括号内容（含中英文半角/全角），避免把情绪说明送入 TTS。
    bracket_patterns = [
        r"\[[^\[\]]*\]",
        r"\{[^{}]*\}",
        r"\([^()]*\)",
        r"【[^【】]*】",
        r"（[^（）]*）",
        r"｛[^｛｝]*｝",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in bracket_patterns:
            updated = re.sub(pattern, "", cleaned)
            if updated != cleaned:
                changed = True
                cleaned = updated

    # 统一空白，避免残留换行/多空格影响后续分组与合成。
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sanitize_subtitles_for_tts(subtitles: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """批量清洗字幕文本，返回新字幕列表与发生变更的行数。"""
    output: List[Dict[str, Any]] = []
    changed_count = 0
    for item in subtitles:
        old_text = str(item.get("text", "") or "")
        new_text = sanitize_subtitle_text(old_text)
        if new_text != old_text:
            changed_count += 1
        updated = dict(item)
        updated["text"] = new_text
        output.append(updated)
    return output, changed_count


def merge_text_lines(lines: List[str], *, cjk_mode: bool) -> str:
    if cjk_mode:
        merged = "".join((line or "").strip() for line in lines)
        merged = re.sub(r"\s+", "", merged)
        return merged

    merged = " ".join((line or "").strip() for line in lines)
    merged = re.sub(r"\s+", " ", merged).strip()
    merged = re.sub(r"\s+([,.;:!?])", r"\1", merged)
    return merged


def normalize_layout_compare(text: str, *, cjk_mode: bool) -> str:
    compact = re.sub(r"\s+", "", text or "")
    compact = re.sub(r"[,.;:!?，。！？、；：…\"'`]+", "", compact)
    if not cjk_mode:
        compact = compact.lower()
    return compact


def has_same_layout_content(before: str, after: str, *, cjk_mode: bool) -> bool:
    return normalize_layout_compare(before, cjk_mode=cjk_mode) == normalize_layout_compare(after, cjk_mode=cjk_mode)


def split_text_by_weights(
    *,
    text: str,
    durations: List[float],
    cjk_mode: bool,
) -> List[str]:
    count = len(durations)
    if count <= 0:
        return []
    if count == 1:
        return [text.strip()]

    safe_durations = [max(0.05, float(item)) for item in durations]
    total = sum(safe_durations) or 1.0

    if cjk_mode:
        chars = [char for char in text if char != "\n"]
        if not chars:
            return ["…"] * count

        mins = [1 if dur < 0.55 else 2 for dur in safe_durations]
        if len(chars) >= 2 * count:
            mins = [max(item, 2) for item in mins]
        if sum(mins) > len(chars):
            mins = [1] * count

        allocation = mins[:]
        remain = len(chars) - sum(allocation)
        for _ in range(remain):
            idx = max(range(count), key=lambda index: safe_durations[index] / (allocation[index] + 1.0))
            allocation[idx] += 1

        parts: List[str] = []
        cursor = 0
        for length in allocation:
            part = "".join(chars[cursor : cursor + length]).strip()
            cursor += length
            parts.append(part)

        for index in range(1, len(parts)):
            if re.fullmatch(r"[,.;:!?，。！？、；：…]+", parts[index] or ""):
                parts[index - 1] = (parts[index - 1] + parts[index]).strip()
                parts[index] = ""

        fixed = [part if part else "…" for part in parts]
        fixed = repair_orphan_parts(fixed, cjk_mode=True)
        return fixed

    words = [word for word in re.split(r"\s+", text.strip()) if word]
    if not words:
        return ["…"] * count

    mins = [2] * count if len(words) >= 2 * count else [1] * count
    if sum(mins) > len(words):
        mins = [0] * count
        for index in range(min(len(words), count)):
            mins[index] = 1

    allocation = mins[:]
    remain = len(words) - sum(allocation)
    for _ in range(remain):
        idx = max(range(count), key=lambda index: safe_durations[index] / (allocation[index] + 1.0))
        allocation[idx] += 1

    parts = []
    cursor = 0
    for length in allocation:
        part = " ".join(words[cursor : cursor + length]).strip()
        cursor += length
        parts.append(part if part else "…")
    return repair_orphan_parts(parts, cjk_mode=False)


def repair_orphan_parts(parts: List[str], *, cjk_mode: bool) -> List[str]:
    fixed = list(parts)
    for index, part in enumerate(fixed):
        if not is_orphan_like_line(part):
            continue

        if cjk_mode:
            if index > 0 and len(fixed[index - 1]) > 2:
                fixed[index] = fixed[index - 1][-1] + fixed[index]
                fixed[index - 1] = fixed[index - 1][:-1]
            elif index + 1 < len(fixed) and len(fixed[index + 1]) > 2:
                fixed[index] = fixed[index] + fixed[index + 1][0]
                fixed[index + 1] = fixed[index + 1][1:]
        else:
            if index > 0:
                prev_words = fixed[index - 1].split()
                if len(prev_words) > 2:
                    take = prev_words.pop()
                    fixed[index - 1] = " ".join(prev_words).strip() or fixed[index - 1]
                    fixed[index] = (take + " " + fixed[index]).strip()
                    continue
            if index + 1 < len(fixed):
                next_words = fixed[index + 1].split()
                if len(next_words) > 2:
                    take = next_words.pop(0)
                    fixed[index + 1] = " ".join(next_words).strip() or fixed[index + 1]
                    fixed[index] = (fixed[index] + " " + take).strip()

    return [item.strip() if item.strip() else "…" for item in fixed]


def reflow_cluster_with_llm(
    *,
    translator: Translator,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    indices: List[int],
    target_lang: str,
) -> List[str]:
    rows = []
    for row_no, idx in enumerate(indices, start=1):
        duration = float(subtitles[idx]["end"]) - float(subtitles[idx]["start"])
        rows.append(
            f"{row_no}. [{duration:.2f}s]\n"
            f"SRC: {subtitles[idx]['text']}\n"
            f"CUR: {translated_lines[idx]}"
        )

    prompt = (
        f"Rewrite subtitle lines in {target_lang} with better layout.\n"
        f"You MUST output exactly {len(indices)} numbered lines.\n"
        "Rules:\n"
        "1) Keep meaning and speaking order.\n"
        "2) Keep each line non-empty.\n"
        "3) Avoid orphan particles or punctuation-only lines.\n"
        "4) Match line lengths to durations (short duration => shorter line).\n"
        "5) Return numbered lines only.\n\n"
        "Input:\n"
        + "\n\n".join(rows)
    )

    response = translator.client.chat.completions.create(
        model=translator.model,
        messages=[
            {"role": "system", "content": "You are a subtitle layout editor for dubbing."},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    content = (response.choices[0].message.content or "").strip()
    return translator._parse_translated_lines(content, len(indices))


def smart_layout_translated_lines(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    translator: Translator,
    target_lang: str,
    enabled: bool,
    max_gap_sec: float,
    use_llm: bool,
    logger: JsonlLogger,
) -> List[str]:
    if not enabled or len(subtitles) <= 1:
        return translated_lines

    cjk_mode = is_cjk_target_lang(target_lang)
    output = list(translated_lines)

    clusters: List[List[int]] = []
    current = [0]
    for idx in range(len(subtitles) - 1):
        cur_text = (subtitles[idx]["text"] or "").strip()
        next_start = float(subtitles[idx + 1]["start"])
        cur_end = float(subtitles[idx]["end"])
        gap = next_start - cur_end

        keep_cluster = (not is_sentence_end(cur_text)) and (gap <= max_gap_sec)
        if keep_cluster:
            current.append(idx + 1)
        else:
            if len(current) > 1:
                clusters.append(current[:])
            current = [idx + 1]
    if len(current) > 1:
        clusters.append(current[:])

    adjusted_clusters = 0
    for cluster in clusters:
        cluster_lines = [output[idx] for idx in cluster]
        if not any(is_orphan_like_line(line) for line in cluster_lines):
            continue

        durations = [float(subtitles[idx]["end"]) - float(subtitles[idx]["start"]) for idx in cluster]
        fallback_text = merge_text_lines(cluster_lines, cjk_mode=cjk_mode)
        fixed = split_text_by_weights(text=fallback_text, durations=durations, cjk_mode=cjk_mode)

        if use_llm:
            try:
                candidate = reflow_cluster_with_llm(
                    translator=translator,
                    subtitles=subtitles,
                    translated_lines=output,
                    indices=cluster,
                    target_lang=target_lang,
                )
                candidate_merged = merge_text_lines(candidate, cjk_mode=cjk_mode)
                if (
                    len(candidate) == len(cluster)
                    and all(item.strip() for item in candidate)
                    and has_same_layout_content(fallback_text, candidate_merged, cjk_mode=cjk_mode)
                ):
                    fixed = candidate
            except Exception:
                pass

        for local_index, global_index in enumerate(cluster):
            output[global_index] = fixed[local_index].strip()
        adjusted_clusters += 1

    if adjusted_clusters > 0:
        logger.log(
            "INFO",
            "translate",
            "layout_reflow_applied",
            "smart translation layout applied",
            data={"clusters": adjusted_clusters},
        )
    return output


def repair_punctuation_only_translations(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    translator: Translator,
    target_lang: str,
    logger: JsonlLogger,
) -> List[str]:
    bad_indices: List[int] = []
    for index, (subtitle, translated) in enumerate(zip(subtitles, translated_lines)):
        src_text = (subtitle.get("text") or "").strip()
        tgt_text = (translated or "").strip()
        if has_speakable_content(src_text) and is_punctuation_only_text(tgt_text):
            bad_indices.append(index)

    if not bad_indices:
        return translated_lines

    retry_inputs = [subtitles[index]["text"] for index in bad_indices]
    retry_system_prompt = (
        "You are a professional subtitle translator. "
        "Translate each input line faithfully and naturally. "
        "Never output only punctuation or ellipsis."
    )
    retried = translator.translate_batch(
        retry_inputs,
        target_lang=target_lang,
        system_prompt=retry_system_prompt,
        chunk_size=50,
    )

    output = list(translated_lines)
    fixed_count = 0
    fallback_source_count = 0
    for index, candidate in zip(bad_indices, retried):
        text = (candidate or "").strip()
        if text and has_speakable_content(text) and not is_punctuation_only_text(text):
            output[index] = text
            fixed_count += 1
        else:
            output[index] = (subtitles[index].get("text") or "").strip()
            fallback_source_count += 1

    logger.log(
        "WARN",
        "translate",
        "punct_only_translation_repaired",
        "punctuation-only translations repaired",
        data={
            "lines": len(bad_indices),
            "fixed_by_retry": fixed_count,
            "fallback_source": fallback_source_count,
        },
    )
    return output


def infer_cjk_mode_from_lines(lines: List[str]) -> bool:
    merged = "".join(lines)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", merged))
    latin_count = len(re.findall(r"[A-Za-z]", merged))
    return cjk_count > 0 and cjk_count >= max(1, latin_count // 2)


def rebalance_source_subtitles(
    *,
    subtitles: List[Dict[str, Any]],
    max_gap_sec: float,
    logger: JsonlLogger,
) -> List[Dict[str, Any]]:
    if len(subtitles) <= 1:
        return subtitles

    output = [dict(item) for item in subtitles]
    clusters: List[List[int]] = []
    current = [0]

    for idx in range(len(output) - 1):
        cur_text = (output[idx].get("text") or "").strip()
        next_text = (output[idx + 1].get("text") or "").strip()
        gap = float(output[idx + 1]["start"]) - float(output[idx]["end"])
        keep_cluster = (
            gap <= max_gap_sec
            and (
                not is_sentence_end(cur_text)
                or is_orphan_like_line(cur_text)
                or is_orphan_like_line(next_text)
            )
        )
        if keep_cluster:
            current.append(idx + 1)
        else:
            if len(current) > 1:
                clusters.append(current[:])
            current = [idx + 1]
    if len(current) > 1:
        clusters.append(current[:])

    changed_clusters = 0
    for cluster in clusters:
        lines = [(output[index].get("text") or "").strip() for index in cluster]
        if not any(is_orphan_like_line(line) for line in lines):
            continue

        durations = [float(output[index]["end"]) - float(output[index]["start"]) for index in cluster]
        cjk_mode = infer_cjk_mode_from_lines(lines)
        merged_text = merge_text_lines(lines, cjk_mode=cjk_mode)
        redistributed = split_text_by_weights(
            text=merged_text,
            durations=durations,
            cjk_mode=cjk_mode,
        )
        if len(redistributed) != len(cluster):
            continue
        for local_index, global_index in enumerate(cluster):
            output[global_index]["text"] = redistributed[local_index].strip()
        changed_clusters += 1

    if changed_clusters > 0:
        logger.log(
            "INFO",
            "asr_align",
            "source_layout_rebalanced",
            "source subtitle lines rebalanced",
            data={"clusters": changed_clusters},
        )
    return output


def wrap_subtitle_text(text: str, *, target_lang: str, cjk_max_chars: int) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if "\n" in cleaned:
        return cleaned
    if not is_cjk_target_lang(target_lang):
        return cleaned

    compact = re.sub(r"\s+", "", cleaned)
    if len(compact) <= cjk_max_chars:
        return compact

    ideal = len(compact) // 2
    candidate_positions = [match.start() + 1 for match in re.finditer(r"[，。！？、；：,.!?]", compact)]
    if candidate_positions:
        split_at = min(candidate_positions, key=lambda pos: abs(pos - ideal))
    else:
        split_at = ideal
    left = compact[:split_at].strip()
    right = compact[split_at:].strip()
    if not left or not right:
        return compact
    return f"{left}\n{right}"


def build_display_groups(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    max_gap_sec: float,
) -> List[List[int]]:
    if len(subtitles) <= 1:
        return [[index] for index in range(len(subtitles))]

    groups: List[List[int]] = []
    current = [0]
    for idx in range(len(subtitles) - 1):
        cur_src = (subtitles[idx].get("text") or "").strip()
        cur_tgt = (translated_lines[idx] or "").strip()
        next_tgt = (translated_lines[idx + 1] or "").strip()
        gap = float(subtitles[idx + 1]["start"]) - float(subtitles[idx]["end"])

        should_merge = (
            gap <= max_gap_sec
            and (
                not is_sentence_end(cur_src)
                or is_orphan_like_line(cur_tgt)
                or is_orphan_like_line(next_tgt)
            )
        )
        if should_merge:
            current.append(idx + 1)
        else:
            groups.append(current[:])
            current = [idx + 1]
    groups.append(current[:])
    return groups


def build_translation_prompt(lines: List[str], durations: List[float], target_lang: str) -> str:
    rows = []
    for idx, (text, dur) in enumerate(zip(lines, durations), start=1):
        rows.append(f"{idx}. [{dur:.2f}s] {text}")
    packed = "\n".join(rows)
    return (
        f"Translate each subtitle line into {target_lang}.\n"
        "Rules:\n"
        "1) Keep line count exactly the same.\n"
        "2) Keep meaning and tone.\n"
        "3) Keep the translation concise so it can be spoken within the target duration.\n"
        "4) Do NOT output timestamps or bracketed durations.\n"
        "5) Return ONLY numbered translated lines.\n\n"
        f"Input:\n{packed}\n"
    )


def translate_batch_with_budget(
    *,
    translator: Translator,
    lines: List[str],
    durations: List[float],
    target_lang: str,
    system_prompt: Optional[str],
    chunk_size: int = 80,
) -> List[str]:
    translated: List[str] = []
    total = len(lines)
    for start in range(0, total, chunk_size):
        chunk_lines = lines[start : start + chunk_size]
        chunk_durations = durations[start : start + chunk_size]
        content = build_translation_prompt(chunk_lines, chunk_durations, target_lang)
        response = translator.client.chat.completions.create(
            model=translator.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                    if system_prompt and system_prompt.strip()
                    else "You are a professional subtitle dubbing translator.",
                },
                {"role": "user", "content": content},
            ],
            stream=False,
        )
        output = (response.choices[0].message.content or "").strip()
        parsed = translator._parse_translated_lines(output, len(chunk_lines))
        translated.extend(parsed)
    return translated


def retranslate_single_line(
    *,
    translator: Translator,
    source_text: str,
    current_translation: str,
    target_lang: str,
    target_duration_sec: float,
    need_shorter: bool,
    aggressiveness: int,
) -> str:
    direction = "shorter" if need_shorter else "slightly longer"
    prompt = (
        f"Rewrite the translated subtitle in {target_lang}.\n"
        f"Goal: make it {direction} while preserving meaning.\n"
        f"Target speaking duration: {target_duration_sec:.2f}s.\n"
        f"Aggressiveness: {aggressiveness}/2.\n\n"
        f"Source: {source_text}\n"
        f"Current translation: {current_translation}\n\n"
        "Return ONE line only. No numbering. No explanations."
    )
    response = translator.client.chat.completions.create(
        model=translator.model,
        messages=[
            {"role": "system", "content": "You rewrite subtitle lines for dubbing duration fit."},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    text = (response.choices[0].message.content or "").strip()
    return text or current_translation


def extract_reference_audio(
    *,
    vocals_audio: Path,
    out_ref: Path,
    seconds: float,
) -> Path:
    audio, sr = sf.read(str(vocals_audio))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    abs_audio = np.abs(audio.astype(np.float32))
    if abs_audio.size == 0:
        raise RuntimeError("E-REF-001 invalid vocals energy")

    kernel = max(1, int(sr * 0.02))
    smoothed = np.convolve(abs_audio, np.ones(kernel, dtype=np.float32) / kernel, mode="same")
    threshold = max(1e-4, float(np.percentile(smoothed, 75) * 0.2))
    speech_indices = np.where(smoothed > threshold)[0]
    start_idx = int(speech_indices[0]) if speech_indices.size > 0 else 0
    end_idx = min(len(audio), start_idx + int(seconds * sr))
    ref = audio[start_idx:end_idx]
    if len(ref) < int(0.8 * sr):
        raise RuntimeError("E-REF-001 extracted reference too short")

    ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sr)
    return out_ref


def extract_reference_audio_from_offset(
    *,
    vocals_audio: Path,
    out_ref: Path,
    seconds: float,
    start_sec: float,
) -> Path:
    # 按时间偏移提取参考音色片段，用于多人模式构造多个参考音
    audio, sr = sf.read(str(vocals_audio))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    start_sample = max(0, int(float(start_sec) * sr))
    end_sample = min(len(audio), start_sample + int(max(0.8, float(seconds)) * sr))
    ref = audio[start_sample:end_sample]
    if len(ref) < int(0.8 * sr):
        raise RuntimeError("E-REF-001 extracted reference too short")

    ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sr)
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
    # 按字幕时间窗口切片参考音：用于“每条字幕对应原人声片段做音色/情绪参考”
    audio, sr = sf.read(str(vocals_audio))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    total_sec = len(audio) / float(sr)
    safe_start = max(0.0, float(start_sec) - float(pad_seconds))
    safe_end = min(total_sec, float(end_sec) + float(pad_seconds))
    if safe_end <= safe_start:
        safe_end = min(total_sec, safe_start + max(0.2, float(min_seconds)))

    start_sample = int(safe_start * sr)
    end_sample = int(safe_end * sr)
    ref = audio[start_sample:end_sample]

    # 片段过短时，围绕中点扩张到最短长度，避免 TTS 参考音不足
    min_len = int(max(0.2, float(min_seconds)) * sr)
    if len(ref) < min_len:
        mid = (start_sample + end_sample) // 2
        half = min_len // 2
        new_start = max(0, mid - half)
        new_end = min(len(audio), new_start + min_len)
        new_start = max(0, new_end - min_len)
        ref = audio[new_start:new_end]

    if len(ref) < int(0.2 * sr):
        raise RuntimeError("E-REF-001 extracted reference too short from subtitle window")

    ensure_parent(out_ref)
    sf.write(str(out_ref), ref, sr)
    return out_ref


def run_simple_diarization(
    *,
    vocals_audio: Path,
    speaker_mode: str,
    window_sec: float = 1.2,
    hop_sec: float = 0.6,
) -> List[Dict[str, Any]]:
    # 简易说话人分离：按时间窗提取 MFCC 特征，再做 KMeans 聚类得到 speaker_id + 时间段
    wav, sr = sf.read(str(vocals_audio))
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if wav.size == 0:
        raise RuntimeError("E-SPK-001 empty vocals audio for diarization")

    wav = wav.astype(np.float32)
    total_sec = len(wav) / float(sr)
    if total_sec <= 0.3:
        return [{"start": 0.0, "end": max(0.3, total_sec), "speaker_id": "spk_1"}]

    frame_len = max(int(window_sec * sr), int(0.8 * sr))
    hop_len = max(int(hop_sec * sr), int(0.35 * sr))

    windows: List[Tuple[float, float, np.ndarray]] = []
    cursor = 0
    while cursor < len(wav):
        end = min(len(wav), cursor + frame_len)
        chunk = wav[cursor:end]
        if len(chunk) >= int(0.35 * sr):
            windows.append((cursor / sr, end / sr, chunk))
        if end >= len(wav):
            break
        cursor += hop_len

    if not windows:
        return [{"start": 0.0, "end": max(0.3, total_sec), "speaker_id": "spk_1"}]

    feats: List[np.ndarray] = []
    for _, _, chunk in windows:
        # 关键逻辑：用 MFCC 均值+方差作为窗口级说话人嵌入
        mfcc = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=20)
        feat = np.concatenate([np.mean(mfcc, axis=1), np.std(mfcc, axis=1)], axis=0)
        feats.append(feat.astype(np.float32))

    X = np.vstack(feats)
    target_clusters = 2 if speaker_mode in {"auto", "per-speaker"} else 1
    target_clusters = max(1, min(target_clusters, len(X)))

    if target_clusters == 1:
        labels = np.zeros(len(windows), dtype=np.int32)
    else:
        kmeans = KMeans(n_clusters=target_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)

    segments: List[Dict[str, Any]] = []
    for index, (start, end, _) in enumerate(windows):
        segments.append(
            {
                "start": float(start),
                "end": float(end),
                "speaker_id": f"spk_{int(labels[index]) + 1}",
            }
        )
    return segments


def resolve_pyannote_model_source(model_id_or_path: str) -> str:
    # 解析 pyannote 模型来源：优先用户给的绝对路径，其次尝试本地 HF 缓存，最后回退到模型 ID
    raw = (model_id_or_path or "").strip()
    if not raw:
        raw = "pyannote/speaker-diarization-community-1"

    direct = Path(raw).expanduser()
    if direct.exists():
        if direct.is_dir():
            config = direct / "config.yaml"
            if config.exists():
                return str(config)
        return str(direct)

    if raw == "pyannote/speaker-diarization-community-1":
        snapshot_glob = (
            Path.home()
            / ".cache"
            / "huggingface"
            / "hub"
            / "models--pyannote--speaker-diarization-community-1"
            / "snapshots"
            / "*"
        )
        candidates = [Path(item) for item in glob.glob(str(snapshot_glob))]
        candidates = [item for item in candidates if item.exists()]
        if candidates:
            latest = max(candidates, key=lambda item: item.stat().st_mtime)
            return str(latest)

    return raw


def run_pyannote_diarization(
    *,
    vocals_audio: Path,
    model_id_or_path: str,
    hf_token: Optional[str],
    device: str,
) -> List[Dict[str, Any]]:
    # 使用 pyannote 官方 diarization 模型输出说话人时间段，满足“先分说话人再逐句映射”
    try:
        from pyannote.audio import Pipeline
    except Exception as exc:
        raise RuntimeError(f"E-SPK-101 pyannote unavailable: {exc}") from exc

    source = resolve_pyannote_model_source(model_id_or_path)
    load_kwargs: Dict[str, Any] = {}
    if hf_token:
        load_kwargs["token"] = hf_token
    pipeline = Pipeline.from_pretrained(source, **load_kwargs)

    # 关键逻辑：尽量把 diarization 放到可用设备；失败不阻塞，继续用默认设备
    try:
        if device == "auto":
            run_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            run_device = torch.device(device)
        pipeline.to(run_device)
    except Exception:
        pass

    diarization = pipeline(str(vocals_audio))
    segments: List[Dict[str, Any]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        start = float(turn.start)
        end = float(turn.end)
        if end <= start:
            continue
        segments.append(
            {
                "start": start,
                "end": end,
                "speaker_id": str(speaker),
            }
        )
    if not segments:
        raise RuntimeError("E-SPK-102 pyannote returned empty diarization")
    return segments


def run_pyannote_diarization_external(
    *,
    vocals_audio: Path,
    model_id_or_path: str,
    hf_token: Optional[str],
    device: str,
    python_bin: str,
    job_dir: Path,
) -> List[Dict[str, Any]]:
    # 使用独立 Python 环境跑 pyannote，避免与主项目 torch/torchaudio 版本冲突
    if not python_bin.strip():
        raise RuntimeError("E-SPK-103 missing external python bin for pyannote")

    worker = REPO_ROOT / "tools" / "pyannote_diarize_worker.py"
    output_json = job_dir / "refs" / "pyannote_external_segments.json"
    ensure_parent(output_json)
    cmd = [
        python_bin,
        str(worker),
        "--audio",
        str(vocals_audio),
        "--model-source",
        resolve_pyannote_model_source(model_id_or_path),
        "--output-json",
        str(output_json),
        "--device",
        device,
    ]
    if hf_token:
        cmd.extend(["--hf-token", hf_token])
    code, out, err = run_cmd(cmd, cwd=REPO_ROOT)
    if code != 0:
        raise RuntimeError(f"E-SPK-104 external pyannote failed: {err.strip() or out.strip()}")
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    segments = payload.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise RuntimeError("E-SPK-105 external pyannote returned empty segments")
    return segments


def assign_speakers_to_subtitles(
    *,
    subtitles: List[Dict[str, Any]],
    diar_segments: List[Dict[str, Any]],
) -> List[str]:
    # 将每条字幕按时间重叠映射到 speaker_id
    if not subtitles:
        return []
    if not diar_segments:
        return ["spk_1" for _ in subtitles]

    assigned: List[str] = []
    for sub in subtitles:
        s0 = float(sub.get("start", 0.0) or 0.0)
        s1 = float(sub.get("end", s0) or s0)
        best_spk = "spk_1"
        best_overlap = -1.0
        for seg in diar_segments:
            d0 = float(seg.get("start", 0.0) or 0.0)
            d1 = float(seg.get("end", d0) or d0)
            overlap = max(0.0, min(s1, d1) - max(s0, d0))
            if overlap > best_overlap:
                best_overlap = overlap
                best_spk = str(seg.get("speaker_id") or "spk_1")
        assigned.append(best_spk)
    return assigned


def build_speaker_ref_map(
    *,
    subtitles: List[Dict[str, Any]],
    subtitle_speakers: List[str],
    vocals_audio: Path,
    out_dir: Path,
    default_ref: Path,
) -> Dict[str, Path]:
    # 为每个 speaker 选择一个代表性字幕时间段，并抽取该说话人的参考音色
    out_dir.mkdir(parents=True, exist_ok=True)
    speaker_best: Dict[str, Tuple[float, float]] = {}
    for idx, spk in enumerate(subtitle_speakers):
        if idx >= len(subtitles):
            continue
        s0 = float(subtitles[idx].get("start", 0.0) or 0.0)
        s1 = float(subtitles[idx].get("end", s0) or s0)
        dur = max(0.0, s1 - s0)
        prev = speaker_best.get(spk)
        if prev is None or dur > (prev[1] - prev[0]):
            speaker_best[spk] = (s0, s1)

    mapping: Dict[str, Path] = {}
    for spk, (s0, s1) in speaker_best.items():
        out_ref = out_dir / f"{spk}_ref.wav"
        try:
            mapping[spk] = extract_reference_audio_from_window(
                vocals_audio=vocals_audio,
                out_ref=out_ref,
                start_sec=s0,
                end_sec=s1,
                min_seconds=0.8,
                pad_seconds=0.2,
            )
        except Exception:
            mapping[spk] = default_ref
    if not mapping:
        mapping["spk_1"] = default_ref
    return mapping


def build_subtitle_reference_map(
    *,
    subtitles: List[Dict[str, Any]],
    source_audio: Path,
    out_dir: Path,
    default_ref: Path,
) -> Dict[int, Path]:
    # 按字幕时间窗逐句抽取“原音频”参考：用于音色克隆和情绪参考一一对应
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


def extract_multi_speaker_references(
    *,
    vocals_audio: Path,
    out_dir: Path,
    seconds: float,
    speaker_count: int,
) -> List[Path]:
    # 多人模式下，基于语音能量分布抽取多个参考音色（不依赖额外分离/说话人模型）
    count = max(1, int(speaker_count))
    if count == 1:
        single = out_dir / "speaker_01_ref.wav"
        return [extract_reference_audio(vocals_audio=vocals_audio, out_ref=single, seconds=seconds)]

    audio, sr = sf.read(str(vocals_audio))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size == 0:
        raise RuntimeError("E-REF-001 empty vocals audio")

    abs_audio = np.abs(audio.astype(np.float32))
    kernel = max(1, int(sr * 0.02))
    smoothed = np.convolve(abs_audio, np.ones(kernel, dtype=np.float32) / kernel, mode="same")
    threshold = max(1e-4, float(np.percentile(smoothed, 75) * 0.2))
    speech_indices = np.where(smoothed > threshold)[0]
    if speech_indices.size == 0:
        speech_indices = np.array([0], dtype=np.int64)

    pick_positions = np.linspace(0, speech_indices.size - 1, num=count, dtype=int)
    picked_starts: List[int] = []
    min_gap_samples = int(max(0.8, float(seconds) * 0.6) * sr)
    for pos in pick_positions:
        candidate = int(speech_indices[pos])
        if not picked_starts or all(abs(candidate - prior) >= min_gap_samples for prior in picked_starts):
            picked_starts.append(candidate)

    # 去重后数量不足时，用“中段偏移”继续补齐，保证下游至少拿到 count 个参考
    fallback = 0
    total_samples = len(audio)
    while len(picked_starts) < count:
        candidate = int((fallback + 0.5) / count * total_samples)
        fallback += 1
        if all(abs(candidate - prior) >= min_gap_samples // 2 for prior in picked_starts):
            picked_starts.append(candidate)
        elif fallback > count * 4:
            picked_starts.append(candidate)

    out_dir.mkdir(parents=True, exist_ok=True)
    refs: List[Path] = []
    for idx, start_sample in enumerate(picked_starts[:count], start=1):
        out_ref = out_dir / f"speaker_{idx:02d}_ref.wav"
        start_sec = max(0.0, float(start_sample) / sr)
        refs.append(
            extract_reference_audio_from_offset(
                vocals_audio=vocals_audio,
                out_ref=out_ref,
                seconds=seconds,
                start_sec=start_sec,
            )
        )
    return refs


def build_time_bucket_ref_selector(
    *,
    subtitles: List[Dict[str, Any]],
    ref_audio_paths: List[Path],
) -> Callable[[int], Path]:
    # 用字幕时间做分桶：将早/中/晚段落映射到不同参考音色，提升多人可控性
    paths = ref_audio_paths[:] if ref_audio_paths else []
    if not paths:
        raise RuntimeError("E-REF-001 no reference audio paths provided")
    if len(paths) == 1:
        return lambda _idx: paths[0]

    max_end = max(float(item.get("end", 0.0) or 0.0) for item in subtitles) if subtitles else 0.0
    safe_total = max(max_end, 0.001)
    bucket_count = len(paths)

    def _selector(index: int) -> Path:
        if not subtitles:
            return paths[0]
        clamped = min(max(0, int(index)), len(subtitles) - 1)
        start_sec = float(subtitles[clamped].get("start", 0.0) or 0.0)
        ratio = min(0.999999, max(0.0, start_sec / safe_total))
        bucket = int(ratio * bucket_count)
        bucket = min(bucket_count - 1, max(0, bucket))
        return paths[bucket]

    return _selector


def apply_atempo(
    *,
    input_path: Path,
    output_path: Path,
    tempo: float,
) -> None:
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
    wav, sr = sf.read(str(input_path))
    if sr <= 0:
        raise RuntimeError("E-ALN-001 invalid sample rate")
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        mono = wav.mean(axis=1)
    else:
        mono = np.asarray(wav)
    mono = np.asarray(mono, dtype=np.float32)

    full_duration = float(len(mono) / sr) if len(mono) > 0 else 0.0
    if mono.size == 0:
        shutil.copy2(input_path, output_path)
        return full_duration, full_duration

    threshold_amp = float(10 ** (threshold_db / 20.0))
    active = np.where(np.abs(mono) >= threshold_amp)[0]
    if active.size == 0:
        shutil.copy2(input_path, output_path)
        return full_duration, full_duration

    pad_samples = max(0, int(pad_sec * sr))
    start = max(0, int(active[0]) - pad_samples)
    end = min(len(mono), int(active[-1]) + 1 + pad_samples)
    min_keep_samples = max(1, int(min_keep_sec * sr))

    if end - start < min_keep_samples:
        center = int((start + end) / 2)
        half = int(min_keep_samples / 2)
        start = max(0, center - half)
        end = min(len(mono), start + min_keep_samples)

    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        trimmed = wav[start:end, :]
    else:
        trimmed = wav[start:end]

    ensure_parent(output_path)
    sf.write(str(output_path), trimmed, sr)
    trimmed_duration = float(max(0, end - start) / sr)
    return full_duration, trimmed_duration


def fit_audio_to_duration(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> None:
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
    # 仅做时长上限裁剪，不做变速，避免“时快时慢”的听感。
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


def compose_vocals_master(
    *,
    segments: List[Dict[str, Any]],
    output_path: Path,
    source_audio_fallback: Optional[Path] = None,
) -> Tuple[Path, int]:
    valid_segments = [
        segment
        for segment in segments
        if Path(segment["tts_audio_path"]).exists() and not bool(segment.get("skip_compose", False))
    ]
    if not valid_segments:
        # 没有任何待合成片段时输出与源音频等长的静音轨，保证后续混音/导出不中断。
        if source_audio_fallback is None:
            raise RuntimeError("E-TTS-001 no segment audio produced")
        wav, sr = sf.read(str(source_audio_fallback))
        if isinstance(wav, np.ndarray) and wav.ndim > 1:
            wav = wav.mean(axis=1)
        silence = np.zeros(len(wav), dtype=np.float32)
        ensure_parent(output_path)
        sf.write(str(output_path), silence, sr)
        return output_path, sr

    valid_segments.sort(key=lambda item: float(item["start_sec"]))

    first_audio, sr = sf.read(valid_segments[0]["tts_audio_path"])
    if first_audio.ndim > 1:
        first_audio = first_audio.mean(axis=1)

    max_len = 0
    cached: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for index, segment in enumerate(valid_segments):
        wav, cur_sr = sf.read(segment["tts_audio_path"])
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if cur_sr != sr:
            raise RuntimeError("E-MIX-001 inconsistent segment sample rates")

        start_sample = int(float(segment["start_sec"]) * sr)
        # 关键逻辑：若存在“借静音后”的有效目标时长，合成窗口也要同步扩展，
        # 否则会在最终拼轨阶段把前面保留下来的尾音再次截掉。
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
        clipped = wav.astype(np.float32)[:max_allowed_len]
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

    ensure_parent(output_path)
    sf.write(str(output_path), master, sr)
    return output_path, sr


def mix_with_bgm(
    *,
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    target_sr: int,
) -> None:
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
    code, _, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"E-MIX-001 ffmpeg mix failed: {err.strip()}")


def load_tts_model(model_path: str, device: str, dtype_name: str) -> Qwen3TTSModel:
    dtype_map = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    if dtype_name not in dtype_map:
        raise ValueError(f"unsupported --tts-dtype: {dtype_name}")
    return Qwen3TTSModel.from_pretrained(
        model_path,
        device_map=device,
        dtype=dtype_map[dtype_name],
    )


def load_index_tts_model(
    *,
    root_dir: Optional[str],
    cfg_path: Optional[str],
    model_dir: Optional[str],
    device: str,
    use_fp16: bool,
    use_accel: bool,
    use_torch_compile: bool,
) -> Any:
    if not root_dir:
        raise ValueError("--index-tts-root is required when --tts-backend index-tts")

    root = Path(root_dir).expanduser().resolve()
    if not root.exists():
        raise RuntimeError(f"E-TTS-001 index-tts root not found: {root}")

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from indextts.infer_v2 import IndexTTS2
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 failed to import indextts: {exc}") from exc

    final_cfg = Path(cfg_path).expanduser() if cfg_path else (root / "checkpoints" / "config.yaml")
    final_model_dir = Path(model_dir).expanduser() if model_dir else (root / "checkpoints")

    if not final_cfg.exists():
        raise RuntimeError(f"E-TTS-001 index-tts config not found: {final_cfg}")
    if not final_model_dir.exists():
        raise RuntimeError(f"E-TTS-001 index-tts model dir not found: {final_model_dir}")

    try:
        return IndexTTS2(
            cfg_path=str(final_cfg),
            model_dir=str(final_model_dir),
            use_fp16=use_fp16,
            device=device,
            use_accel=use_accel,
            use_torch_compile=use_torch_compile,
        )
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 failed to initialize index-tts: {exc}") from exc


def _http_json_request(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    timeout_sec: float,
) -> Dict[str, Any]:
    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"E-TTS-001 index-tts api http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api connect failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api request failed: {exc}") from exc

    try:
        return json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api invalid json: {body[:200]}") from exc


def check_index_tts_service(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    url = api_url.rstrip("/") + "/health"
    payload = _http_json_request(method="GET", url=url, payload=None, timeout_sec=timeout_sec)
    if not payload.get("ok"):
        raise RuntimeError(f"E-TTS-001 index-tts service unhealthy: {payload}")
    return payload


def release_index_tts_api_model(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    url = api_url.rstrip("/") + "/model/release"
    payload = _http_json_request(
        method="POST",
        url=url,
        payload={},
        timeout_sec=timeout_sec,
    )
    if not payload.get("ok"):
        raise RuntimeError(f"E-TTS-001 index-tts api release failed: {payload}")
    return payload


def release_local_tts_models(
    *,
    tts_qwen: Optional[Qwen3TTSModel],
    tts_index: Optional[Any],
    logger: JsonlLogger,
) -> None:
    if tts_qwen is None and tts_index is None:
        return
    try:
        del tts_qwen
    except Exception:
        pass
    try:
        del tts_index
    except Exception:
        pass
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    logger.log("INFO", "tts", "tts_model_released", "local tts model released")


def synthesize_via_index_tts_api(
    *,
    api_url: str,
    timeout_sec: float,
    text: str,
    ref_audio_path: Path,
    output_path: Path,
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
) -> None:
    payload = {
        "text": text,
        "spk_audio_prompt": str(ref_audio_path.expanduser().resolve()),
        "output_path": str(output_path.expanduser().resolve()),
        "emo_audio_prompt": str(index_emo_audio_prompt.expanduser().resolve()) if index_emo_audio_prompt else None,
        "emo_alpha": index_emo_alpha,
        "use_emo_text": index_use_emo_text,
        "emo_text": index_emo_text,
        "top_p": index_top_p,
        "top_k": index_top_k,
        "temperature": index_temperature,
        "max_text_tokens_per_segment": index_max_text_tokens,
    }
    url = api_url.rstrip("/") + "/synthesize"
    result = _http_json_request(
        method="POST",
        url=url,
        payload=payload,
        timeout_sec=timeout_sec,
    )
    if not result.get("ok"):
        raise RuntimeError(f"E-TTS-001 index-tts api returned non-ok: {result}")

    if not output_path.exists():
        raise RuntimeError("E-TTS-001 index-tts api finished but output missing")


def split_text_for_index_tts(text: str, *, max_text_tokens: int) -> List[str]:
    content = (text or "").strip()
    if not content:
        return [content]

    has_cjk = bool(re.search(r"[\u3400-\u9fff]", content))
    if has_cjk:
        budget_chars = max(12, int(max_text_tokens * 0.45))
        units = re.findall(r"[^。！？!?；;，,、\n]+[。！？!?；;，,、]?", content)
    else:
        budget_chars = max(24, int(max_text_tokens * 0.90))
        units = re.findall(r"[^.!?;,:，。！？；：\n]+[.!?;,:，。！？；：]?", content)

    if not units:
        units = [content]

    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{unit}".strip()
        if not current:
            current = unit.strip()
            continue
        if len(candidate) <= budget_chars:
            current = candidate
        else:
            chunks.append(current.strip())
            current = unit.strip()
    if current:
        chunks.append(current.strip())

    final_chunks: List[str] = []
    for chunk in chunks:
        if len(chunk) <= budget_chars:
            final_chunks.append(chunk)
            continue
        start = 0
        while start < len(chunk):
            end = min(len(chunk), start + budget_chars)
            part = chunk[start:end].strip()
            if part:
                final_chunks.append(part)
            start = end
    return final_chunks or [content]


def concat_generated_wavs(inputs: List[Path], output_wav: Path) -> None:
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
    code, out, err = run_cmd(
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
            "22050",
            str(output_wav),
        ]
    )
    if code != 0:
        raise RuntimeError(f"E-TTS-001 concat generated parts failed: {out}\n{err}")


def synthesize_text_once(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    text: str,
    output_path: Path,
) -> None:
    if tts_backend == "qwen":
        if tts_qwen is None or qwen_prompt_items is None:
            raise RuntimeError("qwen backend not initialized")
        wavs, sr = tts_qwen.generate_voice_clone(
            text=text,
            language="Auto",
            voice_clone_prompt=qwen_prompt_items,
            x_vector_only_mode=True,
            non_streaming_mode=True,
        )
        wav = np.asarray(wavs[0], dtype=np.float32)
        sf.write(str(output_path), wav, sr)
        return

    if tts_backend == "index-tts":
        chunks = split_text_for_index_tts(text, max_text_tokens=index_max_text_tokens)
        part_paths: List[Path] = []

        def synthesize_one(chunk_text: str, chunk_output: Path) -> None:
            if index_tts_via_api:
                try:
                    synthesize_via_index_tts_api(
                        api_url=index_tts_api_url,
                        timeout_sec=index_tts_api_timeout_sec,
                        text=chunk_text,
                        ref_audio_path=ref_audio_path,
                        output_path=chunk_output,
                        index_emo_audio_prompt=index_emo_audio_prompt,
                        index_emo_alpha=index_emo_alpha,
                        index_use_emo_text=index_use_emo_text,
                        index_emo_text=index_emo_text,
                        index_top_p=index_top_p,
                        index_top_k=index_top_k,
                        index_temperature=index_temperature,
                        index_max_text_tokens=index_max_text_tokens,
                    )
                    return
                except Exception as first_exc:
                    try:
                        release_index_tts_api_model(
                            api_url=index_tts_api_url,
                            timeout_sec=index_tts_api_timeout_sec,
                        )
                    except Exception:
                        pass
                    try:
                        synthesize_via_index_tts_api(
                            api_url=index_tts_api_url,
                            timeout_sec=index_tts_api_timeout_sec,
                            text=chunk_text,
                            ref_audio_path=ref_audio_path,
                            output_path=chunk_output,
                            index_emo_audio_prompt=index_emo_audio_prompt,
                            index_emo_alpha=index_emo_alpha,
                            index_use_emo_text=index_use_emo_text,
                            index_emo_text=index_emo_text,
                            index_top_p=index_top_p,
                            index_top_k=index_top_k,
                            index_temperature=index_temperature,
                            index_max_text_tokens=index_max_text_tokens,
                        )
                        return
                    except Exception as second_exc:
                        raise RuntimeError(
                            f"E-TTS-001 index-tts api failed after one retry: first={first_exc}; second={second_exc}"
                        ) from second_exc
            else:
                if tts_index is None:
                    raise RuntimeError("index-tts backend not initialized")
                tts_index.infer(
                    spk_audio_prompt=str(ref_audio_path),
                    text=chunk_text,
                    output_path=str(chunk_output),
                    emo_audio_prompt=str(index_emo_audio_prompt) if index_emo_audio_prompt else None,
                    emo_alpha=index_emo_alpha,
                    use_emo_text=index_use_emo_text,
                    emo_text=index_emo_text,
                    verbose=False,
                    max_text_tokens_per_segment=index_max_text_tokens,
                    top_p=index_top_p,
                    top_k=index_top_k,
                    temperature=index_temperature,
                )
                if not chunk_output.exists():
                    raise RuntimeError("index-tts produced no output audio")

        for index, chunk in enumerate(chunks):
            chunk_out = output_path.with_name(f"{output_path.stem}_part{index:03d}.wav")
            synthesize_one(chunk, chunk_out)
            part_paths.append(chunk_out)

        try:
            concat_generated_wavs(part_paths, output_path)
        finally:
            for part in part_paths:
                try:
                    if part.exists():
                        part.unlink()
                except Exception:
                    pass
        return

    raise RuntimeError(f"Unsupported tts backend: {tts_backend}")


def build_synthesis_groups(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    max_gap_sec: float,
    min_group_duration_sec: float,
    max_group_duration_sec: float,
    subtitle_speakers: Optional[List[str]] = None,
    grouping_strategy: str = "legacy",
) -> List[List[int]]:
    # 支持两种分组策略：
    # 1) legacy：兼容历史分组（gap + 时长 + 句末）
    # 2) sentence：纯句末边界（可选 speaker 切换）
    if len(subtitles) <= 1:
        return [[index] for index in range(len(subtitles))]

    strategy = (grouping_strategy or "legacy").strip().lower()
    if strategy not in {"legacy", "sentence"}:
        strategy = "legacy"

    if strategy == "sentence":
        groups: List[List[int]] = []
        current = [0]
        for idx in range(len(subtitles) - 1):
            source_text = (subtitles[idx].get("text") or "").strip()
            translated_text = (translated_lines[idx] if idx < len(translated_lines) else "").strip()
            sentence_end = is_sentence_end(source_text) or is_sentence_end(translated_text)
            speaker_changed = False
            if subtitle_speakers and idx + 1 < len(subtitle_speakers):
                speaker_changed = subtitle_speakers[idx] != subtitle_speakers[idx + 1]
            if speaker_changed or sentence_end:
                groups.append(current[:])
                current = [idx + 1]
            else:
                current.append(idx + 1)
        groups.append(current[:])
        return groups

    # legacy：保留原行为，避免回归
    effective_min_group_duration = float(min_group_duration_sec)
    if subtitle_speakers:
        effective_min_group_duration = max(effective_min_group_duration, 3.0)

    groups: List[List[int]] = []
    current = [0]
    current_start = float(subtitles[0]["start"])

    for idx in range(len(subtitles) - 1):
        cur_end = float(subtitles[idx]["end"])
        next_start = float(subtitles[idx + 1]["start"])
        next_end = float(subtitles[idx + 1]["end"])
        gap = next_start - cur_end
        current_duration = cur_end - current_start
        next_duration = next_end - current_start
        source_text = (subtitles[idx].get("text") or "").strip()
        translated_text = (translated_lines[idx] if idx < len(translated_lines) else "").strip()
        sentence_end = is_sentence_end(source_text) or is_sentence_end(translated_text)
        speaker_changed = False
        if subtitle_speakers and idx + 1 < len(subtitle_speakers):
            speaker_changed = subtitle_speakers[idx] != subtitle_speakers[idx + 1]

        hard_break = speaker_changed or gap > max_gap_sec or (gap >= 0.0 and next_duration > max_group_duration_sec)
        natural_break = sentence_end and current_duration >= effective_min_group_duration
        if hard_break or natural_break:
            groups.append(current[:])
            current = [idx + 1]
            current_start = float(subtitles[idx + 1]["start"])
        else:
            current.append(idx + 1)

    groups.append(current[:])

    def _group_duration(index_group: List[int]) -> float:
        start = float(subtitles[index_group[0]].get("start", 0.0) or 0.0)
        end = float(subtitles[index_group[-1]].get("end", start) or start)
        return max(0.0, end - start)

    def _group_speaker(index_group: List[int]) -> str:
        if not subtitle_speakers:
            return ""
        first = index_group[0]
        if 0 <= first < len(subtitle_speakers):
            return subtitle_speakers[first]
        return ""

    merged_groups: List[List[int]] = []
    for group in groups:
        if not merged_groups:
            merged_groups.append(group[:])
            continue
        group_is_short = _group_duration(group) < effective_min_group_duration
        same_speaker_prev = _group_speaker(merged_groups[-1]) == _group_speaker(group)
        if group_is_short and same_speaker_prev:
            merged_groups[-1].extend(group)
        else:
            merged_groups.append(group[:])

    return merged_groups


def split_waveform_by_durations(
    *,
    wav: np.ndarray,
    durations: List[float],
) -> List[np.ndarray]:
    n = len(durations)
    if n == 0:
        return []
    if n == 1:
        return [wav]

    total_samples = len(wav)
    if total_samples <= n:
        chunks: List[np.ndarray] = []
        for index in range(n):
            if index < total_samples:
                chunks.append(wav[index : index + 1].copy())
            else:
                chunks.append(np.zeros(1, dtype=np.float32))
        return chunks

    safe = [max(0.05, float(item)) for item in durations]
    sum_safe = sum(safe) or float(n)
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

    chunks = []
    for index in range(n):
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
    """估计单句“可说话负载”，用于均衡分配组内时长。"""
    content = (text or "").strip()
    if not content:
        return max(0.1, float(target_duration_sec))

    # 基础负载：按字符/词数量估计发音信息量。
    if cjk_mode:
        unit_count = len([ch for ch in content if not ch.isspace()])
    else:
        unit_count = len([item for item in content.split(" ") if item.strip()])
    base = max(1.0, float(unit_count))

    # 结构修正：标点与数字通常会增加停顿或读法复杂度。
    punctuation_count = sum(1 for ch in content if ch in ",.;:!?，。；：！？、")
    digit_count = sum(1 for ch in content if ch.isdigit())
    structure_bonus = 1.0 + min(0.35, punctuation_count * 0.04 + digit_count * 0.02)

    # 时间窗修正：保留原始时间分布的先验，避免完全偏离字幕节奏。
    duration_prior = max(0.2, float(target_duration_sec))
    return max(0.1, base * structure_bonus * (0.55 + 0.45 * duration_prior))


def allocate_balanced_durations(
    *,
    texts: List[str],
    target_durations: List[float],
    min_line_sec: float,
    cjk_mode: bool,
) -> List[float]:
    """在组时长不变的前提下，按文本负载均衡分配每句时长。"""
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
    for idx in range(count):
        text = texts[idx] if idx < len(texts) else ""
        weights.append(
            estimate_line_speech_weight(
                text=text,
                target_duration_sec=safe_targets[idx],
                cjk_mode=cjk_mode,
            )
        )
    sum_weights = sum(weights) or float(count)

    # 先按权重分配，再做最小时长约束与总量守恒修正。
    allocated = [total_target * (weight / sum_weights) for weight in weights]
    floor_value = max(0.05, float(min_line_sec))
    if floor_value * count <= total_target:
        deficit = 0.0
        for idx, value in enumerate(allocated):
            if value < floor_value:
                deficit += floor_value - value
                allocated[idx] = floor_value
        if deficit > 1e-9:
            donors = [idx for idx, value in enumerate(allocated) if value > floor_value + 1e-9]
            while deficit > 1e-9 and donors:
                donor_total = sum(allocated[idx] - floor_value for idx in donors)
                if donor_total <= 1e-9:
                    break
                used = 0.0
                for idx in donors[:]:
                    room = allocated[idx] - floor_value
                    take = min(room, deficit * (room / donor_total))
                    allocated[idx] -= take
                    used += take
                    if allocated[idx] <= floor_value + 1e-9:
                        donors.remove(idx)
                if used <= 1e-9:
                    break
                deficit -= used

    corrected_sum = sum(allocated)
    if corrected_sum > 1e-9:
        scale = total_target / corrected_sum
        allocated = [max(0.05, value * scale) for value in allocated]

    # 再次校正尾差，确保总和严格等于组目标时长。
    tail_fix = total_target - sum(allocated)
    allocated[-1] = max(0.05, allocated[-1] + tail_fix)
    return allocated


def compute_effective_target_duration(
    *,
    start_sec: float,
    end_sec: float,
    next_start_sec: Optional[float],
    gap_guard_sec: float = 0.10,
) -> Tuple[float, float]:
    """计算“可借后续静音”后的有效目标时长。

    设计目标：
    1) 默认目标仍是字幕窗口 end-start；
    2) 若下一句开始前存在空白，则允许借用空白（扣除 guard）；
    3) 借用后得到 effective_target_sec，用于替代硬压到原窗口的目标。
    """
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
    """为分割后的片段加短淡入淡出，减少切点爆音。"""
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


def synthesize_segments_grouped(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    ref_audio_selector: Optional[Callable[[int], Path]],
    source_media_duration_sec: Optional[float],
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    force_fit_timing: bool,
    group_gap_sec: float,
    group_min_duration_sec: float,
    group_max_duration_sec: float,
    subtitle_speakers: Optional[List[str]],
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    segment_dir: Path,
    delta_pass_ms: float,
    timing_mode: str,
    balanced_max_tempo_shift: float,
    balanced_min_line_sec: float,
    grouping_strategy: str,
    logger: JsonlLogger,
    target_lang: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    segment_dir.mkdir(parents=True, exist_ok=True)
    records_by_index: Dict[int, Dict[str, Any]] = {}
    manual_review: List[Dict[str, Any]] = []

    groups = build_synthesis_groups(
        subtitles=subtitles,
        translated_lines=translated_lines,
        max_gap_sec=group_gap_sec,
        min_group_duration_sec=group_min_duration_sec,
        max_group_duration_sec=group_max_duration_sec,
        subtitle_speakers=subtitle_speakers,
        grouping_strategy=grouping_strategy,
    )
    cjk_mode = is_cjk_target_lang(target_lang)

    for group_no, indices in enumerate(groups, start=1):
        group_id = f"group_{group_no:04d}"
        group_start = float(subtitles[indices[0]]["start"])
        group_end = float(subtitles[indices[-1]]["end"])
        group_target_duration = max(0.05, group_end - group_start)
        # 关键逻辑：允许借用“下一句开始前”的静音窗口，避免无谓的重压缩。
        next_start_for_group: Optional[float] = None
        next_index = indices[-1] + 1
        if next_index < len(subtitles):
            next_start_for_group = float(subtitles[next_index].get("start", group_end) or group_end)
        elif source_media_duration_sec is not None:
            # 关键边界：最后一句/最后一组可借用“到音频末尾”的静音，不应默认为 0。
            next_start_for_group = float(source_media_duration_sec)
        group_effective_target_duration, group_borrowed_gap_sec = compute_effective_target_duration(
            start_sec=group_start,
            end_sec=group_end,
            next_start_sec=next_start_for_group,
        )
        group_texts = [
            (translated_lines[index] if index < len(translated_lines) else subtitles[index]["text"]) or subtitles[index]["text"]
            for index in indices
        ]
        group_text = merge_text_lines(group_texts, cjk_mode=cjk_mode)
        subtitle_empty = group_subtitle_is_empty(
            subtitles=subtitles,
            translated_lines=translated_lines,
            indices=indices,
        )
        logger.log("INFO", "tts", "group_tts_started", f"synthesizing {group_id}", data={"segments": len(indices)})
        group_ref_audio_path = ref_audio_selector(indices[0]) if ref_audio_selector else ref_audio_path

        raw_path = segment_dir / f"{group_id}_raw.wav"
        fit_path = segment_dir / f"{group_id}_fit.wav"
        attempts_base: List[Dict[str, Any]] = []
        try:
            if force_fit_timing and fit_path.exists():
                reused_actual = audio_duration(fit_path)
                use_path = fit_path
                attempts_base.append(
                    {
                        "attempt_no": 0,
                        "action": "group_reuse_fit",
                        "input_text": group_text,
                        "actual_duration_sec": round(reused_actual, 3),
                        "delta_sec": round(reused_actual - group_target_duration, 3),
                        "result": "pass",
                        "error": None,
                        "ts": iso_now(),
                    }
                )
                logger.log(
                    "INFO",
                    "tts",
                    "group_tts_reused",
                    f"reused existing synthesized audio: {group_id}",
                    data={"path": str(fit_path)},
                )
            else:
                non_speech_group = not has_speakable_content(group_text)
                if non_speech_group:
                    ref_sr = 16000
                    try:
                        ref_sr = max(8000, int(sf.info(str(group_ref_audio_path)).samplerate))
                    except Exception:
                        ref_sr = 16000
                    sample_count = max(1, int(round(group_target_duration * ref_sr)))
                    silence_path = segment_dir / f"{group_id}_silent.wav"
                    sf.write(str(silence_path), np.zeros(sample_count, dtype=np.float32), ref_sr)
                    use_path = silence_path
                    silent_actual = audio_duration(silence_path)
                    attempts_base.append(
                        {
                            "attempt_no": 0,
                            "action": "group_non_speech_silence",
                            "input_text": group_text,
                            "actual_duration_sec": round(silent_actual, 3),
                            "delta_sec": round(silent_actual - group_target_duration, 3),
                            "result": "pass",
                            "error": None,
                            "ts": iso_now(),
                        }
                    )
                    logger.log(
                        "INFO",
                        "tts",
                        "group_non_speech_detected",
                        f"non-speech group uses silence: {group_id}",
                        data={"group_text": group_text},
                    )
                else:
                    synthesize_text_once(
                        tts_backend=tts_backend,
                        index_tts_via_api=index_tts_via_api,
                        index_tts_api_url=index_tts_api_url,
                        index_tts_api_timeout_sec=index_tts_api_timeout_sec,
                        tts_qwen=tts_qwen,
                        qwen_prompt_items=qwen_prompt_items,
                        tts_index=tts_index,
                        ref_audio_path=group_ref_audio_path,
                        index_emo_audio_prompt=index_emo_audio_prompt,
                        index_emo_alpha=index_emo_alpha,
                        index_use_emo_text=index_use_emo_text,
                        index_emo_text=index_emo_text,
                        index_top_p=index_top_p,
                        index_top_k=index_top_k,
                        index_temperature=index_temperature,
                        index_max_text_tokens=index_max_text_tokens,
                        text=group_text,
                        output_path=raw_path,
                    )
                    raw_actual = audio_duration(raw_path)
                    attempts_base.append(
                        {
                            "attempt_no": 0,
                            "action": "group_tts",
                            "input_text": group_text,
                            "actual_duration_sec": round(raw_actual, 3),
                            "delta_sec": round(raw_actual - group_target_duration, 3),
                            "result": "pass",
                            "error": None,
                            "ts": iso_now(),
                        }
                    )

                    trim_path = segment_dir / f"{group_id}_trim.wav"
                    use_path = raw_path
                    try:
                        before_trim, after_trim = trim_silence_edges(
                            input_path=raw_path,
                            output_path=trim_path,
                        )
                        attempts_base.append(
                            {
                                "attempt_no": 0,
                                "action": "group_trim_edges",
                                "input_text": group_text,
                                "actual_duration_sec": round(after_trim, 3),
                                "delta_sec": round(after_trim - group_target_duration, 3),
                                "result": "pass",
                                "error": None,
                                "data": {
                                    "before_trim_sec": round(before_trim, 3),
                                    "after_trim_sec": round(after_trim, 3),
                                },
                                "ts": iso_now(),
                            }
                        )
                        if after_trim >= 0.05:
                            use_path = trim_path
                    except Exception as trim_exc:
                        attempts_base.append(
                            {
                                "attempt_no": 0,
                                "action": "group_trim_edges",
                                "input_text": group_text,
                                "actual_duration_sec": round(raw_actual, 3),
                                "delta_sec": round(raw_actual - group_target_duration, 3),
                                "result": "fail",
                                "error": f"E-ALN-001 {type(trim_exc).__name__}: {trim_exc}",
                                "ts": iso_now(),
                            }
                        )

                    if force_fit_timing:
                        raw_group_actual = audio_duration(use_path)
                        raw_group_delta = raw_group_actual - group_target_duration
                        raw_group_delta_effective = raw_group_actual - group_effective_target_duration
                        # sentence 策略：优先做“整句时长拟合”（轻微变速），避免硬截断导致尾音/尾词丢失。
                        if grouping_strategy == "sentence":
                            if raw_group_actual > group_effective_target_duration:
                                sentence_fit_path = segment_dir / f"{group_id}_sentence_fit.wav"
                                try:
                                    fit_audio_to_duration(
                                        input_path=use_path,
                                        output_path=sentence_fit_path,
                                        target_duration_sec=group_effective_target_duration,
                                    )
                                    fitted_actual = audio_duration(sentence_fit_path)
                                    attempts_base.append(
                                        {
                                            "attempt_no": 0,
                                            "action": "group_sentence_fit_duration",
                                            "input_text": group_text,
                                            "actual_duration_sec": round(fitted_actual, 3),
                                            "delta_sec": round(fitted_actual - group_target_duration, 3),
                                            "result": "pass",
                                            "error": None,
                                            "data": {
                                                "effective_target_sec": round(group_effective_target_duration, 3),
                                                "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            },
                                            "ts": iso_now(),
                                        }
                                    )
                                    use_path = sentence_fit_path
                                except Exception as fit_exc:
                                    # 兜底：若变速拟合失败，再退回旧的硬裁剪，保证流水线不中断。
                                    sentence_cap_path = segment_dir / f"{group_id}_sentence_cap.wav"
                                    trim_audio_to_max_duration(
                                        input_path=use_path,
                                        output_path=sentence_cap_path,
                                        max_duration_sec=group_effective_target_duration,
                                    )
                                    capped_actual = audio_duration(sentence_cap_path)
                                    attempts_base.append(
                                        {
                                            "attempt_no": 0,
                                            "action": "group_sentence_cap_duration_fallback",
                                            "input_text": group_text,
                                            "actual_duration_sec": round(capped_actual, 3),
                                            "delta_sec": round(capped_actual - group_target_duration, 3),
                                            "result": "pass",
                                            "error": f"E-ALN-001 sentence fit failed: {fit_exc}",
                                            "data": {
                                                "effective_target_sec": round(group_effective_target_duration, 3),
                                                "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            },
                                            "ts": iso_now(),
                                        }
                                    )
                                    use_path = sentence_cap_path
                            else:
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_sentence_keep_natural",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(raw_group_actual, 3),
                                        "delta_sec": round(raw_group_delta, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            "effective_delta_sec": round(raw_group_delta_effective, 3),
                                        },
                                        "ts": iso_now(),
                                    }
                                )
                        # strict/balanced 仅在 legacy 策略下生效
                        elif timing_mode == "strict":
                            fit_audio_to_duration(
                                input_path=use_path,
                                output_path=fit_path,
                                target_duration_sec=group_effective_target_duration,
                            )
                            fit_actual = audio_duration(fit_path)
                            attempts_base.append(
                                {
                                    "attempt_no": 0,
                                    "action": "group_fit_timing",
                                    "input_text": group_text,
                                    "actual_duration_sec": round(fit_actual, 3),
                                    "delta_sec": round(fit_actual - group_target_duration, 3),
                                    "result": "pass",
                                    "error": None,
                                    "data": {
                                        "effective_target_sec": round(group_effective_target_duration, 3),
                                        "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                    },
                                    "ts": iso_now(),
                                }
                            )
                            use_path = fit_path
                        else:
                            # balanced 模式优先保留自然节奏；仅超阈值时回退 strict 兜底。
                            relative_shift = abs(raw_group_delta_effective) / max(0.05, group_effective_target_duration)
                            if relative_shift > max(0.0, float(balanced_max_tempo_shift)):
                                fit_audio_to_duration(
                                    input_path=use_path,
                                    output_path=fit_path,
                                    target_duration_sec=group_effective_target_duration,
                                )
                                fit_actual = audio_duration(fit_path)
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_balanced_fallback_strict",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(fit_actual, 3),
                                        "delta_sec": round(fit_actual - group_target_duration, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                        },
                                        "ts": iso_now(),
                                    }
                                )
                                use_path = fit_path
                            else:
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_balanced_keep_natural",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(raw_group_actual, 3),
                                        "delta_sec": round(raw_group_delta, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            "effective_delta_sec": round(raw_group_delta_effective, 3),
                                        },
                                        "ts": iso_now(),
                                    }
                                )

            if (not subtitle_empty) and audio_is_effectively_silent(use_path):
                attempts_base.append(
                    {
                        "attempt_no": 1,
                        "action": "group_silence_check",
                        "input_text": group_text,
                        "actual_duration_sec": round(audio_duration(use_path), 3),
                        "delta_sec": round(audio_duration(use_path) - group_target_duration, 3),
                        "result": "fail",
                        "error": "E-TTS-001 detected silent-like output",
                        "ts": iso_now(),
                    }
                )
                logger.log(
                    "WARN",
                    "tts",
                    "group_silence_detected",
                    f"silent-like group detected, retry once: {group_id}",
                    data={"path": str(use_path)},
                )

                retry_raw = segment_dir / f"{group_id}_retry1_raw.wav"
                retry_trim = segment_dir / f"{group_id}_retry1_trim.wav"
                retry_fit = segment_dir / f"{group_id}_retry1_fit.wav"
                retry_use = retry_raw

                synthesize_text_once(
                    tts_backend=tts_backend,
                    index_tts_via_api=index_tts_via_api,
                    index_tts_api_url=index_tts_api_url,
                    index_tts_api_timeout_sec=index_tts_api_timeout_sec,
                    tts_qwen=tts_qwen,
                    qwen_prompt_items=qwen_prompt_items,
                    tts_index=tts_index,
                    ref_audio_path=group_ref_audio_path,
                    index_emo_audio_prompt=index_emo_audio_prompt,
                    index_emo_alpha=index_emo_alpha,
                    index_use_emo_text=index_use_emo_text,
                    index_emo_text=index_emo_text,
                    index_top_p=index_top_p,
                    index_top_k=index_top_k,
                    index_temperature=index_temperature,
                    index_max_text_tokens=index_max_text_tokens,
                    text=group_text,
                    output_path=retry_raw,
                )
                try:
                    _, retry_trim_dur = trim_silence_edges(
                        input_path=retry_raw,
                        output_path=retry_trim,
                    )
                    if retry_trim_dur >= 0.05:
                        retry_use = retry_trim
                except Exception:
                    retry_use = retry_raw

                if force_fit_timing:
                    retry_actual = audio_duration(retry_use)
                    retry_delta = retry_actual - group_target_duration
                    retry_delta_effective = retry_actual - group_effective_target_duration
                    if grouping_strategy == "sentence":
                        if retry_actual > group_effective_target_duration:
                            try:
                                fit_audio_to_duration(
                                    input_path=retry_use,
                                    output_path=retry_fit,
                                    target_duration_sec=group_effective_target_duration,
                                )
                                retry_use = retry_fit
                            except Exception:
                                # 兜底保持原行为，确保重试路径不因拟合失败直接中断。
                                trim_audio_to_max_duration(
                                    input_path=retry_use,
                                    output_path=retry_fit,
                                    max_duration_sec=group_effective_target_duration,
                                )
                                retry_use = retry_fit
                    elif timing_mode == "strict":
                        fit_audio_to_duration(
                            input_path=retry_use,
                            output_path=retry_fit,
                            target_duration_sec=group_effective_target_duration,
                        )
                        retry_use = retry_fit
                    else:
                        relative_shift = abs(retry_delta_effective) / max(0.05, group_effective_target_duration)
                        if relative_shift > max(0.0, float(balanced_max_tempo_shift)):
                            fit_audio_to_duration(
                                input_path=retry_use,
                                output_path=retry_fit,
                                target_duration_sec=group_effective_target_duration,
                            )
                            retry_use = retry_fit

                retry_still_silent = audio_is_effectively_silent(retry_use)
                attempts_base.append(
                    {
                        "attempt_no": 1,
                        "action": "group_retry_after_silence",
                        "input_text": group_text,
                        "actual_duration_sec": round(audio_duration(retry_use), 3),
                        "delta_sec": round(audio_duration(retry_use) - group_target_duration, 3),
                        "result": "pass" if not retry_still_silent else "fail",
                        "error": None if not retry_still_silent else "E-TTS-001 still silent after one retry",
                        "ts": iso_now(),
                    }
                )
                if not retry_still_silent:
                    use_path = retry_use
                else:
                    anchor_seg_id = f"seg_{indices[0] + 1:04d}"
                    manual_review.append(
                        {
                            "segment_id": anchor_seg_id,
                            "reason_code": "tts_silent_after_retry",
                            "reason_detail": "silent-like audio remains after one retry",
                            "last_delta_sec": None,
                            "last_attempt_no": 1,
                            "error_code": "E-TTS-001",
                            "error_stage": "tts",
                        }
                    )

            group_actual = audio_duration(use_path)
            group_delta = group_actual - group_target_duration
            group_delta_effective = group_actual - group_effective_target_duration
            anchor_status = "done" if abs(group_delta_effective) * 1000 <= delta_pass_ms else "manual_review"

            # 统一按“整句组”落盘，不再把组内再次切成短片段。
            for local_index, global_index in enumerate(indices):
                seg_id = f"seg_{global_index + 1:04d}"
                seg_start = float(subtitles[global_index]["start"])
                seg_end = float(subtitles[global_index]["end"])
                seg_target = max(0.05, seg_end - seg_start)
                translated_text = (
                    translated_lines[global_index]
                    if global_index < len(translated_lines)
                    else subtitles[global_index]["text"]
                )

                record: Dict[str, Any] = {
                    "id": seg_id,
                    "start_sec": round(seg_start, 3),
                    "end_sec": round(seg_end, 3),
                    "target_duration_sec": round(seg_target, 3),
                    "source_text": subtitles[global_index]["text"],
                    "translated_text": translated_text,
                    "voice_ref_path": str(group_ref_audio_path),
                    "tts_audio_path": str(use_path),
                    "actual_duration_sec": 0.0,
                    "delta_sec": 0.0,
                    "status": "done",
                    "retry_count": 0,
                    "attempt_history": [dict(item) for item in attempts_base],
                    "skip_compose": True,
                    "group_id": group_id,
                }

                if local_index == 0:
                    record["target_duration_sec"] = round(group_target_duration, 3)
                    record["actual_duration_sec"] = round(group_actual, 3)
                    record["delta_sec"] = round(group_delta, 3)
                    record["status"] = anchor_status
                    record["skip_compose"] = False
                    record["group_anchor_end_sec"] = round(group_end, 3)
                    record["group_text"] = group_text
                    record["effective_target_duration_sec"] = round(group_effective_target_duration, 3)
                    record["borrowed_gap_sec"] = round(group_borrowed_gap_sec, 3)
                    record["effective_delta_sec"] = round(group_delta_effective, 3)

                records_by_index[global_index] = record

            if anchor_status != "done":
                anchor_seg_id = f"seg_{indices[0] + 1:04d}"
                manual_review.append(
                    {
                        "segment_id": anchor_seg_id,
                        "reason_code": "duration_exceeded_after_retries",
                        "reason_detail": "grouped synthesis anchor out of threshold",
                        "last_delta_sec": round(group_delta, 3),
                        "last_effective_delta_sec": round(group_delta_effective, 3),
                        "last_attempt_no": 0,
                        "error_code": "E-ALN-001",
                        "error_stage": "duration_align",
                    }
                )
        except Exception as exc:
            logger.log(
                "ERROR",
                "tts",
                "group_tts_failed",
                f"{group_id} synthesis failed",
                data={"error": str(exc)},
            )
            for global_index in indices:
                seg_id = f"seg_{global_index + 1:04d}"
                target_duration = max(0.05, float(subtitles[global_index]["end"]) - float(subtitles[global_index]["start"]))
                missing_path = segment_dir / f"{seg_id}_missing.wav"
                sf.write(str(missing_path), np.zeros(max(1600, int(16000 * target_duration)), dtype=np.float32), 16000)
                records_by_index[global_index] = {
                    "id": seg_id,
                    "start_sec": round(float(subtitles[global_index]["start"]), 3),
                    "end_sec": round(float(subtitles[global_index]["end"]), 3),
                    "target_duration_sec": round(target_duration, 3),
                    "source_text": subtitles[global_index]["text"],
                    "translated_text": translated_lines[global_index] if global_index < len(translated_lines) else subtitles[global_index]["text"],
                    "voice_ref_path": str(group_ref_audio_path),
                    "tts_audio_path": str(missing_path),
                    "actual_duration_sec": round(audio_duration(missing_path), 3),
                    "delta_sec": round(audio_duration(missing_path) - target_duration, 3),
                    "status": "manual_review",
                    "retry_count": 0,
                    "attempt_history": [
                        {
                            "attempt_no": 0,
                            "action": "group_tts",
                            "input_text": group_text,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "fail",
                            "error": f"E-TTS-001 {type(exc).__name__}: {exc}",
                            "ts": iso_now(),
                        }
                    ],
                }
                manual_review.append(
                    {
                        "segment_id": seg_id,
                        "reason_code": "tts_failed",
                        "reason_detail": str(exc),
                        "last_delta_sec": None,
                        "last_attempt_no": 0,
                        "error_code": "E-TTS-001",
                        "error_stage": "tts",
                    }
                )

    records = [records_by_index[index] for index in sorted(records_by_index.keys())]
    return records, manual_review


def synthesize_segments(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    ref_audio_selector: Optional[Callable[[int], Path]],
    source_vocals_audio: Path,
    source_media_duration_sec: Optional[float],
    speaker_mode: str,
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    force_fit_timing: bool,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    segment_dir: Path,
    delta_pass_ms: float,
    delta_rewrite_ms: float,
    atempo_min: float,
    atempo_max: float,
    max_retry: int,
    translator: Translator,
    target_lang: str,
    allow_rewrite_translation: bool,
    logger: JsonlLogger,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    segment_dir.mkdir(parents=True, exist_ok=True)
    # 清理历史重试残留，避免 resume in-place 时出现 a0/a1/a3 混杂误导排查。
    for stale_path in segment_dir.glob("seg_*_a*.wav"):
        try:
            stale_path.unlink(missing_ok=True)
        except Exception:
            pass
    records: List[Dict[str, Any]] = []
    manual_review: List[Dict[str, Any]] = []

    for idx, (subtitle, translated_text) in enumerate(zip(subtitles, translated_lines), start=1):
        seg_id = f"seg_{idx:04d}"
        seg_ref_audio_path = ref_audio_selector(idx - 1) if ref_audio_selector else ref_audio_path
        start_sec = float(subtitle["start"])
        end_sec = float(subtitle["end"])
        target_duration = max(0.05, end_sec - start_sec)
        # 关键逻辑：在单句模式也允许借用后续静音，减少无谓压缩。
        next_start_sec: Optional[float] = None
        if idx < len(subtitles):
            next_start_sec = float(subtitles[idx].get("start", end_sec) or end_sec)
        elif source_media_duration_sec is not None:
            # 关键边界：最后一句可借用到媒体末尾的静音，避免被过度压缩。
            next_start_sec = float(source_media_duration_sec)
        effective_target_duration, borrowed_gap_sec = compute_effective_target_duration(
            start_sec=start_sec,
            end_sec=end_sec,
            next_start_sec=next_start_sec,
        )
        source_text = subtitle["text"]
        current_text = translated_text or source_text
        attempts: List[Dict[str, Any]] = []
        # 记录本句产生的临时尝试音频，结束后统一清理，仅保留最终产物。
        attempt_artifacts: List[Path] = []
        best: Optional[Tuple[Path, float, float]] = None
        final_status = "failed"
        retry_count = 0
        failure_reason_code = "duration_exceeded_after_retries"
        failure_error_code = "E-ALN-001"
        failure_stage = "duration_align"

        logger.log("INFO", "tts", "segment_tts_started", f"synthesizing {seg_id}", segment_id=seg_id)
        # 统一策略：对应句子的原音频同时用于克隆参考与情绪参考。
        seg_emo_audio_prompt = seg_ref_audio_path

        for attempt_no in range(0, max_retry + 1):
            raw_path = segment_dir / f"{seg_id}_a{attempt_no}.wav"
            attempt_artifacts.append(raw_path)
            try:
                if tts_backend == "qwen":
                    if tts_qwen is None or qwen_prompt_items is None:
                        raise RuntimeError("qwen backend not initialized")
                    wavs, sr = tts_qwen.generate_voice_clone(
                        text=current_text,
                        language="Auto",
                        voice_clone_prompt=qwen_prompt_items,
                        x_vector_only_mode=True,
                        non_streaming_mode=True,
                    )
                    wav = np.asarray(wavs[0], dtype=np.float32)
                    sf.write(str(raw_path), wav, sr)
                elif tts_backend == "index-tts":
                    if index_tts_via_api:
                        synthesize_via_index_tts_api(
                            api_url=index_tts_api_url,
                            timeout_sec=index_tts_api_timeout_sec,
                            text=current_text,
                            ref_audio_path=seg_ref_audio_path,
                            output_path=raw_path,
                            index_emo_audio_prompt=seg_emo_audio_prompt,
                            index_emo_alpha=index_emo_alpha,
                            index_use_emo_text=index_use_emo_text,
                            index_emo_text=index_emo_text,
                            index_top_p=index_top_p,
                            index_top_k=index_top_k,
                            index_temperature=index_temperature,
                            index_max_text_tokens=index_max_text_tokens,
                        )
                    else:
                        if tts_index is None:
                            raise RuntimeError("index-tts backend not initialized")
                        tts_index.infer(
                            spk_audio_prompt=str(seg_ref_audio_path),
                            text=current_text,
                            output_path=str(raw_path),
                            emo_audio_prompt=str(seg_emo_audio_prompt) if seg_emo_audio_prompt else None,
                            emo_alpha=index_emo_alpha,
                            use_emo_text=index_use_emo_text,
                            emo_text=index_emo_text,
                            verbose=False,
                            max_text_tokens_per_segment=index_max_text_tokens,
                            top_p=index_top_p,
                            top_k=index_top_k,
                            temperature=index_temperature,
                        )
                        if not raw_path.exists():
                            raise RuntimeError("index-tts produced no output audio")
                else:
                    raise RuntimeError(f"Unsupported tts backend: {tts_backend}")
            except Exception as exc:
                failure_reason_code = "tts_failed"
                failure_error_code = "E-TTS-001"
                failure_stage = "tts"
                attempts.append(
                    {
                        "attempt_no": attempt_no,
                        "action": "tts",
                        "input_text": current_text,
                        "actual_duration_sec": None,
                        "delta_sec": None,
                        "result": "fail",
                        "error": f"E-TTS-001 {type(exc).__name__}: {exc}",
                        "ts": iso_now(),
                    }
                )
                logger.log(
                    "ERROR",
                    "tts",
                    "segment_tts_failed",
                    f"{seg_id} tts failed",
                    segment_id=seg_id,
                    data={"error_code": "E-TTS-001", "error": str(exc)},
                )
                break

            actual = audio_duration(raw_path)
            min_valid_duration = max(0.20, min(0.60, target_duration * 0.25))
            invalid_audio = audio_is_effectively_silent(raw_path) or actual < min_valid_duration
            if invalid_audio:
                failure_reason_code = "tts_invalid_audio"
                failure_error_code = "E-TTS-002"
                failure_stage = "tts"
                attempts.append(
                    {
                        "attempt_no": attempt_no,
                        "action": "validate_audio",
                        "input_text": current_text,
                        "actual_duration_sec": round(actual, 3),
                        "delta_sec": round(actual - target_duration, 3),
                        "result": "fail",
                        "error": f"E-TTS-002 invalid audio output (too short/silent, min={min_valid_duration:.2f}s)",
                        "ts": iso_now(),
                    }
                )
                # 参考片段无效时回退兜底参考，避免坏参考持续污染重试。
                if seg_ref_audio_path != ref_audio_path:
                    seg_ref_audio_path = ref_audio_path
                if attempt_no < max_retry:
                    continue
                break
            delta = actual - target_duration
            delta_effective = actual - effective_target_duration
            abs_delta = abs(delta_effective)
            attempts.append(
                {
                    "attempt_no": attempt_no,
                    "action": "tts",
                    "input_text": current_text,
                    "actual_duration_sec": round(actual, 3),
                    "delta_sec": round(delta, 3),
                    "result": "pass" if abs_delta * 1000 <= delta_pass_ms else "fail",
                    "error": None,
                    "data": {
                        "effective_target_sec": round(effective_target_duration, 3),
                        "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                        "effective_delta_sec": round(delta_effective, 3),
                    },
                    "ts": iso_now(),
                }
            )

            if force_fit_timing:
                fit_path = segment_dir / f"{seg_id}_a{attempt_no}_fit.wav"
                try:
                    fit_audio_to_duration(
                        input_path=raw_path,
                        output_path=fit_path,
                        target_duration_sec=effective_target_duration,
                    )
                    attempt_artifacts.append(fit_path)
                    actual_fit = audio_duration(fit_path)
                    delta_fit = actual_fit - target_duration
                    delta_fit_effective = actual_fit - effective_target_duration
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "fit_timing",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual_fit, 3),
                            "delta_sec": round(delta_fit, 3),
                            "result": "pass",
                            "error": None,
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_fit_effective, 3),
                            },
                            "ts": iso_now(),
                        }
                    )
                    best = (fit_path, actual_fit, delta_fit)
                    final_status = "done"
                    retry_count = attempt_no
                    break
                except Exception as exc:
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "fit_timing",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual, 3),
                            "delta_sec": round(delta, 3),
                            "result": "fail",
                            "error": f"E-ALN-001 {type(exc).__name__}: {exc}",
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_effective, 3),
                            },
                            "ts": iso_now(),
                        }
                    )

            if best is None or abs_delta < abs(best[1] - effective_target_duration):
                best = (raw_path, actual, delta)

            if abs_delta * 1000 <= delta_pass_ms:
                final_status = "done"
                retry_count = attempt_no
                break

            if abs_delta * 1000 <= delta_rewrite_ms:
                tempo = clamp(actual / effective_target_duration, atempo_min, atempo_max)
                adjusted_path = segment_dir / f"{seg_id}_a{attempt_no}_atempo.wav"
                try:
                    apply_atempo(input_path=raw_path, output_path=adjusted_path, tempo=tempo)
                    attempt_artifacts.append(adjusted_path)
                    actual2 = audio_duration(adjusted_path)
                    delta2 = actual2 - target_duration
                    delta2_effective = actual2 - effective_target_duration
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "atempo",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual2, 3),
                            "delta_sec": round(delta2, 3),
                            "result": "pass" if abs(delta2_effective) * 1000 <= delta_pass_ms else "fail",
                            "error": None,
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta2_effective, 3),
                            },
                            "ts": iso_now(),
                        }
                    )
                    if best is None or abs(delta2_effective) < abs(best[1] - effective_target_duration):
                        best = (adjusted_path, actual2, delta2)
                    if abs(delta2_effective) * 1000 <= delta_pass_ms:
                        final_status = "done"
                        retry_count = attempt_no
                        break
                except Exception as exc:
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "atempo",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual, 3),
                            "delta_sec": round(delta, 3),
                            "result": "fail",
                            "error": f"E-ALN-001 {type(exc).__name__}: {exc}",
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_effective, 3),
                            },
                            "ts": iso_now(),
                        }
                    )

            # 上传翻译字幕场景可关闭改写：仅做语音合成重试，不再改动字幕文本本身。
            if allow_rewrite_translation and attempt_no < max_retry:
                need_shorter = delta > 0
                try:
                    rewritten = retranslate_single_line(
                        translator=translator,
                        source_text=source_text,
                        current_translation=current_text,
                        target_lang=target_lang,
                        target_duration_sec=target_duration,
                        need_shorter=need_shorter,
                        aggressiveness=attempt_no + 1,
                    )
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "retranslate_tts",
                            "input_text": rewritten,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "pass",
                            "error": None,
                            "ts": iso_now(),
                        }
                    )
                    current_text = rewritten
                except Exception as exc:
                    failure_reason_code = "translation_empty_or_error"
                    failure_error_code = "E-TRN-002"
                    failure_stage = "translate"
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "retranslate_tts",
                            "input_text": current_text,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "fail",
                            "error": f"E-TRN-002 {type(exc).__name__}: {exc}",
                            "ts": iso_now(),
                        }
                    )

        if best is None:
            output_path = segment_dir / f"{seg_id}_missing.wav"
            sf.write(str(output_path), np.zeros(1600, dtype=np.float32), 16000)
            actual_best = 0.1
            delta_best = actual_best - target_duration
        else:
            output_path = segment_dir / f"{seg_id}.wav"
            shutil.copy2(best[0], output_path)
            actual_best = best[1]
            delta_best = best[2]
        effective_delta_best = actual_best - effective_target_duration

        record: Dict[str, Any] = {
            "id": seg_id,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "target_duration_sec": round(target_duration, 3),
            "source_text": source_text,
            "translated_text": current_text,
            "voice_ref_path": str(seg_ref_audio_path),
            "tts_audio_path": str(output_path),
            "actual_duration_sec": round(actual_best, 3),
            "delta_sec": round(delta_best, 3),
            "effective_target_duration_sec": round(effective_target_duration, 3),
            "borrowed_gap_sec": round(borrowed_gap_sec, 3),
            "effective_delta_sec": round(effective_delta_best, 3),
            "status": final_status if final_status == "done" else "manual_review",
            "retry_count": retry_count,
            "attempt_history": attempts,
        }
        records.append(record)

        if record["status"] != "done":
            manual_review.append(
                {
                    "segment_id": seg_id,
                    "reason_code": failure_reason_code,
                    "reason_detail": "segment not within pass threshold after retries",
                    "last_delta_sec": round(delta_best, 3),
                    "last_effective_delta_sec": round(effective_delta_best, 3),
                    "last_attempt_no": max_retry,
                    "error_code": failure_error_code,
                    "error_stage": failure_stage,
                }
            )
            logger.log(
                "WARN",
                "duration_align",
                "segment_manual_review_marked",
                f"{seg_id} marked manual review",
                segment_id=seg_id,
                data={
                    "error_code": failure_error_code,
                    "delta_sec": round(delta_best, 3),
                    "effective_delta_sec": round(effective_delta_best, 3),
                },
            )

        # 清理本句中间重试文件，目录中仅保留最终可消费结果，避免“命名一会一变”。
        for artifact in attempt_artifacts:
            try:
                if artifact.exists():
                    artifact.unlink(missing_ok=True)
            except Exception:
                pass

    return records, manual_review


def make_translated_and_bilingual_srt(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    translated_srt_path: Path,
    bilingual_srt_path: Optional[Path],
    bilingual_enabled: bool,
    target_lang: str,
    cjk_wrap_chars: int,
    display_merge_fragments: bool,
    display_merge_gap_sec: float,
) -> None:
    translated_subs: List[Dict[str, Any]] = []
    bilingual_subs: List[Dict[str, Any]] = []
    groups = (
        build_display_groups(
            subtitles=subtitles,
            translated_lines=translated_lines,
            max_gap_sec=display_merge_gap_sec,
        )
        if display_merge_fragments
        else [[index] for index in range(len(subtitles))]
    )

    cjk_mode = is_cjk_target_lang(target_lang)
    for group in groups:
        group_subs = [subtitles[index] for index in group]
        group_tgt = [translated_lines[index] for index in group]
        group_src = [subtitles[index]["text"] for index in group]

        merged_tgt = merge_text_lines(group_tgt, cjk_mode=cjk_mode)
        merged_src = merge_text_lines(group_src, cjk_mode=False)
        display_text = wrap_subtitle_text(
            merged_tgt,
            target_lang=target_lang,
            cjk_max_chars=cjk_wrap_chars,
        )

        translated_subs.append(
            {
                "start": float(group_subs[0]["start"]),
                "end": float(group_subs[-1]["end"]),
                "text": display_text,
            }
        )
        if bilingual_enabled:
            bilingual_subs.append(
                {
                    "start": float(group_subs[0]["start"]),
                    "end": float(group_subs[-1]["end"]),
                    "text": f"{display_text}\n{merged_src}",
                }
            )
    save_srt(translated_subs, translated_srt_path)
    if bilingual_enabled and bilingual_srt_path is not None:
        save_srt(bilingual_subs, bilingual_srt_path)


def make_dubbed_final_srt(
    *,
    subtitles: List[Dict[str, Any]],
    segment_records: List[Dict[str, Any]],
    final_srt_path: Path,
) -> None:
    final_subs: List[Dict[str, Any]] = []
    for item, record in zip(subtitles, segment_records):
        text = (record.get("translated_text") or item.get("text") or "").strip()
        final_subs.append(
            {
                "start": float(item["start"]),
                "end": float(item["end"]),
                "text": text,
            }
        )
    save_srt(final_subs, final_srt_path)


def build_manifest(
    *,
    job_id: str,
    args: argparse.Namespace,
    separation: SeparationResult,
    paths: Dict[str, Optional[Path]],
    segment_records: List[Dict[str, Any]],
    manual_review: List[Dict[str, Any]],
) -> Dict[str, Any]:
    done_count = sum(1 for item in segment_records if item["status"] == "done")
    failed_count = sum(1 for item in segment_records if item["status"] == "failed")
    manual_count = len(manual_review)
    return {
        "manifest_version": "v1",
        "job_id": job_id,
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "input_media_path": str(Path(args.input_media).expanduser()),
        "target_lang": args.target_lang,
        "speaker_mode": args.speaker_mode,
        "speaker_mode_requested": getattr(args, "speaker_mode_requested", args.speaker_mode),
        "speaker_mode_effective": getattr(args, "speaker_mode_effective", args.speaker_mode),
        "diarization_provider_requested": getattr(args, "diarization_provider", "auto"),
        "diarization_provider_effective": getattr(args, "diarization_provider_effective", "single"),
        "tts_backend": args.tts_backend,
        "range_strategy": getattr(args, "range_strategy", "all"),
        "requested_time_ranges": getattr(args, "requested_time_ranges", []),
        "effective_time_ranges": getattr(args, "effective_time_ranges", []),
        "separation_status": separation.separation_status,
        "paths": {
            "source_audio": str(paths["source_audio"]) if paths["source_audio"] else None,
            "source_vocals": str(paths["source_vocals"]) if paths["source_vocals"] else None,
            "source_bgm": str(paths["source_bgm"]) if paths["source_bgm"] else None,
            "source_srt": str(paths["source_srt"]) if paths["source_srt"] else None,
            "translated_srt": str(paths["translated_srt"]) if paths["translated_srt"] else None,
            "bilingual_srt": str(paths["bilingual_srt"]) if paths["bilingual_srt"] else None,
            "dubbed_final_srt": str(paths["dubbed_final_srt"]) if paths["dubbed_final_srt"] else None,
            "dubbed_vocals": str(paths["dubbed_vocals"]) if paths["dubbed_vocals"] else None,
            "dubbed_mix": str(paths["dubbed_mix"]) if paths["dubbed_mix"] else None,
            "separation_report": str(paths["separation_report"]) if paths["separation_report"] else None,
            "log_jsonl": str(paths["log_jsonl"]) if paths["log_jsonl"] else None,
        },
        "stats": {
            "total": len(segment_records),
            "done": done_count,
            "failed": failed_count,
            "manual_review": manual_count,
        },
        "segments": segment_records,
        "manual_review": manual_review,
    }


def build_failure_manifest(
    *,
    job_id: str,
    args: argparse.Namespace,
    paths: Dict[str, Optional[Path]],
    segment_records: List[Dict[str, Any]],
    manual_review: List[Dict[str, Any]],
    error_text: str,
    separation_status: str,
) -> Dict[str, Any]:
    done_count = sum(1 for item in segment_records if item.get("status") == "done")
    failed_count = max(1, sum(1 for item in segment_records if item.get("status") == "failed"))
    return {
        "manifest_version": "v1",
        "job_id": job_id,
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "input_media_path": str(Path(args.input_media).expanduser()),
        "target_lang": args.target_lang,
        "speaker_mode": args.speaker_mode,
        "speaker_mode_requested": getattr(args, "speaker_mode_requested", args.speaker_mode),
        "speaker_mode_effective": getattr(args, "speaker_mode_effective", args.speaker_mode),
        "diarization_provider_requested": getattr(args, "diarization_provider", "auto"),
        "diarization_provider_effective": getattr(args, "diarization_provider_effective", "single"),
        "tts_backend": args.tts_backend,
        "range_strategy": getattr(args, "range_strategy", "all"),
        "requested_time_ranges": getattr(args, "requested_time_ranges", []),
        "effective_time_ranges": getattr(args, "effective_time_ranges", []),
        "separation_status": separation_status,
        "status": "failed",
        "error": error_text,
        "paths": {
            "source_audio": str(paths["source_audio"]) if paths["source_audio"] else None,
            "source_vocals": str(paths["source_vocals"]) if paths["source_vocals"] else None,
            "source_bgm": str(paths["source_bgm"]) if paths["source_bgm"] else None,
            "source_srt": str(paths["source_srt"]) if paths["source_srt"] else None,
            "translated_srt": str(paths["translated_srt"]) if paths["translated_srt"] else None,
            "bilingual_srt": str(paths["bilingual_srt"]) if paths["bilingual_srt"] else None,
            "dubbed_final_srt": str(paths["dubbed_final_srt"]) if paths["dubbed_final_srt"] else None,
            "dubbed_vocals": str(paths["dubbed_vocals"]) if paths["dubbed_vocals"] else None,
            "dubbed_mix": str(paths["dubbed_mix"]) if paths["dubbed_mix"] else None,
            "separation_report": str(paths["separation_report"]) if paths["separation_report"] else None,
            "log_jsonl": str(paths["log_jsonl"]) if paths["log_jsonl"] else None,
        },
        "stats": {
            "total": len(segment_records),
            "done": done_count,
            "failed": failed_count,
            "manual_review": len(manual_review),
        },
        "segments": segment_records,
        "manual_review": manual_review,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-speaker dubbing pipeline (media -> subtitles -> translation -> cloning)")
    parser.add_argument("--input-media", required=True, help="Input media path (video/audio)")
    parser.add_argument("--target-lang", required=True, help="Target translation language")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--input-srt", help="Optional SRT path to skip ASR")
    parser.add_argument(
        "--input-srt-kind",
        default="source",
        choices=["source", "translated"],
        help="Type of --input-srt: source(need translation) or translated(skip translation)",
    )

    parser.add_argument("--speaker-mode", default="single-speaker", choices=["single-speaker", "per-speaker", "auto"])
    parser.add_argument("--diarization-provider", default="auto", choices=["auto", "pyannote", "simple"])
    parser.add_argument("--pyannote-model", default="pyannote/speaker-diarization-community-1")
    parser.add_argument("--pyannote-hf-token", default=None)
    parser.add_argument("--pyannote-device", default="auto")
    parser.add_argument("--pyannote-python-bin", default=os.environ.get("PYANNOTE_PYTHON_BIN", ""))
    parser.add_argument("--single-speaker-ref", help="Optional reference wav for single-speaker mode")
    parser.add_argument("--single-speaker-ref-seconds", type=float, default=10.0)

    parser.add_argument("--separate-vocals", default="true")
    parser.add_argument("--separator-model", default="htdemucs")
    parser.add_argument("--separator-fallback-model", default="mdx_q")
    parser.add_argument("--separator-device", default="auto")
    parser.add_argument("--on-separation-fail", default="vocals-only", choices=["vocals-only"])

    parser.add_argument("--delta-pass-ms", type=float, default=120.0)
    parser.add_argument("--delta-rewrite-ms", type=float, default=450.0)
    parser.add_argument("--atempo-min", type=float, default=0.92)
    parser.add_argument("--atempo-max", type=float, default=1.08)
    parser.add_argument("--max-retry", type=int, default=2)
    parser.add_argument("--force-fit-timing", default="true")
    parser.add_argument("--grouped-synthesis", default="true")
    parser.add_argument("--group-gap-sec", type=float, default=0.35)
    parser.add_argument("--group-min-dur-sec", type=float, default=1.8)
    parser.add_argument("--group-max-dur-sec", type=float, default=8.0)
    parser.add_argument("--grouping-strategy", default="sentence", choices=["legacy", "sentence"])
    parser.add_argument("--timing-mode", default="strict", choices=["strict", "balanced"])
    parser.add_argument("--balanced-max-tempo-shift", type=float, default=0.08)
    parser.add_argument("--balanced-min-line-sec", type=float, default=0.35)

    parser.add_argument("--bilingual-srt", default="false")
    parser.add_argument("--export-vocals", default="true")
    parser.add_argument("--export-mix", default="true")

    parser.add_argument("--asr-model-path", default=str(REPO_ROOT / "models/Qwen3-ASR-0.6B"))
    parser.add_argument("--aligner-path", default=str(REPO_ROOT / "models/Qwen3-ForcedAligner-0.6B"))
    parser.add_argument("--asr-device", default="mps")
    parser.add_argument("--asr-language", default=None)
    parser.add_argument("--max-width", type=int, default=40)
    parser.add_argument("--asr-balance-lines", default="true")
    parser.add_argument("--asr-balance-gap-sec", type=float, default=0.35)
    parser.add_argument("--time-ranges-json", default=None, help="Optional JSON list of {start_sec,end_sec} for dubbing")
    parser.add_argument("--auto-pick-ranges", default="false")
    parser.add_argument("--auto-pick-min-silence-sec", type=float, default=0.8)
    parser.add_argument("--auto-pick-min-speech-sec", type=float, default=1.0)

    parser.add_argument("--translate-base-url", default="https://api.deepseek.com")
    parser.add_argument("--translate-model", default="deepseek-chat")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--translate-system-prompt", default=None)
    parser.add_argument("--smart-layout", default="true")
    parser.add_argument("--smart-layout-gap-sec", type=float, default=0.35)
    parser.add_argument("--smart-layout-use-llm", default="false")
    parser.add_argument("--cjk-wrap-chars", type=int, default=18)
    parser.add_argument("--display-merge-fragments", default="false")
    parser.add_argument("--display-merge-gap-sec", type=float, default=0.35)

    parser.add_argument("--tts-backend", default="qwen", choices=["qwen", "index-tts"])
    parser.add_argument("--tts-model-path", default=str(REPO_ROOT / "models/Qwen3-TTS-12Hz-0.6B-Base"))
    parser.add_argument("--tts-device", default="mps")
    parser.add_argument("--tts-dtype", default="float16", choices=["float16", "bfloat16", "float32"])

    parser.add_argument("--index-tts-root", default="/Users/tim/Documents/vibe-coding/MVP/index-tts-1108")
    parser.add_argument("--index-tts-cfg-path", default=None)
    parser.add_argument("--index-tts-model-dir", default=None)
    parser.add_argument("--index-tts-via-api", default="true")
    parser.add_argument("--index-tts-api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--index-tts-api-timeout-sec", type=float, default=900.0)
    parser.add_argument("--index-tts-api-release-after-job", default="true")
    parser.add_argument("--index-use-fp16", default="false")
    parser.add_argument("--index-use-accel", default="false")
    parser.add_argument("--index-use-torch-compile", default="false")
    parser.add_argument("--index-emo-audio-prompt", default=None)
    parser.add_argument("--index-emo-alpha", type=float, default=1.0)
    parser.add_argument("--index-use-emo-text", default="false")
    parser.add_argument("--index-emo-text", default=None)
    parser.add_argument("--index-top-p", type=float, default=0.8)
    parser.add_argument("--index-top-k", type=int, default=30)
    parser.add_argument("--index-temperature", type=float, default=0.8)
    parser.add_argument("--index-max-text-tokens", type=int, default=120)
    parser.add_argument("--resume-job-dir", default=None, help="Reuse an existing job directory and continue processing")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (0 < args.single_speaker_ref_seconds <= 20):
        raise ValueError("--single-speaker-ref-seconds must be in (0, 20]")
    if not (0.8 <= args.atempo_min < 1.0):
        raise ValueError("--atempo-min must be in [0.8, 1.0)")
    if not (1.0 < args.atempo_max <= 1.2):
        raise ValueError("--atempo-max must be in (1.0, 1.2]")
    if not (0 < args.delta_pass_ms < args.delta_rewrite_ms):
        raise ValueError("--delta-pass-ms must be smaller than --delta-rewrite-ms")
    if not (0 <= args.max_retry <= 5):
        raise ValueError("--max-retry must be in [0, 5]")
    if not (0.0 <= args.group_gap_sec <= 1.5):
        raise ValueError("--group-gap-sec must be in [0.0, 1.5]")
    if not (0.5 <= args.group_min_dur_sec <= 10.0):
        raise ValueError("--group-min-dur-sec must be in [0.5, 10.0]")
    if not (1.0 <= args.group_max_dur_sec <= 20.0):
        raise ValueError("--group-max-dur-sec must be in [1.0, 20.0]")
    if args.group_min_dur_sec > args.group_max_dur_sec:
        raise ValueError("--group-min-dur-sec must be <= --group-max-dur-sec")
    if args.grouping_strategy not in {"legacy", "sentence"}:
        raise ValueError("--grouping-strategy must be one of: legacy, sentence")
    if args.timing_mode not in {"strict", "balanced"}:
        raise ValueError("--timing-mode must be one of: strict, balanced")
    if not (0.0 <= args.balanced_max_tempo_shift <= 0.3):
        raise ValueError("--balanced-max-tempo-shift must be in [0.0, 0.3]")
    if not (0.05 <= args.balanced_min_line_sec <= 2.0):
        raise ValueError("--balanced-min-line-sec must be in [0.05, 2.0]")
    if args.tts_backend not in {"qwen", "index-tts"}:
        raise ValueError("--tts-backend must be one of: qwen, index-tts")
    if not (0.0 <= args.index_emo_alpha <= 1.0):
        raise ValueError("--index-emo-alpha must be in [0.0, 1.0]")
    if not (0.1 <= args.index_top_p <= 1.0):
        raise ValueError("--index-top-p must be in [0.1, 1.0]")
    if not (1 <= args.index_top_k <= 200):
        raise ValueError("--index-top-k must be in [1, 200]")
    if not (0.1 <= args.index_temperature <= 2.0):
        raise ValueError("--index-temperature must be in [0.1, 2.0]")
    if not (10 <= args.index_max_text_tokens <= 400):
        raise ValueError("--index-max-text-tokens must be in [10, 400]")
    if not args.index_tts_api_url.strip():
        raise ValueError("--index-tts-api-url must not be empty")
    if args.index_tts_api_timeout_sec <= 0:
        raise ValueError("--index-tts-api-timeout-sec must be > 0")
    if not (0.0 <= args.smart_layout_gap_sec <= 1.5):
        raise ValueError("--smart-layout-gap-sec must be in [0.0, 1.5]")
    if not (0.0 <= args.display_merge_gap_sec <= 1.5):
        raise ValueError("--display-merge-gap-sec must be in [0.0, 1.5]")
    if not (0.0 <= args.asr_balance_gap_sec <= 1.5):
        raise ValueError("--asr-balance-gap-sec must be in [0.0, 1.5]")
    if not (10 <= args.cjk_wrap_chars <= 40):
        raise ValueError("--cjk-wrap-chars must be in [10, 40]")
    if args.diarization_provider not in {"auto", "pyannote", "simple"}:
        raise ValueError("--diarization-provider must be one of: auto, pyannote, simple")
    if args.auto_pick_min_silence_sec < 0.1 or args.auto_pick_min_silence_sec > 10.0:
        raise ValueError("--auto-pick-min-silence-sec must be in [0.1, 10.0]")
    if args.auto_pick_min_speech_sec < 0.1 or args.auto_pick_min_speech_sec > 30.0:
        raise ValueError("--auto-pick-min-speech-sec must be in [0.1, 30.0]")


def main() -> int:
    args = parse_args()
    validate_args(args)

    input_media = Path(args.input_media).expanduser()
    if not input_media.exists():
        print("E-IO-001 input media not found")
        return EXIT_FAILED

    output_root = Path(args.out_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.resume_job_dir:
        job_dir = Path(args.resume_job_dir).expanduser().resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        job_id = job_dir.name
    else:
        job_id = build_readable_run_id(
            root_dir=output_root,
            time_tag=datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
        )
        job_dir = output_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / "logs" / f"{job_id}.jsonl"
    logger = JsonlLogger(log_path, job_id)
    logger.log("INFO", "init", "job_started", "dubbing job started", progress=0)

    # 记录请求/生效的说话人模式，便于任务结果与日志排查。
    # 说明：auto/per-speaker 优先 pyannote community-1，失败自动回退 simple diarization。
    requested_speaker_mode = args.speaker_mode
    effective_speaker_mode = requested_speaker_mode
    args.speaker_mode_requested = requested_speaker_mode
    args.speaker_mode_effective = effective_speaker_mode
    if requested_speaker_mode != effective_speaker_mode:
        logger.log(
            "WARN",
            "init",
            "speaker_mode_fallback",
            "requested speaker mode is not fully implemented yet; fallback to single-speaker",
            data={
                "speaker_mode_requested": requested_speaker_mode,
                "speaker_mode_effective": effective_speaker_mode,
            },
        )
    elif effective_speaker_mode != "single-speaker":
        logger.log(
            "INFO",
            "init",
            "speaker_mode_preview_enabled",
            "multi-speaker mode enabled (simple diarization + speaker mapping)",
            data={"speaker_mode_effective": effective_speaker_mode},
        )
    args.speaker_mode = effective_speaker_mode

    source_audio = job_dir / "stems" / "source_audio.wav"
    source_vocals = job_dir / "stems" / "source_vocals.wav"
    source_bgm = job_dir / "stems" / "source_bgm.wav"
    translated_srt = job_dir / "subtitles" / "translated.srt"
    bilingual_srt = job_dir / "subtitles" / "bilingual.srt"
    dubbed_final_srt = job_dir / "subtitles" / "dubbed_final.srt"
    source_srt = job_dir / "subtitles" / "source.srt"
    segment_dir = job_dir / "dubbed_segments"
    dubbed_vocals = job_dir / "dubbed_vocals.wav"
    dubbed_mix = job_dir / "dubbed_mix.wav"
    ref_audio_path = job_dir / "refs" / "single_speaker_ref.wav"
    manifest_path = job_dir / "manifest.json"

    separate_vocals = read_bool(args.separate_vocals)
    input_srt_kind = (args.input_srt_kind or "source").strip().lower()
    input_srt_is_translated = bool(args.input_srt) and input_srt_kind == "translated"
    bilingual_enabled = read_bool(args.bilingual_srt)
    export_vocals = read_bool(args.export_vocals)
    export_mix = read_bool(args.export_mix)
    asr_balance_lines = read_bool(args.asr_balance_lines)
    auto_pick_ranges = read_bool(args.auto_pick_ranges)
    smart_layout_enabled = read_bool(args.smart_layout)
    smart_layout_use_llm = read_bool(args.smart_layout_use_llm)
    display_merge_fragments = read_bool(args.display_merge_fragments)
    force_fit_timing = read_bool(args.force_fit_timing)
    grouped_synthesis = read_bool(args.grouped_synthesis)
    # 上传“已翻译字幕”时，优先遵循用户提供的句级时间轴：
    # 1) 关闭 grouped 合成，改为逐句合成与逐句贴轨（严格对齐）；
    # 2) 逐句流程仍保留“借后续静音”窗口，避免尾音被硬截断导致漏音。
    if input_srt_is_translated:
        if grouped_synthesis:
            grouped_synthesis = False
            logger.log(
                "INFO",
                "tts",
                "grouped_synthesis_forced_off",
                "uploaded translated subtitles force per-line synthesis for strict start-time alignment",
                data={"input_srt_kind": "translated"},
            )
        # 上传翻译字幕时：只要求 start 严格对齐，end 允许自然收尾（可借后续静音，不强制 fit 到 end）。
        if force_fit_timing:
            force_fit_timing = False
            logger.log(
                "INFO",
                "duration_align",
                "force_fit_timing_forced_off",
                "uploaded translated subtitles disable hard end fitting (start-aligned, natural ending)",
                data={"input_srt_kind": "translated"},
            )
    # 保留 grouped 开关：用于对比 legacy/sentence 两种切分策略。
    index_use_fp16 = read_bool(args.index_use_fp16)
    index_use_accel = read_bool(args.index_use_accel)
    index_use_torch_compile = read_bool(args.index_use_torch_compile)
    index_use_emo_text = read_bool(args.index_use_emo_text)
    index_tts_via_api = read_bool(args.index_tts_via_api)
    index_tts_api_release_after_job = read_bool(args.index_tts_api_release_after_job)
    dubbed_vocals_internal = dubbed_vocals if export_vocals else (job_dir / "_tmp_dubbed_vocals.wav")
    should_release_index_tts_api = (
        args.tts_backend == "index-tts" and index_tts_via_api and index_tts_api_release_after_job
    )
    tts_qwen: Optional[Qwen3TTSModel] = None
    qwen_prompt_items: Optional[List[Any]] = None
    tts_index: Optional[Any] = None

    manual_review: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    separation_status = "unknown"
    paths: Dict[str, Optional[Path]] = {
        "source_audio": source_audio,
        "source_vocals": source_vocals,
        "source_bgm": source_bgm,
        "source_srt": source_srt,
        "translated_srt": translated_srt,
        "bilingual_srt": bilingual_srt if bilingual_enabled else None,
        "dubbed_final_srt": dubbed_final_srt,
        "dubbed_vocals": dubbed_vocals if export_vocals else None,
        "dubbed_mix": None,
        "separation_report": None,
        "log_jsonl": log_path,
    }
    manual_ranges_provided = args.time_ranges_json is not None
    requested_time_ranges = parse_time_ranges_json(args.time_ranges_json)
    effective_time_ranges: List[Tuple[float, float]] = []
    range_strategy = "all"

    try:
        if source_audio.exists():
            logger.log("INFO", "extract_audio", "extract_reused", "reused existing extracted audio", progress=10)
        else:
            logger.log("INFO", "extract_audio", "extract_started", "extracting source audio", progress=6)
            extract_audio(input_media, source_audio)
            logger.log("INFO", "extract_audio", "extract_completed", "source audio extracted", progress=10)

        source_duration_sec = audio_duration(source_audio)
        if manual_ranges_provided:
            effective_time_ranges = normalize_time_ranges(
                [
                    (
                        max(0.0, min(start_sec, source_duration_sec)),
                        max(0.0, min(end_sec, source_duration_sec)),
                    )
                    for start_sec, end_sec in requested_time_ranges
                    if end_sec > start_sec
                ]
            )
            range_strategy = "manual"
        elif auto_pick_ranges:
            effective_time_ranges = detect_speech_time_ranges(
                input_audio=source_audio,
                min_silence_sec=float(args.auto_pick_min_silence_sec),
                min_speech_sec=float(args.auto_pick_min_speech_sec),
            )
            range_strategy = "auto"
        if effective_time_ranges:
            logger.log(
                "INFO",
                "asr_align",
                "range_selection_result",
                "time range selection enabled",
                data={
                    "strategy": range_strategy,
                    "requested_ranges": [{"start_sec": round(s, 3), "end_sec": round(e, 3)} for s, e in requested_time_ranges],
                    "effective_ranges": [{"start_sec": round(s, 3), "end_sec": round(e, 3)} for s, e in effective_time_ranges],
                },
            )
        elif range_strategy != "all":
            logger.log(
                "WARN",
                "asr_align",
                "range_selection_empty",
                "no effective time ranges selected, fallback to all subtitles",
                data={"strategy": range_strategy},
            )
        args.range_strategy = range_strategy
        args.requested_time_ranges = [
            {"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
            for start_sec, end_sec in requested_time_ranges
        ]
        args.effective_time_ranges = [
            {"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)}
            for start_sec, end_sec in effective_time_ranges
        ]
        if source_srt.exists():
            source_subtitles_loaded = parse_srt(source_srt.read_text(encoding="utf-8"))
            # 兼容历史任务：复用旧字幕前先做文本清洗，避免旧文件中的标签/括号说明污染 TTS。
            source_subtitles_loaded, source_sanitize_count = sanitize_subtitles_for_tts(source_subtitles_loaded)
            if source_sanitize_count > 0:
                save_srt(source_subtitles_loaded, source_srt)
                logger.log(
                    "INFO",
                    "asr_align",
                    "source_subtitle_sanitized",
                    "sanitized existing source subtitles before reuse",
                    data={"sanitized_lines": int(source_sanitize_count)},
                )
            source_health = analyze_subtitle_timestamps(source_subtitles_loaded)
            bad_source_srt = (
                source_health["zero_or_negative"] > 0
                or source_health["non_monotonic"] > 0
                or source_health["zero_ratio"] > 0.05
            )
            if bad_source_srt:
                logger.log(
                    "WARN",
                    "asr_align",
                    "source_subtitle_rejected",
                    "existing source subtitle failed timestamp health check, regenerating",
                    data=source_health,
                )
                subtitles = load_or_transcribe_subtitles(
                    input_srt=Path(args.input_srt).expanduser() if args.input_srt else None,
                    asr_audio=source_audio,
                    source_srt_path=source_srt,
                    asr_model_path=args.asr_model_path,
                    aligner_path=args.aligner_path,
                    device=args.asr_device,
                    language=args.asr_language,
                    max_width=args.max_width,
                    asr_balance_lines=asr_balance_lines,
                    asr_balance_gap_sec=args.asr_balance_gap_sec,
                    logger=logger,
                )
                translated_lines = []
            else:
                subtitles = source_subtitles_loaded
                if translated_srt.exists():
                    translated_items = parse_srt(translated_srt.read_text(encoding="utf-8"))
                    translated_items, translated_sanitize_count = sanitize_subtitles_for_tts(translated_items)
                    if translated_sanitize_count > 0:
                        save_srt(translated_items, translated_srt)
                        logger.log(
                            "INFO",
                            "translate",
                            "translated_subtitle_sanitized",
                            "sanitized existing translated subtitles before reuse",
                            data={"sanitized_lines": int(translated_sanitize_count)},
                        )
                else:
                    translated_items = []
                if len(subtitles) == len(translated_items) and subtitles and translated_items:
                    translated_lines = [item["text"] for item in translated_items]
                    logger.log(
                        "INFO",
                        "asr_align",
                        "subtitle_reused",
                        "reused existing source/translated subtitles",
                        data={"count": len(subtitles), "timestamp_health": source_health},
                    )
                else:
                    logger.log(
                        "INFO",
                        "asr_align",
                        "source_subtitle_reused",
                        "reused existing source subtitles, will regenerate translation",
                        data={"count": len(subtitles), "timestamp_health": source_health},
                    )
                    translated_lines = []
        else:
            subtitles = load_or_transcribe_subtitles(
                input_srt=Path(args.input_srt).expanduser() if args.input_srt else None,
                asr_audio=source_audio,
                source_srt_path=source_srt,
                asr_model_path=args.asr_model_path,
                aligner_path=args.aligner_path,
                device=args.asr_device,
                language=args.asr_language,
                max_width=args.max_width,
                asr_balance_lines=asr_balance_lines,
                asr_balance_gap_sec=args.asr_balance_gap_sec,
                logger=logger,
            )
            if not subtitles:
                raise RuntimeError("E-ASR-001 no subtitles produced")
            translated_lines = []

        # 在识别完成后按时间区间过滤字幕，确保后续翻译/TTS 仅处理指定区间。
        if range_strategy != "all":
            before_count = len(subtitles)
            subtitles = filter_subtitles_by_time_ranges(
                subtitles=subtitles,
                time_ranges=effective_time_ranges,
                boundary_pad_sec=0.20,
            )
            subtitles = enforce_subtitle_timestamps(
                subtitles=subtitles,
                media_duration_sec=source_duration_sec,
            )
            save_srt(subtitles, source_srt)
            logger.log(
                "INFO",
                "asr_align",
                "range_filter_applied",
                "subtitle range filtering applied",
                data={"before": before_count, "after": len(subtitles)},
            )
            if input_srt_is_translated:
                # 上传的是翻译字幕：区间过滤后直接复用为配音文本，跳过翻译阶段。
                translated_lines = [sanitize_subtitle_text(item["text"]) for item in subtitles]
                save_srt(
                    [
                        {"start": float(item["start"]), "end": float(item["end"]), "text": text}
                        for item, text in zip(subtitles, translated_lines)
                    ],
                    translated_srt,
                )
            else:
                translated_lines = []

        # 识别字幕完成后再做人声分离，避免“分离音频退化”影响字幕时间戳。
        if source_vocals.exists():
            separation = SeparationResult(
                source_audio=source_audio,
                vocals_audio=source_vocals,
                bgm_audio=source_bgm if source_bgm.exists() else None,
                separation_status="ok",
                separation_report=job_dir / "separation_report.json",
            )
            logger.log("INFO", "separate_vocals", "separation_reused", "reused existing separated vocals/bgm", progress=36)
        elif separate_vocals:
            separation = separate_audio(
                source_audio=source_audio,
                source_vocals=source_vocals,
                source_bgm=source_bgm,
                out_dir=job_dir,
                primary_model=args.separator_model,
                fallback_model=args.separator_fallback_model,
                separator_device=args.separator_device,
                logger=logger,
            )
        else:
            shutil.copy2(source_audio, source_vocals)
            separation = SeparationResult(
                source_audio=source_audio,
                vocals_audio=source_vocals,
                bgm_audio=None,
                separation_status="ok",
                separation_report=job_dir / "separation_report.json",
            )
            separation.separation_report.write_text(
                json.dumps(
                    {
                        "ts": iso_now(),
                        "status": "ok",
                        "attempts": [{"model": "disabled", "ok": True, "error": ""}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        paths["source_vocals"] = separation.vocals_audio
        paths["source_bgm"] = separation.bgm_audio
        paths["separation_report"] = separation.separation_report
        separation_status = separation.separation_status
        logger.log(
            "INFO",
            "asr_align",
            "asr_source_timeline_confirmed",
            "asr timeline anchored to source audio before separation",
            data={"source_audio_duration_sec": round(float(source_duration_sec), 3)},
        )

        translator: Optional[Translator] = None
        if not subtitles:
            logger.log(
                "INFO",
                "translate",
                "translation_skipped_no_subtitles",
                "no subtitles selected by ranges, skip translation",
                progress=60,
            )
            translated_lines = []
        elif input_srt_is_translated:
            # 关键逻辑：当输入字幕已是目标语言时，直接跳过翻译并复用文本。
            translated_lines = [sanitize_subtitle_text(item["text"]) for item in subtitles]
            save_srt(
                [
                    {"start": float(item["start"]), "end": float(item["end"]), "text": text}
                    for item, text in zip(subtitles, translated_lines)
                ],
                translated_srt,
            )
            logger.log(
                "INFO",
                "translate",
                "translation_skipped_input_translated_srt",
                "uploaded subtitles marked translated, skip translation step",
                progress=60,
                data={"count": len(translated_lines)},
            )
            logger.log(
                "INFO",
                "translate",
                "translation_rewrite_disabled",
                "uploaded translated subtitles disable rewrite step to preserve provided wording",
                data={"input_srt_kind": "translated"},
            )
        elif not translated_lines:
            api_key = args.api_key or os.environ.get(args.api_key_env)
            if not api_key:
                raise RuntimeError(f"E-TRN-001 missing api key (set --api-key or {args.api_key_env})")
            translator = Translator(
                api_key=api_key,
                base_url=args.translate_base_url,
                model=args.translate_model,
            )

            source_lines = [item["text"] for item in subtitles]
            durations = [float(item["end"]) - float(item["start"]) for item in subtitles]
            logger.log("INFO", "translate", "translation_started", "translating subtitles", progress=50)
            translated_lines = translate_batch_with_budget(
                translator=translator,
                lines=source_lines,
                durations=durations,
                target_lang=args.target_lang,
                system_prompt=args.translate_system_prompt,
            )
            if len(translated_lines) != len(subtitles):
                raise RuntimeError("E-TRN-002 translation count mismatch")

            translated_lines = smart_layout_translated_lines(
                subtitles=subtitles,
                translated_lines=translated_lines,
                translator=translator,
                target_lang=args.target_lang,
                enabled=smart_layout_enabled,
                max_gap_sec=args.smart_layout_gap_sec,
                use_llm=smart_layout_use_llm,
                logger=logger,
            )
            translated_lines = repair_punctuation_only_translations(
                subtitles=subtitles,
                translated_lines=translated_lines,
                translator=translator,
                target_lang=args.target_lang,
                logger=logger,
            )
            logger.log("INFO", "translate", "translation_completed", "translation completed", progress=60)

            make_translated_and_bilingual_srt(
                subtitles=subtitles,
                translated_lines=translated_lines,
                translated_srt_path=translated_srt,
                bilingual_srt_path=bilingual_srt,
                bilingual_enabled=bilingual_enabled,
                target_lang=args.target_lang,
                cjk_wrap_chars=args.cjk_wrap_chars,
                display_merge_fragments=display_merge_fragments,
                display_merge_gap_sec=args.display_merge_gap_sec,
            )
        else:
            logger.log("INFO", "translate", "translation_reused", "reused existing translated subtitles", progress=60)

        ref_audio_selector: Optional[Callable[[int], Path]] = None
        subtitle_speakers: List[str] = []
        diar_segments: List[Dict[str, Any]] = []
        if args.single_speaker_ref:
            src_ref = Path(args.single_speaker_ref).expanduser()
            if not src_ref.exists():
                raise RuntimeError("E-REF-001 provided --single-speaker-ref does not exist")
            ensure_parent(ref_audio_path)
            shutil.copy2(src_ref, ref_audio_path)
        else:
            # 保留一个兜底参考音（当分段切片失败时回退使用）
            extract_reference_audio(
                vocals_audio=separation.vocals_audio,
                out_ref=ref_audio_path,
                seconds=float(args.single_speaker_ref_seconds),
            )

        # 统一策略：停用 pyannote/simple，不区分单人多人，逐句使用“原音频窗口”做克隆+情绪参考。
        args.diarization_provider_effective = "disabled"
        subtitle_ref_map = build_subtitle_reference_map(
            subtitles=subtitles,
            source_audio=source_audio,
            out_dir=job_dir / "refs" / "subtitles",
            default_ref=ref_audio_path,
        )

        def _selector(index: int) -> Path:
            return subtitle_ref_map.get(index, ref_audio_path)

        ref_audio_selector = _selector
        subtitle_speakers = [f"line_{index + 1:04d}" for index in range(len(subtitles))]
        diar_segments = []
        logger.log(
            "INFO",
            "ref_extract",
            "sentence_reference_mode_enabled",
            "using per-subtitle original-audio references for all speaker modes",
            data={"reference_count": len(subtitle_ref_map)},
        )

        logger.log(
            "INFO",
            "ref_extract",
            "reference_ready",
            "reference audio ready",
            progress=63,
            data={
                "speaker_mode_effective": args.speaker_mode,
                "reference_strategy": "sentence_original_audio_per_subtitle",
                "diarization_provider_effective": getattr(args, "diarization_provider_effective", "single"),
                "diar_segments": len(diar_segments),
                "speakers": sorted(list({seg.get("speaker_id") for seg in diar_segments})) if diar_segments else ["spk_1"],
            },
        )

        logger.log("INFO", "tts", "tts_model_loading", "loading tts model")

        if args.tts_backend == "qwen":
            tts_qwen = load_tts_model(args.tts_model_path, args.tts_device, args.tts_dtype)
            qwen_prompt_items = tts_qwen.create_voice_clone_prompt(
                ref_audio=str(ref_audio_path),
                ref_text=None,
                x_vector_only_mode=True,
            )
        else:
            if index_tts_via_api:
                check_index_tts_service(
                    api_url=args.index_tts_api_url,
                    timeout_sec=args.index_tts_api_timeout_sec,
                )
                logger.log(
                    "INFO",
                    "tts",
                    "index_tts_api_ready",
                    "index-tts api service is ready",
                    data={"api_url": args.index_tts_api_url},
                )
            else:
                tts_index = load_index_tts_model(
                    root_dir=args.index_tts_root,
                    cfg_path=args.index_tts_cfg_path,
                    model_dir=args.index_tts_model_dir,
                    device=args.tts_device,
                    use_fp16=index_use_fp16,
                    use_accel=index_use_accel,
                    use_torch_compile=index_use_torch_compile,
                )

        index_emo_audio_prompt_path: Optional[Path] = None
        if args.index_emo_audio_prompt:
            index_emo_audio_prompt_path = Path(args.index_emo_audio_prompt).expanduser()
            if not index_emo_audio_prompt_path.exists():
                raise RuntimeError(f"E-TTS-001 index emo audio prompt not found: {index_emo_audio_prompt_path}")

        if grouped_synthesis:
            records, segment_manual = synthesize_segments_grouped(
                tts_backend=args.tts_backend,
                index_tts_via_api=index_tts_via_api,
                index_tts_api_url=args.index_tts_api_url,
                index_tts_api_timeout_sec=args.index_tts_api_timeout_sec,
                tts_qwen=tts_qwen,
                qwen_prompt_items=qwen_prompt_items,
                tts_index=tts_index,
                ref_audio_path=ref_audio_path,
                ref_audio_selector=ref_audio_selector,
                source_media_duration_sec=source_duration_sec,
                index_emo_audio_prompt=index_emo_audio_prompt_path,
                index_emo_alpha=args.index_emo_alpha,
                index_use_emo_text=index_use_emo_text,
                index_emo_text=args.index_emo_text,
                index_top_p=args.index_top_p,
                index_top_k=args.index_top_k,
                index_temperature=args.index_temperature,
                index_max_text_tokens=args.index_max_text_tokens,
                force_fit_timing=force_fit_timing,
                group_gap_sec=args.group_gap_sec,
                group_min_duration_sec=args.group_min_dur_sec,
                group_max_duration_sec=args.group_max_dur_sec,
                subtitle_speakers=subtitle_speakers if args.speaker_mode != "single-speaker" else None,
                timing_mode=args.timing_mode,
                balanced_max_tempo_shift=args.balanced_max_tempo_shift,
                balanced_min_line_sec=args.balanced_min_line_sec,
                grouping_strategy=args.grouping_strategy,
                subtitles=subtitles,
                translated_lines=translated_lines,
                segment_dir=segment_dir,
                delta_pass_ms=args.delta_pass_ms,
                logger=logger,
                target_lang=args.target_lang,
            )
        else:
            records, segment_manual = synthesize_segments(
                tts_backend=args.tts_backend,
                index_tts_via_api=index_tts_via_api,
                index_tts_api_url=args.index_tts_api_url,
                index_tts_api_timeout_sec=args.index_tts_api_timeout_sec,
                tts_qwen=tts_qwen,
                qwen_prompt_items=qwen_prompt_items,
                tts_index=tts_index,
                ref_audio_path=ref_audio_path,
                ref_audio_selector=ref_audio_selector,
                source_vocals_audio=separation.vocals_audio,
                source_media_duration_sec=source_duration_sec,
                speaker_mode=args.speaker_mode,
                index_emo_audio_prompt=index_emo_audio_prompt_path,
                index_emo_alpha=args.index_emo_alpha,
                index_use_emo_text=index_use_emo_text,
                index_emo_text=args.index_emo_text,
                index_top_p=args.index_top_p,
                index_top_k=args.index_top_k,
                index_temperature=args.index_temperature,
                index_max_text_tokens=args.index_max_text_tokens,
                force_fit_timing=force_fit_timing,
                subtitles=subtitles,
                translated_lines=translated_lines,
                segment_dir=segment_dir,
                delta_pass_ms=args.delta_pass_ms,
                delta_rewrite_ms=args.delta_rewrite_ms,
                atempo_min=args.atempo_min,
                atempo_max=args.atempo_max,
                max_retry=args.max_retry,
                translator=translator if translator is not None else Translator(
                    api_key=args.api_key or os.environ.get(args.api_key_env) or "",
                    base_url=args.translate_base_url,
                    model=args.translate_model,
                ),
                target_lang=args.target_lang,
                allow_rewrite_translation=not input_srt_is_translated,
                logger=logger,
            )
        manual_review.extend(segment_manual)
        for record in records:
            if not record.get("voice_ref_path"):
                record["voice_ref_path"] = str(ref_audio_path)

        if not index_tts_via_api:
            release_local_tts_models(tts_qwen=tts_qwen, tts_index=tts_index, logger=logger)
            tts_qwen = None
            tts_index = None

        make_dubbed_final_srt(
            subtitles=subtitles,
            segment_records=records,
            final_srt_path=dubbed_final_srt,
        )

        logger.log("INFO", "mix", "compose_vocals_started", "building dubbed vocals master", progress=90)
        vocals_master_path, vocals_sr = compose_vocals_master(
            segments=records,
            output_path=dubbed_vocals_internal,
            source_audio_fallback=separation.vocals_audio,
        )
        if export_vocals:
            paths["dubbed_vocals"] = vocals_master_path

        if export_mix and separation.bgm_audio is not None:
            try:
                logger.log("INFO", "mix", "mix_started", "mixing vocals with bgm", progress=94)
                mix_with_bgm(
                    vocals_path=vocals_master_path,
                    bgm_path=separation.bgm_audio,
                    output_path=dubbed_mix,
                    target_sr=vocals_sr,
                )
                paths["dubbed_mix"] = dubbed_mix
            except Exception as exc:
                manual_review.append(
                    {
                        "segment_id": "__mix__",
                        "reason_code": "separation_failed_mix_missing",
                        "reason_detail": str(exc),
                        "last_delta_sec": None,
                        "last_attempt_no": None,
                        "error_code": "E-MIX-001",
                        "error_stage": "mix",
                    }
                )
                logger.log(
                    "WARN",
                    "mix",
                    "mix_failed",
                    "mix failed, vocals-only output preserved",
                    data={"error_code": "E-MIX-001", "error": str(exc)},
                )

        if not export_vocals and dubbed_vocals_internal.exists():
            dubbed_vocals_internal.unlink(missing_ok=True)

        manifest = build_manifest(
            job_id=job_id,
            args=args,
            separation=separation,
            paths=paths,
            segment_records=records,
            manual_review=manual_review,
        )
        ensure_parent(manifest_path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = {
            "job_id": job_id,
            "out_dir": str(job_dir),
            "manifest_path": str(manifest_path),
            "summary": manifest["stats"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        logger.log("INFO", "finish", "job_finished", "job completed", progress=100, data=manifest["stats"])

        if manual_review:
            return EXIT_OK_WITH_MANUAL_REVIEW
        return EXIT_OK
    except BaseException as exc:
        logger.log(
            "ERROR",
            "finish",
            "job_failed",
            "pipeline failed",
            data={"error": str(exc)},
        )
        try:
            failed_manifest = build_failure_manifest(
                job_id=job_id,
                args=args,
                paths=paths,
                segment_records=records,
                manual_review=manual_review,
                error_text=str(exc),
                separation_status=separation_status,
            )
            ensure_parent(manifest_path)
            manifest_path.write_text(json.dumps(failed_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        print(f"Pipeline failed: {exc}")
        if isinstance(exc, KeyboardInterrupt):
            raise
        return EXIT_FAILED
    finally:
        if tts_qwen is not None or tts_index is not None:
            try:
                release_local_tts_models(tts_qwen=tts_qwen, tts_index=tts_index, logger=logger)
            except Exception:
                pass
        if should_release_index_tts_api:
            try:
                release_index_tts_api_model(
                    api_url=args.index_tts_api_url,
                    timeout_sec=args.index_tts_api_timeout_sec,
                )
                logger.log("INFO", "tts", "index_tts_api_released", "index-tts api model released")
            except Exception as release_exc:
                logger.log(
                    "WARN",
                    "tts",
                    "index_tts_api_release_failed",
                    "index-tts api model release failed",
                    data={"error": str(release_exc)},
                )


if __name__ == "__main__":
    raise SystemExit(main())
