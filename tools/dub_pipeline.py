#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import html
import json
import math
import os
import re
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
import librosa

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from subtitle_maker.transcriber import SubtitleGenerator, format_srt, parse_srt
from subtitle_maker.backends import (
    check_index_tts_service as check_index_tts_service_impl,
    release_index_tts_api_model as release_index_tts_api_model_impl,
    split_text_for_index_tts as split_text_for_index_tts_impl,
    synthesize_via_index_tts_api as synthesize_via_index_tts_api_impl,
)
from subtitle_maker.core.ffmpeg import run_cmd as run_cmd_impl
from subtitle_maker.domains.dubbing import (
    allocate_balanced_durations as allocate_balanced_durations_impl,
    apply_atempo as apply_atempo_impl,
    apply_short_fade_edges as apply_short_fade_edges_impl,
    build_atempo_filter_chain as build_atempo_filter_chain_impl,
    build_subtitle_reference_map as build_subtitle_reference_map_impl,
    build_synthesis_groups as build_synthesis_groups_impl,
    compute_effective_target_duration as compute_effective_target_duration_impl,
    estimate_line_speech_weight as estimate_line_speech_weight_impl,
    extract_reference_audio as extract_reference_audio_impl,
    extract_reference_audio_from_offset as extract_reference_audio_from_offset_impl,
    extract_reference_audio_from_window as extract_reference_audio_from_window_impl,
    fit_audio_to_duration as fit_audio_to_duration_impl,
    split_waveform_by_durations as split_waveform_by_durations_impl,
    synthesize_segments as synthesize_segments_impl,
    synthesize_segments_grouped as synthesize_segments_grouped_impl,
    synthesize_text_once as synthesize_text_once_impl,
    trim_audio_to_max_duration as trim_audio_to_max_duration_impl,
    trim_silence_edges as trim_silence_edges_impl,
)
from subtitle_maker.domains.media import (
    audio_duration as audio_duration_impl,
    compose_vocals_master as compose_vocals_master_impl,
    concat_generated_wavs as concat_generated_wavs_impl,
    mix_with_bgm as mix_with_bgm_impl,
)
from subtitle_maker.domains.subtitles import (
    allocate_text_segment_times as allocate_text_segment_times_impl,
    build_asr_gap_clusters as build_asr_gap_clusters_impl,
    choose_asr_sentence_split_index as choose_asr_sentence_split_index_impl,
    expand_block_with_punctuation_splits as expand_block_with_punctuation_splits_impl,
    has_internal_explicit_break_boundary as has_internal_explicit_break_boundary_impl,
    merge_short_source_subtitles as merge_short_source_subtitles_impl,
    source_short_merge_tolerance_seconds as source_short_merge_tolerance_seconds_impl,
    split_cluster_into_punctuation_blocks as split_cluster_into_punctuation_blocks_impl,
    split_cluster_into_sentence_blocks as split_cluster_into_sentence_blocks_impl,
    split_oversized_asr_sentence_block as split_oversized_asr_sentence_block_impl,
    split_subtitle_item_by_punctuation as split_subtitle_item_by_punctuation_impl,
    split_text_on_punctuation_boundaries as split_text_on_punctuation_boundaries_impl,
)
from subtitle_maker.manifests import (
    BatchReplayOptions,
    build_failed_segment_manifest,
    build_segment_manifest,
    load_segment_manifest,
    write_manifest_json,
)
from subtitle_maker.translator import Translator
from subtitle_maker.qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel

# Exit-code contract for callers (e.g. dub_long_video.py)
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_OK_WITH_MANUAL_REVIEW = 2

# 第 2 步“合并短句”改为按时间窗工作，而不是按字数凑阈值。
DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC = 15
MIN_SOURCE_SHORT_MERGE_TARGET_SEC = 6
MAX_SOURCE_SHORT_MERGE_TARGET_SEC = 20
DEFAULT_SOURCE_SHORT_MERGE_GAP_SEC = 1.5


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
    """兼容旧入口：读取音频元信息并返回时长秒数。"""
    return audio_duration_impl(path)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """兼容旧入口：执行命令并返回退出码、stdout、stderr。"""
    return run_cmd_impl(cmd, cwd=cwd)


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


def normalize_subtitle_sentence_units(
    *,
    subtitles: List[Dict[str, Any]],
    media_duration_sec: float,
    min_duration_sec: float = 0.12,
) -> List[Dict[str, Any]]:
    """标准化句单元时间轴：保证 start/end 单调，且最后一句可落到媒体末尾。

    设计目标：
    1) 统一输出稳定句单元（句 + start/end）；
    2) 对无效 end（缺失/倒序）使用“下一句 start”补齐；
    3) 最后一句在必要时补到媒体末尾，减少尾句被过早截断。
    """
    if not subtitles:
        return []

    safe_media_duration = max(float(media_duration_sec), float(min_duration_sec))
    prepared: List[Dict[str, Any]] = []
    for item in subtitles:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", start_sec) or start_sec)
        prepared.append({"start": start_sec, "end": end_sec, "text": text})
    if not prepared:
        return []

    prepared.sort(key=lambda x: float(x.get("start", 0.0) or 0.0))
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

        if raw_end > start_sec + 1e-6:
            end_sec = min(raw_end, next_start)
        else:
            end_sec = next_start

        if index == total - 1 and end_sec <= start_sec + 1e-6:
            end_sec = safe_media_duration

        if end_sec <= start_sec + 1e-6:
            end_sec = min(safe_media_duration, start_sec + float(min_duration_sec))
        if end_sec <= start_sec + 1e-6:
            continue

        output.append({"start": start_sec, "end": end_sec, "text": item["text"]})
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


def parse_redub_line_indices_json(raw: Optional[str]) -> Optional[set[int]]:
    # 解析局部重配行号（1-based）；None 表示不限制（全量）。
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise ValueError(f"invalid --redub-line-indices-json: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("--redub-line-indices-json must be a list")
    indices: set[int] = set()
    for item in payload:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            indices.add(value)
    return indices


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
    persist_input_srt_to_source: bool,
    asr_model_path: str,
    aligner_path: str,
    device: str,
    language: Optional[str],
    max_width: int,
    asr_balance_lines: bool,
    asr_balance_gap_sec: float,
    source_layout_mode: str,
    source_layout_llm_min_duration_sec: float,
    source_layout_llm_min_text_units: int,
    source_layout_llm_max_cues: int,
    source_short_merge_enabled: bool,
    source_short_merge_threshold: int,
    translator_factory: Optional[Callable[[], Translator]],
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
        # 上传 source.srt 也复用与 ASR 相同的分句规则，保证最终落盘的
        # source.srt 与后续翻译/TTS 使用的是同一份句级结果。
        if persist_input_srt_to_source and asr_balance_lines:
            subtitles = rebalance_source_subtitles(
                subtitles=subtitles,
                max_gap_sec=asr_balance_gap_sec,
                max_line_width=max_width,
                source_layout_mode=source_layout_mode,
                source_layout_llm_min_duration_sec=source_layout_llm_min_duration_sec,
                source_layout_llm_min_text_units=source_layout_llm_min_text_units,
                source_layout_llm_max_cues=source_layout_llm_max_cues,
                source_short_merge_enabled=source_short_merge_enabled,
                source_short_merge_threshold=source_short_merge_threshold,
                translator_factory=translator_factory,
                logger=logger,
            )
            subtitles = enforce_subtitle_timestamps(
                subtitles=subtitles,
                media_duration_sec=media_duration_sec,
            )
        if persist_input_srt_to_source:
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
                max_line_width=max_width,
                source_layout_mode=source_layout_mode,
                source_layout_llm_min_duration_sec=source_layout_llm_min_duration_sec,
                source_layout_llm_min_text_units=source_layout_llm_min_text_units,
                source_layout_llm_max_cues=source_layout_llm_max_cues,
                source_short_merge_enabled=source_short_merge_enabled,
                source_short_merge_threshold=source_short_merge_threshold,
                translator_factory=translator_factory,
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


def has_soft_sentence_break(text: str) -> bool:
    """判断文本里是否存在适合长句软切分的次级停顿标记。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(re.search(r"[,;:，、；：…]", cleaned))


def ends_with_soft_sentence_break(text: str) -> bool:
    """判断文本是否以逗号等软停顿结尾。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(re.search(r"[,;:，、；：…]\s*$", cleaned))


def ends_with_explicit_break(text: str) -> bool:
    """判断文本是否以显式标点边界结尾。"""
    return is_sentence_end(text) or ends_with_soft_sentence_break(text)


def subtitle_group_duration(items: List[Dict[str, Any]]) -> float:
    """返回连续字幕组的总时长。"""
    if not items:
        return 0.0
    return max(0.0, float(items[-1]["end"]) - float(items[0]["start"]))


def subtitle_group_text(items: List[Dict[str, Any]], *, cjk_mode: bool) -> str:
    """按语言模式合并连续字幕组文本。"""
    return merge_text_lines([(item.get("text") or "").strip() for item in items], cjk_mode=cjk_mode)


def subtitle_text_units(text: str, *, cjk_mode: bool) -> int:
    """估算文本负载，用于决定超长句是否需要再拆。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    if cjk_mode:
        return len(re.sub(r"\s+", "", cleaned))
    return len(re.sub(r"\s+", " ", cleaned))


def asr_sentence_text_limit(*, max_line_width: int, cjk_mode: bool) -> int:
    """给句级合并提供较宽松的文本上限，避免退回碎片字幕。"""
    width = max(8, int(max_line_width or 0))
    if cjk_mode:
        return max(48, width * 2)
    return max(160, width * 4)


def extract_edge_tokens(text: str) -> List[str]:
    """抽取文本首尾 token，用于避免切在明显生硬的位置。"""
    return re.findall(r"[A-Za-z']+|[\u4e00-\u9fff]+", (text or "").lower())


def ends_with_connector(text: str) -> bool:
    """检测文本是否以连接词结尾，避免拆出半句。"""
    tokens = extract_edge_tokens(text)
    if not tokens:
        return False
    return tokens[-1] in {
        "a",
        "an",
        "and",
        "as",
        "at",
        "because",
        "but",
        "for",
        "from",
        "if",
        "in",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "to",
        "when",
        "while",
        "with",
        "了",
        "但",
        "又",
        "和",
        "就",
        "而",
        "还",
    }


def starts_with_connector(text: str) -> bool:
    """检测文本是否以连接词起头，避免后半句悬空。"""
    tokens = extract_edge_tokens(text)
    if not tokens:
        return False
    return tokens[0] in {
        "and",
        "as",
        "because",
        "but",
        "for",
        "if",
        "no",
        "or",
        "so",
        "that",
        "then",
        "to",
        "when",
        "while",
        "with",
        "但",
        "又",
        "和",
        "就",
        "而",
        "还",
    }


def split_text_on_punctuation_boundaries(
    text: str,
    *,
    include_soft_breaks: bool,
) -> List[str]:
    """兼容旧入口：按标点切分文本，并把标点保留在左侧片段。"""
    return split_text_on_punctuation_boundaries_impl(text, include_soft_breaks=include_soft_breaks)


def allocate_text_segment_times(
    *,
    start_sec: float,
    end_sec: float,
    segments: List[str],
    cjk_mode: bool,
) -> List[Tuple[float, float]]:
    """兼容旧入口：按文本负载把原 cue 时长分配到切开的多个片段。"""
    return allocate_text_segment_times_impl(
        start_sec=start_sec,
        end_sec=end_sec,
        segments=segments,
        cjk_mode=cjk_mode,
    )


def split_subtitle_item_by_punctuation(
    item: Dict[str, Any],
    *,
    include_soft_breaks: bool,
) -> List[Dict[str, Any]]:
    """兼容旧入口：当单个 cue 内部包含可用标点切点时，拆成更细的字幕片段。"""
    return split_subtitle_item_by_punctuation_impl(item, include_soft_breaks=include_soft_breaks)


def expand_block_with_punctuation_splits(
    block: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> List[Dict[str, Any]]:
    """兼容旧入口：为句块补充标点级切点。"""
    return expand_block_with_punctuation_splits_impl(block, include_soft_breaks=include_soft_breaks)


def split_cluster_into_punctuation_blocks(
    cluster: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> List[List[Dict[str, Any]]]:
    """兼容旧入口：按显式标点边界切成多个句块。"""
    return split_cluster_into_punctuation_blocks_impl(cluster, include_soft_breaks=include_soft_breaks)


def build_asr_gap_clusters(
    subtitles: List[Dict[str, Any]],
    *,
    max_gap_sec: float,
) -> List[List[Dict[str, Any]]]:
    """兼容旧入口：先按短停顿聚类，避免跨明显停顿误合并。"""
    return build_asr_gap_clusters_impl(subtitles, max_gap_sec=max_gap_sec)


def split_cluster_into_sentence_blocks(cluster: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """兼容旧入口：在短停顿簇内部优先按句末标点收敛为句级块。"""
    return split_cluster_into_sentence_blocks_impl(cluster)


def has_internal_explicit_break_boundary(
    block: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> bool:
    """兼容旧入口：判断句块内部是否存在可用于切分的显式标点边界。"""
    return has_internal_explicit_break_boundary_impl(block, include_soft_breaks=include_soft_breaks)


def choose_asr_sentence_split_index(
    block: List[Dict[str, Any]],
    *,
    cjk_mode: bool,
    max_gap_sec: float,
    target_duration_sec: float,
    target_text_units: float,
    require_explicit_break: bool = False,
) -> Optional[int]:
    """兼容旧入口：为超长句挑一个尽量自然的切点。"""
    return choose_asr_sentence_split_index_impl(
        block,
        cjk_mode=cjk_mode,
        max_gap_sec=max_gap_sec,
        target_duration_sec=target_duration_sec,
        target_text_units=target_text_units,
        require_explicit_break=require_explicit_break,
    )


def split_oversized_asr_sentence_block(
    block: List[Dict[str, Any]],
    *,
    max_gap_sec: float,
    max_line_width: int,
) -> List[List[Dict[str, Any]]]:
    """兼容旧入口：把超长句拆成更稳妥的子句块。"""
    return split_oversized_asr_sentence_block_impl(
        block,
        max_gap_sec=max_gap_sec,
        max_line_width=max_line_width,
    )


def build_rebalanced_subtitle(block: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把连续 cue 块重建成新的字幕项，时间仍沿用原始边界。"""
    if len(block) == 1:
        return dict(block[0])
    cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in block])
    merged = dict(block[0])
    merged["start"] = float(block[0]["start"])
    merged["end"] = float(block[-1]["end"])
    merged["text"] = subtitle_group_text(block, cjk_mode=cjk_mode)
    return merged


def source_short_merge_tolerance_seconds(target_seconds: int) -> int:
    """兼容旧入口：按文档公式计算短句合并容差。"""
    return source_short_merge_tolerance_seconds_impl(target_seconds)


def subtitle_item_duration_ms(item: Dict[str, Any]) -> int:
    """把单条字幕时长统一转成毫秒整数，避免在比较窗口时混用浮点秒。"""
    start_sec = float(item.get("start", 0.0) or 0.0)
    end_sec = float(item.get("end", 0.0) or 0.0)
    return max(0, int(round((end_sec - start_sec) * 1000.0)))


def subtitle_items_gap_ms(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    """返回两条相邻字幕之间的静默间隔（毫秒）。"""
    left_end_sec = float(left.get("end", 0.0) or 0.0)
    right_start_sec = float(right.get("start", 0.0) or 0.0)
    return int(round((right_start_sec - left_end_sec) * 1000.0))


def short_merge_ending_score(text: str) -> int:
    """给候选断点做浅层句尾打分，优先完整句末，回避明显残句。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return -4

    score = 0
    if is_sentence_end(cleaned):
        score += 3
    elif ends_with_connector(cleaned):
        score -= 3
    elif re.search(r"[,，、]\s*$", cleaned):
        score -= 2
    elif re.search(r"[:;：；]\s*$", cleaned):
        score -= 1

    # 极短残句即使带句号也要适度降权，避免把 “And then.” 这类碎片优先选出来。
    if 0 < len(extract_edge_tokens(cleaned)) <= 2:
        score -= 1
    return score


def choose_best_short_merge_candidate(
    *,
    candidates: List[Dict[str, Any]],
    target_ms: int,
    min_ms: int,
    max_ms: int,
) -> Dict[str, Any]:
    """按“合法区间 > 自然句尾 > 接近目标 > 略偏短”挑选最佳断点。"""
    valid_candidates = [
        candidate
        for candidate in candidates
        if min_ms <= int(candidate["duration_ms"]) <= max_ms
    ]
    pool = valid_candidates or candidates
    return max(
        pool,
        key=lambda candidate: (
            short_merge_ending_score(str(candidate["item"].get("text") or "")),
            -abs(int(candidate["duration_ms"]) - target_ms),
            -int(candidate["duration_ms"]),
            -int(candidate["end_idx"]),
        ),
    )


def merge_short_source_subtitles(
    *,
    subtitles: List[Dict[str, Any]],
    short_merge_target_seconds: int,
    gap_threshold_sec: float = DEFAULT_SOURCE_SHORT_MERGE_GAP_SEC,
) -> Tuple[List[Dict[str, Any]], int]:
    """兼容旧入口：第二阶段仅做相邻短句时间窗合并。"""
    return merge_short_source_subtitles_impl(
        subtitles=subtitles,
        short_merge_target_seconds=short_merge_target_seconds,
        gap_threshold_sec=gap_threshold_sec,
    )


def soft_source_layout_text_limit(*, max_line_width: int, cjk_mode: bool) -> int:
    """给句级分句评分使用更严格的软上限，避免行长失控。"""
    width = max(8, int(max_line_width or 0))
    if cjk_mode:
        return max(28, width + 6)
    return max(70, int(round(width * 2.25)))


def describe_source_layout_groups(groups: List[List[Dict[str, Any]]]) -> str:
    """把分组结果编码成便于日志与 prompt 复用的区间串。"""
    parts: List[str] = []
    cursor = 1
    for group in groups:
        end = cursor + len(group) - 1
        if end <= cursor:
            parts.append(str(cursor))
        else:
            parts.append(f"{cursor}-{end}")
        cursor = end + 1
    return ",".join(parts)


def score_source_layout_groups(
    *,
    groups: List[List[Dict[str, Any]]],
    max_line_width: int,
) -> float:
    """对候选分句打分，值越小表示越自然。"""
    if not groups:
        return 9999.0

    cjk_mode = infer_cjk_mode_from_lines(
        [(item.get("text") or "") for group in groups for item in group]
    )
    soft_text_limit = soft_source_layout_text_limit(max_line_width=max_line_width, cjk_mode=cjk_mode)
    score = max(0.0, float(len(groups) - 1) * 0.15)
    texts = [subtitle_group_text(group, cjk_mode=cjk_mode) for group in groups]

    for index, group in enumerate(groups):
        text = texts[index]
        prev_text = texts[index - 1] if index > 0 else ""
        duration = subtitle_group_duration(group)
        text_units = subtitle_text_units(text, cjk_mode=cjk_mode)
        score += max(0.0, duration - 7.2) * 1.35
        if len(groups) > 1:
            score += max(0.0, 1.0 - duration) * 0.8
        score += max(0.0, (text_units - soft_text_limit) / max(1.0, float(soft_text_limit))) * 2.2
        if ends_with_connector(text):
            score += 3.5
        if index > 0 and starts_with_connector(text) and not ends_with_explicit_break(prev_text):
            score += 1.5
        if is_orphan_like_line(text):
            score += 3.5
        if index < len(groups) - 1:
            if is_sentence_end(text):
                score -= 0.4
            elif ends_with_soft_sentence_break(text):
                score -= 0.2
            else:
                score += 0.8
        if index > 0 and text_units <= max(8, soft_text_limit // 6):
            score += 0.6

    return max(0.0, round(float(score), 4))


def count_source_layout_connector_issues(groups: List[List[Dict[str, Any]]]) -> int:
    """统计分句中的连接词坏切点，供 LLM 方案验收使用。"""
    if not groups:
        return 0
    cjk_mode = infer_cjk_mode_from_lines(
        [(item.get("text") or "") for group in groups for item in group]
    )
    texts = [subtitle_group_text(group, cjk_mode=cjk_mode) for group in groups]
    issue_count = 0
    for index, text in enumerate(texts):
        if index < len(texts) - 1 and ends_with_connector(text):
            issue_count += 1
        prev_text = texts[index - 1] if index > 0 else ""
        if index > 0 and starts_with_connector(text) and not ends_with_explicit_break(prev_text):
            issue_count += 1
    return issue_count


def should_try_llm_source_layout(
    *,
    block: List[Dict[str, Any]],
    rule_groups: List[List[Dict[str, Any]]],
    max_line_width: int,
    llm_min_duration_sec: float,
    llm_min_text_units: int,
    llm_max_cues: int,
) -> bool:
    """只在疑难句块上触发 LLM，控制成本与时延。"""
    if len(block) < 2 or len(block) > llm_max_cues:
        return False

    cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in block])
    block_text = subtitle_group_text(block, cjk_mode=cjk_mode)
    if subtitle_group_duration(block) >= float(llm_min_duration_sec):
        return True
    if subtitle_text_units(block_text, cjk_mode=cjk_mode) >= int(llm_min_text_units):
        return True

    rule_texts = [subtitle_group_text(group, cjk_mode=cjk_mode) for group in rule_groups]
    if any(ends_with_connector(text) for text in rule_texts[:-1]):
        return True
    for index, text in enumerate(rule_texts[1:], start=1):
        if starts_with_connector(text) and not ends_with_explicit_break(rule_texts[index - 1]):
            return True
    if any(is_orphan_like_line(text) for text in rule_texts):
        return True
    return score_source_layout_groups(groups=rule_groups, max_line_width=max_line_width) >= 2.0


def build_source_layout_plan_prompt(
    *,
    block: List[Dict[str, Any]],
    rule_groups: List[List[Dict[str, Any]]],
) -> str:
    """构造 source layout 的 LLM 提示词，只允许输出 cue 分组计划。"""
    rows: List[str] = []
    for row_no, item in enumerate(block, start=1):
        duration = float(item["end"]) - float(item["start"])
        rows.append(f"{row_no}. [{duration:.2f}s] {(item.get('text') or '').strip()}")

    return (
        "Plan subtitle line breaks for dubbing.\n"
        f"You MUST cover cue indices 1..{len(block)} exactly once, in order, using contiguous ranges.\n"
        "Return ONLY the ranges, one per line. Examples:\n"
        "1-4\n"
        "5-8\n"
        "9\n\n"
        "Rules:\n"
        "1) Do not rewrite, paraphrase, or quote the text.\n"
        "2) Cuts can only happen between existing cues.\n"
        "3) Prefer natural sentence or clause boundaries.\n"
        "4) Avoid ending a line with connectors like but/and/that/of/to.\n"
        "5) If splitting would sound unnatural, keep fewer groups.\n\n"
        f"Current heuristic plan: {describe_source_layout_groups(rule_groups) or '1'}\n\n"
        "Cues:\n"
        + "\n".join(rows)
    )


def parse_source_layout_plan(content: str) -> List[Tuple[int, int]]:
    """解析 LLM 返回的 cue 区间计划。"""
    ranges: List[Tuple[int, int]] = []
    text = (content or "").replace("```", "\n")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.search(r"(\d+)(?:\s*-\s*(\d+))?$", line)
        if match is None:
            continue
        start_index = int(match.group(1))
        end_index = int(match.group(2) or match.group(1))
        ranges.append((start_index, end_index))
    return ranges


def validate_source_layout_plan(
    *,
    plan: List[Tuple[int, int]],
    cue_count: int,
) -> bool:
    """校验 LLM 分组计划必须连续、完整且无重叠。"""
    if not plan:
        return False
    cursor = 1
    for start_index, end_index in plan:
        if start_index != cursor:
            return False
        if end_index < start_index or end_index > cue_count:
            return False
        cursor = end_index + 1
    return cursor == cue_count + 1


def apply_source_layout_plan(
    *,
    block: List[Dict[str, Any]],
    plan: List[Tuple[int, int]],
) -> List[List[Dict[str, Any]]]:
    """把合法的 cue 区间计划转成实际分组。"""
    groups: List[List[Dict[str, Any]]] = []
    for start_index, end_index in plan:
        groups.append(block[start_index - 1 : end_index])
    return [group for group in groups if group]


def plan_source_layout_with_llm(
    *,
    translator: Translator,
    block: List[Dict[str, Any]],
    rule_groups: List[List[Dict[str, Any]]],
) -> List[Tuple[int, int]]:
    """调用 LLM 生成 source layout 分组计划。"""
    prompt = build_source_layout_plan_prompt(block=block, rule_groups=rule_groups)
    response = translator.client.chat.completions.create(
        model=translator.model,
        messages=[
            {
                "role": "system",
                "content": "You are a subtitle segmentation planner for dubbing. Output only contiguous cue ranges.",
            },
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    content = (response.choices[0].message.content or "").strip()
    return parse_source_layout_plan(content)


def refine_source_layout_with_llm(
    *,
    block: List[Dict[str, Any]],
    rule_groups: List[List[Dict[str, Any]]],
    max_line_width: int,
    llm_min_duration_sec: float,
    llm_min_text_units: int,
    llm_max_cues: int,
    translator_factory: Optional[Callable[[], Translator]],
    logger: JsonlLogger,
) -> List[List[Dict[str, Any]]]:
    """在疑难句块上用 LLM 规划切点，不合法或无收益时回退规则版。"""
    if not should_try_llm_source_layout(
        block=block,
        rule_groups=rule_groups,
        max_line_width=max_line_width,
        llm_min_duration_sec=llm_min_duration_sec,
        llm_min_text_units=llm_min_text_units,
        llm_max_cues=llm_max_cues,
    ):
        return rule_groups
    if translator_factory is None:
        return rule_groups

    try:
        translator = translator_factory()
    except Exception as exc:
        logger.log(
            "WARN",
            "asr_align",
            "source_layout_llm_unavailable",
            "source layout llm unavailable, fallback to rule layout",
            data={"error": str(exc), "cue_count": len(block)},
        )
        return rule_groups

    try:
        plan = plan_source_layout_with_llm(
            translator=translator,
            block=block,
            rule_groups=rule_groups,
        )
    except Exception as exc:
        logger.log(
            "WARN",
            "asr_align",
            "source_layout_llm_failed",
            "source layout llm failed, fallback to rule layout",
            data={"error": str(exc), "cue_count": len(block)},
        )
        return rule_groups

    if not validate_source_layout_plan(plan=plan, cue_count=len(block)):
        logger.log(
            "WARN",
            "asr_align",
            "source_layout_llm_invalid_plan",
            "source layout llm returned invalid plan, fallback to rule layout",
            data={"plan": plan, "cue_count": len(block)},
        )
        return rule_groups

    candidate_groups = apply_source_layout_plan(block=block, plan=plan)
    if not candidate_groups:
        return rule_groups

    rule_score = score_source_layout_groups(groups=rule_groups, max_line_width=max_line_width)
    candidate_score = score_source_layout_groups(groups=candidate_groups, max_line_width=max_line_width)
    rule_connector_issues = count_source_layout_connector_issues(rule_groups)
    candidate_connector_issues = count_source_layout_connector_issues(candidate_groups)
    if rule_connector_issues > 0 and candidate_connector_issues >= rule_connector_issues:
        logger.log(
            "INFO",
            "asr_align",
            "source_layout_llm_rejected",
            "source layout llm plan rejected because connector-ending issues were not reduced",
            data={
                "cue_count": len(block),
                "rule_plan": describe_source_layout_groups(rule_groups),
                "llm_plan": describe_source_layout_groups(candidate_groups),
                "rule_score": rule_score,
                "llm_score": candidate_score,
                "rule_connector_issues": rule_connector_issues,
                "llm_connector_issues": candidate_connector_issues,
            },
        )
        return rule_groups

    if candidate_score <= rule_score - 0.01:
        logger.log(
            "INFO",
            "asr_align",
            "source_layout_llm_applied",
            "source layout llm improved rule-based sentence grouping",
            data={
                "cue_count": len(block),
                "rule_plan": describe_source_layout_groups(rule_groups),
                "llm_plan": describe_source_layout_groups(candidate_groups),
                "rule_score": rule_score,
                "llm_score": candidate_score,
                "rule_connector_issues": rule_connector_issues,
                "llm_connector_issues": candidate_connector_issues,
            },
        )
        return candidate_groups

    logger.log(
        "INFO",
        "asr_align",
        "source_layout_llm_rejected",
        "source layout llm plan rejected because it was not better than the rule layout",
        data={
            "cue_count": len(block),
            "rule_plan": describe_source_layout_groups(rule_groups),
            "llm_plan": describe_source_layout_groups(candidate_groups),
            "rule_score": rule_score,
            "llm_score": candidate_score,
            "rule_connector_issues": rule_connector_issues,
            "llm_connector_issues": candidate_connector_issues,
        },
    )
    return rule_groups


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


def extract_prosody_fingerprint(path: Path) -> Optional[Dict[str, float]]:
    # 提取语音韵律指纹：用于“情绪一致性”近似比较（能量/停顿/起伏），不依赖重模型。
    if not path.exists():
        return None
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size < 32 or sample_rate <= 0:
        return None

    target_sr = 22050
    if sample_rate != target_sr:
        mono = librosa.resample(mono, orig_sr=sample_rate, target_sr=target_sr)
        sample_rate = target_sr
    if mono.size < 32:
        return None

    rms = librosa.feature.rms(y=mono, frame_length=1024, hop_length=256)[0]
    zcr = librosa.feature.zero_crossing_rate(y=mono, frame_length=1024, hop_length=256)[0]
    onset_env = librosa.onset.onset_strength(y=mono, sr=sample_rate, hop_length=256)
    if rms.size == 0 or zcr.size == 0 or onset_env.size == 0:
        return None

    # 以低能量帧比例近似停顿占比，反映语气“碎/稳”。
    silence_threshold = max(1e-6, float(np.percentile(rms, 35)))
    pause_ratio = float(np.mean(rms <= silence_threshold))
    return {
        "rms_mean": float(np.mean(rms)),
        "rms_std": float(np.std(rms)),
        "zcr_mean": float(np.mean(zcr)),
        "zcr_std": float(np.std(zcr)),
        "onset_mean": float(np.mean(onset_env)),
        "onset_std": float(np.std(onset_env)),
        "pause_ratio": float(np.clip(pause_ratio, 0.0, 1.0)),
    }


def compute_prosody_distance(
    *,
    candidate_fp: Optional[Dict[str, float]],
    reference_fp: Optional[Dict[str, float]],
) -> float:
    # 计算候选与参考韵律距离：值越小越接近（0 最佳）。
    if candidate_fp is None or reference_fp is None:
        return 1.0

    def rel_diff(a: float, b: float, eps: float = 1e-6) -> float:
        return min(3.0, abs(float(a) - float(b)) / (abs(float(b)) + eps))

    weighted_features = [
        ("rms_mean", 0.18),
        ("rms_std", 0.14),
        ("zcr_mean", 0.14),
        ("zcr_std", 0.10),
        ("onset_mean", 0.18),
        ("onset_std", 0.14),
        ("pause_ratio", 0.12),
    ]
    total_weight = sum(weight for _, weight in weighted_features)
    if total_weight <= 0:
        return 1.0
    score = 0.0
    for key, weight in weighted_features:
        score += weight * rel_diff(candidate_fp.get(key, 0.0), reference_fp.get(key, 0.0))
    return float(max(0.0, score / total_weight))


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
    # 音乐符号字幕（如 ♪...♪）直接跳过，避免把背景音乐说明送入 TTS。
    if re.search(r"[♪♫♬♩♭♯]", text or ""):
        return ""

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
    max_line_width: int,
    source_layout_mode: str = "rule",
    source_layout_llm_min_duration_sec: float = 6.5,
    source_layout_llm_min_text_units: int = 90,
    source_layout_llm_max_cues: int = 12,
    source_short_merge_enabled: bool = False,
    source_short_merge_threshold: int = DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
    translator_factory: Optional[Callable[[], Translator]] = None,
    logger: JsonlLogger,
) -> List[Dict[str, Any]]:
    if len(subtitles) <= 1:
        return [dict(item) for item in subtitles]

    clusters = build_asr_gap_clusters(subtitles, max_gap_sec=max_gap_sec)
    output: List[Dict[str, Any]] = []
    sentence_blocks = 0
    oversized_splits = 0

    for cluster in clusters:
        blocks = split_cluster_into_sentence_blocks(cluster)
        sentence_blocks += len(blocks)
        for block in blocks:
            rule_pieces = split_oversized_asr_sentence_block(
                block,
                max_gap_sec=max_gap_sec,
                max_line_width=max_line_width,
            )
            pieces = rule_pieces
            if source_layout_mode == "hybrid":
                pieces = refine_source_layout_with_llm(
                    block=block,
                    rule_groups=rule_pieces,
                    max_line_width=max_line_width,
                    llm_min_duration_sec=source_layout_llm_min_duration_sec,
                    llm_min_text_units=source_layout_llm_min_text_units,
                    llm_max_cues=source_layout_llm_max_cues,
                    translator_factory=translator_factory,
                    logger=logger,
                )
            oversized_splits += max(0, len(pieces) - 1)
            for piece in pieces:
                output.append(build_rebalanced_subtitle(piece))

    # 第二阶段短句合并改为显式开关控制，默认关闭，避免误把对话中的短句并在一起。
    short_sentence_merges = 0
    if source_short_merge_enabled:
        output, short_sentence_merges = merge_short_source_subtitles(
            subtitles=output,
            short_merge_target_seconds=source_short_merge_threshold,
            gap_threshold_sec=DEFAULT_SOURCE_SHORT_MERGE_GAP_SEC,
        )

    before_signature = [
        (round(float(item["start"]), 3), round(float(item["end"]), 3), (item.get("text") or "").strip())
        for item in subtitles
    ]
    after_signature = [
        (round(float(item["start"]), 3), round(float(item["end"]), 3), (item.get("text") or "").strip())
        for item in output
    ]
    if after_signature != before_signature:
        logger.log(
            "INFO",
            "asr_align",
            "source_layout_rebalanced",
            "source subtitles regrouped toward sentence-level layout",
            data={
                "before_count": len(subtitles),
                "after_count": len(output),
                "gap_clusters": len(clusters),
                "sentence_blocks": sentence_blocks,
                "oversized_splits": oversized_splits,
                "short_merge_enabled": bool(source_short_merge_enabled),
                "short_sentence_merges": short_sentence_merges,
                "short_merge_target_seconds": int(source_short_merge_threshold),
                "short_merge_tolerance_seconds": source_short_merge_tolerance_seconds(
                    int(source_short_merge_threshold)
                ),
                "short_merge_gap_seconds": DEFAULT_SOURCE_SHORT_MERGE_GAP_SEC,
            },
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
    """兼容旧入口：从整段人声中抽取默认参考音。"""
    return extract_reference_audio_impl(
        vocals_audio=vocals_audio,
        out_ref=out_ref,
        seconds=seconds,
    )


def extract_reference_audio_from_offset(
    *,
    vocals_audio: Path,
    out_ref: Path,
    seconds: float,
    start_sec: float,
) -> Path:
    """兼容旧入口：按时间偏移抽取参考音。"""
    return extract_reference_audio_from_offset_impl(
        vocals_audio=vocals_audio,
        out_ref=out_ref,
        seconds=seconds,
        start_sec=start_sec,
    )


def extract_reference_audio_from_window(
    *,
    vocals_audio: Path,
    out_ref: Path,
    start_sec: float,
    end_sec: float,
    min_seconds: float = 0.8,
    pad_seconds: float = 0.15,
) -> Path:
    """兼容旧入口：按字幕时间窗抽取参考音。"""
    return extract_reference_audio_from_window_impl(
        vocals_audio=vocals_audio,
        out_ref=out_ref,
        start_sec=start_sec,
        end_sec=end_sec,
        min_seconds=min_seconds,
        pad_seconds=pad_seconds,
    )


def build_subtitle_reference_map(
    *,
    subtitles: List[Dict[str, Any]],
    source_audio: Path,
    out_dir: Path,
    default_ref: Path,
) -> Dict[int, Path]:
    """兼容旧入口：构造逐句参考音映射。"""
    return build_subtitle_reference_map_impl(
        subtitles=subtitles,
        source_audio=source_audio,
        out_dir=out_dir,
        default_ref=default_ref,
    )


def apply_atempo(
    *,
    input_path: Path,
    output_path: Path,
    tempo: float,
) -> None:
    """兼容旧入口：对音频执行轻量变速。"""
    return apply_atempo_impl(
        input_path=input_path,
        output_path=output_path,
        tempo=tempo,
    )


def build_atempo_filter_chain(tempo: float) -> str:
    """兼容旧入口：构造 ffmpeg atempo 过滤链。"""
    return build_atempo_filter_chain_impl(tempo)


def trim_silence_edges(
    *,
    input_path: Path,
    output_path: Path,
    threshold_db: float = -35.0,
    pad_sec: float = 0.03,
    min_keep_sec: float = 0.10,
) -> Tuple[float, float]:
    """兼容旧入口：裁掉音频首尾静音。"""
    return trim_silence_edges_impl(
        input_path=input_path,
        output_path=output_path,
        threshold_db=threshold_db,
        pad_sec=pad_sec,
        min_keep_sec=min_keep_sec,
    )


def fit_audio_to_duration(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> None:
    """兼容旧入口：把音频拟合到目标时长。"""
    return fit_audio_to_duration_impl(
        input_path=input_path,
        output_path=output_path,
        target_duration_sec=target_duration_sec,
    )


def trim_audio_to_max_duration(
    *,
    input_path: Path,
    output_path: Path,
    max_duration_sec: float,
) -> None:
    """兼容旧入口：只裁切到时长上限，不做变速。"""
    return trim_audio_to_max_duration_impl(
        input_path=input_path,
        output_path=output_path,
        max_duration_sec=max_duration_sec,
    )


def compose_vocals_master(
    *,
    segments: List[Dict[str, Any]],
    output_path: Path,
    source_audio_fallback: Optional[Path] = None,
) -> Tuple[Path, int]:
    """兼容旧入口：把逐句或逐段配音按时间轴回填为一条 master vocals。"""
    return compose_vocals_master_impl(
        segments=segments,
        output_path=output_path,
        source_audio_fallback=source_audio_fallback,
    )


def mix_with_bgm(
    *,
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    target_sr: int,
) -> None:
    """兼容旧入口：混合配音人声和背景音。"""
    return mix_with_bgm_impl(
        vocals_path=vocals_path,
        bgm_path=bgm_path,
        output_path=output_path,
        target_sr=target_sr,
        error_prefix="E-MIX-001 ffmpeg mix failed",
    )


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
    """兼容旧入口：检查 Index-TTS API 健康状态。"""
    return check_index_tts_service_impl(api_url=api_url, timeout_sec=timeout_sec)


def release_index_tts_api_model(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    """兼容旧入口：请求 Index-TTS 释放模型。"""
    return release_index_tts_api_model_impl(api_url=api_url, timeout_sec=timeout_sec)


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
    """兼容旧入口：通过 Index-TTS API 执行一次合成。"""
    return synthesize_via_index_tts_api_impl(
        api_url=api_url,
        timeout_sec=timeout_sec,
        text=text,
        ref_audio_path=ref_audio_path,
        output_path=output_path,
        emo_audio_prompt=index_emo_audio_prompt,
        emo_alpha=index_emo_alpha,
        use_emo_text=index_use_emo_text,
        emo_text=index_emo_text,
        top_p=index_top_p,
        top_k=index_top_k,
        temperature=index_temperature,
        max_text_tokens=index_max_text_tokens,
    )


def split_text_for_index_tts(text: str, *, max_text_tokens: int) -> List[str]:
    """兼容旧入口：按 Index-TTS 限制切分长文本。"""
    return split_text_for_index_tts_impl(text, max_text_tokens=max_text_tokens)


def concat_generated_wavs(inputs: List[Path], output_wav: Path) -> None:
    """兼容旧入口：拼接单句 TTS 分片。"""
    return concat_generated_wavs_impl(inputs, output_wav)


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
    """兼容旧入口：执行一次单句 TTS 合成。"""
    return synthesize_text_once_impl(
        tts_backend=tts_backend,
        index_tts_via_api=index_tts_via_api,
        index_tts_api_url=index_tts_api_url,
        index_tts_api_timeout_sec=index_tts_api_timeout_sec,
        tts_qwen=tts_qwen,
        qwen_prompt_items=qwen_prompt_items,
        tts_index=tts_index,
        ref_audio_path=ref_audio_path,
        index_emo_audio_prompt=index_emo_audio_prompt,
        index_emo_alpha=index_emo_alpha,
        index_use_emo_text=index_use_emo_text,
        index_emo_text=index_emo_text,
        index_top_p=index_top_p,
        index_top_k=index_top_k,
        index_temperature=index_temperature,
        index_max_text_tokens=index_max_text_tokens,
        text=text,
        output_path=output_path,
    )


def build_synthesis_groups(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    max_gap_sec: float,
    min_group_duration_sec: float,
    max_group_duration_sec: float,
    grouping_strategy: str = "legacy",
) -> List[List[int]]:
    """兼容旧入口：按历史规则或句末规则分组字幕。"""
    return build_synthesis_groups_impl(
        subtitles=subtitles,
        translated_lines=translated_lines,
        max_gap_sec=max_gap_sec,
        min_group_duration_sec=min_group_duration_sec,
        max_group_duration_sec=max_group_duration_sec,
        grouping_strategy=grouping_strategy,
    )


def split_waveform_by_durations(
    *,
    wav: np.ndarray,
    durations: List[float],
) -> List[np.ndarray]:
    """兼容旧入口：按目标时长比例切分整段波形。"""
    return split_waveform_by_durations_impl(wav=wav, durations=durations)


def estimate_line_speech_weight(*, text: str, target_duration_sec: float, cjk_mode: bool) -> float:
    """兼容旧入口：估计单句语音负载。"""
    return estimate_line_speech_weight_impl(
        text=text,
        target_duration_sec=target_duration_sec,
        cjk_mode=cjk_mode,
    )


def allocate_balanced_durations(
    *,
    texts: List[str],
    target_durations: List[float],
    min_line_sec: float,
    cjk_mode: bool,
) -> List[float]:
    """兼容旧入口：按文本负载重新分配每句时长。"""
    return allocate_balanced_durations_impl(
        texts=texts,
        target_durations=target_durations,
        min_line_sec=min_line_sec,
        cjk_mode=cjk_mode,
    )


def compute_effective_target_duration(
    *,
    start_sec: float,
    end_sec: float,
    next_start_sec: Optional[float],
    gap_guard_sec: float = 0.10,
) -> Tuple[float, float]:
    """兼容旧入口：计算可借静音后的有效目标时长。"""
    return compute_effective_target_duration_impl(
        start_sec=start_sec,
        end_sec=end_sec,
        next_start_sec=next_start_sec,
        gap_guard_sec=gap_guard_sec,
    )


def apply_short_fade_edges(*, wav: np.ndarray, sample_rate: int, fade_ms: float = 10.0) -> np.ndarray:
    """兼容旧入口：给分片加短淡入淡出。"""
    return apply_short_fade_edges_impl(
        wav=wav,
        sample_rate=sample_rate,
        fade_ms=fade_ms,
    )


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
    """兼容旧入口：grouped / legacy 主循环转调到新的 dubbing pipeline。"""
    return synthesize_segments_grouped_impl(
        tts_backend=tts_backend,
        index_tts_via_api=index_tts_via_api,
        index_tts_api_url=index_tts_api_url,
        index_tts_api_timeout_sec=index_tts_api_timeout_sec,
        tts_qwen=tts_qwen,
        qwen_prompt_items=qwen_prompt_items,
        tts_index=tts_index,
        ref_audio_path=ref_audio_path,
        ref_audio_selector=ref_audio_selector,
        source_media_duration_sec=source_media_duration_sec,
        index_emo_audio_prompt=index_emo_audio_prompt,
        index_emo_alpha=index_emo_alpha,
        index_use_emo_text=index_use_emo_text,
        index_emo_text=index_emo_text,
        index_top_p=index_top_p,
        index_top_k=index_top_k,
        index_temperature=index_temperature,
        index_max_text_tokens=index_max_text_tokens,
        force_fit_timing=force_fit_timing,
        group_gap_sec=group_gap_sec,
        group_min_duration_sec=group_min_duration_sec,
        group_max_duration_sec=group_max_duration_sec,
        subtitles=subtitles,
        translated_lines=translated_lines,
        segment_dir=segment_dir,
        delta_pass_ms=delta_pass_ms,
        timing_mode=timing_mode,
        balanced_max_tempo_shift=balanced_max_tempo_shift,
        balanced_min_line_sec=balanced_min_line_sec,
        grouping_strategy=grouping_strategy,
        logger=logger,
        target_lang=target_lang,
    )


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
    translator: Optional[Translator],
    target_lang: str,
    allow_rewrite_translation: bool,
    prefer_translated_text: bool,
    existing_records_by_id: Optional[Dict[str, Dict[str, Any]]],
    redub_line_indices: Optional[set[int]],
    v2_mode: bool,
    logger: JsonlLogger,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """兼容旧入口：逐句主循环转调到新的 dubbing pipeline。"""
    return synthesize_segments_impl(
        tts_backend=tts_backend,
        index_tts_via_api=index_tts_via_api,
        index_tts_api_url=index_tts_api_url,
        index_tts_api_timeout_sec=index_tts_api_timeout_sec,
        tts_qwen=tts_qwen,
        qwen_prompt_items=qwen_prompt_items,
        tts_index=tts_index,
        ref_audio_path=ref_audio_path,
        ref_audio_selector=ref_audio_selector,
        source_vocals_audio=source_vocals_audio,
        source_media_duration_sec=source_media_duration_sec,
        index_emo_audio_prompt=index_emo_audio_prompt,
        index_emo_alpha=index_emo_alpha,
        index_use_emo_text=index_use_emo_text,
        index_emo_text=index_emo_text,
        index_top_p=index_top_p,
        index_top_k=index_top_k,
        index_temperature=index_temperature,
        index_max_text_tokens=index_max_text_tokens,
        force_fit_timing=force_fit_timing,
        subtitles=subtitles,
        translated_lines=translated_lines,
        segment_dir=segment_dir,
        delta_pass_ms=delta_pass_ms,
        delta_rewrite_ms=delta_rewrite_ms,
        atempo_min=atempo_min,
        atempo_max=atempo_max,
        max_retry=max_retry,
        translator=translator,
        target_lang=target_lang,
        allow_rewrite_translation=allow_rewrite_translation,
        prefer_translated_text=prefer_translated_text,
        existing_records_by_id=existing_records_by_id,
        redub_line_indices=redub_line_indices,
        v2_mode=v2_mode,
        logger=logger,
    )


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


def sync_translated_outputs_from_records(
    *,
    subtitles: List[Dict[str, Any]],
    segment_records: List[Dict[str, Any]],
    translated_srt_path: Path,
    bilingual_srt_path: Optional[Path],
    bilingual_enabled: bool,
) -> None:
    # 将“最终实际配音文本”同步回 translated/bilingual 字幕。
    # 目的：当 TTS 阶段发生改写时，避免字幕仍停留在改写前文本，导致“听到的内容”和“看到的字幕”不一致。
    translated_subs: List[Dict[str, Any]] = []
    bilingual_subs: List[Dict[str, Any]] = []
    for item, record in zip(subtitles, segment_records):
        source_text = (item.get("text") or "").strip()
        translated_text = (record.get("translated_text") or source_text).strip()
        start_sec = float(item["start"])
        end_sec = float(item["end"])
        translated_subs.append(
            {
                "start": start_sec,
                "end": end_sec,
                "text": translated_text,
            }
        )
        if bilingual_enabled:
            bilingual_text = translated_text if not source_text else f"{translated_text}\n{source_text}"
            bilingual_subs.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": bilingual_text,
                }
            )
    save_srt(translated_subs, translated_srt_path)
    if bilingual_enabled and bilingual_srt_path is not None:
        save_srt(bilingual_subs, bilingual_srt_path)


def _build_manifest_replay_options(args: argparse.Namespace) -> BatchReplayOptions:
    """把当前运行参数收口成可重放的 manifest 配置。"""

    return BatchReplayOptions(
        target_lang=args.target_lang,
        pipeline_version="v2" if read_bool(str(getattr(args, "v2_mode", "false"))) else "v1",
        rewrite_translation=read_bool(str(getattr(args, "v2_rewrite_translation", "true"))),
        timing_mode=getattr(args, "timing_mode", "strict"),
        grouping_strategy=getattr(args, "grouping_strategy", "sentence"),
        input_srt_kind=getattr(args, "input_srt_kind", "source"),
        index_tts_api_url=getattr(args, "index_tts_api_url", None),
        auto_pick_ranges=read_bool(str(getattr(args, "auto_pick_ranges", "false"))),
        time_ranges=list(getattr(args, "requested_time_ranges", [])),
        source_short_merge_enabled=read_bool(str(getattr(args, "source_short_merge_enabled", "false"))),
        source_short_merge_threshold=int(
            getattr(args, "source_short_merge_threshold", DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC)
            or DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC
        ),
        source_short_merge_threshold_mode="seconds",
        grouped_synthesis=bool(
            getattr(args, "grouped_synthesis_effective", read_bool(str(getattr(args, "grouped_synthesis", "true"))))
        ),
        force_fit_timing=bool(
            getattr(args, "force_fit_timing_effective", read_bool(str(getattr(args, "force_fit_timing", "true"))))
        ),
        tts_backend=args.tts_backend,
    )


def build_manifest(
    *,
    job_id: str,
    args: argparse.Namespace,
    separation: SeparationResult,
    paths: Dict[str, Optional[Path]],
    segment_records: List[Dict[str, Any]],
    manual_review: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return build_segment_manifest(
        job_id=job_id,
        created_at=iso_now(),
        updated_at=iso_now(),
        input_media_path=Path(args.input_media).expanduser(),
        target_lang=args.target_lang,
        options=_build_manifest_replay_options(args),
        separation_status=separation.separation_status,
        paths=paths,
        segment_records=segment_records,
        manual_review=manual_review,
        requested_time_ranges=list(getattr(args, "requested_time_ranges", [])),
        effective_time_ranges=list(getattr(args, "effective_time_ranges", [])),
        range_strategy=getattr(args, "range_strategy", "all"),
    )


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
    return build_failed_segment_manifest(
        job_id=job_id,
        created_at=iso_now(),
        updated_at=iso_now(),
        input_media_path=Path(args.input_media).expanduser(),
        target_lang=args.target_lang,
        options=_build_manifest_replay_options(args),
        separation_status=separation_status,
        paths=paths,
        segment_records=segment_records,
        manual_review=manual_review,
        error_text=error_text,
        requested_time_ranges=list(getattr(args, "requested_time_ranges", [])),
        effective_time_ranges=list(getattr(args, "effective_time_ranges", [])),
        range_strategy=getattr(args, "range_strategy", "all"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dubbing pipeline (media -> subtitles -> translation -> cloning)")
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
    parser.add_argument("--translated-input-preserve-synthesis-mode", default="false")
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
    parser.add_argument("--source-layout-mode", default="hybrid")
    parser.add_argument("--source-layout-llm-min-duration-sec", type=float, default=6.5)
    parser.add_argument("--source-layout-llm-min-text-units", type=int, default=90)
    parser.add_argument("--source-layout-llm-max-cues", type=int, default=12)
    parser.add_argument("--source-short-merge-enabled", default="false")
    parser.add_argument("--source-short-merge-threshold", type=int, default=DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC)
    parser.add_argument("--time-ranges-json", default=None, help="Optional JSON list of {start_sec,end_sec} for dubbing")
    parser.add_argument(
        "--redub-line-indices-json",
        default=None,
        help="Optional JSON list of 1-based subtitle line indices to re-dub; others reuse existing audio",
    )
    parser.add_argument("--auto-pick-ranges", default="false")
    parser.add_argument("--auto-pick-min-silence-sec", type=float, default=0.8)
    parser.add_argument("--auto-pick-min-speech-sec", type=float, default=1.0)
    parser.add_argument("--v2-mode", default="false")
    parser.add_argument("--v2-rewrite-translation", default="true")

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
    if args.source_layout_mode not in {"rule", "hybrid"}:
        raise ValueError("--source-layout-mode must be one of: rule, hybrid")
    if not (1.0 <= args.source_layout_llm_min_duration_sec <= 20.0):
        raise ValueError("--source-layout-llm-min-duration-sec must be in [1.0, 20.0]")
    if not (20 <= args.source_layout_llm_min_text_units <= 400):
        raise ValueError("--source-layout-llm-min-text-units must be in [20, 400]")
    if not (2 <= args.source_layout_llm_max_cues <= 40):
        raise ValueError("--source-layout-llm-max-cues must be in [2, 40]")
    if read_bool(str(args.source_short_merge_enabled)) and not (
        MIN_SOURCE_SHORT_MERGE_TARGET_SEC <= args.source_short_merge_threshold <= MAX_SOURCE_SHORT_MERGE_TARGET_SEC
    ):
        raise ValueError(
            f"--source-short-merge-threshold must be in "
            f"[{MIN_SOURCE_SHORT_MERGE_TARGET_SEC}, {MAX_SOURCE_SHORT_MERGE_TARGET_SEC}]"
        )
    if not (10 <= args.cjk_wrap_chars <= 40):
        raise ValueError("--cjk-wrap-chars must be in [10, 40]")
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
    # 局部重配白名单：仅重配给定行，其他行复用已有音频。
    redub_line_indices = parse_redub_line_indices_json(getattr(args, "redub_line_indices_json", None))
    existing_records_by_id: Dict[str, Dict[str, Any]] = {}
    if args.resume_job_dir and manifest_path.exists():
        try:
            existing_manifest = load_segment_manifest(manifest_path)
            for row in existing_manifest.segment_rows:
                seg_id = str(row.get("id") or "").strip()
                if seg_id:
                    existing_records_by_id[seg_id] = dict(row)
        except Exception:
            existing_records_by_id = {}

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
    v2_mode = read_bool(args.v2_mode)
    v2_rewrite_translation = read_bool(args.v2_rewrite_translation)
    source_layout_mode = (args.source_layout_mode or "hybrid").strip().lower() or "hybrid"
    force_fit_timing = read_bool(args.force_fit_timing)
    grouped_synthesis = read_bool(args.grouped_synthesis)
    translated_input_preserve_synthesis_mode = read_bool(args.translated_input_preserve_synthesis_mode)
    if v2_mode:
        # V2 主链路：默认逐句合成，避免分组合成导致的节奏撕裂。
        grouped_synthesis = False
        # V2 以“start 严格对齐 + 自然收尾”为主，不走硬性 end 拟合。
        force_fit_timing = False
    # 上传“已翻译字幕”时，优先遵循用户提供的句级时间轴：
    # 1) 关闭 grouped 合成，改为逐句合成与逐句贴轨（严格对齐）；
    # 2) 逐句流程仍保留“借后续静音”窗口，避免尾音被硬截断导致漏音。
    if input_srt_is_translated and (not translated_input_preserve_synthesis_mode):
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
    args.grouped_synthesis_effective = grouped_synthesis
    args.force_fit_timing_effective = force_fit_timing
    # 保留 grouped 开关：用于对比 legacy/sentence 两种切分策略。
    index_use_fp16 = read_bool(args.index_use_fp16)
    index_use_accel = read_bool(args.index_use_accel)
    index_use_torch_compile = read_bool(args.index_use_torch_compile)
    index_use_emo_text = read_bool(args.index_use_emo_text)
    index_tts_via_api = read_bool(args.index_tts_via_api)
    # 只有“真实源字幕”链路才允许落盘到 source.srt；已翻译字幕仅借时间轴，不得污染源字幕文件。
    source_subtitles_writable = not input_srt_is_translated
    if input_srt_is_translated and (not source_srt.exists()) and bilingual_enabled:
        bilingual_enabled = False
        logger.log(
            "INFO",
            "translate",
            "bilingual_disabled_without_source_subtitles",
            "translated input without source subtitles disables bilingual subtitle outputs",
            data={"input_srt_kind": "translated"},
        )
    index_tts_api_release_after_job = read_bool(args.index_tts_api_release_after_job)
    dubbed_vocals_internal = dubbed_vocals if export_vocals else (job_dir / "_tmp_dubbed_vocals.wav")
    should_release_index_tts_api = (
        args.tts_backend == "index-tts" and index_tts_via_api and index_tts_api_release_after_job
    )
    tts_qwen: Optional[Qwen3TTSModel] = None
    qwen_prompt_items: Optional[List[Any]] = None
    tts_index: Optional[Any] = None
    translator_cache: Dict[str, Translator] = {}

    def get_or_create_translator() -> Translator:
        """按需懒加载 Translator，供 source layout 与翻译阶段共用。"""
        cached = translator_cache.get("main")
        if cached is not None:
            return cached
        api_key = args.api_key or os.environ.get(args.api_key_env)
        if not api_key:
            raise RuntimeError(f"E-TRN-001 missing api key (set --api-key or {args.api_key_env})")
        translator = Translator(
            api_key=api_key,
            base_url=args.translate_base_url,
            model=args.translate_model,
        )
        translator_cache["main"] = translator
        return translator

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
        # 根因修复：
        # 当明确声明 input_srt_kind=translated 时，必须以传入的翻译字幕为唯一文本源。
        # 不能复用 source_srt，否则会把“保存并重配”的译文覆盖回源文。
        if (not input_srt_is_translated) and source_srt.exists():
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
                    persist_input_srt_to_source=True,
                    asr_model_path=args.asr_model_path,
                    aligner_path=args.aligner_path,
                    device=args.asr_device,
                    language=args.asr_language,
                    max_width=args.max_width,
                    asr_balance_lines=asr_balance_lines,
                    asr_balance_gap_sec=args.asr_balance_gap_sec,
                    source_layout_mode=source_layout_mode,
                    source_layout_llm_min_duration_sec=args.source_layout_llm_min_duration_sec,
                    source_layout_llm_min_text_units=args.source_layout_llm_min_text_units,
                    source_layout_llm_max_cues=args.source_layout_llm_max_cues,
                    source_short_merge_enabled=read_bool(str(args.source_short_merge_enabled)),
                    source_short_merge_threshold=args.source_short_merge_threshold,
                    translator_factory=get_or_create_translator,
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
            # 对于 translated 输入（尤其 save-and-redub 的 resume 场景），
            # 这里会直接读取 args.input_srt（即段内最新 translated.srt），
            # 从源头保证后续 TTS 输入就是用户编辑后的文本。
            subtitles = load_or_transcribe_subtitles(
                input_srt=Path(args.input_srt).expanduser() if args.input_srt else None,
                asr_audio=source_audio,
                source_srt_path=source_srt,
                persist_input_srt_to_source=False,
                asr_model_path=args.asr_model_path,
                aligner_path=args.aligner_path,
                device=args.asr_device,
                language=args.asr_language,
                max_width=args.max_width,
                asr_balance_lines=asr_balance_lines,
                asr_balance_gap_sec=args.asr_balance_gap_sec,
                source_layout_mode=source_layout_mode,
                source_layout_llm_min_duration_sec=args.source_layout_llm_min_duration_sec,
                source_layout_llm_min_text_units=args.source_layout_llm_min_text_units,
                source_layout_llm_max_cues=args.source_layout_llm_max_cues,
                source_short_merge_enabled=read_bool(str(args.source_short_merge_enabled)),
                source_short_merge_threshold=args.source_short_merge_threshold,
                translator_factory=get_or_create_translator,
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
            if source_subtitles_writable:
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

        if v2_mode and subtitles:
            # V2 在翻译/TTS 前统一标准化句单元时间轴，降低后续对齐抖动。
            before_count = len(subtitles)
            subtitles = normalize_subtitle_sentence_units(
                subtitles=subtitles,
                media_duration_sec=source_duration_sec,
            )
            subtitles = enforce_subtitle_timestamps(
                subtitles=subtitles,
                media_duration_sec=source_duration_sec,
            )
            if source_subtitles_writable:
                save_srt(subtitles, source_srt)
            logger.log(
                "INFO",
                "asr_align",
                "v2_sentence_units_normalized",
                "normalized sentence units for v2 pipeline",
                data={"before": before_count, "after": len(subtitles)},
            )

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
            translator = get_or_create_translator()

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

        # 当前固定策略：逐句使用“原音频窗口”做克隆+情绪参考。
        subtitle_ref_map = build_subtitle_reference_map(
            subtitles=subtitles,
            source_audio=source_audio,
            out_dir=job_dir / "refs" / "subtitles",
            default_ref=ref_audio_path,
        )

        def _selector(index: int) -> Path:
            return subtitle_ref_map.get(index, ref_audio_path)

        ref_audio_selector: Optional[Callable[[int], Path]] = _selector
        logger.log(
            "INFO",
            "ref_extract",
            "sentence_reference_mode_enabled",
            "using per-subtitle original-audio references",
            data={"reference_count": len(subtitle_ref_map)},
        )

        logger.log(
            "INFO",
            "ref_extract",
            "reference_ready",
            "reference audio ready",
            progress=63,
            data={
                "reference_strategy": "sentence_original_audio_per_subtitle",
                "reference_count": len(subtitle_ref_map),
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
            # 关键逻辑：翻译字幕直通链路（input_srt_kind=translated）默认禁用改写。
            # 此处按 allow_rewrite_translation 惰性初始化 Translator，避免无 Key 的误报失败。
            allow_rewrite_translation = (not input_srt_is_translated) and ((not v2_mode) or v2_rewrite_translation)
            rewrite_translator: Optional[Translator] = translator
            if allow_rewrite_translation and rewrite_translator is None:
                rewrite_translator = Translator(
                    api_key=args.api_key or os.environ.get(args.api_key_env) or "",
                    base_url=args.translate_base_url,
                    model=args.translate_model,
                )
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
                atempo_min=max(float(args.atempo_min), 0.92) if v2_mode else args.atempo_min,
                atempo_max=min(float(args.atempo_max), 1.08) if v2_mode else args.atempo_max,
                max_retry=max(int(args.max_retry), 2) if v2_mode else args.max_retry,
                translator=rewrite_translator,
                target_lang=args.target_lang,
                allow_rewrite_translation=allow_rewrite_translation,
                prefer_translated_text=input_srt_is_translated,
                existing_records_by_id=existing_records_by_id,
                redub_line_indices=redub_line_indices,
                v2_mode=v2_mode,
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

        # 关键同步：确保 translated/bilingual 使用“最终实际配音文本”（含必要改写）。
        sync_translated_outputs_from_records(
            subtitles=subtitles,
            segment_records=records,
            translated_srt_path=translated_srt,
            bilingual_srt_path=bilingual_srt,
            bilingual_enabled=bilingual_enabled,
        )

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
        write_manifest_json(manifest_path, manifest)

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
            write_manifest_json(manifest_path, failed_manifest)
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
