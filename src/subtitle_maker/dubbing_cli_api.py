"""FastAPI bridge for the CLI dubbing pipeline.

This module intentionally keeps dubbing task state separate from the existing
transcription task store in web.py so the new UI path cannot affect subtitle
generation, translation, or export flows.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from subtitle_maker.app import legacy_runtime
from subtitle_maker.domains.dubbing import resolve_segment_redub_runtime_options
from subtitle_maker.jobs import (
    AutoDubbingCommandConfig,
    SegmentRedubCommandConfig,
    TaskPayload,
    TaskStore,
    build_batch_artifacts,
    build_batch_task_updates,
    build_auto_dubbing_command,
    build_loaded_batch_task,
    build_segment_redub_command,
    find_batch_dir_by_name,
    find_batch_manifest_by_name,
    list_available_batches,
)
from subtitle_maker.manifests import load_batch_manifest, load_segment_manifest, write_manifest_json
from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.translator import (
    DEFAULT_TRANSLATE_BASE_URL,
    DEFAULT_TRANSLATE_MODEL,
    LEGACY_TRANSLATE_API_KEY_ENV,
    TRANSLATE_API_KEY_ENV,
    get_translate_provider_label,
    resolve_translation_api_key,
)
from subtitle_maker.domains.subtitles import (
    build_segment_speaker_metadata_from_subtitles,
    normalize_subtitles_with_speakers,
    optimize_srt_import_subtitles,
    parse_speaker_ref_map_json,
    parse_speaker_reference_specs_json,
)

router = APIRouter(prefix="/dubbing/auto", tags=["dubbing"])

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = REPO_ROOT / "uploads" / "dubbing"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "dub_jobs"
TOOL_PATH = REPO_ROOT / "tools" / "dub_long_video.py"
INDEX_TTS_START_SCRIPT = REPO_ROOT / "start_index_tts_api.sh"
INDEX_TTS_STOP_SCRIPT = REPO_ROOT / "stop_index_tts_api.sh"

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

_task_store = TaskStore()
# 保留旧全局名，兼容现有测试与少量尚未迁移的代码。
_tasks: Dict[str, TaskPayload] = _task_store.items
_lock = _task_store.lock
DEFAULT_INDEX_TTS_API_URL = "http://127.0.0.1:8010"
DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC = 15
MIN_SOURCE_SHORT_MERGE_TARGET_SEC = 6
MAX_SOURCE_SHORT_MERGE_TARGET_SEC = 20
DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS = 0.12
DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB = -35.0
DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB = 8.0
DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING = 0.95
DEFAULT_SEGMENT_MINUTES = 8.0
DEFAULT_MIN_SEGMENT_MINUTES = 4.0

logger = logging.getLogger(__name__)


def _index_tts_target_lang_supported(target_lang: str) -> bool:
    """判断当前 index-tts 服务是否支持目标语种（本地部署版本仅稳定支持中/英）。"""
    lowered = (target_lang or "").strip().lower()
    if not lowered:
        return False
    # 兼容中英文常见写法；其余语种（如 Japanese）直接拦截，避免生成无效音。
    supported_markers = [
        "chinese",
        "中文",
        "mandarin",
        "cantonese",
        "english",
        "英文",
        "en",
        "zh",
    ]
    return any(marker in lowered for marker in supported_markers)

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_short_merge_target_seconds_for_display(
    value: Any,
    *,
    mode: str = "",
) -> int:
    """把历史 batch 中的旧字数字段兼容回新的秒数语义。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC

    if MIN_SOURCE_SHORT_MERGE_TARGET_SEC <= parsed <= MAX_SOURCE_SHORT_MERGE_TARGET_SEC:
        return parsed
    if (mode or "").strip().lower() == "seconds":
        return max(
            MIN_SOURCE_SHORT_MERGE_TARGET_SEC,
            min(MAX_SOURCE_SHORT_MERGE_TARGET_SEC, parsed),
        )
    # 历史 manifest 的 30~80 表示“字数阈值”，这里统一回退到新默认 15 秒。
    return DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC


def _sanitize_filename(name: str) -> str:
    stem = Path(name or "media").stem
    suffix = Path(name or "").suffix
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-") or "media"
    safe_suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix or "") else ""
    return f"{safe_stem}{safe_suffix}"


def _store_uploaded_reference_file(*, upload_dir: Path, file: Optional[UploadFile], fallback_name: str) -> str:
    """把前端上传的参考音频落盘，并返回可供 CLI 使用的绝对路径。"""

    if file is None or not file.filename:
        return ""
    safe_name = _sanitize_filename(file.filename or fallback_name)
    if not Path(safe_name).suffix:
        safe_name = f"{Path(safe_name).stem or fallback_name}.wav"
    target_path = upload_dir / safe_name
    with target_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return str(target_path.resolve())


def _vtt_token_to_srt_time(token: str) -> str:
    # 将 VTT 时间戳（HH:MM:SS.mmm 或 MM:SS.mmm）转换为 SRT 时间戳格式。
    text = (token or "").strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0] or "0")
        seconds = float(parts[1] or "0")
    elif len(parts) == 3:
        hours = int(parts[0] or "0")
        minutes = int(parts[1] or "0")
        seconds = float(parts[2] or "0")
    else:
        raise ValueError(f"invalid VTT timestamp: {token}")
    sec_int = int(seconds)
    millis = int(round((seconds - sec_int) * 1000.0))
    # 处理四舍五入导致的 1000ms 进位。
    if millis >= 1000:
        sec_int += 1
        millis -= 1000
    if sec_int >= 60:
        minutes += sec_int // 60
        sec_int = sec_int % 60
    if minutes >= 60:
        hours += minutes // 60
        minutes = minutes % 60
    return f"{hours:02d}:{minutes:02d}:{sec_int:02d},{millis:03d}"


def _convert_vtt_to_srt_text(vtt_text: str) -> str:
    # 轻量 VTT 解析：提取时间轴与正文，忽略 NOTE/STYLE/REGION 块。
    lines = (vtt_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    entries: List[Dict[str, Any]] = []
    index = 0
    total = len(lines)

    while index < total:
        line = (lines[index] or "").strip()
        if not line:
            index += 1
            continue
        # 跳过 WEBVTT 头与元信息块。
        upper = line.upper()
        if upper == "WEBVTT" or upper.startswith("X-TIMESTAMP-MAP="):
            index += 1
            continue
        if upper.startswith("NOTE") or upper.startswith("STYLE") or upper.startswith("REGION"):
            index += 1
            while index < total and (lines[index] or "").strip():
                index += 1
            continue

        # 支持可选 cue id：下一行才是时间轴。
        timing_line = line
        if "-->" not in timing_line and (index + 1) < total and "-->" in (lines[index + 1] or ""):
            index += 1
            timing_line = (lines[index] or "").strip()

        if "-->" not in timing_line:
            index += 1
            continue

        left, right = timing_line.split("-->", 1)
        start_token = (left or "").strip().split()[0]
        end_token = (right or "").strip().split()[0]
        try:
            start_time = _vtt_token_to_srt_time(start_token)
            end_time = _vtt_token_to_srt_time(end_token)
        except Exception:
            index += 1
            continue

        index += 1
        text_lines: List[str] = []
        while index < total:
            text_line = lines[index]
            if not (text_line or "").strip():
                break
            text_lines.append(text_line.rstrip())
            index += 1

        entries.append(
            {
                "start": start_time,
                "end": end_time,
                "text": "\n".join(text_lines).strip(),
            }
        )

    if not entries:
        raise HTTPException(status_code=400, detail="Invalid subtitle_file: VTT contains no valid cues")

    # 按 SRT 结构重组。
    chunks: List[str] = []
    for idx, entry in enumerate(entries, start=1):
        chunks.append(
            "\n".join(
                [
                    str(idx),
                    f"{entry['start']} --> {entry['end']}",
                    entry["text"],
                    "",
                ]
            )
        )
    return "\n".join(chunks).rstrip() + "\n"


def _markdown_time_to_seconds(token: str) -> float:
    # 解析 Markdown 时间稿中的时间（支持 MM:SS / HH:MM:SS，允许秒带小数）。
    value = (token or "").strip()
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0] or "0")
        seconds = float(parts[1] or "0")
    elif len(parts) == 3:
        hours = int(parts[0] or "0")
        minutes = int(parts[1] or "0")
        seconds = float(parts[2] or "0")
    else:
        raise ValueError(f"invalid markdown timestamp: {token}")
    return float(hours * 3600 + minutes * 60 + seconds)


def _seconds_to_srt_time(seconds_value: float) -> str:
    # 将秒数转换为 SRT 时间戳格式。
    total_ms = max(0, int(round(float(seconds_value) * 1000.0)))
    hours = total_ms // 3_600_000
    total_ms = total_ms % 3_600_000
    minutes = total_ms // 60_000
    total_ms = total_ms % 60_000
    seconds = total_ms // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _convert_markdown_timeline_to_srt_text(markdown_text: str) -> str:
    # 支持形如：[0:04] hello / [02:17:39] hello 的时间稿转 SRT。
    # 规则：当前行 end 使用下一行 start；最后一行使用 +2 秒兜底。
    lines = (markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pattern = re.compile(r"^\s*\[(?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?)\]\s*(?P<text>.*)$")
    entries: List[Dict[str, Any]] = []

    for line in lines:
        raw = (line or "").strip()
        if not raw:
            continue
        match = pattern.match(raw)
        if match:
            try:
                start_sec = _markdown_time_to_seconds(match.group("ts"))
            except Exception:
                continue
            text = (match.group("text") or "").strip()
            entries.append({"start_sec": float(start_sec), "text": text})
            continue
        # 兼容文本换行：无时间戳时追加到上一条。
        if entries:
            previous_text = (entries[-1].get("text") or "").strip()
            appended = raw if not previous_text else f"{previous_text} {raw}"
            entries[-1]["text"] = appended.strip()

    if not entries:
        raise HTTPException(status_code=400, detail="Invalid subtitle_file: Markdown timeline contains no valid cues")

    chunks: List[str] = []
    for idx, entry in enumerate(entries, start=1):
        start_sec = float(entry["start_sec"])
        if idx < len(entries):
            end_sec = float(entries[idx]["start_sec"])
        else:
            end_sec = start_sec + 2.0
        if end_sec <= start_sec:
            end_sec = start_sec + 0.2
        chunks.append(
            "\n".join(
                [
                    str(idx),
                    f"{_seconds_to_srt_time(start_sec)} --> {_seconds_to_srt_time(end_sec)}",
                    (entry.get("text") or "").strip(),
                    "",
                ]
            )
        )
    return "\n".join(chunks).rstrip() + "\n"


def _read_bool_form(value: str, *, field_name: str) -> bool:
    # 解析表单布尔值，统一支持 true/false/1/0。
    lowered = (value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def _coerce_bool(value: Any, *, default: bool) -> bool:
    # 宽松解析 manifest/任务状态里的布尔值，缺失或异常时回退默认值。
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _parse_time_ranges_form(raw: str) -> List[Dict[str, float]]:
    # 解析 time_ranges，支持 JSON 与简写文本（如 00:10-00:45, 01:20-02:00）。
    if not raw or not raw.strip():
        return []
    text = raw.strip()

    def parse_time_token(token: str) -> float:
        value = (token or "").strip()
        if not value:
            raise ValueError("empty time token")
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return float(value)
        parts = value.split(":")
        if len(parts) == 2:
            minutes = int(parts[0] or "0")
            seconds = float(parts[1] or "0")
            return minutes * 60.0 + seconds
        if len(parts) == 3:
            hours = int(parts[0] or "0")
            minutes = int(parts[1] or "0")
            seconds = float(parts[2] or "0")
            return hours * 3600.0 + minutes * 60.0 + seconds
        raise ValueError(f"invalid time token: {token}")

    parsed: List[Dict[str, float]] = []
    if text.startswith("["):
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid time_ranges JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise HTTPException(status_code=400, detail="Invalid time_ranges JSON: must be a list")
        for item in payload:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Invalid time_ranges JSON item")
            start_sec = float(item.get("start_sec", item.get("start", 0.0)) or 0.0)
            end_sec = float(item.get("end_sec", item.get("end", start_sec)) or start_sec)
            if end_sec <= start_sec:
                continue
            parsed.append({"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)})
    else:
        entries = [part.strip() for part in re.split(r"[,\n;，；]+", text) if part.strip()]
        for entry in entries:
            if "-" not in entry:
                raise HTTPException(status_code=400, detail=f"Invalid time_ranges entry: {entry}")
            start_text, end_text = entry.split("-", 1)
            try:
                start_sec = parse_time_token(start_text)
                end_sec = parse_time_token(end_text)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid time_ranges entry: {entry} ({exc})") from exc
            if end_sec <= start_sec:
                continue
            parsed.append({"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)})

    parsed.sort(key=lambda item: item["start_sec"])
    return parsed


def _build_readable_task_id() -> str:
    # 生成可读任务 ID：UTC 时间戳 + 冲突递增序号，不使用随机串。
    base = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    existing_ids = set(_task_store.keys_snapshot())
    candidate = base
    index = 2
    while (
        candidate in existing_ids
        or (UPLOAD_ROOT / candidate).exists()
        or (OUTPUT_ROOT / f"web_{candidate}").exists()
    ):
        candidate = f"{base}_{index:02d}"
        index += 1
    return candidate


def _collapse_single_reference_payload(
    *,
    single_ref_audio: str,
    single_ref_text: str,
    speaker_ref_map_json: str,
) -> tuple[str, str, str]:
    """把“仅上传 1 份 speaker 参考音”的情况收敛成 single speaker 输入。

    这样后续的 CLI 校验、命令构建和字幕优化都可以走更简单的单 speaker 分支。
    """

    normalized_single_ref_audio = str(single_ref_audio or "").strip()
    normalized_single_ref_text = str(single_ref_text or "").strip()
    normalized_speaker_ref_map_json = str(speaker_ref_map_json or "").strip()
    if normalized_single_ref_audio:
        return normalized_single_ref_audio, normalized_single_ref_text, ""
    if not normalized_speaker_ref_map_json:
        return normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json
    try:
        speaker_ref_specs = parse_speaker_reference_specs_json(normalized_speaker_ref_map_json)
    except Exception:
        return normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json
    if len(speaker_ref_specs) != 1:
        return normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json

    speaker_spec = next(iter(speaker_ref_specs.values()))
    ref_audio_path = str(speaker_spec.get("ref_audio_path") or "").strip()
    if not ref_audio_path:
        return normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json
    ref_text = str(speaker_spec.get("ref_text") or "").strip()
    return ref_audio_path, normalized_single_ref_text or ref_text, ""


def _normalize_auto_dubbing_request(
    *,
    subtitle_mode: str,
    dubbing_mode: str,
    source_lang: str,
    target_lang: str,
    api_key: str,
    translate_base_url: str,
    translate_model: str,
    translate_system_prompt: str,
    tts_backend: str,
    tts_model_path: str,
    index_tts_api_url: str,
    single_ref_audio: str,
    single_ref_text: str,
    speaker_ref_map_json: str,
    detected_speaker_ids: Optional[List[str]],
    segment_minutes: float,
    min_segment_minutes: float,
    timing_mode: str,
    grouping_strategy: str,
    short_merge_enabled: str,
    short_merge_threshold: int,
    translated_short_merge_enabled: str,
    translated_short_merge_threshold: int,
    time_ranges: str,
    rewrite_translation: str,
    has_subtitle_input: bool,
    dub_audio_leveling_enabled: bool = True,
    dub_audio_leveling_target_rms: float = DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS,
    dub_audio_leveling_activity_threshold_db: float = DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB,
    dub_audio_leveling_max_gain_db: float = DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB,
    dub_audio_leveling_peak_ceiling: float = DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING,
) -> Dict[str, Any]:
    """统一解析两条启动入口的公共参数，避免 Current Project / Standalone 语义漂移。"""

    if not TOOL_PATH.exists():
        raise HTTPException(status_code=500, detail=f"CLI not found: {TOOL_PATH}")
    if segment_minutes <= 0 or min_segment_minutes <= 0 or min_segment_minutes > segment_minutes:
        raise HTTPException(status_code=400, detail="Invalid segment duration settings")
    if not target_lang.strip():
        raise HTTPException(status_code=400, detail="target_lang is required")
    if (tts_backend or "").strip().lower() in {"", "index-tts"} and not _index_tts_target_lang_supported(target_lang):
        raise HTTPException(
            status_code=400,
            detail=(
                "Current index-tts backend in this project only supports Chinese/English reliably. "
                f"Unsupported target_lang: {target_lang}"
            ),
        )

    normalized_timing_mode = (timing_mode or "").strip() or "strict"
    if normalized_timing_mode not in {"strict", "balanced"}:
        raise HTTPException(status_code=400, detail="Invalid timing_mode")
    normalized_grouping_strategy = (grouping_strategy or "").strip() or "sentence"
    if normalized_grouping_strategy not in {"legacy", "sentence"}:
        raise HTTPException(status_code=400, detail="Invalid grouping_strategy")
    short_merge_enabled_value = _read_bool_form(short_merge_enabled, field_name="short_merge_enabled")
    if short_merge_enabled_value and not (
        MIN_SOURCE_SHORT_MERGE_TARGET_SEC <= short_merge_threshold <= MAX_SOURCE_SHORT_MERGE_TARGET_SEC
    ):
        raise HTTPException(status_code=400, detail="Invalid short_merge_threshold")
    translated_short_merge_enabled_value = _read_bool_form(
        translated_short_merge_enabled,
        field_name="translated_short_merge_enabled",
    )
    if translated_short_merge_enabled_value and not (
        MIN_SOURCE_SHORT_MERGE_TARGET_SEC <= translated_short_merge_threshold <= MAX_SOURCE_SHORT_MERGE_TARGET_SEC
    ):
        raise HTTPException(status_code=400, detail="Invalid translated_short_merge_threshold")
    if dub_audio_leveling_target_rms <= 0.0 or dub_audio_leveling_target_rms > 0.5:
        raise HTTPException(status_code=400, detail="Invalid dub_audio_leveling_target_rms")
    if dub_audio_leveling_activity_threshold_db > -5.0 or dub_audio_leveling_activity_threshold_db < -80.0:
        raise HTTPException(status_code=400, detail="Invalid dub_audio_leveling_activity_threshold_db")
    if dub_audio_leveling_max_gain_db < 0.0 or dub_audio_leveling_max_gain_db > 24.0:
        raise HTTPException(status_code=400, detail="Invalid dub_audio_leveling_max_gain_db")
    if dub_audio_leveling_peak_ceiling <= 0.0 or dub_audio_leveling_peak_ceiling > 0.99:
        raise HTTPException(status_code=400, detail="Invalid dub_audio_leveling_peak_ceiling")

    normalized_subtitle_mode = (subtitle_mode or "").strip().lower() or "source"
    if normalized_subtitle_mode not in {"source", "translated"}:
        raise HTTPException(status_code=400, detail="Invalid subtitle_mode")
    requested_dubbing_mode = (dubbing_mode or "").strip().lower() or "single"
    if requested_dubbing_mode not in {"single", "multi"}:
        raise HTTPException(status_code=400, detail="Invalid dubbing_mode")
    # Auto Dubbing 现阶段固定只走 index-tts，兼容旧字段但不再接受切换。
    normalized_tts_backend = "index-tts"
    # `dubbing_mode` 不再以表单选择为真值，而是优先看 speaker 参考音是否已经收敛为单人，
    # 再回退到字幕里是否存在稳定 speaker 信息。
    normalized_detected_speaker_ids = [
        str(speaker_id or "").strip()
        for speaker_id in (detected_speaker_ids or [])
        if str(speaker_id or "").strip()
    ]
    rewrite_translation_enabled = _read_bool_form(rewrite_translation, field_name="rewrite_translation")
    parsed_time_ranges = _parse_time_ranges_form(time_ranges)
    normalized_translate_base_url = (translate_base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL
    normalized_translate_model = (translate_model or "").strip() or DEFAULT_TRANSLATE_MODEL
    normalized_translate_system_prompt = str(translate_system_prompt or "").strip()
    normalized_tts_model_path = (tts_model_path or "").strip()
    normalized_index_tts_api_url = (index_tts_api_url or "").strip() or DEFAULT_INDEX_TTS_API_URL
    effective_api_key = resolve_translation_api_key(api_key=api_key)
    skip_translation_by_subtitle = bool(has_subtitle_input and normalized_subtitle_mode == "translated")
    if (not skip_translation_by_subtitle) and (not effective_api_key):
        raise HTTPException(
            status_code=400,
            detail=(
                "Translation API key is required. Provide api_key or configure "
                f"{TRANSLATE_API_KEY_ENV} / {LEGACY_TRANSLATE_API_KEY_ENV}."
            ),
        )
    _switch_tts_runtime_on_demand(
        tts_backend=normalized_tts_backend,
        index_tts_api_url=normalized_index_tts_api_url,
    )
    normalized_single_ref_audio = str(single_ref_audio or "").strip()
    normalized_single_ref_text = str(single_ref_text or "").strip()
    normalized_speaker_ref_specs = (
        parse_speaker_reference_specs_json(speaker_ref_map_json or "")
        if str(speaker_ref_map_json or "").strip()
        else {}
    )
    normalized_speaker_ref_map = (
        parse_speaker_ref_map_json(speaker_ref_map_json or "")
        if str(speaker_ref_map_json or "").strip()
        else {}
    )
    normalized_has_single_reference_audio = bool(normalized_single_ref_audio)
    normalized_dubbing_mode = (
        "single"
        if normalized_has_single_reference_audio
        else ("multi" if normalized_detected_speaker_ids else "single")
    )
    if normalized_dubbing_mode == "single":
        if len(normalized_speaker_ref_map) > 0:
            raise HTTPException(status_code=400, detail="speaker_ref_map_json is only allowed when subtitles contain speaker metadata")
    else:
        missing_speakers = [
            speaker_id
            for speaker_id in normalized_detected_speaker_ids
            if speaker_id not in normalized_speaker_ref_map
        ]
        # 当前产品规则：有 speaker 时，只允许 0 上传或全上传，不允许部分上传。
        if normalized_speaker_ref_map and missing_speakers:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Detected speaker subtitles only allow zero uploaded references or a full set for every speaker. "
                    f"Missing: {', '.join(missing_speakers)}"
                ),
            )
        for speaker_id, ref_path in normalized_speaker_ref_map.items():
            if speaker_id not in normalized_detected_speaker_ids:
                raise HTTPException(status_code=400, detail=f"unknown speaker_id in speaker_ref_map_json: {speaker_id}")
            if not ref_path.exists():
                raise HTTPException(status_code=400, detail=f"speaker reference audio not found for {speaker_id}: {ref_path}")
    return {
        "subtitle_mode": normalized_subtitle_mode,
        "dubbing_mode": normalized_dubbing_mode,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "tts_backend": normalized_tts_backend,
        "single_ref_audio": normalized_single_ref_audio,
        "single_ref_text": normalized_single_ref_text,
        "speaker_ref_map": [
            {
                "speaker_id": speaker_id,
                "ref_audio_path": str(spec.get("ref_audio_path") or ""),
                "ref_text": str(spec.get("ref_text") or "").strip(),
            }
            for speaker_id, spec in normalized_speaker_ref_specs.items()
            if str(spec.get("ref_audio_path") or "").strip()
        ],
        "tts_model_path": normalized_tts_model_path,
        "effective_api_key": effective_api_key,
        "translate_base_url": normalized_translate_base_url,
        "translate_model": normalized_translate_model,
        "translate_system_prompt": normalized_translate_system_prompt,
        "index_tts_api_url": normalized_index_tts_api_url,
        "segment_minutes": segment_minutes,
        "min_segment_minutes": min_segment_minutes,
        "timing_mode": normalized_timing_mode,
        "grouping_strategy": normalized_grouping_strategy,
        "short_merge_enabled": short_merge_enabled_value,
        "short_merge_threshold": int(short_merge_threshold),
        "translated_short_merge_enabled": translated_short_merge_enabled_value,
        "translated_short_merge_threshold": int(translated_short_merge_threshold),
        "dub_audio_leveling_enabled": bool(dub_audio_leveling_enabled),
        "dub_audio_leveling_target_rms": float(dub_audio_leveling_target_rms),
        "dub_audio_leveling_activity_threshold_db": float(dub_audio_leveling_activity_threshold_db),
        "dub_audio_leveling_max_gain_db": float(dub_audio_leveling_max_gain_db),
        "dub_audio_leveling_peak_ceiling": float(dub_audio_leveling_peak_ceiling),
        "time_ranges": parsed_time_ranges,
        "rewrite_translation": rewrite_translation_enabled,
    }


def _write_subtitles_json_to_srt(
    *,
    upload_dir: Path,
    subtitles_json: str,
    subtitle_mode: str,
    speaker_mode: str = "auto",
) -> Optional[Path]:
    """把主 workflow 内存中的字幕数组落成 SRT，供 CLI 直接复用当前项目上下文。"""

    raw = (subtitles_json or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid subtitles_json: {exc}") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Invalid subtitles_json: must be a list")
    if not payload:
        return None

    subtitle_items: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Invalid subtitles_json item")
        start_sec = item.get("start", item.get("start_sec"))
        end_sec = item.get("end", item.get("end_sec"))
        text = str(item.get("text", "") or "").strip()
        if start_sec is None or end_sec is None or not text:
            continue
        try:
            start_value = float(start_sec)
            end_value = float(end_sec)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid subtitles_json timing: {exc}") from exc
        if end_value <= start_value:
            continue
        subtitle_items.append(
            {
                "start": start_value,
                "end": end_value,
                "text": text,
                "speaker_id": str(item.get("speaker_id") or "").strip(),
            }
        )

    if not subtitle_items:
        raise HTTPException(status_code=400, detail="Invalid subtitles_json: no valid subtitle rows")

    subtitle_items, _ = normalize_subtitles_with_speakers(subtitle_items)
    subtitle_items = optimize_srt_import_subtitles(subtitle_items, speaker_mode=speaker_mode)
    srt_path = upload_dir / f"project_{subtitle_mode}.srt"
    srt_path.write_text(format_srt(subtitle_items), encoding="utf-8")
    return srt_path


def _resolve_project_media_path(filename: str, task_id: str) -> Path:
    """只从已知上传目录解析 Current Project 媒体，避免 project-aware 启动变成任意文件读取。"""

    candidates: List[str] = []
    requested_name = (filename or "").strip()
    if requested_name:
        normalized_name = Path(requested_name).name
        if normalized_name != requested_name:
            raise HTTPException(status_code=400, detail="Invalid project filename")
        candidates.append(normalized_name)

    task_payload = legacy_runtime.tasks.get(task_id) if task_id else None
    for key in ("video_filename", "filename"):
        value = str((task_payload or {}).get(key, "") or "").strip()
        if not value:
            continue
        normalized_name = Path(value).name
        if normalized_name == value and normalized_name not in candidates:
            candidates.append(normalized_name)

    upload_dir = Path(legacy_runtime.UPLOAD_DIR)
    for candidate in candidates:
        if candidate.lower().endswith(".srt"):
            continue
        media_path = upload_dir / candidate
        if media_path.exists() and media_path.is_file():
            return media_path

    if task_payload and str(task_payload.get("filename", "") or "").lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Current project has subtitles but no reusable media file")
    raise HTTPException(status_code=404, detail="Current project media not found")


def _queue_auto_dubbing_task(
    *,
    task_id: Optional[str] = None,
    filename: str,
    input_path: Path,
    input_srt_path: Optional[Path],
    input_speaker_metadata_path: Optional[Path],
    options: Dict[str, Any],
    resume_batch_dir: Optional[Path] = None,
    out_root_override: Optional[Path] = None,
) -> Dict[str, str]:
    """创建 Auto Dubbing 任务记录并启动后台 CLI 线程，供两条启动入口共用。"""

    active = _task_store.list_active_ids()
    if active:
        raise HTTPException(status_code=409, detail="Another auto dubbing job is already running")

    resolved_task_id = task_id or _build_readable_task_id()
    out_root = (
        Path(str(out_root_override)).expanduser().resolve()
        if out_root_override is not None
        else (OUTPUT_ROOT / f"web_{resolved_task_id}")
    )
    out_root.mkdir(parents=True, exist_ok=True)

    normalized_backend = str(options.get("tts_backend") or "").strip().lower() or "index-tts"
    normalized_mode = str(options.get("dubbing_mode") or "").strip().lower() or "single"
    grouped_synthesis_effective, grouped_synthesis_effective_reason = _derive_grouped_synthesis_effective_state(
        {
            "subtitle_mode": options.get("subtitle_mode"),
            "source_short_merge_enabled": options.get("short_merge_enabled"),
        }
    )
    force_fit_timing_effective, force_fit_timing_effective_reason = _derive_force_fit_timing_effective_state(
        {
            "subtitle_mode": options.get("subtitle_mode"),
        }
    )
    if options.get("time_ranges"):
        effective_range_strategy = "manual"
    else:
        effective_range_strategy = "all"
    speaker_ref_map_payload = list(options.get("speaker_ref_map") or [])

    merge_track = "auto"
    # index-tts 的自动配音实测以较短文本块更稳定；统一回退到 40，避免长文本导致时长和韵律明显漂移。
    index_max_text_tokens = 40

    cmd = build_auto_dubbing_command(
        AutoDubbingCommandConfig(
            python_executable=sys.executable,
            tool_path=TOOL_PATH,
            input_media=input_path,
            target_lang=options["target_lang"],
            out_dir=out_root,
            segment_minutes=options["segment_minutes"],
            min_segment_minutes=options["min_segment_minutes"],
            timing_mode=options["timing_mode"],
            grouping_strategy=options["grouping_strategy"],
            dubbing_mode=options["dubbing_mode"],
            short_merge_enabled=options["short_merge_enabled"],
            short_merge_threshold=options["short_merge_threshold"],
            translated_short_merge_enabled=options["translated_short_merge_enabled"],
            translated_short_merge_threshold=options["translated_short_merge_threshold"],
            dub_audio_leveling_enabled=options["dub_audio_leveling_enabled"],
            dub_audio_leveling_target_rms=options["dub_audio_leveling_target_rms"],
            dub_audio_leveling_activity_threshold_db=options["dub_audio_leveling_activity_threshold_db"],
            dub_audio_leveling_max_gain_db=options["dub_audio_leveling_max_gain_db"],
            dub_audio_leveling_peak_ceiling=options["dub_audio_leveling_peak_ceiling"],
            translate_base_url=options["translate_base_url"],
            translate_model=options["translate_model"],
            translate_system_prompt=options["translate_system_prompt"],
            tts_model_path=options["tts_model_path"],
            tts_backend=options["tts_backend"],
            index_tts_api_url=options["index_tts_api_url"],
            resume_batch_dir=resume_batch_dir,
            input_srt=input_srt_path,
            speaker_metadata_path=input_speaker_metadata_path,
            input_srt_kind=options["subtitle_mode"],
            time_ranges=options["time_ranges"],
            source_lang=options["source_lang"],
            rewrite_translation=options["rewrite_translation"],
            single_ref_audio=options["single_ref_audio"],
            single_ref_text=options["single_ref_text"],
            speaker_ref_map_json=json.dumps(speaker_ref_map_payload, ensure_ascii=False) if speaker_ref_map_payload else "",
            merge_track=merge_track,
            index_max_text_tokens=index_max_text_tokens,
        )
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if options["effective_api_key"]:
        env[TRANSLATE_API_KEY_ENV] = options["effective_api_key"]

    task = {
        "id": resolved_task_id,
        "short_id": resolved_task_id.split("-")[0],
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "filename": filename,
        "target_lang": options["target_lang"],
        "timing_mode": options["timing_mode"],
        "grouping_strategy": options["grouping_strategy"],
        "source_short_merge_enabled": options["short_merge_enabled"],
        "source_short_merge_threshold": options["short_merge_threshold"],
        "source_short_merge_threshold_mode": "seconds",
        "translated_short_merge_enabled": options["translated_short_merge_enabled"],
        "translated_short_merge_threshold": options["translated_short_merge_threshold"],
        "translated_short_merge_threshold_mode": "seconds",
        "dub_audio_leveling_enabled": options["dub_audio_leveling_enabled"],
        "dub_audio_leveling_target_rms": options["dub_audio_leveling_target_rms"],
        "dub_audio_leveling_activity_threshold_db": options["dub_audio_leveling_activity_threshold_db"],
        "dub_audio_leveling_max_gain_db": options["dub_audio_leveling_max_gain_db"],
        "dub_audio_leveling_peak_ceiling": options["dub_audio_leveling_peak_ceiling"],
        "source_lang": options["source_lang"],
        "subtitle_mode": options["subtitle_mode"],
        "segment_minutes": float(options.get("segment_minutes", DEFAULT_SEGMENT_MINUTES) or DEFAULT_SEGMENT_MINUTES),
        "min_segment_minutes": float(
            options.get("min_segment_minutes", DEFAULT_MIN_SEGMENT_MINUTES) or DEFAULT_MIN_SEGMENT_MINUTES
        ),
        "translate_base_url": options["translate_base_url"],
        "translate_model": options["translate_model"],
        "translate_system_prompt": options["translate_system_prompt"],
        "dubbing_mode": options["dubbing_mode"],
        "tts_backend": options["tts_backend"],
        "single_ref_audio": options["single_ref_audio"],
        "single_ref_text": options["single_ref_text"],
        "speaker_ref_map": options["speaker_ref_map"],
        "tts_model_path": options["tts_model_path"],
        "index_tts_api_url": options["index_tts_api_url"],
        "time_ranges": options["time_ranges"],
        "rewrite_translation": options["rewrite_translation"],
        "translate_request_count": 0,
        "index_max_text_tokens": index_max_text_tokens,
        "grouped_synthesis_effective": grouped_synthesis_effective,
        "grouped_synthesis_effective_reason": grouped_synthesis_effective_reason,
        "force_fit_timing_effective": force_fit_timing_effective,
        "force_fit_timing_effective_reason": force_fit_timing_effective_reason,
        "effective_range_strategy": effective_range_strategy,
        "processed_segments": 0,
        "total_segments": None,
        "artifacts": [],
        "stdout_tail": [],
        "input_path": str(input_path),
        "input_srt": str(input_srt_path) if input_srt_path else None,
        "input_speaker_metadata": str(input_speaker_metadata_path) if input_speaker_metadata_path else None,
        "upload_dir": str(input_path.parent),
        "out_root": str(out_root),
        "resume_batch_dir": str(resume_batch_dir) if resume_batch_dir else None,
        "command": [part if part != options["effective_api_key"] else "***" for part in cmd],
    }
    task["runtime_brief"] = _build_task_runtime_brief(task)
    _task_store.create(resolved_task_id, task)
    _set_task(
        resolved_task_id,
        runtime_brief=task["runtime_brief"],
        _runtime_brief_changed=True,
    )

    thread = threading.Thread(target=_run_cli_task, args=(resolved_task_id, cmd, env, out_root), daemon=True)
    thread.start()
    return {"task_id": resolved_task_id, "short_id": task["short_id"], "status": "queued"}


def _set_task(task_id: str, **updates: Any) -> None:
    """更新任务状态，并在关键字段变化时输出一次摘要日志。"""

    previous = _task_store.get_copy(task_id) or {}
    payload = dict(updates)
    runtime_brief_changed = bool(payload.pop("_runtime_brief_changed", False))
    payload.setdefault("updated_at", _iso_now())
    updated = _task_store.update(task_id, **payload)
    if not updated:
        return
    log_updates = dict(updates)
    if runtime_brief_changed:
        log_updates["_runtime_brief_changed"] = True
    _log_task_state_change(task_id, previous=previous, current=updated, updates=log_updates)


def _append_stdout(task_id: str, line: str) -> None:
    _task_store.append_stdout(task_id, line)


def _public_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return _task_store.to_public(task)


def _progress_for_segment(processed: int, total: Optional[int]) -> float:
    if not total or total <= 0:
        return 45.0
    return min(92.0, 25.0 + 67.0 * (processed / total))


def _bump_stage(task_id: str, stage: str, minimum_progress: float) -> None:
    """在任务进入新阶段时推进进度，并输出一次阶段摘要日志。"""

    previous = _task_store.get_copy(task_id) or {}
    updated = _task_store.set_stage(task_id, stage, minimum_progress, updated_at=_iso_now())
    if not updated:
        return
    _log_task_state_change(
        task_id,
        previous=previous,
        current=updated,
        updates={"stage": stage, "progress": updated.get("progress")},
    )


def _format_progress_value(value: Any) -> str:
    """将任务进度格式化为易读百分比字符串。"""

    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "?"


def _derive_task_tts_base(task: Dict[str, Any]) -> str:
    """根据任务快照生成当前使用的 TTS 底座说明。"""

    api_url = str(task.get("index_tts_api_url") or "").strip() or "-"
    return f"index-tts(api={api_url})"


def _derive_grouped_synthesis_effective_state(task: Dict[str, Any]) -> tuple[bool, str]:
    """根据任务快照推导 grouped synthesis 的最终状态与原因。"""

    subtitle_mode = str(task.get("subtitle_mode") or "source").strip().lower() or "source"
    if subtitle_mode == "translated":
        return False, "input_translated_strict_alignment"
    return True, "user"


def _derive_force_fit_timing_effective_state(task: Dict[str, Any]) -> tuple[bool, str]:
    """根据任务快照推导 force-fit timing 的最终状态与原因。"""

    subtitle_mode = str(task.get("subtitle_mode") or "source").strip().lower() or "source"
    if subtitle_mode == "translated":
        return False, "input_translated_natural_ending"
    return True, "user"


def _derive_task_grouping_policy(task: Dict[str, Any]) -> str:
    """根据任务快照生成分组策略摘要。"""

    grouping_strategy = str(task.get("grouping_strategy") or "").strip() or "sentence"
    grouped_effective = bool(task.get("grouped_synthesis_effective", True))
    grouped_reason = str(task.get("grouped_synthesis_effective_reason") or "user").strip() or "user"
    fit_effective = bool(task.get("force_fit_timing_effective", True))
    fit_reason = str(task.get("force_fit_timing_effective_reason") or "user").strip() or "user"
    grouped_label = str(grouped_effective).lower()
    fit_label = str(fit_effective).lower()
    if grouped_reason != "user":
        grouped_label = f"{grouped_label}[{grouped_reason}]"
    if fit_reason != "user":
        fit_label = f"{fit_label}[{fit_reason}]"
    return (
        f"{grouping_strategy}("
        f"grouped={grouped_label},force_fit={fit_label})"
    )


def _derive_task_range_policy(task: Dict[str, Any]) -> str:
    """根据任务快照生成范围选择策略摘要。"""

    effective = str(task.get("effective_range_strategy") or "").strip().lower()
    if effective in {"all", "manual"}:
        strategy = effective
    elif task.get("time_ranges"):
        strategy = "manual"
    else:
        strategy = "all"
    ranges = task.get("time_ranges") or []
    if isinstance(ranges, list):
        return f"{strategy}(ranges={len(ranges)})"
    return f"{strategy}(ranges=0)"


def _derive_task_translation_policy(task: Dict[str, Any]) -> str:
    """根据任务快照生成翻译策略摘要。"""

    subtitle_mode = str(task.get("subtitle_mode") or "source").strip().lower() or "source"
    rewrite_translation = bool(task.get("rewrite_translation", True))
    custom_prompt = bool(str(task.get("translate_system_prompt") or "").strip())
    prompt_label = "custom" if custom_prompt else "default"
    translate_base_url = str(task.get("translate_base_url") or "").strip()
    provider_label = get_translate_provider_label(translate_base_url)
    if subtitle_mode == "translated":
        return f"skip(input=translated,via={provider_label})"
    rewrite_label = "on" if rewrite_translation else "off"
    return f"run(input=source,via={provider_label},rewrite={rewrite_label},prompt={prompt_label})"


def _build_task_runtime_brief(task: Dict[str, Any]) -> Dict[str, str]:
    """提炼 Auto Dubbing 任务的关键运行配置，供状态日志打印。"""

    source_merge = (
        f"{'on' if bool(task.get('source_short_merge_enabled')) else 'off'}"
        f"({task.get('source_short_merge_threshold', '-')}s)"
    )
    translated_merge = (
        f"{'on' if bool(task.get('translated_short_merge_enabled')) else 'off'}"
        f"({task.get('translated_short_merge_threshold', '-')}s)"
    )
    segment_minutes = task.get("segment_minutes")
    min_segment_minutes = task.get("min_segment_minutes")
    return {
        "tts_base": _derive_task_tts_base(task),
        "dubbing_mode": str(task.get("dubbing_mode") or "single"),
        "grouping": _derive_task_grouping_policy(task),
        "timing_mode": str(task.get("timing_mode") or "strict"),
        "translation": _derive_task_translation_policy(task),
        "merge": f"source={source_merge},translated={translated_merge}",
        "range": _derive_task_range_policy(task),
        "segment": f"{segment_minutes}m/{min_segment_minutes}m",
    }


def _log_task_state_change(
    task_id: str,
    *,
    previous: Dict[str, Any],
    current: Dict[str, Any],
    updates: Dict[str, Any],
) -> None:
    """仅在状态、阶段或关键计数变化时输出任务摘要日志。"""

    runtime_brief_changed = bool(updates.get("_runtime_brief_changed"))
    previous_status = str(previous.get("status") or "")
    current_status = str(current.get("status") or "")
    previous_stage = str(previous.get("stage") or "")
    current_stage = str(current.get("stage") or "")
    previous_processed = previous.get("processed_segments")
    current_processed = current.get("processed_segments")
    previous_total = previous.get("total_segments")
    current_total = current.get("total_segments")
    status_changed = previous_status != current_status
    stage_changed = previous_stage != current_stage
    processed_changed = previous_processed != current_processed and current_processed is not None
    total_changed = previous_total != current_total and current_total is not None
    should_log = status_changed or stage_changed or processed_changed or total_changed or runtime_brief_changed
    if not should_log:
        return

    short_id = str(current.get("short_id") or task_id[-8:] or task_id)
    progress_text = _format_progress_value(current.get("progress"))
    summary = [f"[auto-dubbing] task={short_id}", f"status={current_status or '-'}"]
    if current_stage:
        summary.append(f"stage={current_stage}")
    summary.append(f"progress={progress_text}")

    if current_processed is not None and current_total:
        summary.append(f"segments={current_processed}/{current_total}")
    elif current_processed is not None:
        summary.append(f"segments={current_processed}")
    elif total_changed:
        summary.append(f"total_segments={current_total}")

    if "error" in updates and updates.get("error"):
        summary.append(f"error={updates['error']}")

    runtime_brief = current.get("runtime_brief")
    if isinstance(runtime_brief, dict):
        summary.append(f"tts={runtime_brief.get('tts_base', '-')}")
        summary.append(f"dubbing_mode={runtime_brief.get('dubbing_mode', '-')}")
        summary.append(f"grouping={runtime_brief.get('grouping', '-')}")
        summary.append(f"timing={runtime_brief.get('timing_mode', '-')}")
        summary.append(f"translation={runtime_brief.get('translation', '-')}")
        translate_calls = int(current.get("translate_request_count", current.get("deepseek_request_count", 0)) or 0)
        summary.append(f"translate_calls={translate_calls}")
        summary.append(f"merge={runtime_brief.get('merge', '-')}")
        summary.append(f"range={runtime_brief.get('range', '-')}")
        summary.append(f"segment={runtime_brief.get('segment', '-')}")

    # 状态摘要之间加一空行，避免与 access log 粘连在一起难以阅读。
    logger.info("%s\n", " | ".join(summary))


def _update_from_stdout(task_id: str, line: str) -> None:
    if "HTTP Request:" in line and "/chat/completions" in line:
        with _lock:
            task = _task_store.get(task_id)
            if task:
                base_count = int(task.get("translate_request_count", task.get("deepseek_request_count", 0)) or 0)
                next_count = base_count + 1
                if "deepseek_request_count" in task:
                    task.pop("deepseek_request_count", None)
            else:
                next_count = None
        if next_count is not None:
            _set_task(task_id, translate_request_count=next_count)

    planned_match = re.search(r"Planned segments:\s*(\d+)", line)
    existing_match = re.search(r"Existing segments:\s*(\d+)", line)
    if planned_match or existing_match:
        total = int((planned_match or existing_match).group(1))
        _set_task(task_id, total_segments=total, line_progress_total=total)
        return

    if "Step 1/5" in line:
        _set_task(task_id, stage="dubbing:preparing", progress=8.0)
        return
    if "Step 2/5" in line:
        _set_task(task_id, stage="dubbing:planning", progress=16.0)
        return
    if "Step 3/5" in line:
        _set_task(task_id, stage="dubbing:segmenting", progress=23.0)
        return
    if "Step 4/5" in line:
        _set_task(task_id, stage="dubbing", progress=28.0)
        return
    if "Step 5/5" in line:
        _set_task(task_id, stage="dubbing:merging", progress=94.0)
        return

    # 旧 transcribing 阶段已从前端面板移除：这些日志并入 dubbing 高亮。
    if "[INFO] extract_audio:" in line or "[INFO] asr_align:" in line:
        _bump_stage(task_id, "dubbing", 34.0)
        return
    if "[INFO] translate:" in line:
        _bump_stage(task_id, "translating", 52.0)
        return
    if (
        "[INFO] separate_vocals:" in line
        or "[INFO] ref_extract:" in line
        or "[INFO] tts:" in line
        or "[INFO] mix:" in line
    ):
        _bump_stage(task_id, "dubbing", 68.0)
        return

    done_match = re.search(r"===== Segment\s+(\d+)\s+done", line)
    if done_match:
        with _lock:
            task = _task_store.get(task_id)
            if not task:
                return
            processed = max(int(task.get("processed_segments", 0)), int(done_match.group(1)))
            total = task.get("total_segments")
        _set_task(
            task_id,
            processed_segments=processed,
            line_progress_processed=processed,
            progress=_progress_for_segment(processed, total),
            stage="dubbing",
        )
        return

    if "Batch completed." in line:
        _set_task(task_id, stage="dubbing:completed", progress=98.0)


def _normalize_cli_failure_line(line: str, max_length: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", (line or "").strip())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _extract_cli_failure_detail(stdout_tail: List[str]) -> Optional[str]:
    def _normalize_provider_auth_error(line: str) -> Optional[str]:
        """把 provider 返回的 401 文案转成可读的鉴权提示。"""

        lowered = line.lower()
        if "error code: 401" not in lowered and "401 unauthorized" not in lowered:
            return None
        if "/chat/completions" in lowered or "internal server error" in lowered:
            return (
                "Pipeline failed: Translation provider authentication failed "
                "(HTTP 401). Please verify API key/base URL/model or switch provider."
            )
        return (
            "Pipeline failed: Upstream authentication failed (HTTP 401). "
            "Please verify API credentials."
        )

    # 第一优先级：直接抽取 pipeline 明确给出的失败原因，避免被 traceback 包装信息覆盖。
    for raw_line in reversed(stdout_tail):
        line = (raw_line or "").strip()
        if not line:
            continue
        normalized_auth_error = _normalize_provider_auth_error(line)
        if normalized_auth_error:
            return normalized_auth_error
        if line.startswith("Pipeline failed:"):
            return _normalize_cli_failure_line(
                normalized_auth_error or line
            )
        if line.startswith("[ERROR]"):
            parts = line.split(" - ", 1)
            if len(parts) == 2:
                message = parts[1].strip()
                if message and message.lower() not in {"pipeline failed", "job failed"}:
                    return _normalize_cli_failure_line(message)

    # 第二优先级：回退到最后一条“非包装噪音”日志行。
    for raw_line in reversed(stdout_tail):
        line = (raw_line or "").strip()
        if not line:
            continue
        normalized_auth_error = _normalize_provider_auth_error(line)
        if normalized_auth_error:
            return normalized_auth_error
        if line.startswith("[INFO]") or line.startswith("HTTP Request:"):
            continue
        if line.startswith("Traceback ") or line == "Traceback (most recent call last):":
            continue
        if line.startswith("During handling of the above exception"):
            continue
        if line.startswith("^"):
            continue
        # traceback 里的源码行（如 `raise RuntimeError(...)`）是包装噪音，不作为根因输出。
        if line.startswith("raise ") or line.startswith("... raise "):
            continue
        if re.match(r'^File ".+", line \d+, in .+', line):
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+$", line):
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(.+\)$", line):
            continue
        if line.startswith("raise RuntimeError("):
            continue
        if line.startswith("RuntimeError: command failed"):
            continue
        if "command failed (" in line:
            continue
        return _normalize_cli_failure_line(line)
    return None


def _build_cli_exit_error(code: int, stdout_tail: List[str]) -> str:
    message = f"dub_long_video.py exited with code {code}"
    detail = _extract_cli_failure_detail(stdout_tail)
    if not detail:
        return message
    return f"{message}: {detail}"


def _find_batch_manifest(out_root: Path) -> Optional[Path]:
    manifests = sorted(
        out_root.glob("longdub_*/batch_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return manifests[0] if manifests else None


def _find_latest_batch_dir(out_root: Path) -> Optional[Path]:
    # 从 web 输出目录下挑选最近的 longdub 目录，用于失败任务续跑。
    root = out_root.expanduser().resolve()
    candidates: List[Path] = []
    if root.is_dir() and root.name.startswith("longdub_"):
        candidates.append(root)
    if root.exists():
        candidates.extend(root.glob("longdub_*"))
    for candidate in sorted({item.resolve() for item in candidates}, key=lambda item: item.stat().st_mtime, reverse=True):
        if not candidate.is_dir():
            continue
        if (candidate / "segment_jobs").exists() or (candidate / "segments").exists() or (candidate / "batch_manifest.json").exists():
            return candidate
    return None


def _resolve_resume_batch_dir(task: Dict[str, Any]) -> Path:
    # 解析续跑批次目录：优先历史字段，其次 batch manifest，再退回 out_root 下最近 longdub。
    direct = str(task.get("resume_batch_dir") or "").strip()
    if direct:
        direct_path = Path(direct).expanduser().resolve()
        if direct_path.exists() and direct_path.is_dir():
            return direct_path

    manifest_text = str(task.get("batch_manifest_path") or "").strip()
    if manifest_text:
        manifest_path = Path(manifest_text).expanduser().resolve()
        if manifest_path.exists():
            return manifest_path.parent

    out_root_text = str(task.get("out_root") or "").strip()
    if out_root_text:
        out_root = Path(out_root_text).expanduser().resolve()
        latest = _find_latest_batch_dir(out_root)
        if latest is not None:
            return latest

    raise HTTPException(status_code=404, detail="Resume batch directory not found")


def _resolve_resume_out_root(task: Dict[str, Any], *, resume_batch_dir: Path) -> Path:
    # 续跑输出根目录优先沿用原任务 out_root，保证结果继续落在同一 web_* 目录下。
    out_root_text = str(task.get("out_root") or "").strip()
    if out_root_text:
        out_root = Path(out_root_text).expanduser().resolve()
        if out_root.exists() and out_root.is_dir():
            return out_root
    return resume_batch_dir.parent.resolve()


def _resolve_resume_input_media(task: Dict[str, Any], *, resume_batch_dir: Path) -> Path:
    # 续跑时优先复用原始输入媒体路径，缺失时回退 batch manifest 中的 input_media_path。
    preferred_candidates: List[Path] = []
    fallback_candidates: List[Path] = []

    def push_candidate(candidate: Path) -> None:
        try:
            normalized = candidate.expanduser().resolve()
        except Exception:
            return
        if normalized in preferred_candidates or normalized in fallback_candidates:
            return
        target = fallback_candidates if _is_segment_slice_media_path(normalized) else preferred_candidates
        target.append(normalized)

    input_path_text = str(task.get("input_path") or "").strip()
    if input_path_text:
        push_candidate(Path(input_path_text))

    manifest_path = resume_batch_dir / "batch_manifest.json"
    if manifest_path.exists():
        try:
            batch_manifest = load_batch_manifest(manifest_path)
            input_media_path = str(batch_manifest.input_media_path or "").strip()
            if input_media_path:
                preferred = _resolve_preferred_batch_input_media(
                    batch_dir=resume_batch_dir,
                    manifest_input_path=input_media_path,
                )
                if preferred is not None:
                    push_candidate(preferred)
                else:
                    push_candidate(Path(input_media_path))
        except Exception:
            pass
    else:
        # 无 batch manifest 的中断批次，尝试按 web_<task_id> 回溯上传目录。
        uploaded_media = _find_uploaded_media_for_batch_dir(resume_batch_dir)
        if uploaded_media is not None:
            push_candidate(uploaded_media)

    upload_dir_text = str(task.get("upload_dir") or "").strip()
    filename_text = str(task.get("filename") or "").strip()
    if upload_dir_text and filename_text:
        push_candidate(Path(upload_dir_text).expanduser().resolve() / Path(filename_text).name)

    for candidate in preferred_candidates + fallback_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail="Resume input media not found")


def _resolve_resume_input_srt(task: Dict[str, Any]) -> Optional[Path]:
    # 若原任务带了外部字幕输入，续跑时继续复用；文件丢失则自动回退无字幕输入。
    input_srt_text = str(task.get("input_srt") or "").strip()
    if not input_srt_text:
        return None
    input_srt_path = Path(input_srt_text).expanduser().resolve()
    if not input_srt_path.exists() or not input_srt_path.is_file():
        return None
    return input_srt_path


def _build_resume_options(
    *,
    task: Dict[str, Any],
    resume_batch_dir: Path,
    api_key: str,
    has_subtitle_input: bool,
) -> Dict[str, Any]:
    # 从历史任务 + batch manifest 回放参数，并复用统一请求校验逻辑。
    batch_options = None
    batch_raw: Dict[str, Any] = {}
    batch_manifest_path = resume_batch_dir / "batch_manifest.json"
    if batch_manifest_path.exists():
        try:
            batch_manifest = load_batch_manifest(batch_manifest_path)
            batch_options = batch_manifest.options
            batch_raw = batch_manifest.raw
        except Exception:
            batch_options = None
            batch_raw = {}

    def pick_text(*values: Any, default: str = "") -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return default

    def pick_bool(*values: Any, default: bool) -> bool:
        for value in values:
            if value is None:
                continue
            return _coerce_bool(value, default=default)
        return bool(default)

    def pick_int(*values: Any, default: int) -> int:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return int(default)

    def pick_float(*values: Any, default: float) -> float:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return float(default)

    time_ranges_value: Any = task.get("time_ranges")
    if not isinstance(time_ranges_value, list) and batch_options is not None:
        time_ranges_value = batch_options.time_ranges
    time_ranges_form = ""
    if isinstance(time_ranges_value, list) and time_ranges_value:
        time_ranges_form = json.dumps(time_ranges_value, ensure_ascii=False)
    elif isinstance(time_ranges_value, str):
        time_ranges_form = time_ranges_value

    return _normalize_auto_dubbing_request(
        subtitle_mode=pick_text(task.get("subtitle_mode"), getattr(batch_options, "input_srt_kind", None), default="source"),
        dubbing_mode=pick_text(task.get("dubbing_mode"), getattr(batch_options, "dubbing_mode", None), default="single"),
        source_lang=pick_text(task.get("source_lang"), default="auto"),
        target_lang=pick_text(task.get("target_lang"), getattr(batch_options, "target_lang", None)),
        api_key=str(api_key or ""),
        translate_base_url=pick_text(task.get("translate_base_url"), default=DEFAULT_TRANSLATE_BASE_URL),
        translate_model=pick_text(task.get("translate_model"), default=DEFAULT_TRANSLATE_MODEL),
        translate_system_prompt=pick_text(
            task.get("translate_system_prompt"),
            getattr(batch_options, "translate_system_prompt", None),
            default="",
        ),
        tts_backend=pick_text(task.get("tts_backend"), getattr(batch_options, "tts_backend", None), default="index-tts"),
        tts_model_path=pick_text(
            task.get("tts_model_path"),
            getattr(batch_options, "tts_model_path", None),
            default="",
        ),
        single_ref_audio=pick_text(
            task.get("single_ref_audio"),
            getattr(batch_options, "single_ref_audio", None),
            default="",
        ),
        single_ref_text=pick_text(
            task.get("single_ref_text"),
            getattr(batch_options, "single_ref_text", None),
            default="",
        ),
        speaker_ref_map_json=json.dumps(
            list(task.get("speaker_ref_map") or getattr(batch_options, "speaker_ref_map", []) or []),
            ensure_ascii=False,
        ),
        detected_speaker_ids=[
            str(item.get("speaker_id") or "").strip()
            for item in list(task.get("speaker_ref_map") or getattr(batch_options, "speaker_ref_map", []) or [])
            if str(item.get("speaker_id") or "").strip()
        ],
        index_tts_api_url=pick_text(
            task.get("index_tts_api_url"),
            getattr(batch_options, "index_tts_api_url", None),
            default=DEFAULT_INDEX_TTS_API_URL,
        ),
        segment_minutes=pick_float(
            task.get("segment_minutes"),
            batch_raw.get("segment_minutes"),
            default=DEFAULT_SEGMENT_MINUTES,
        ),
        min_segment_minutes=pick_float(
            task.get("min_segment_minutes"),
            batch_raw.get("min_segment_minutes"),
            default=DEFAULT_MIN_SEGMENT_MINUTES,
        ),
        timing_mode=pick_text(task.get("timing_mode"), getattr(batch_options, "timing_mode", None), default="strict"),
        grouping_strategy=pick_text(
            task.get("grouping_strategy"),
            getattr(batch_options, "grouping_strategy", None),
            default="sentence",
        ),
        short_merge_enabled="true"
        if pick_bool(
            task.get("source_short_merge_enabled"),
            getattr(batch_options, "source_short_merge_enabled", None),
            default=False,
        )
        else "false",
        short_merge_threshold=pick_int(
            task.get("source_short_merge_threshold"),
            getattr(batch_options, "source_short_merge_threshold", None),
            default=DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
        ),
        translated_short_merge_enabled="true"
        if pick_bool(
            task.get("translated_short_merge_enabled"),
            getattr(batch_options, "translated_short_merge_enabled", None),
            default=False,
        )
        else "false",
        translated_short_merge_threshold=pick_int(
            task.get("translated_short_merge_threshold"),
            getattr(batch_options, "translated_short_merge_threshold", None),
            default=DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
        ),
        time_ranges=time_ranges_form,
        rewrite_translation="true"
        if pick_bool(
            task.get("rewrite_translation"),
            getattr(batch_options, "rewrite_translation", None),
            default=True,
        )
        else "false",
        has_subtitle_input=has_subtitle_input,
        dub_audio_leveling_enabled=pick_bool(
            task.get("dub_audio_leveling_enabled"),
            getattr(batch_options, "dub_audio_leveling_enabled", None),
            default=True,
        ),
        dub_audio_leveling_target_rms=pick_float(
            task.get("dub_audio_leveling_target_rms"),
            getattr(batch_options, "dub_audio_leveling_target_rms", None),
            default=DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS,
        ),
        dub_audio_leveling_activity_threshold_db=pick_float(
            task.get("dub_audio_leveling_activity_threshold_db"),
            getattr(batch_options, "dub_audio_leveling_activity_threshold_db", None),
            default=DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB,
        ),
        dub_audio_leveling_max_gain_db=pick_float(
            task.get("dub_audio_leveling_max_gain_db"),
            getattr(batch_options, "dub_audio_leveling_max_gain_db", None),
            default=DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB,
        ),
        dub_audio_leveling_peak_ceiling=pick_float(
            task.get("dub_audio_leveling_peak_ceiling"),
            getattr(batch_options, "dub_audio_leveling_peak_ceiling", None),
            default=DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING,
        ),
    )


def _find_batch_manifest_by_name(batch_id: str) -> Optional[Path]:
    # 根据 longdub 批次目录名回查 manifest，支持刷新后恢复结果。
    return find_batch_manifest_by_name(output_root=OUTPUT_ROOT, batch_id=batch_id)


def _find_batch_dir_by_name(batch_id: str) -> Optional[Path]:
    # 根据 longdub 批次目录名回查目录（允许中断批次无 manifest）。
    return find_batch_dir_by_name(output_root=OUTPUT_ROOT, batch_id=batch_id)


def _list_available_batches(limit: int = 200) -> List[Dict[str, Any]]:
    # 列出可回载的 longdub 批次目录，供前端下拉选择。
    return list_available_batches(output_root=OUTPUT_ROOT, limit=limit)


def _is_segment_slice_media_path(path: Path) -> bool:
    """判断是否为 `segments/segment_0001.wav` 这类分段切片媒体。"""

    try:
        normalized = path.expanduser().resolve()
    except Exception:
        normalized = path
    if normalized.parent.name != "segments":
        return False
    return re.fullmatch(r"segment_\d{4}", normalized.stem or "") is not None


def _find_uploaded_media_for_batch_dir(batch_dir: Path) -> Optional[Path]:
    """按 `web_<task_id>` 回溯 `uploads/dubbing/<task_id>/`，优先选视频文件。"""

    web_dir_name = str(batch_dir.parent.name or "")
    if not web_dir_name.startswith("web_"):
        return None
    task_hint = web_dir_name.removeprefix("web_").strip()
    if not task_hint:
        return None
    upload_dir = (UPLOAD_ROOT / task_hint).expanduser()
    if not upload_dir.exists() or not upload_dir.is_dir():
        return None
    files = [item for item in upload_dir.iterdir() if item.is_file()]
    if not files:
        return None
    video_exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
    media_exts = video_exts | {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
    video_files = [item for item in files if item.suffix.lower() in video_exts]
    if video_files:
        video_files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return video_files[0].resolve()
    media_files = [item for item in files if item.suffix.lower() in media_exts]
    if media_files:
        media_files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return media_files[0].resolve()
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0].resolve()


def _resolve_preferred_batch_input_media(*, batch_dir: Path, manifest_input_path: str = "") -> Optional[Path]:
    """统一选择批次输入媒体：优先原始上传媒体，其次 manifest 记录。"""

    manifest_candidate: Optional[Path] = None
    manifest_text = str(manifest_input_path or "").strip()
    if manifest_text:
        try:
            candidate = Path(manifest_text).expanduser().resolve()
            if candidate.exists() and candidate.is_file():
                manifest_candidate = candidate
        except Exception:
            manifest_candidate = None

    uploaded_candidate = _find_uploaded_media_for_batch_dir(batch_dir)
    if manifest_candidate and not _is_segment_slice_media_path(manifest_candidate):
        return manifest_candidate
    if uploaded_candidate is not None:
        return uploaded_candidate
    return manifest_candidate


def _infer_incomplete_batch_task_fields(batch_dir: Path) -> Dict[str, Any]:
    # 从中断批次的 segment manifest 里尽量回填续跑所需参数。
    defaults: Dict[str, Any] = {
        "filename": "",
        "input_path": "",
        "input_srt": None,
        "source_lang": "auto",
        "target_lang": "",
        "subtitle_mode": "source",
        "segment_minutes": DEFAULT_SEGMENT_MINUTES,
        "min_segment_minutes": DEFAULT_MIN_SEGMENT_MINUTES,
        "timing_mode": "strict",
        "grouping_strategy": "sentence",
        "source_short_merge_enabled": False,
        "source_short_merge_threshold": DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
        "translated_short_merge_enabled": False,
        "translated_short_merge_threshold": DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
        "dub_audio_leveling_enabled": True,
        "dub_audio_leveling_target_rms": DEFAULT_DUB_AUDIO_LEVELING_TARGET_RMS,
        "dub_audio_leveling_activity_threshold_db": DEFAULT_DUB_AUDIO_LEVELING_ACTIVITY_THRESHOLD_DB,
        "dub_audio_leveling_max_gain_db": DEFAULT_DUB_AUDIO_LEVELING_MAX_GAIN_DB,
        "dub_audio_leveling_peak_ceiling": DEFAULT_DUB_AUDIO_LEVELING_PEAK_CEILING,
        "translate_base_url": DEFAULT_TRANSLATE_BASE_URL,
        "translate_model": DEFAULT_TRANSLATE_MODEL,
        "translate_system_prompt": "",
        "dubbing_mode": "single",
        "tts_backend": "index-tts",
        "single_ref_audio": "",
        "single_ref_text": "",
        "speaker_ref_map": [],
        "tts_model_path": "",
        "index_tts_api_url": DEFAULT_INDEX_TTS_API_URL,
        "time_ranges": [],
        "rewrite_translation": True,
    }
    # 先尝试回溯原始上传媒体，避免续跑时把 segment_0001.wav 当输入媒体。
    uploaded_media = _find_uploaded_media_for_batch_dir(batch_dir)
    if uploaded_media is not None:
        defaults["input_path"] = str(uploaded_media)
        defaults["filename"] = uploaded_media.name

    manifest_paths = sorted(batch_dir.glob("segment_jobs/segment_*/manifest.json"))
    for manifest_path in manifest_paths:
        try:
            segment_manifest = load_segment_manifest(manifest_path)
        except Exception:
            continue
        raw = segment_manifest.raw
        input_media_path = str(segment_manifest.input_media_path or raw.get("input_media_path") or "").strip()
        if input_media_path:
            candidate = Path(input_media_path).expanduser().resolve()
            if candidate.exists() and candidate.is_file():
                # 仅当没有更可靠候选时，才使用 segment manifest 推断出的输入媒体。
                if not defaults["input_path"]:
                    defaults["input_path"] = str(candidate)
                    defaults["filename"] = candidate.name
                else:
                    current = Path(str(defaults["input_path"])).expanduser()
                    if _is_segment_slice_media_path(current) and not _is_segment_slice_media_path(candidate):
                        defaults["input_path"] = str(candidate)
                        defaults["filename"] = candidate.name
        defaults["target_lang"] = str(raw.get("target_lang") or defaults["target_lang"])
        defaults["source_lang"] = str(raw.get("source_lang") or defaults["source_lang"])
        defaults["subtitle_mode"] = str(raw.get("input_srt_kind") or defaults["subtitle_mode"])
        defaults["timing_mode"] = str(raw.get("timing_mode") or defaults["timing_mode"])
        defaults["grouping_strategy"] = str(raw.get("grouping_strategy") or defaults["grouping_strategy"])
        defaults["source_short_merge_enabled"] = _coerce_bool(
            raw.get("source_short_merge_enabled"),
            default=bool(defaults["source_short_merge_enabled"]),
        )
        try:
            defaults["source_short_merge_threshold"] = int(
                raw.get("source_short_merge_threshold") or defaults["source_short_merge_threshold"]
            )
        except (TypeError, ValueError):
            pass
        defaults["translated_short_merge_enabled"] = _coerce_bool(
            raw.get("translated_short_merge_enabled"),
            default=bool(defaults["translated_short_merge_enabled"]),
        )
        try:
            defaults["translated_short_merge_threshold"] = int(
                raw.get("translated_short_merge_threshold") or defaults["translated_short_merge_threshold"]
            )
        except (TypeError, ValueError):
            pass
        defaults["dub_audio_leveling_enabled"] = _coerce_bool(
            raw.get("dub_audio_leveling_enabled"),
            default=bool(defaults["dub_audio_leveling_enabled"]),
        )
        for key in (
            "dub_audio_leveling_target_rms",
            "dub_audio_leveling_activity_threshold_db",
            "dub_audio_leveling_max_gain_db",
            "dub_audio_leveling_peak_ceiling",
        ):
            try:
                defaults[key] = float(raw.get(key) or defaults[key])
            except (TypeError, ValueError):
                pass
        defaults["dubbing_mode"] = str(raw.get("dubbing_mode") or defaults["dubbing_mode"])
        defaults["rewrite_translation"] = _coerce_bool(raw.get("rewrite_translation"), default=True)
        defaults["tts_backend"] = "index-tts"
        defaults["single_ref_audio"] = str(raw.get("single_ref_audio") or defaults["single_ref_audio"])
        defaults["single_ref_text"] = str(raw.get("single_ref_text") or defaults["single_ref_text"])
        defaults["speaker_ref_map"] = list(raw.get("speaker_ref_map") or defaults["speaker_ref_map"])
        defaults["translate_system_prompt"] = str(raw.get("translate_system_prompt") or defaults["translate_system_prompt"])
        defaults["tts_model_path"] = str(raw.get("tts_model_path") or defaults["tts_model_path"])
        defaults["index_tts_api_url"] = str(raw.get("index_tts_api_url") or defaults["index_tts_api_url"])
        break
    return defaults


def _artifact_url(task_id: str, key: str) -> str:
    return f"/dubbing/auto/artifact/{task_id}/{key}"


def _check_index_tts_service(api_url: str, timeout_sec: float = 2.0) -> None:
    url = api_url.rstrip("/") + "/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"index-tts service unavailable: {exc}. Run ./start_index_tts_api.sh first.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"index-tts health check failed: {exc}. Run ./start_index_tts_api.sh first.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise HTTPException(
            status_code=503,
            detail=f"index-tts service unhealthy: {payload}. Run ./start_index_tts_api.sh first.",
        )


def _auto_start_local_index_tts(api_url: str) -> None:
    normalized = api_url.rstrip("/")
    if normalized != DEFAULT_INDEX_TTS_API_URL:
        return
    if not INDEX_TTS_START_SCRIPT.exists():
        return

    proc = subprocess.run(
        [str(INDEX_TTS_START_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "unknown error"
        raise HTTPException(
            status_code=503,
            detail=f"index-tts auto-start failed: {details}. Run ./start_index_tts_api.sh manually.",
        )


def _ensure_index_tts_service(api_url: str) -> None:
    try:
        _check_index_tts_service(api_url)
    except HTTPException as exc:
        _auto_start_local_index_tts(api_url)
        try:
            _check_index_tts_service(api_url)
        except HTTPException:
            raise exc


def _switch_tts_runtime_on_demand(
    *,
    tts_backend: str,
    index_tts_api_url: str,
) -> None:
    """Auto Dubbing 现阶段固定只保 index-tts 运行时。"""

    del tts_backend
    _ensure_index_tts_service(index_tts_api_url)


def _build_artifacts(task_id: str, manifest_path: Path) -> List[Dict[str, str]]:
    return build_batch_artifacts(
        task_id=task_id,
        manifest_path=manifest_path,
        artifact_url_builder=_artifact_url,
    )


def _complete_task_from_manifest(task_id: str, manifest_path: Path) -> None:
    updates = build_batch_task_updates(
        task_id=task_id,
        manifest_path=manifest_path,
        artifact_url_builder=_artifact_url,
    )
    task = _task_store.get(task_id)
    if task is None:
        loaded = build_loaded_batch_task(
            task_id=task_id,
            manifest_path=manifest_path,
            created_at=_iso_now(),
            default_short_merge_threshold=DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
            default_index_tts_api_url=DEFAULT_INDEX_TTS_API_URL,
            artifact_url_builder=_artifact_url,
        )
        _task_store.create(task_id, loaded)
        return
    _set_task(task_id, **updates)


def _run_cli_task(task_id: str, cmd: List[str], env: Dict[str, str], out_root: Path) -> None:
    stdout_log = out_root / "web_cli_stdout.log"
    _set_task(task_id, status="running", stage="queued", progress=2.0, stdout_log=str(stdout_log))
    try:
        with stdout_log.open("a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            _set_task(task_id, process=proc, pid=proc.pid)
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                log_handle.write(line + "\n")
                log_handle.flush()
                _append_stdout(task_id, line)
                _update_from_stdout(task_id, line)

            code = proc.wait()

        task = _task_store.get(task_id)
        if task and task.get("status") == "cancelled":
            return

        if code != 0:
            task = _task_store.get_copy(task_id) or {}
            stdout_tail = list(task.get("stdout_tail", []))
            _set_task(
                task_id,
                status="failed",
                stage="failed",
                progress=100.0,
                error=_build_cli_exit_error(code, stdout_tail),
                exit_code=code,
            )
            return

        manifest_path = _find_batch_manifest(out_root)
        if not manifest_path:
            _set_task(
                task_id,
                status="failed",
                stage="failed",
                progress=100.0,
                error="CLI completed but batch_manifest.json was not found",
                exit_code=code,
            )
            return

        _complete_task_from_manifest(task_id, manifest_path)
        _set_task(task_id, exit_code=code)
    except BaseException as exc:
        _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))
    finally:
        _set_task(task_id, process=None)


@router.post("/start")
async def start_auto_dubbing(
    video: UploadFile = File(...),
    subtitle_file: Optional[UploadFile] = File(None),
    single_ref_audio_file: Optional[UploadFile] = File(None),
    speaker_ref_files: List[UploadFile] = File([]),
    speaker_ref_speaker_ids_json: str = Form(""),
    single_ref_text: str = Form(""),
    speaker_ref_texts_json: str = Form(""),
    subtitle_mode: str = Form("source"),
    dubbing_mode: str = Form("single"),
    source_lang: str = Form("auto"),
    target_lang: str = Form(...),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
    tts_backend: str = Form("index-tts"),
    tts_model_path: str = Form(""),
    single_ref_audio: str = Form(""),
    speaker_ref_map_json: str = Form(""),
    index_tts_api_url: str = Form(DEFAULT_INDEX_TTS_API_URL),
    segment_minutes: float = Form(8.0),
    min_segment_minutes: float = Form(4.0),
    timing_mode: str = Form("strict"),
    grouping_strategy: str = Form("sentence"),
    short_merge_enabled: str = Form("false"),
    short_merge_threshold: int = Form(DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC),
    translated_short_merge_enabled: str = Form("false"),
    translated_short_merge_threshold: int = Form(DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC),
    time_ranges: str = Form(""),
    rewrite_translation: str = Form("true"),
):
    task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(video.filename or "input_media")
    input_path = upload_dir / filename
    with input_path.open("wb") as handle:
        shutil.copyfileobj(video.file, handle)
    input_srt_path: Optional[Path] = None
    if subtitle_file is not None and subtitle_file.filename:
        subtitle_name = _sanitize_filename(subtitle_file.filename)
        suffix = Path(subtitle_name).suffix.lower()
        raw_bytes = subtitle_file.file.read()
        if suffix == ".srt":
            input_srt_path = upload_dir / f"manual_{subtitle_name}"
            input_srt_path.write_bytes(raw_bytes)
        elif suffix == ".vtt":
            try:
                vtt_text = raw_bytes.decode("utf-8-sig")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid subtitle_file encoding: {exc}") from exc
            srt_text = _convert_vtt_to_srt_text(vtt_text)
            srt_name = f"{Path(subtitle_name).stem}.srt"
            input_srt_path = upload_dir / f"manual_{srt_name}"
            input_srt_path.write_text(srt_text, encoding="utf-8")
        elif suffix == ".md":
            try:
                markdown_text = raw_bytes.decode("utf-8-sig")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid subtitle_file encoding: {exc}") from exc
            srt_text = _convert_markdown_timeline_to_srt_text(markdown_text)
            srt_name = f"{Path(subtitle_name).stem}.srt"
            input_srt_path = upload_dir / f"manual_{srt_name}"
            input_srt_path.write_text(srt_text, encoding="utf-8")
        else:
            raise HTTPException(status_code=400, detail="subtitle_file must be .srt, .vtt or .md")
    if input_srt_path is None:
        raise HTTPException(status_code=400, detail="Auto dubbing requires subtitle_file (.srt/.vtt/.md)")
    detected_speaker_ids: List[str] = []
    if input_srt_path is not None:
        parsed_subtitles = parse_srt(input_srt_path.read_text(encoding="utf-8"))
        _, detected_speaker_ids = normalize_subtitles_with_speakers(parsed_subtitles)
    normalized_single_ref_audio = str(single_ref_audio or "").strip()
    normalized_single_ref_text = str(single_ref_text or "").strip()
    if single_ref_audio_file is not None and single_ref_audio_file.filename:
        normalized_single_ref_audio = _store_uploaded_reference_file(
            upload_dir=upload_dir,
            file=single_ref_audio_file,
            fallback_name="single_ref_audio.wav",
        )
    normalized_speaker_ref_map_json = speaker_ref_map_json
    if speaker_ref_speaker_ids_json.strip():
        try:
            speaker_ids_payload = json.loads(speaker_ref_speaker_ids_json)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_speaker_ids_json: {exc}") from exc
        if not isinstance(speaker_ids_payload, list):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json must be a list")
        if len(speaker_ids_payload) != len(speaker_ref_files):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json count must match speaker_ref_files")
        try:
            speaker_texts_payload = json.loads(speaker_ref_texts_json) if speaker_ref_texts_json.strip() else {}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_texts_json: {exc}") from exc
        if speaker_ref_texts_json.strip() and not isinstance(speaker_texts_payload, dict):
            raise HTTPException(status_code=400, detail="speaker_ref_texts_json must be an object")
        speaker_file_specs: List[Dict[str, str]] = []
        for speaker_id, ref_file in zip(speaker_ids_payload, speaker_ref_files):
            stored_path = _store_uploaded_reference_file(
                upload_dir=upload_dir,
                file=ref_file,
                fallback_name=f"{_sanitize_filename(str(speaker_id)) or 'speaker'}_ref.wav",
            )
            if not stored_path:
                continue
            speaker_file_specs.append(
                {
                    "speaker_id": str(speaker_id or "").strip(),
                    "ref_audio_path": stored_path,
                    "ref_text": str(speaker_texts_payload.get(str(speaker_id or "").strip()) or "").strip(),
                }
            )
        normalized_speaker_ref_map_json = json.dumps(speaker_file_specs, ensure_ascii=False)

    normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json = _collapse_single_reference_payload(
        single_ref_audio=normalized_single_ref_audio,
        single_ref_text=normalized_single_ref_text,
        speaker_ref_map_json=normalized_speaker_ref_map_json,
    )
    reference_mode_hint = "single" if normalized_single_ref_audio else ("multi" if normalized_speaker_ref_map_json.strip() else "auto")
    if input_srt_path is not None:
        subtitle_items = parse_srt(input_srt_path.read_text(encoding="utf-8"))
        subtitle_items, _ = normalize_subtitles_with_speakers(subtitle_items)
    subtitle_items = optimize_srt_import_subtitles(subtitle_items, speaker_mode=reference_mode_hint)
    if not subtitle_items:
        raise HTTPException(status_code=400, detail="Auto dubbing requires subtitle_file with valid subtitles")
    input_srt_path.write_text(format_srt(subtitle_items), encoding="utf-8")

    options = _normalize_auto_dubbing_request(
        subtitle_mode=subtitle_mode,
        dubbing_mode=dubbing_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        api_key=api_key,
        translate_base_url=translate_base_url,
        translate_model=translate_model,
        translate_system_prompt=translate_system_prompt,
        tts_backend=tts_backend,
        tts_model_path=tts_model_path,
        single_ref_audio=normalized_single_ref_audio,
        single_ref_text=normalized_single_ref_text,
        speaker_ref_map_json=normalized_speaker_ref_map_json,
        detected_speaker_ids=detected_speaker_ids,
        index_tts_api_url=index_tts_api_url,
        segment_minutes=segment_minutes,
        min_segment_minutes=min_segment_minutes,
        timing_mode=timing_mode,
        grouping_strategy=grouping_strategy,
        short_merge_enabled=short_merge_enabled,
        short_merge_threshold=short_merge_threshold,
        translated_short_merge_enabled=translated_short_merge_enabled,
        translated_short_merge_threshold=translated_short_merge_threshold,
        time_ranges=time_ranges,
        rewrite_translation=rewrite_translation,
        has_subtitle_input=input_srt_path is not None,
    )
    return _queue_auto_dubbing_task(
        task_id=task_id,
        filename=filename,
        input_path=input_path,
        input_srt_path=input_srt_path,
        input_speaker_metadata_path=None,
        options=options,
    )


@router.post("/start-from-project")
async def start_auto_dubbing_from_project(
    filename: str = Form(""),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    subtitles_json: str = Form(""),
    single_ref_audio_file: Optional[UploadFile] = File(None),
    speaker_ref_files: List[UploadFile] = File([]),
    speaker_ref_speaker_ids_json: str = Form(""),
    single_ref_text: str = Form(""),
    speaker_ref_texts_json: str = Form(""),
    subtitle_mode: str = Form("source"),
    dubbing_mode: str = Form("single"),
    source_lang: str = Form("auto"),
    target_lang: str = Form(...),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
    tts_backend: str = Form("index-tts"),
    tts_model_path: str = Form(""),
    single_ref_audio: str = Form(""),
    speaker_ref_map_json: str = Form(""),
    index_tts_api_url: str = Form(DEFAULT_INDEX_TTS_API_URL),
    segment_minutes: float = Form(8.0),
    min_segment_minutes: float = Form(4.0),
    timing_mode: str = Form("strict"),
    grouping_strategy: str = Form("sentence"),
    short_merge_enabled: str = Form("false"),
    short_merge_threshold: int = Form(DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC),
    translated_short_merge_enabled: str = Form("false"),
    translated_short_merge_threshold: int = Form(DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC),
    time_ranges: str = Form(""),
    rewrite_translation: str = Form("true"),
):
    """基于主 workflow 当前项目状态启动 Auto Dubbing，避免前端重新上传同一份媒体。"""

    readable_task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / readable_task_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    source_media_path = _resolve_project_media_path(filename, task_id)
    display_name = _sanitize_filename(original_filename or source_media_path.name)
    # Current Project 模式直接复用原始上传媒体，避免在 uploads/dubbing 下重复拷贝整段视频。
    input_path = source_media_path.resolve()
    normalized_subtitles: List[Dict[str, Any]] = []
    if subtitles_json.strip():
        try:
            parsed_subtitles_payload = json.loads(subtitles_json)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid subtitles_json: {exc}") from exc
        if not isinstance(parsed_subtitles_payload, list):
            raise HTTPException(status_code=400, detail="Invalid subtitles_json: must be a list")
        for item in parsed_subtitles_payload:
            if not isinstance(item, dict):
                continue
            start_sec = item.get("start", item.get("start_sec"))
            end_sec = item.get("end", item.get("end_sec"))
            text = str(item.get("text", "") or "").strip()
            if start_sec is None or end_sec is None or not text:
                continue
            try:
                start_value = float(start_sec)
                end_value = float(end_sec)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid subtitles_json timing: {exc}") from exc
            if end_value <= start_value:
                continue
            normalized_subtitles.append(
                {
                    "start": start_value,
                    "end": end_value,
                    "text": text,
                    "speaker_id": str(item.get("speaker_id") or "").strip(),
                }
            )
    normalized_subtitles, _ = normalize_subtitles_with_speakers(normalized_subtitles)
    if not normalized_subtitles:
        raise HTTPException(status_code=400, detail="Auto dubbing requires subtitles_json from current project")

    normalized_single_ref_audio = str(single_ref_audio or "").strip()
    normalized_single_ref_text = str(single_ref_text or "").strip()
    if single_ref_audio_file is not None and single_ref_audio_file.filename:
        normalized_single_ref_audio = _store_uploaded_reference_file(
            upload_dir=upload_dir,
            file=single_ref_audio_file,
            fallback_name="single_ref_audio.wav",
        )
    normalized_speaker_ref_map_json = speaker_ref_map_json
    if speaker_ref_speaker_ids_json.strip():
        try:
            speaker_ids_payload = json.loads(speaker_ref_speaker_ids_json)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_speaker_ids_json: {exc}") from exc
        if not isinstance(speaker_ids_payload, list):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json must be a list")
        if len(speaker_ids_payload) != len(speaker_ref_files):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json count must match speaker_ref_files")
        try:
            speaker_texts_payload = json.loads(speaker_ref_texts_json) if speaker_ref_texts_json.strip() else {}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_texts_json: {exc}") from exc
        if speaker_ref_texts_json.strip() and not isinstance(speaker_texts_payload, dict):
            raise HTTPException(status_code=400, detail="speaker_ref_texts_json must be an object")
        speaker_file_specs: List[Dict[str, str]] = []
        for speaker_id, ref_file in zip(speaker_ids_payload, speaker_ref_files):
            stored_path = _store_uploaded_reference_file(
                upload_dir=upload_dir,
                file=ref_file,
                fallback_name=f"{_sanitize_filename(str(speaker_id)) or 'speaker'}_ref.wav",
            )
            if not stored_path:
                continue
            speaker_file_specs.append(
                {
                    "speaker_id": str(speaker_id or "").strip(),
                    "ref_audio_path": stored_path,
                    "ref_text": str(speaker_texts_payload.get(str(speaker_id or "").strip()) or "").strip(),
                }
            )
        if len(speaker_file_specs) == 1 and not normalized_single_ref_audio:
            normalized_single_ref_audio = str(speaker_file_specs[0].get("ref_audio_path") or "").strip()
            normalized_single_ref_text = normalized_single_ref_text or str(speaker_file_specs[0].get("ref_text") or "").strip()
            normalized_speaker_ref_map_json = ""
        else:
            normalized_speaker_ref_map_json = json.dumps(speaker_file_specs, ensure_ascii=False)

    normalized_single_ref_audio, normalized_single_ref_text, normalized_speaker_ref_map_json = _collapse_single_reference_payload(
        single_ref_audio=normalized_single_ref_audio,
        single_ref_text=normalized_single_ref_text,
        speaker_ref_map_json=normalized_speaker_ref_map_json,
    )
    reference_mode_hint = "single" if normalized_single_ref_audio else ("multi" if normalized_speaker_ref_map_json.strip() else "auto")

    input_srt_path = upload_dir / f"project_{subtitle_mode}.srt"
    subtitle_items = optimize_srt_import_subtitles(normalized_subtitles, speaker_mode=reference_mode_hint)
    input_srt_path.write_text(format_srt(subtitle_items), encoding="utf-8")
    detected_speaker_ids = sorted(
        {
            str(item.get("speaker_id") or "").strip()
            for item in subtitle_items
            if str(item.get("speaker_id") or "").strip()
        }
    )

    input_speaker_metadata_path: Optional[Path] = None
    segment_speaker_metadata = build_segment_speaker_metadata_from_subtitles(subtitle_items)
    if segment_speaker_metadata:
        input_speaker_metadata_path = input_srt_path.parent / "_input_project.speakers.json"
        input_speaker_metadata_path.write_text(
            json.dumps(segment_speaker_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    options = _normalize_auto_dubbing_request(
        subtitle_mode=subtitle_mode,
        dubbing_mode=dubbing_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        api_key=api_key,
        translate_base_url=translate_base_url,
        translate_model=translate_model,
        translate_system_prompt=translate_system_prompt,
        tts_backend=tts_backend,
        tts_model_path=tts_model_path,
        single_ref_audio=normalized_single_ref_audio,
        single_ref_text=normalized_single_ref_text,
        speaker_ref_map_json=normalized_speaker_ref_map_json,
        detected_speaker_ids=detected_speaker_ids,
        index_tts_api_url=index_tts_api_url,
        segment_minutes=segment_minutes,
        min_segment_minutes=min_segment_minutes,
        timing_mode=timing_mode,
        grouping_strategy=grouping_strategy,
        short_merge_enabled=short_merge_enabled,
        short_merge_threshold=short_merge_threshold,
        translated_short_merge_enabled=translated_short_merge_enabled,
        translated_short_merge_threshold=translated_short_merge_threshold,
        time_ranges=time_ranges,
        rewrite_translation=rewrite_translation,
        has_subtitle_input=input_srt_path is not None,
    )
    response = _queue_auto_dubbing_task(
        task_id=readable_task_id,
        filename=input_path.name,
        input_path=input_path,
        input_srt_path=input_srt_path,
        input_speaker_metadata_path=input_speaker_metadata_path,
        options=options,
    )
    response["project_filename"] = source_media_path.name
    return response


@router.post("/load-batch")
async def load_auto_dubbing_batch(batch_id: str = Form(...)):
    # 通过 longdub 文件夹名恢复历史任务状态与下载入口（页面刷新后可继续查看结果）。
    manifest_path = _find_batch_manifest_by_name(batch_id)
    if manifest_path is None:
        batch_dir = _find_batch_dir_by_name(batch_id)
        if batch_dir is None:
            raise HTTPException(status_code=404, detail="Batch folder not found")

        task_id = _build_readable_task_id()
        inferred = _infer_incomplete_batch_task_fields(batch_dir)
        task = {
            "id": task_id,
            "short_id": task_id.split("-")[0],
            "status": "failed",
            "stage": "failed",
            "progress": 100.0,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "source_lang": inferred["source_lang"],
            "target_lang": inferred["target_lang"],
            "subtitle_mode": inferred["subtitle_mode"],
            "segment_minutes": inferred["segment_minutes"],
            "min_segment_minutes": inferred["min_segment_minutes"],
            "timing_mode": inferred["timing_mode"],
            "grouping_strategy": inferred["grouping_strategy"],
            "source_short_merge_enabled": inferred["source_short_merge_enabled"],
            "source_short_merge_threshold": inferred["source_short_merge_threshold"],
            "source_short_merge_threshold_mode": "seconds",
            "translated_short_merge_enabled": inferred["translated_short_merge_enabled"],
            "translated_short_merge_threshold": inferred["translated_short_merge_threshold"],
            "translated_short_merge_threshold_mode": "seconds",
            "dub_audio_leveling_enabled": inferred["dub_audio_leveling_enabled"],
            "dub_audio_leveling_target_rms": inferred["dub_audio_leveling_target_rms"],
            "dub_audio_leveling_activity_threshold_db": inferred["dub_audio_leveling_activity_threshold_db"],
            "dub_audio_leveling_max_gain_db": inferred["dub_audio_leveling_max_gain_db"],
            "dub_audio_leveling_peak_ceiling": inferred["dub_audio_leveling_peak_ceiling"],
            "translate_base_url": inferred["translate_base_url"],
            "translate_model": inferred["translate_model"],
            "translate_system_prompt": inferred["translate_system_prompt"],
            "dubbing_mode": inferred["dubbing_mode"],
            "tts_backend": inferred["tts_backend"],
            "single_ref_audio": inferred["single_ref_audio"],
            "speaker_ref_map": inferred["speaker_ref_map"],
            "index_tts_api_url": inferred["index_tts_api_url"],
            "time_ranges": inferred["time_ranges"],
            "rewrite_translation": inferred["rewrite_translation"],
            "processed_segments": 0,
            "total_segments": None,
            "manual_review_segments": 0,
            "artifacts": [],
            "stdout_tail": [],
            "filename": inferred["filename"] or batch_dir.name,
            "input_path": inferred["input_path"],
            "input_srt": inferred["input_srt"],
            "upload_dir": str(UPLOAD_ROOT),
            "out_root": str(batch_dir.parent),
            "resume_batch_dir": str(batch_dir),
            "batch_id": batch_dir.name,
            "batch_manifest_path": None,
            "error": "Batch manifest missing: loaded as interrupted job. Use '从失败处继续' to resume.",
            "command": [],
            "process": None,
        }
        _task_store.create(task_id, task)
        loaded = _task_store.get_public(task_id)
        if not loaded:
            raise HTTPException(status_code=500, detail="Failed to load interrupted batch")
        return loaded

    task_id = _build_readable_task_id()
    task = build_loaded_batch_task(
        task_id=task_id,
        manifest_path=manifest_path,
        created_at=_iso_now(),
        default_short_merge_threshold=DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC,
        default_index_tts_api_url=DEFAULT_INDEX_TTS_API_URL,
        artifact_url_builder=_artifact_url,
    )
    _task_store.create(task_id, task)

    loaded = _task_store.get_public(task_id)
    if not loaded:
        raise HTTPException(status_code=500, detail="Failed to load batch result")
    return loaded


@router.get("/batches")
async def list_auto_dubbing_batches(limit: int = 200):
    # 返回可加载的批次列表，前端用于“选择文件夹”下拉框。
    safe_limit = max(1, min(int(limit), 500))
    return {"batches": _list_available_batches(limit=safe_limit)}


@router.get("/status/{task_id}")
async def get_auto_dubbing_status(task_id: str):
    task = _task_store.get_public(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Dubbing task not found")
    return task


@router.post("/resume/{task_id}")
async def resume_auto_dubbing(task_id: str, api_key: str = Form("")):
    # 失败/取消任务从既有 batch 断点续跑：复用 segment 目录与 CLI resume 机制。
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")

    task_status = str(task_copy.get("status") or "").strip().lower()
    if task_status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed/cancelled tasks can be resumed")

    active_ids = [active_id for active_id in _task_store.list_active_ids() if active_id != task_id]
    if active_ids:
        raise HTTPException(status_code=409, detail="Another auto dubbing job is already running")

    resume_batch_dir = _resolve_resume_batch_dir(task_copy)
    resume_out_root = _resolve_resume_out_root(task_copy, resume_batch_dir=resume_batch_dir)
    input_path = _resolve_resume_input_media(task_copy, resume_batch_dir=resume_batch_dir)
    input_srt_path = _resolve_resume_input_srt(task_copy)
    options = _build_resume_options(
        task=task_copy,
        resume_batch_dir=resume_batch_dir,
        api_key=api_key,
        has_subtitle_input=input_srt_path is not None,
    )
    resumed_task_id = _build_readable_task_id()
    response = _queue_auto_dubbing_task(
        task_id=resumed_task_id,
        filename=Path(str(task_copy.get("filename") or input_path.name)).name,
        input_path=input_path,
        input_srt_path=input_srt_path,
        input_speaker_metadata_path=None,
        options=options,
        resume_batch_dir=resume_batch_dir,
        out_root_override=resume_out_root,
    )
    response["resumed_from_task_id"] = task_id
    response["resume_batch_id"] = resume_batch_dir.name
    return response


@router.get("/review/{task_id}")
async def get_auto_dubbing_review_lines(task_id: str):
    # 返回可逐句审阅的翻译列表（来自 batch + segment manifest）。
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")
    manifest_path = _resolve_task_manifest(task_copy)
    lines = _collect_review_lines(manifest_path)
    return {"task_id": task_id, "total": len(lines), "lines": lines}


@router.post("/review/{task_id}/save")
async def save_auto_dubbing_review_lines(task_id: str, edits_json: str = Form(...)):
    # 保存逐句审阅结果，写回 final 目录字幕文件。
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")

    manifest_path = _resolve_task_manifest(task_copy)
    try:
        payload = json.loads(edits_json or "[]")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid edits_json: {exc}") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Invalid edits_json: must be list")

    updates: Dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        index = int(item.get("index", 0) or 0)
        text = str(item.get("translated_text", "") or "").strip()
        if index <= 0:
            continue
        updates[index] = text
    if not updates:
        return {"status": "no_changes"}
    updates = _filter_effective_review_updates(manifest_path, updates)
    if not updates:
        return {"status": "no_changes"}

    written = _persist_review_lines(manifest_path, updates)
    return {"status": "saved", "updated_count": len(updates), "written": written}


@router.post("/review/{task_id}/save-and-redub")
async def save_and_redub_review_lines(
    task_id: str,
    edits_json: str = Form(...),
):
    # 保存逐句修改后，一气呵成执行“局部重配 + final 重拼”。
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")

    manifest_path = _resolve_task_manifest(task_copy)
    try:
        payload = json.loads(edits_json or "[]")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid edits_json: {exc}") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Invalid edits_json: must be list")

    updates: Dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        index = int(item.get("index", 0) or 0)
        text = str(item.get("translated_text", "") or "").strip()
        if index <= 0:
            continue
        updates[index] = text
    if not updates:
        return {"status": "no_changes"}
    updates = _filter_effective_review_updates(manifest_path, updates)
    if not updates:
        return {"status": "no_changes"}
    _set_task(task_id, status="running", stage="dubbing:review_redub", progress=35.0)
    return _execute_review_redub(
        task_id=task_id,
        task_copy=task_copy,
        manifest_path=manifest_path,
        text_updates=updates,
    )


@router.post("/review/{task_id}/redub-failed")
async def force_redub_failed_review_lines(task_id: str):
    # 保持当前 translated.srt 不变，只对 missing/manual_review 候选句触发局部重配。
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")

    manifest_path = _resolve_task_manifest(task_copy)
    force_indices = set(_collect_force_redub_review_indices(manifest_path))
    if not force_indices:
        return {"status": "no_candidates", "forced_line_count": 0}
    _set_task(task_id, status="running", stage="dubbing:review_redub", progress=35.0)
    return _execute_review_redub(
        task_id=task_id,
        task_copy=task_copy,
        manifest_path=manifest_path,
        text_updates={},
        force_global_indices=force_indices,
    )


@router.post("/cancel/{task_id}")
async def cancel_auto_dubbing(task_id: str):
    cancelled = _cancel_task(task_id, "Cancelled by user")
    if not cancelled:
        raise HTTPException(status_code=404, detail="Dubbing task not found or already finished")
    return {"status": "cancelled"}


def _resolve_artifact(task: Dict[str, Any], artifact: str) -> Path:
    manifest_path_text = task.get("batch_manifest_path")
    if not manifest_path_text:
        if artifact == "stdout" and task.get("stdout_log"):
            path = Path(task["stdout_log"]).resolve()
            out_root = Path(task["out_root"]).resolve()
            try:
                path.relative_to(out_root)
            except ValueError as exc:
                raise HTTPException(status_code=403, detail="Artifact path is outside task output") from exc
            if not path.exists():
                raise HTTPException(status_code=404, detail="Artifact file not found")
            return path
        raise HTTPException(status_code=404, detail="Artifacts are not ready yet")

    manifest_path = Path(manifest_path_text).resolve()
    manifest = load_batch_manifest(manifest_path)
    paths = manifest.paths
    resolved_input_media = _resolve_preferred_batch_input_media(
        batch_dir=manifest_path.parent,
        manifest_input_path=manifest.input_media_path,
    )
    key_to_path = {
        "input_media": str(resolved_input_media) if resolved_input_media is not None else manifest.input_media_path,
        "preferred_audio": paths.get("preferred_audio"),
        "video": paths.get("dubbed_video_full"),
        "mix": paths.get("dubbed_mix_full"),
        "vocals": paths.get("dubbed_vocals_full"),
        "bgm": paths.get("source_bgm_full"),
        "source_srt": paths.get("source_full_srt"),
        "translated_srt": paths.get("translated_full_srt"),
        "bilingual_srt": paths.get("dubbed_final_full_srt"),
        "manifest": str(manifest_path),
        "stdout": task.get("stdout_log"),
    }
    path_text = key_to_path.get(artifact)
    if not path_text:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(path_text).expanduser().resolve()
    out_root = Path(task["out_root"]).resolve()
    upload_root = UPLOAD_ROOT.resolve()
    try:
        path.relative_to(out_root)
    except ValueError:
        try:
            path.relative_to(upload_root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Artifact path is outside task output") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return path


def _resolve_task_manifest(task: Dict[str, Any]) -> Path:
    # 解析任务关联的 batch_manifest 路径并校验存在性。
    manifest_path_text = task.get("batch_manifest_path")
    if not manifest_path_text:
        raise HTTPException(status_code=404, detail="Batch manifest not ready")
    manifest_path = Path(str(manifest_path_text)).expanduser().resolve()
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Batch manifest not found")
    return manifest_path


def _collect_review_lines(manifest_path: Path) -> List[Dict[str, Any]]:
    # 收集逐句 review 数据：按全局时间轴输出 source/translated/质量指标。
    # 关键修复：
    # - translated_text 优先使用 final/translated_full.srt（用户真正看到和修改的文本）
    # - source_text 优先使用 final/source_full.srt（避免 segment manifest 历史字段漂移）
    # 这样可避免“审阅界面加载成源字幕”的错读问题。
    batch_manifest = load_batch_manifest(manifest_path)
    lines: List[Dict[str, Any]] = []
    line_index = 1
    for segment in batch_manifest.segments:
        segment_start = float(segment.get("start_sec", 0.0) or 0.0)
        job_dir = Path(str(segment.get("job_dir") or "")).expanduser()
        segment_manifest_path = job_dir / "manifest.json"
        if not segment_manifest_path.exists():
            continue
        segment_manifest = load_segment_manifest(segment_manifest_path)
        for row in segment_manifest.segment_rows:
            start_local = float(row.get("start_sec", 0.0) or 0.0)
            end_local = float(row.get("end_sec", start_local) or start_local)
            tts_audio_path = str(row.get("tts_audio_path") or "")
            needs_force_redub = _segment_row_needs_force_redub(row)
            lines.append(
                {
                    "index": line_index,
                    "segment_id": row.get("id"),
                    "start_sec": round(segment_start + start_local, 3),
                    "end_sec": round(segment_start + end_local, 3),
                    "source_text": row.get("source_text") or "",
                    "translated_text": row.get("translated_text") or "",
                    "status": row.get("status") or "unknown",
                    "duration_error_ratio": row.get("duration_error_ratio"),
                    "prosody_distance": row.get("prosody_distance"),
                    "selection_score": row.get("selection_score"),
                    "tts_audio_path": tts_audio_path,
                    "tts_audio_missing": tts_audio_path.endswith("_missing.wav"),
                    "needs_force_redub": needs_force_redub,
                }
            )
            line_index += 1
    lines.sort(key=lambda item: (float(item.get("start_sec", 0.0) or 0.0), int(item.get("index", 0) or 0)))
    for idx, item in enumerate(lines, start=1):
        item["index"] = idx

    # 使用 final 字幕文件覆盖文本字段，确保审阅数据与最终产物一致。
    paths = batch_manifest.paths
    translated_path_text = paths.get("translated_full_srt")
    source_path_text = paths.get("source_full_srt")

    if translated_path_text:
        try:
            translated_path = Path(str(translated_path_text)).expanduser().resolve()
            if translated_path.exists():
                translated_items = parse_srt(translated_path.read_text(encoding="utf-8"))
                for idx, item in enumerate(lines, start=1):
                    if idx <= len(translated_items):
                        item["translated_text"] = str(translated_items[idx - 1].get("text") or "")
        except Exception:
            # 容错：final 文件异常时回退 segment manifest 文本。
            pass

    if source_path_text:
        try:
            source_path = Path(str(source_path_text)).expanduser().resolve()
            if source_path.exists():
                source_items = parse_srt(source_path.read_text(encoding="utf-8"))
                for idx, item in enumerate(lines, start=1):
                    if idx <= len(source_items):
                        item["source_text"] = str(source_items[idx - 1].get("text") or "")
        except Exception:
            # 容错：source 文件异常时保留已有字段。
            pass

    return lines


def _segment_row_needs_force_redub(row: Dict[str, Any]) -> bool:
    # 判断该行是否属于“保留现有译文也应该强制重配”的候选。
    status = str(row.get("status") or "").strip().lower()
    tts_audio_path_text = str(row.get("tts_audio_path") or "").strip()
    if tts_audio_path_text.endswith("_missing.wav"):
        return True
    if status == "failed":
        return True
    if status != "manual_review":
        return False
    if not tts_audio_path_text:
        return True
    try:
        return not Path(tts_audio_path_text).expanduser().exists()
    except Exception:
        return True


def _collect_force_redub_review_indices(manifest_path: Path) -> List[int]:
    # 从 batch/segment manifest 中找出需要“原文不变重配”的全局行号。
    batch_manifest = load_batch_manifest(manifest_path)
    indices: List[int] = []
    global_index = 1
    for segment in batch_manifest.segments:
        job_dir = Path(str(segment.get("job_dir") or "")).expanduser()
        segment_manifest_path = job_dir / "manifest.json"
        if not segment_manifest_path.exists():
            continue
        segment_manifest = load_segment_manifest(segment_manifest_path)
        for row in segment_manifest.segment_rows:
            if _segment_row_needs_force_redub(row):
                indices.append(global_index)
            global_index += 1
    return indices


def _persist_review_lines(manifest_path: Path, updates: Dict[int, str]) -> Dict[str, Optional[str]]:
    # 将逐句审阅文本写回 translated_full.srt / dubbed_final_full.srt。
    batch_manifest = load_batch_manifest(manifest_path)
    paths = batch_manifest.paths
    translated_path_text = paths.get("translated_full_srt")
    bilingual_path_text = paths.get("dubbed_final_full_srt")
    source_path_text = paths.get("source_full_srt")

    translated_path = Path(str(translated_path_text)).expanduser().resolve() if translated_path_text else None
    bilingual_path = Path(str(bilingual_path_text)).expanduser().resolve() if bilingual_path_text else None
    source_path = Path(str(source_path_text)).expanduser().resolve() if source_path_text else None

    if translated_path is None or not translated_path.exists():
        raise HTTPException(status_code=404, detail="translated_full.srt not found")

    translated_items = parse_srt(translated_path.read_text(encoding="utf-8"))
    for idx, item in enumerate(translated_items, start=1):
        if idx in updates:
            item["text"] = updates[idx]
    translated_path.write_text(format_srt(translated_items), encoding="utf-8")

    if bilingual_path is not None and bilingual_path.exists() and source_path is not None and source_path.exists():
        source_items = parse_srt(source_path.read_text(encoding="utf-8"))
        if len(source_items) == len(translated_items):
            bilingual_items: List[Dict[str, Any]] = []
            for src, tgt in zip(source_items, translated_items):
                src_text = (src.get("text") or "").strip()
                tgt_text = (tgt.get("text") or "").strip()
                text = tgt_text if not src_text else f"{tgt_text}\n{src_text}"
                bilingual_items.append(
                    {
                        "start": float(tgt.get("start", 0.0) or 0.0),
                        "end": float(tgt.get("end", 0.0) or 0.0),
                        "text": text,
                    }
                )
            bilingual_path.write_text(format_srt(bilingual_items), encoding="utf-8")

    return {
        "translated_full_srt": str(translated_path) if translated_path.exists() else None,
        "dubbed_final_full_srt": str(bilingual_path) if bilingual_path and bilingual_path.exists() else None,
    }


def _filter_effective_review_updates(manifest_path: Path, updates: Dict[int, str]) -> Dict[int, str]:
    # 仅保留“真正有变化”的字幕更新，避免保存/重配时把全量行都当作改动处理。
    if not updates:
        return {}
    batch_manifest = load_batch_manifest(manifest_path)
    translated_path_text = batch_manifest.paths.get("translated_full_srt")
    if not translated_path_text:
        return dict(updates)
    translated_path = Path(str(translated_path_text)).expanduser().resolve()
    if not translated_path.exists():
        return dict(updates)
    translated_items = parse_srt(translated_path.read_text(encoding="utf-8"))
    effective: Dict[int, str] = {}
    for index, new_text in updates.items():
        if index <= 0 or index > len(translated_items):
            continue
        old_text = str(translated_items[index - 1].get("text") or "").strip()
        next_text = str(new_text or "").strip()
        if old_text != next_text:
            effective[index] = next_text
    return effective


def _build_review_line_mapping(manifest_path: Path) -> Dict[int, Dict[str, Any]]:
    # 构建全局行号到段内行号的映射，用于“只重配改动句”。
    batch_manifest = load_batch_manifest(manifest_path)
    mapping: Dict[int, Dict[str, Any]] = {}
    global_index = 1
    for segment in batch_manifest.segments:
        segment_index = int(segment.get("index", 0) or 0)
        job_dir = Path(str(segment.get("job_dir") or "")).expanduser()
        segment_manifest_path = job_dir / "manifest.json"
        if not segment_manifest_path.exists():
            continue
        segment_manifest = load_segment_manifest(segment_manifest_path)
        rows = segment_manifest.segment_rows
        for local_index, _ in enumerate(rows, start=1):
            mapping[global_index] = {
                "segment_index": segment_index,
                "job_dir": str(job_dir),
                "local_index": local_index,
            }
            global_index += 1
    return mapping


def _build_segment_bilingual_srt(source_items: List[Dict[str, Any]], translated_items: List[Dict[str, Any]]) -> str:
    # 按“翻译在上、原文在下”重建段内双语字幕。
    merged: List[Dict[str, Any]] = []
    for source, translated in zip(source_items, translated_items):
        src_text = (source.get("text") or "").strip()
        tgt_text = (translated.get("text") or "").strip()
        text = tgt_text if not src_text else f"{tgt_text}\n{src_text}"
        merged.append(
            {
                "start": float(translated.get("start", 0.0) or 0.0),
                "end": float(translated.get("end", 0.0) or 0.0),
                "text": text,
            }
        )
    return format_srt(merged)


def _build_segment_review_redub_plan(
    manifest_path: Path,
    *,
    text_updates: Dict[int, str],
    force_global_indices: Optional[set[int]],
) -> Dict[Path, Dict[str, Any]]:
    # 把全局行号映射成段内计划，统一服务“改文案重配”和“强制重配失败句”两种入口。
    mapping = _build_review_line_mapping(manifest_path)
    segment_updates: Dict[Path, Dict[str, Any]] = {}

    for global_index, text in text_updates.items():
        item = mapping.get(global_index)
        if not item:
            continue
        segment_job_dir = Path(str(item["job_dir"])).expanduser().resolve()
        local_index = int(item["local_index"])
        entry = segment_updates.setdefault(segment_job_dir, {"text_updates": {}, "redub_local_indices": set()})
        entry["text_updates"][local_index] = text
        entry["redub_local_indices"].add(local_index)

    for global_index in sorted(force_global_indices or set()):
        item = mapping.get(global_index)
        if not item:
            continue
        segment_job_dir = Path(str(item["job_dir"])).expanduser().resolve()
        local_index = int(item["local_index"])
        entry = segment_updates.setdefault(segment_job_dir, {"text_updates": {}, "redub_local_indices": set()})
        entry["redub_local_indices"].add(local_index)

    return segment_updates


def _execute_review_redub(
    *,
    task_id: str,
    task_copy: Dict[str, Any],
    manifest_path: Path,
    text_updates: Dict[int, str],
    force_global_indices: Optional[set[int]] = None,
) -> Dict[str, Any]:
    # 统一执行 review redub 事务：可选改字幕文本，也可只重跑失败句。
    segment_updates = _build_segment_review_redub_plan(
        manifest_path,
        text_updates=text_updates,
        force_global_indices=force_global_indices,
    )
    if not segment_updates:
        return {"status": "no_candidates" if force_global_indices else "no_changes"}

    redubbed_segments = 0
    batch_manifest = load_batch_manifest(manifest_path)
    target_lang = str(task_copy.get("target_lang") or batch_manifest.options.target_lang)
    index_tts_api_url = str(task_copy.get("index_tts_api_url") or batch_manifest.options.index_tts_api_url)
    rewrite_translation = _coerce_bool(
        task_copy.get("rewrite_translation"),
        default=batch_manifest.options.rewrite_translation,
    )
    snapshot = _create_review_redub_snapshot(manifest_path=manifest_path, segment_job_dirs=list(segment_updates.keys()))

    try:
        for segment_job_dir, plan in segment_updates.items():
            local_updates = dict(plan.get("text_updates") or {})
            redub_local_indices = sorted(int(index) for index in set(plan.get("redub_local_indices") or set()))
            translated_srt_path = segment_job_dir / "subtitles" / "translated.srt"
            source_srt_path = segment_job_dir / "subtitles" / "source.srt"
            dubbed_final_srt_path = segment_job_dir / "subtitles" / "dubbed_final.srt"
            segment_manifest_path = segment_job_dir / "manifest.json"
            if not translated_srt_path.exists() or not source_srt_path.exists() or not segment_manifest_path.exists():
                continue

            translated_items = parse_srt(translated_srt_path.read_text(encoding="utf-8"))
            source_items = parse_srt(source_srt_path.read_text(encoding="utf-8"))
            if not translated_items or len(translated_items) != len(source_items):
                continue

            for local_index, new_text in local_updates.items():
                if 1 <= local_index <= len(translated_items):
                    translated_items[local_index - 1]["text"] = new_text
            if local_updates:
                translated_srt_path.write_text(format_srt(translated_items), encoding="utf-8")
                dubbed_final_srt_path.write_text(_build_segment_bilingual_srt(source_items, translated_items), encoding="utf-8")

                # 同步更新段 manifest 中的 translated_text，保持调试信息一致。
                segment_manifest = load_segment_manifest(segment_manifest_path)
                records = list(segment_manifest.segment_rows)
                for local_index, new_text in local_updates.items():
                    if 1 <= local_index <= len(records):
                        records[local_index - 1]["translated_text"] = new_text
                segment_manifest.raw["segments"] = records
                manifest_paths = dict(segment_manifest.raw.get("paths") or {})
                manifest_paths["translated_srt"] = str(translated_srt_path.resolve())
                manifest_paths["dubbed_final_srt"] = str(dubbed_final_srt_path.resolve())
                segment_manifest.raw["paths"] = manifest_paths
                write_manifest_json(segment_manifest_path, segment_manifest.raw)

            _rerun_segment_with_translated_srt(
                segment_job_dir=segment_job_dir,
                target_lang=target_lang,
                index_tts_api_url=index_tts_api_url,
                rewrite_translation=rewrite_translation,
                redub_local_indices=redub_local_indices,
            )
            redubbed_segments += 1
            # 局部进度回写：让前端状态轮询可见“重配进行中”。
            progress = min(82.0, 35.0 + 45.0 * (redubbed_segments / max(1, len(segment_updates))))
            _set_task(task_id, stage="dubbing:review_redub", progress=progress)

        # 段内重配完成后，重拼 batch final 产物并刷新任务状态。
        batch_dir = manifest_path.parent
        _set_task(task_id, stage="dubbing:merging", progress=90.0)
        _rebuild_batch_outputs(batch_dir)
        _complete_task_from_manifest(task_id, manifest_path)
        written = _collect_written_batch_paths(manifest_path)
        return {
            "status": "saved_and_redubbed" if text_updates else "forced_redubbed",
            "updated_count": len(text_updates),
            "forced_line_count": len(force_global_indices or set()),
            "redubbed_segments": redubbed_segments,
            "written": written,
        }
    except Exception as exc:
        try:
            _restore_review_redub_snapshot(snapshot)
            _rebuild_batch_outputs(manifest_path.parent)
        except Exception:
            pass
        _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _cleanup_review_redub_snapshot(snapshot)


def _compact_process_error_output(stdout: str, stderr: str, *, keep_lines: int = 120) -> str:
    # 提炼子进程错误：合并 stdout/stderr，过滤 flash-attn 噪音，保留尾部关键上下文。
    noise_markers = ("Warning: flash-attn is not installed",)
    raw_lines = (f"{stdout or ''}\n{stderr or ''}").splitlines()
    filtered_lines: List[str] = []
    for line in raw_lines:
        text = (line or "").strip()
        if not text:
            continue
        if text == "********":
            continue
        if any(marker in text for marker in noise_markers):
            continue
        filtered_lines.append(line.rstrip())
    if not filtered_lines:
        filtered_lines = [line.rstrip() for line in raw_lines if (line or "").strip()]
    tail_lines = filtered_lines[-max(1, int(keep_lines)) :]
    return "\n".join(tail_lines).strip()


def _snapshot_file(path: Path, backup_root: Path) -> Dict[str, Optional[str]]:
    # 为单个文件创建快照；原本不存在的文件仅记录状态，不额外复制。
    resolved = path.expanduser().resolve()
    entry: Dict[str, Optional[str]] = {
        "path": str(resolved),
        "exists": "true" if resolved.exists() else "false",
        "backup": None,
    }
    if not resolved.exists():
        return entry
    backup_path = backup_root / "files" / resolved.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved, backup_path)
    entry["backup"] = str(backup_path)
    return entry


def _create_review_redub_snapshot(*, manifest_path: Path, segment_job_dirs: List[Path]) -> Dict[str, Any]:
    # review redub 前备份受影响 segment 与 batch manifest，便于失败时回滚。
    batch_dir = manifest_path.parent
    backup_root = Path(tempfile.mkdtemp(prefix="review_redub_", dir=str(batch_dir))).resolve()
    segment_entries: List[Dict[str, str]] = []
    for segment_job_dir in sorted({item.expanduser().resolve() for item in segment_job_dirs}, key=lambda item: str(item)):
        backup_dir = backup_root / "segments" / segment_job_dir.name
        shutil.copytree(segment_job_dir, backup_dir)
        segment_entries.append({"path": str(segment_job_dir), "backup": str(backup_dir)})
    return {
        "backup_root": str(backup_root),
        "segment_dirs": segment_entries,
        "files": [_snapshot_file(manifest_path, backup_root)],
    }


def _restore_review_redub_snapshot(snapshot: Dict[str, Any]) -> None:
    # 回滚局部重配过程中对 segment/batch manifest 的改动。
    for entry in snapshot.get("segment_dirs", []):
        target = Path(str(entry.get("path") or "")).expanduser().resolve()
        backup = Path(str(entry.get("backup") or "")).expanduser().resolve()
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(backup, target)

    for entry in snapshot.get("files", []):
        target = Path(str(entry.get("path") or "")).expanduser().resolve()
        existed = str(entry.get("exists") or "").lower() == "true"
        backup_text = entry.get("backup")
        if existed and backup_text:
            backup = Path(str(backup_text)).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif (not existed) and target.exists():
            target.unlink(missing_ok=True)


def _cleanup_review_redub_snapshot(snapshot: Dict[str, Any]) -> None:
    # 清理事务临时目录，避免 batch 目录残留大量备份。
    backup_root_text = snapshot.get("backup_root")
    if not backup_root_text:
        return
    shutil.rmtree(Path(str(backup_root_text)).expanduser(), ignore_errors=True)


def _collect_written_batch_paths(manifest_path: Path) -> Dict[str, Optional[str]]:
    # 从最新 batch manifest 提取最终字幕产物路径。
    batch_manifest = load_batch_manifest(manifest_path)
    paths = batch_manifest.paths
    translated_text = paths.get("translated_full_srt")
    bilingual_text = paths.get("dubbed_final_full_srt")
    translated_path = Path(str(translated_text)).expanduser().resolve() if translated_text else None
    bilingual_path = Path(str(bilingual_text)).expanduser().resolve() if bilingual_text else None
    return {
        "translated_full_srt": str(translated_path) if translated_path and translated_path.exists() else None,
        "dubbed_final_full_srt": str(bilingual_path) if bilingual_path and bilingual_path.exists() else None,
    }


def _rerun_segment_with_translated_srt(
    *,
    segment_job_dir: Path,
    target_lang: str,
    index_tts_api_url: str,
    rewrite_translation: bool,
    redub_local_indices: List[int],
) -> None:
    # 仅重跑单个 segment（跳过 ASR/翻译），实现局部重配而非全量重跑。
    segment_manifest_path = segment_job_dir / "manifest.json"
    if not segment_manifest_path.exists():
        raise RuntimeError(f"segment manifest missing: {segment_manifest_path}")
    segment_manifest = load_segment_manifest(segment_manifest_path)
    input_media_path = segment_manifest.input_media_path
    if not input_media_path:
        raise RuntimeError("segment input_media_path missing")
    runtime_options = resolve_segment_redub_runtime_options(
        segment_manifest=segment_manifest,
        fallback_rewrite_translation=rewrite_translation,
        fallback_index_tts_api_url=index_tts_api_url,
    )
    tts_model_path = str(segment_manifest.raw.get("tts_model_path") or "")
    _switch_tts_runtime_on_demand(
        tts_backend=runtime_options.tts_backend,
        index_tts_api_url=runtime_options.index_tts_api_url,
    )

    translated_srt = segment_job_dir / "subtitles" / "translated.srt"
    speaker_metadata_path = segment_job_dir / "subtitles" / "_input_segment.speakers.json"
    if not translated_srt.exists():
        raise RuntimeError(f"translated.srt missing: {translated_srt}")

    cmd = build_segment_redub_command(
        SegmentRedubCommandConfig(
            python_executable=sys.executable,
            tool_path=REPO_ROOT / "tools" / "dub_pipeline.py",
            segment_job_dir=segment_job_dir,
            out_dir=segment_job_dir.parent,
            input_media=Path(str(input_media_path)).expanduser().resolve(),
            target_lang=target_lang or "Chinese",
            translated_srt=translated_srt,
            tts_model_path=tts_model_path,
            index_tts_api_url=runtime_options.index_tts_api_url,
            rewrite_translation=runtime_options.rewrite_translation,
            grouped_synthesis=runtime_options.grouped_synthesis,
            force_fit_timing=runtime_options.force_fit_timing,
            redub_local_indices=redub_local_indices,
            tts_backend=runtime_options.tts_backend,
            speaker_metadata_path=speaker_metadata_path if speaker_metadata_path.exists() else None,
        )
    )

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 2):
        # 报错信息优先展示真实尾部错误，而不是 flash-attn 的无害 warning 横幅。
        detail = _compact_process_error_output(proc.stdout or "", proc.stderr or "", keep_lines=120)
        segment_name = segment_job_dir.name
        if not detail:
            detail = "no diagnostic output"
        raise RuntimeError(f"segment re-dub failed [{segment_name}] ({proc.returncode}): {detail[:2000]}")


def _rebuild_batch_outputs(batch_dir: Path) -> Dict[str, Any]:
    # 复用 tools/repair_bad_segments.py 内的重拼逻辑，更新 final 全量产物。
    tool_path = REPO_ROOT / "tools" / "repair_bad_segments.py"
    spec = importlib.util.spec_from_file_location("repair_bad_segments_runtime", str(tool_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load repair_bad_segments module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rebuild_batch_outputs(batch_dir)


@router.get("/artifact/{task_id}/{artifact}")
async def download_auto_dubbing_artifact(task_id: str, artifact: str):
    task_copy = _task_store.get_copy(task_id)
    if not task_copy:
        raise HTTPException(status_code=404, detail="Dubbing task not found")
    path = _resolve_artifact(task_copy, artifact)
    return FileResponse(path, filename=path.name)


def _cancel_task(task_id: str, reason: str) -> bool:
    with _lock:
        task = _task_store.get(task_id)
        if not task or task.get("status") in {"completed", "failed", "cancelled"}:
            return False
        proc: Optional[subprocess.Popen[str]] = task.get("process")
        task["status"] = "cancelled"
        task["stage"] = "cancelled"
        task["error"] = reason
        task["updated_at"] = _iso_now()

    if proc and proc.poll() is None:
        if hasattr(os, "killpg"):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
    return True


def cancel_active_dubbing(reason: str) -> int:
    active_ids = _task_store.list_active_ids()
    return sum(1 for task_id in active_ids if _cancel_task(task_id, reason))
