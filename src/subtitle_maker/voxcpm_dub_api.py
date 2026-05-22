from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
import subprocess
import urllib.error
import urllib.request
import math
import unicodedata
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from subtitle_maker.dubbing_cli_api import _resolve_project_media_path, _sanitize_filename, _store_uploaded_reference_file
from subtitle_maker.domains.dubbing.alignment import trim_silence_edges
from subtitle_maker.domains.media import (
    audio_duration,
    build_black_video_with_ass_subtitles,
    build_dubbed_video_two_step,
    build_full_timeline_mix,
    extract_source_audio,
    ffprobe_duration,
    has_video_stream,
    load_mono_audio,
    resample_mono_audio,
)
from subtitle_maker.domains.subtitles import (
    allocate_text_segment_times,
    convert_chinese_script_rows,
    convert_chinese_script_text,
    infer_cjk_mode_from_lines,
    normalize_subtitles_with_speakers,
    parse_podcast_script_text,
    strip_speaker_prefix,
)
from subtitle_maker.domains.subtitles.srt import subtitle_text_units
from subtitle_maker.jobs import TaskStore
from subtitle_maker.omnivoice_dub_api import (
    _rebalance_omnivoice_final_srt_rows,
    _infer_missing_speaker_gender_hints,
    _pick_preset_ref_voices_for_missing_speakers,
    _safe_speaker_name,
    _speaker_ref_text_for_target_lang,
    _validate_preset_ref_voices_available,
)
from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.translator import (
    DEFAULT_TRANSLATE_BASE_URL,
    DEFAULT_TRANSLATE_MODEL,
    Translator,
    build_translation_system_prompt,
    get_translate_provider_host,
    normalize_language_tag_for_passthrough,
    normalize_cantonese_translation_text,
    sanitize_translation_text,
)

router = APIRouter(prefix="/voxcpm/auto", tags=["voxcpm-auto"])

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "dub_jobs"
UPLOAD_ROOT = REPO_ROOT / "uploads" / "dubbing"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_VOXCPM_API_URL = "http://127.0.0.1:7860"
DEFAULT_VOXCPM_CFG_VALUE = 2.0
DEFAULT_VOXCPM_INFERENCE_TIMESTEPS = 10
DEFAULT_VOXCPM_NATURAL_GAP_SEC = 0.12
DEFAULT_VOXCPM_TYPEWRITER_HOLD_SEC = 1.2
DEFAULT_VOXCPM_MAX_LINES_PER_PAGE = 4
DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT = "traditional"
DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET = "1920x1080"
DEFAULT_VOXCPM_PRE_TTS_SOFT_UNITS_CJK = 30
DEFAULT_VOXCPM_PRE_TTS_HARD_UNITS_CJK = 40
DEFAULT_VOXCPM_PRE_TTS_SOFT_UNITS_LATIN = 85
DEFAULT_VOXCPM_PRE_TTS_HARD_UNITS_LATIN = 110
# VoxCPM 的播客脚本预处理不是视觉换行：这里只按完整句组给 TTS 分段，
# 阈值应明显宽于字幕显示行宽，避免 API 调用被拆得过碎。
DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_CJK = 90
DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_LATIN = 160
DEFAULT_VOXCPM_PRE_TTS_MAX_SENTENCES_PER_SEGMENT = 4
DEFAULT_VOXCPM_RETRY_GAP_SEC = 0.08
VOXCPM_SUBTITLE_VIDEO_LAYOUTS: Dict[str, Dict[str, int]] = {
    "1920x1080": {
        "width": 1920,
        "height": 1080,
        "font_size": 144,
        "margin_l": 140,
        "margin_r": 140,
        "margin_v": 80,
        "max_units_per_line": 24,
        "max_lines_per_page": 4,
    },
    "1080x1920": {
        "width": 1080,
        "height": 1920,
        "font_size": 102,
        "margin_l": 92,
        "margin_r": 92,
        "margin_v": 180,
        "max_units_per_line": 18,
        "max_lines_per_page": 6,
    },
    "1440x1080": {
        "width": 1440,
        "height": 1080,
        "font_size": 120,
        "margin_l": 108,
        "margin_r": 108,
        "margin_v": 88,
        "max_units_per_line": 20,
        "max_lines_per_page": 5,
    },
    "1080x1440": {
        "width": 1080,
        "height": 1440,
        "font_size": 112,
        "margin_l": 96,
        "margin_r": 96,
        "margin_v": 120,
        "max_units_per_line": 18,
        "max_lines_per_page": 5,
    },
}
VOXCPM_STUDIO_DIR = Path("/Users/tim/Documents/vibe-coding/MVP/VoxCPM")
VOXCPM_BACKEND_MAIN = VOXCPM_STUDIO_DIR / "run_py311.py"
VOXCPM_BACKEND_PYTHON = VOXCPM_STUDIO_DIR / ".venv" / "bin" / "python"
VOXCPM_BACKEND_PID_FILE = REPO_ROOT / "outputs" / "voxcpm_backend.pid"
VOXCPM_BACKEND_LOG_PATH = REPO_ROOT / "outputs" / "voxcpm_backend.log"
_voxcpm_backend_start_lock = threading.Lock()

logger = logging.getLogger(__name__)
_task_store = TaskStore()


def _iso_now() -> str:
    """统一使用 UTC 时间戳，便于批次恢复与排序。"""

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _build_task_id() -> str:
    """生成独立的 VoxCPM 任务 ID。"""

    base = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    existing_ids = set(_task_store.keys_snapshot())
    candidate = base
    index = 2
    while candidate in existing_ids or (OUTPUT_ROOT / f"voxcpm_{candidate}").exists():
        candidate = f"{base}_{index:02d}"
        index += 1
    return candidate


def _normalize_voxcpm_subtitle_script_variant(variant: str) -> str:
    """把 6 号面板脚本选项归一为 simplified / traditional。"""

    lowered = str(variant or "").strip().lower()
    if lowered in {"traditional", "traditional chinese", "繁体", "繁體", "繁体中文", "繁體中文"}:
        return "traditional"
    return "simplified"


def _is_voxcpm_cantonese_target_lang(language: str) -> bool:
    """判断 6 号面板当前目标语是否为粤语。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in ("cantonese", "yue", "粤语", "廣東話", "广东话"))


def _is_voxcpm_chinese_language(language: str) -> bool:
    """判断 6 号面板当前语种是否可视为中文。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    return lowered in {"chinese", "zh", "zh-cn", "zh-hans", "zh-hant", "中文", "普通话", "mandarin"}


def _is_voxcpm_cantonese_language(language: str) -> bool:
    """判断 6 号面板当前语种是否可视为粤语来源语。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in ("cantonese", "yue", "粤语", "廣東話", "广东话"))


def _looks_like_mostly_chinese_text(text: str) -> bool:
    """用一个保守启发式判断文本是否以中文为主，避免中文到中文时再走计费翻译。"""

    cjk_count = 0
    latin_count = 0
    for char in str(text or ""):
        if "\u4e00" <= char <= "\u9fff":
            cjk_count += 1
            continue
        if ("a" <= char <= "z") or ("A" <= char <= "Z"):
            latin_count += 1
    if cjk_count == 0:
        return False
    return cjk_count >= max(4, latin_count * 2)


def _is_voxcpm_latin_dominant_text(text: str) -> bool:
    """判断译文是否仍被英文主导，用于触发 6 号面板的定向补译。"""

    raw = str(text or "").strip()
    if not raw:
        return False
    latin_count = sum(1 for char in raw if ("a" <= char <= "z") or ("A" <= char <= "Z"))
    cjk_count = sum(1 for char in raw if "\u4e00" <= char <= "\u9fff")
    if latin_count < 8:
        return False
    return cjk_count == 0 or latin_count > cjk_count * 2


def _should_passthrough_source_rows_without_translation(
    *,
    source_rows: List[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
) -> bool:
    """判断当前 source 字幕是否应直接复用，避免同语种场景重复计费翻译。"""

    source_tag = normalize_language_tag_for_passthrough(source_lang)
    target_tag = normalize_language_tag_for_passthrough(target_lang)
    if source_tag and target_tag and source_tag not in {"", "auto"} and source_tag == target_tag:
        return True
    if target_tag != "zh":
        return False
    if source_tag not in {"", "auto"}:
        return False
    sample_text = "".join(str(row.get("text") or "").strip() for row in list(source_rows or [])[:12])
    return _looks_like_mostly_chinese_text(sample_text)


def _sanitize_voxcpm_selected_rows_for_target(
    rows: List[Dict[str, Any]],
    *,
    target_lang: str,
) -> List[Dict[str, Any]]:
    """统一清洗 6 号面板选中字字幕，确保复用态与新翻译态输出一致。"""

    sanitized_rows: List[Dict[str, Any]] = []
    for row in rows:
        text = _sanitize_voxcpm_translation_text(str(row.get("text") or ""), target_lang)
        if _is_cantonese_target_lang(target_lang):
            text = normalize_cantonese_translation_text(text, target_lang=target_lang)
        if not text:
            continue
        sanitized_rows.append(
            {
                **row,
                "text": text,
            }
        )
    return sanitized_rows


def _strip_voxcpm_translation_explanation_tails(text: str) -> str:
    """去掉翻译结果尾部常见的说明性废话，但不截断正常正文。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    explanation_tail_patterns = (
        r"(?is)\s+(?:but|however)\s+chinese\s+output\s+only\b.*$",
        r"(?is)\s+let'?s\s+correct\s+in\s+final\b.*$",
        r"(?is)\s+(?:final\s+answer|final\s+output)\b.*$",
        r"(?is)\s+(?:please\s+)?output\s+only\b.*$",
    )
    for pattern in explanation_tail_patterns:
        normalized = re.sub(pattern, "", normalized).strip()
    return normalized


def _should_use_strict_voxcpm_translation_sanitizer(text: str, target_lang: str) -> bool:
    """仅在明显混入解释/报错时，才退回激进清洗器。"""

    normalized = _strip_voxcpm_translation_explanation_tails(text)
    if not normalized:
        return False
    if not (_is_voxcpm_chinese_language(target_lang) or _is_cantonese_target_lang(target_lang)):
        return True
    lowered = normalized.lower()
    suspicious_markers = (
        "[error]",
        "output only",
        "final answer",
        "final output",
        "let's correct",
        "translation:",
        "translate:",
        "不对",
        "唔对",
        "错误",
        "錯誤",
        "更正",
        "改成",
    )
    if any(marker in lowered for marker in suspicious_markers):
        return True
    if any(marker in normalized for marker in ("不对", "唔对", "错误", "錯誤", "更正", "改成")):
        return True
    return False


def _sanitize_voxcpm_translation_text(text: str, target_lang: str) -> str:
    """6 号面板专用翻译清洗：默认保留整段正文，只在脏输出时激进裁剪。"""

    normalized = _strip_voxcpm_translation_explanation_tails(text)
    if not normalized:
        return ""
    if _should_use_strict_voxcpm_translation_sanitizer(normalized, target_lang):
        return sanitize_translation_text(normalized, target_lang)
    return normalized


def _rows_text_equivalent(left_rows: List[Dict[str, Any]], right_rows: List[Dict[str, Any]]) -> bool:
    """判断两组字幕文本是否等价，用于区分“源真值”和“翻译结果”。"""

    if len(left_rows) != len(right_rows):
        return False
    for left, right in zip(left_rows, right_rows):
        if str(left.get("text") or "").strip() != str(right.get("text") or "").strip():
            return False
        if str(left.get("speaker_id") or "").strip() != str(right.get("speaker_id") or "").strip():
            return False
    return True


def _strip_voxcpm_inline_speaker_label(text: str, speaker_id: str) -> str:
    """只剥离与 sidecar speaker_id 明确匹配的正文前缀，避免误伤普通冒号正文。"""

    raw = str(text or "")
    explicit_speaker_id = str(speaker_id or "").strip()
    if not raw.strip() or not explicit_speaker_id:
        return raw

    stripped_text = raw.lstrip()
    for prefix in (f"[{explicit_speaker_id}]", f"【{explicit_speaker_id}】"):
        if stripped_text.startswith(prefix):
            return stripped_text[len(prefix):].lstrip()

    parsed_speaker_id, clean_text = strip_speaker_prefix(raw)
    if str(parsed_speaker_id or "").strip().lower() == explicit_speaker_id.lower() and clean_text:
        return clean_text
    return raw


def _strip_voxcpm_markdown_style_tokens(text: str) -> str:
    """去掉 6 号面板字幕里的 Markdown 样式标记，只保留正文。"""

    normalized = str(text or "")
    if not normalized.strip():
        return ""
    # 这里只清理样式符号，不改普通文本语义。
    normalized = normalized.replace("**", "")
    normalized = normalized.replace("__", "")
    normalized = normalized.replace("`", "")
    normalized = re.sub(r"(?<!\*)\*(?!\*)", "", normalized)
    normalized = re.sub(r"(?<!_)_(?!_)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_voxcpm_internal_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """统一清洗 6 号面板内部字幕行，确保 speaker_id 与正文文本物理分离。"""

    normalized_rows, _ = normalize_subtitles_with_speakers(list(rows or []))
    output: List[Dict[str, Any]] = []
    for row in normalized_rows:
        text = str(row.get("text") or "")
        speaker_id = str(row.get("speaker_id") or "").strip()
        clean_text = _strip_voxcpm_inline_speaker_label(text, speaker_id).strip()
        clean_text = _strip_voxcpm_markdown_style_tokens(clean_text)
        if not clean_text:
            continue
        output.append(
            {
                **row,
                "text": clean_text,
                "speaker_id": speaker_id,
            }
        )
    return output


def _build_voxcpm_translation_rebuild_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 6 号面板源真值重构成翻译前短句工作副本。"""

    # 翻译前 rebuild 是 6 号面板自己的工作副本，不能再复用 final 的 20 字硬拆语义。
    normalized_rows = _normalize_speaker_ids_for_rows(_normalize_voxcpm_internal_rows(rows))
    return _split_voxcpm_rows_before_tts(normalized_rows)


def _normalize_voxcpm_subtitle_video_preset(preset: str) -> str:
    """把 6 号面板字幕视频画幅选项归一为受支持的固定键。"""

    normalized = str(preset or "").strip().lower()
    if normalized in {"1080x1920", "9:16", "vertical", "portrait"}:
        return "1080x1920"
    if normalized in {"1440x1080", "4:3"}:
        return "1440x1080"
    if normalized in {"1080x1440", "3:4"}:
        return "1080x1440"
    return DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET


def _get_voxcpm_subtitle_video_layout(preset: str) -> Dict[str, int]:
    """集中返回当前画幅对应的 ASS 排版与黑底视频布局配置。"""

    normalized_preset = _normalize_voxcpm_subtitle_video_preset(preset)
    return dict(VOXCPM_SUBTITLE_VIDEO_LAYOUTS[normalized_preset])


def _resolve_output_dir(task_id: str) -> Path:
    """解析 VoxCPM 任务输出目录。"""

    return (OUTPUT_ROOT / f"voxcpm_{task_id}").resolve()


def _artifact_url(task_id: str, artifact: str) -> str:
    """构造产物下载 URL。"""

    return f"/voxcpm/auto/artifact/{task_id}/{artifact}"


def _set_task(task_id: str, **updates: Any) -> None:
    """统一更新任务状态。"""

    payload = dict(updates)
    payload.setdefault("updated_at", _iso_now())
    _task_store.update(task_id, **payload)


def _format_voxcpm_translation_context(base_url: str, model: str) -> Dict[str, str]:
    """统一整理 6 号面板真实翻译配置，便于任务与排障日志复用。"""

    normalized_base_url = str(base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL
    normalized_model = str(model or "").strip() or DEFAULT_TRANSLATE_MODEL
    return {
        "translate_base_url": normalized_base_url,
        "translate_model": normalized_model,
    }


def _capture_voxcpm_effective_translate_provider(*, base_url: str, model: str) -> Dict[str, str]:
    """统一归一 6 号面板本次实际生效的翻译 provider，避免任务状态与执行层脱节。"""

    effective = _format_voxcpm_translation_context(base_url=base_url, model=model)
    effective["translate_provider_host"] = get_translate_provider_host(effective["translate_base_url"])
    return effective


def _normalize_subtitles_payload(raw: str, *, field_name: str) -> List[Dict[str, Any]]:
    """把前端传来的字幕 JSON 规范化为内部结构。"""

    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {exc}") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: must be a list")

    rows: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_text = str(item.get("text") or "").strip()
        if not raw_text:
            continue
        try:
            start_sec = float(item.get("start", item.get("start_sec")))
            end_sec = float(item.get("end", item.get("end_sec")))
        except (TypeError, ValueError):
            continue
        if end_sec <= start_sec:
            continue
        rows.append(
            {
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "text": raw_text,
                "speaker_id": str(item.get("speaker_id") or "").strip(),
            }
        )
    rows.sort(key=lambda item: float(item.get("start", 0.0) or 0.0))
    return rows


def _normalize_speaker_ids_for_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """沿用 5 号面板的补齐顺序：上一行优先，兜底 Speaker 1。"""

    normalized: List[Dict[str, Any]] = []
    previous_speaker_id = ""
    for row in list(rows or []):
        next_row = dict(row)
        explicit_speaker_id = str(next_row.get("speaker_id") or "").strip()
        speaker_id = explicit_speaker_id or previous_speaker_id or "Speaker 1"
        next_row["speaker_id"] = speaker_id
        normalized.append(next_row)
        previous_speaker_id = speaker_id
    return normalized


def _collect_detected_speaker_ids(rows: List[Dict[str, Any]]) -> List[str]:
    """按字幕顺序提取稳定 speaker 列表。"""

    ordered: List[str] = []
    seen: Set[str] = set()
    for row in _normalize_speaker_ids_for_rows(rows):
        speaker_id = str(row.get("speaker_id") or "").strip() or "Speaker 1"
        if speaker_id in seen:
            continue
        seen.add(speaker_id)
        ordered.append(speaker_id)
    return ordered


def _build_speaker_prefixed_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """生成一份带 speaker 前缀的字幕拷贝，供下载与人工核对。"""

    output: List[Dict[str, Any]] = []
    for row in _normalize_speaker_ids_for_rows(rows):
        speaker_id = str(row.get("speaker_id") or "").strip() or "Speaker 1"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        # 兼容两种上游结构：
        # 1. 常规字幕行使用 start/end
        # 2. segment manifest 使用 start_sec/end_sec
        start_sec = float(row.get("start", row.get("start_sec", 0.0)) or 0.0)
        end_sec = float(row.get("end", row.get("end_sec", 0.0)) or 0.0)
        output.append(
            {
                "start": start_sec,
                "end": end_sec,
                "text": f"[{speaker_id}] {text}",
                "speaker_id": speaker_id,
            }
        )
    return output


def _split_voxcpm_text_into_complete_sentences(text: str) -> List[str]:
    """只按完整句边界切分播客脚本长行，禁止在句子内部硬切。"""

    original_text = str(text or "")
    if not original_text.strip():
        return []
    sentence_breaks = {"。", "！", "？", "；", "!", "?", ";"}
    trailing_closers = {'"', "'", "”", "’", ")", "]", "】", "》", "）"}
    sentences: List[str] = []
    sentence_start = 0
    index = 0
    while index < len(original_text):
        char = original_text[index]
        next_non_space = ""
        lookahead_probe = index + 1
        while lookahead_probe < len(original_text):
            probe_char = original_text[lookahead_probe]
            if probe_char.isspace():
                lookahead_probe += 1
                continue
            next_non_space = probe_char
            break
        is_sentence_period = (
            char == "."
            and index > 0
            and original_text[index - 1].isascii()
            and original_text[index - 1].isalnum()
            and not (original_text[index - 1].isdigit() and next_non_space.isdigit())
        )
        if char in sentence_breaks or is_sentence_period:
            lookahead = index + 1
            while lookahead < len(original_text) and original_text[lookahead] in trailing_closers:
                lookahead += 1
            sentence = original_text[sentence_start:lookahead]
            if sentence:
                sentences.append(sentence)
            sentence_start = lookahead
            index = lookahead
            continue
        index += 1
    tail = original_text[sentence_start:]
    if tail:
        # 没有句末强标点的尾巴仍是一个完整 TTS 语义单元，不能按长度剁开。
        sentences.append(tail)
    return sentences or [original_text]


def _group_voxcpm_complete_sentences_for_tts(sentences: List[str], *, cjk_mode: bool) -> List[str]:
    """把相邻短完整句合并成较少的 TTS 段，避免 API 调用过碎。"""

    clean_sentences = [str(sentence or "") for sentence in sentences if str(sentence or "").strip()]
    if len(clean_sentences) <= 1:
        return list(clean_sentences)
    soft_limit = DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_CJK if cjk_mode else DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_LATIN
    grouped: List[str] = []
    current_parts: List[str] = []
    current_sentence_count = 0
    for sentence in clean_sentences:
        if not current_parts:
            current_parts = [sentence]
            current_sentence_count = 1
            continue
        # 这里只能做长度预估，不能 strip；否则会破坏分段拼回原文的一致性。
        candidate = "".join(current_parts + [sentence])
        if (
            current_sentence_count < DEFAULT_VOXCPM_PRE_TTS_MAX_SENTENCES_PER_SEGMENT
            and subtitle_text_units(candidate, cjk_mode=cjk_mode) <= soft_limit
        ):
            current_parts.append(sentence)
            current_sentence_count += 1
            continue
        grouped.append("".join(current_parts))
        current_parts = [sentence]
        current_sentence_count = 1
    if current_parts:
        grouped.append("".join(current_parts))
    return grouped


def _is_voxcpm_ascii_sentence(sentence: str) -> bool:
    """判断一个完整句是否基本由 ASCII/空白/常见英文标点组成。"""

    raw = str(sentence or "")
    if not raw.strip():
        return False
    has_latin = False
    for char in raw:
        if ("a" <= char <= "z") or ("A" <= char <= "Z"):
            has_latin = True
            continue
        if char.isspace() or char.isascii():
            continue
        return False
    return has_latin


def _merge_voxcpm_adjacent_ascii_sentences(sentences: List[str]) -> List[str]:
    """把连续英文完整句先并在一起，避免 `Ideas are everywhere.` 被拆成两条。"""

    merged: List[str] = []
    index = 0
    while index < len(sentences):
        current = str(sentences[index] or "")
        if not current.strip():
            index += 1
            continue
        if not _is_voxcpm_ascii_sentence(current):
            merged.append(current)
            index += 1
            continue
        parts = [current]
        probe = index + 1
        while probe < len(sentences) and _is_voxcpm_ascii_sentence(sentences[probe]):
            parts.append(str(sentences[probe] or ""))
            probe += 1
        merged.append("".join(parts))
        index = probe
    return merged


def _merge_voxcpm_open_quote_sentences(sentences: List[str]) -> List[str]:
    """把被中文/英文引号包裹的连续句子先并回一个语义单元。"""

    merged: List[str] = []
    index = 0
    while index < len(sentences):
        current = str(sentences[index] or "")
        if current.count('"') % 2 == 1 or current.count("“") > current.count("”"):
            parts = [current]
            probe = index + 1
            while probe < len(sentences):
                next_sentence = str(sentences[probe] or "")
                parts.append(next_sentence)
                if next_sentence.count('"') % 2 == 1 or "”" in next_sentence:
                    probe += 1
                    break
                probe += 1
            merged.append("".join(parts))
            index = probe
            continue
        merged.append(current)
        index += 1
    return merged


def _merge_voxcpm_quote_adjacent_ascii_group(sentences: List[str]) -> List[str]:
    """把紧跟引号后的英文句组并回前一句，避免引用内容被生硬拆开。"""

    merged: List[str] = []
    index = 0
    while index < len(sentences):
        current = str(sentences[index] or "")
        if (
            index + 1 < len(sentences)
            and current.rstrip().endswith(('"', "”"))
            and _is_voxcpm_ascii_sentence(sentences[index + 1])
        ):
            merged.append(current + str(sentences[index + 1] or ""))
            index += 2
            continue
        merged.append(current)
        index += 1
    return merged


def _split_voxcpm_sentences_into_balanced_groups(sentences: List[str], *, cjk_mode: bool) -> List[str]:
    """当宽松分组仍合成一段时，按完整句数量强制拆成两组。"""

    # 这里不能 strip 每个句子；否则会把英文句间原始空格吞掉，导致
    # `Ideas are everywhere. They're worthless.` 变成 `Ideas are everywhere.They're worthless.`
    clean_sentences = [str(sentence or "") for sentence in sentences if str(sentence or "").strip()]
    if len(clean_sentences) <= 1:
        return list(clean_sentences)
    split_at = max(1, len(clean_sentences) // 2)
    left = clean_sentences[:split_at]
    right = clean_sentences[split_at:]
    return [
        _group_voxcpm_complete_sentences_for_tts(left, cjk_mode=cjk_mode)[0],
        _group_voxcpm_complete_sentences_for_tts(right, cjk_mode=cjk_mode)[0],
    ]


def _split_voxcpm_long_text_before_tts(text: str) -> List[str]:
    """为 6 号面板播客脚本长字幕行生成完整句 TTS 分段。"""

    original_text = str(text or "")
    if not original_text.strip():
        return []
    cjk_mode = infer_cjk_mode_from_lines([original_text])
    split_threshold = DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_CJK if cjk_mode else DEFAULT_VOXCPM_PRE_TTS_GROUP_UNITS_LATIN
    sentences = _split_voxcpm_text_into_complete_sentences(original_text)
    sentences = _merge_voxcpm_open_quote_sentences(sentences)
    sentences = _merge_voxcpm_adjacent_ascii_sentences(sentences)
    sentences = _merge_voxcpm_quote_adjacent_ascii_group(sentences)
    if len(sentences) <= 1:
        return [original_text]
    if len(sentences) <= 3 and subtitle_text_units(original_text, cjk_mode=cjk_mode) <= split_threshold:
        return [original_text]
    grouped_segments = _group_voxcpm_complete_sentences_for_tts(sentences, cjk_mode=cjk_mode)
    if len(grouped_segments) <= 1 and len(sentences) > 3:
        grouped_segments = _split_voxcpm_sentences_into_balanced_groups(sentences, cjk_mode=cjk_mode)
    if len(grouped_segments) <= 1:
        return [original_text]
    return grouped_segments


def _split_voxcpm_rows_before_tts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把超长字幕行前置拆短，减少 6 号面板口播慢半拍问题。"""

    output: List[Dict[str, Any]] = []
    for row in list(rows or []):
        next_row = dict(row)
        text = str(next_row.get("text") or "")
        if not text.strip():
            continue
        segments = _split_voxcpm_long_text_before_tts(text)
        if len(segments) <= 1:
            next_row["text"] = text
            output.append(next_row)
            continue

        cjk_mode = infer_cjk_mode_from_lines([text])
        start_sec = float(next_row.get("start", 0.0) or 0.0)
        end_sec = float(next_row.get("end", 0.0) or 0.0)
        spans = allocate_text_segment_times(
            start_sec=start_sec,
            end_sec=end_sec,
            segments=segments,
            cjk_mode=cjk_mode,
        )
        if len(spans) != len(segments):
            next_row["text"] = text
            output.append(next_row)
            continue

        for (seg_start, seg_end), seg_text in zip(spans, segments):
            piece = dict(next_row)
            piece["start"] = round(float(seg_start), 3)
            piece["end"] = round(float(seg_end), 3)
            piece["text"] = str(seg_text)
            output.append(piece)
    return output


def _is_cantonese_target_lang(language: str) -> bool:
    """判断目标语是否为粤语变体。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in ("cantonese", "yue", "粤语", "廣東話", "广东话"))


def _translate_subtitles_if_needed(
    *,
    subtitle_mode: str,
    source_rows: List[Dict[str, Any]],
    translated_rows: List[Dict[str, Any]],
    translation_rows: Optional[List[Dict[str, Any]]] = None,
    source_lang: str,
    target_lang: str,
    api_key: str,
    translate_base_url: str,
    translate_model: str,
    translate_system_prompt: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """按 subtitle_mode 决定源真值和翻译工作副本。"""

    translation_input_rows = list(translation_rows or source_rows)
    preferred_mode = str(subtitle_mode or "").strip().lower()
    if preferred_mode == "translated" and translated_rows:
        selected_rows = _sanitize_voxcpm_selected_rows_for_target(translated_rows, target_lang=target_lang)
        source_truth_rows = [
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": str(row.get("text") or "").strip(),
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
            for row in source_rows
            if str(row.get("text") or "").strip()
        ]
        return (source_truth_rows or [dict(item) for item in selected_rows], [dict(item) for item in selected_rows], "translated")
    if preferred_mode == "source" and not source_rows:
        raise HTTPException(status_code=400, detail="VoxCPM source subtitle mode requires source subtitles")
    if preferred_mode != "source" and translated_rows:
        selected_rows = _sanitize_voxcpm_selected_rows_for_target(translated_rows, target_lang=target_lang)
        source_truth_rows = [
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": str(row.get("text") or "").strip(),
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
            for row in source_rows
            if str(row.get("text") or "").strip()
        ]
        return (source_truth_rows or [dict(item) for item in selected_rows], [dict(item) for item in selected_rows], "translated")
    if not source_rows:
        raise HTTPException(status_code=400, detail="VoxCPM requires source or translated subtitles")
    if _should_passthrough_source_rows_without_translation(
        source_rows=source_rows,
        source_lang=source_lang,
        target_lang=target_lang,
    ):
        return (
            [
                {
                    **row,
                    "text": str(row.get("text") or "").strip(),
                }
                for row in source_rows
                if str(row.get("text") or "").strip()
            ],
            [],
            "source",
        )
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="Translation API key required for source subtitle mode")

    translator = Translator(
        api_key=api_key,
        base_url=translate_base_url or DEFAULT_TRANSLATE_BASE_URL,
        model=translate_model or DEFAULT_TRANSLATE_MODEL,
    )
    # 6 号面板翻译 system prompt 与 5 号面板保持完全一致，统一走共享构造函数。
    prompt = build_translation_system_prompt(translate_system_prompt)
    texts = [str(row.get("text") or "").strip() for row in translation_input_rows]
    # 6 号面板保留模型原始正文，只做编号解析；共享激进清洗会误裁正常长段。
    translated_texts = translator.translate_batch(
        texts,
        target_lang=target_lang,
        system_prompt=prompt,
        sanitize_outputs=False,
    )
    if _is_voxcpm_chinese_language(target_lang) or _is_cantonese_target_lang(target_lang):
        retry_indices = [
            index
            for index, translated_text in enumerate(translated_texts)
            if _is_voxcpm_latin_dominant_text(str(translated_text or ""))
        ]
        if retry_indices:
            retry_inputs = [texts[index] for index in retry_indices]
            strict_prompt = (
                f"{prompt}\n"
                "硬性要求：输出必须是目标中文正文，不要保留整句英文，不要输出 [Error] 前缀，不要解释。"
            ).strip()
            try:
                retry_outputs = translator.translate_batch(
                    retry_inputs,
                    target_lang=target_lang,
                    system_prompt=strict_prompt,
                    system_prompt_is_final=True,
                    sanitize_outputs=False,
                )
                if len(retry_outputs) != len(retry_inputs):
                    logger.warning(
                        "VoxCPM translation retry count mismatch: requested=%d returned=%d",
                        len(retry_inputs),
                        len(retry_outputs),
                    )
                    retry_outputs = []
                replaced = 0
                for idx, retry_text in zip(retry_indices, retry_outputs):
                    if not _is_voxcpm_latin_dominant_text(str(retry_text or "")):
                        translated_texts[idx] = str(retry_text or "").strip()
                        replaced += 1
                if replaced > 0:
                    logger.warning(
                        "VoxCPM translation retry replaced %d latin-dominant rows",
                        replaced,
                    )
            except Exception as exc:
                logger.warning("VoxCPM translation retry failed: %s", exc)
    translated_rows_for_output: List[Dict[str, Any]] = []
    for row, translated_text in zip(translation_input_rows, translated_texts):
        text = _sanitize_voxcpm_translation_text(str(translated_text or ""), target_lang)
        if not text:
            continue
        if _is_cantonese_target_lang(target_lang):
            text = normalize_cantonese_translation_text(text, target_lang=target_lang)
        translated_rows_for_output.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": text,
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
        )
    if not translated_rows_for_output:
        raise HTTPException(status_code=400, detail="Translated subtitles are empty")
    source_truth_rows = [
        {
            "start": float(row.get("start", 0.0) or 0.0),
            "end": float(row.get("end", 0.0) or 0.0),
            "text": str(row.get("text") or "").strip(),
            "speaker_id": str(row.get("speaker_id") or "").strip(),
        }
        for row in source_rows
        if str(row.get("text") or "").strip()
    ]
    return (source_truth_rows, _sanitize_voxcpm_selected_rows_for_target(translated_rows_for_output, target_lang=target_lang), "source")


def _http_json(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout_sec: float = 30.0,
    max_incomplete_read_retries: int = 2,
) -> Dict[str, Any]:
    """执行 JSON HTTP 请求，并对截断响应做有限重试。"""

    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_incomplete_error: Optional[IncompleteRead] = None
    for attempt in range(max(0, int(max_incomplete_read_retries)) + 1):
        req = urllib.request.Request(url=url, data=data, headers=headers, method=method.upper())
        try:
            # 本机 VoxCPM 服务必须直连，避免被系统代理或本地抓包代理错误接管。
            if _is_local_voxcpm_api(url):
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                response_ctx = opener.open(req, timeout=timeout_sec)
            else:
                response_ctx = urllib.request.urlopen(req, timeout=timeout_sec)
            with response_ctx as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except IncompleteRead as exc:
            last_incomplete_error = exc
            if attempt >= max_incomplete_read_retries:
                break
            logger.warning(
                "VoxCPM api incomplete read, retrying (%s/%s): %s",
                attempt + 1,
                max_incomplete_read_retries + 1,
                exc,
            )
            time.sleep(min(1.0, 0.2 * (attempt + 1)))
            continue
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VoxCPM api http {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"VoxCPM api connect failed: {exc}") from exc
    if last_incomplete_error is not None:
        raise RuntimeError(f"VoxCPM api incomplete read after retry: {last_incomplete_error}") from last_incomplete_error
    raise RuntimeError("VoxCPM api request failed without response")


def _is_local_voxcpm_api(api_url: str) -> bool:
    """判断 api_url 是否指向本机 VoxCPM 服务。"""

    parsed = urlparse(api_url or DEFAULT_VOXCPM_API_URL)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True
    return host in {"127.0.0.1", "localhost", "::1"}


def _read_pid_file(pid_file: Path) -> Optional[int]:
    """读取 pid 文件。"""

    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        return int(raw)
    except Exception:
        return None


def _pid_is_alive(pid: int) -> bool:
    """检查进程是否仍然存活。"""

    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _start_local_voxcpm_backend() -> Dict[str, Any]:
    """按需拉起本机 7860 VoxCPM 服务。"""

    if not VOXCPM_BACKEND_PYTHON.is_file():
        raise FileNotFoundError(f"VoxCPM backend python not found: {VOXCPM_BACKEND_PYTHON}")
    if not VOXCPM_BACKEND_MAIN.is_file():
        raise FileNotFoundError(f"VoxCPM backend entry not found: {VOXCPM_BACKEND_MAIN}")

    with _voxcpm_backend_start_lock:
        if VOXCPM_BACKEND_PID_FILE.exists():
            pid = _read_pid_file(VOXCPM_BACKEND_PID_FILE)
            if pid and _pid_is_alive(pid):
                return {"started": False, "pid": pid, "reason": "pid-file-alive"}

        VOXCPM_BACKEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.setdefault("FLASK_HOST", "127.0.0.1")
        env.setdefault("FLASK_PORT", "7860")
        with open(VOXCPM_BACKEND_LOG_PATH, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [str(VOXCPM_BACKEND_PYTHON), str(VOXCPM_BACKEND_MAIN)],
                cwd=str(VOXCPM_STUDIO_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        VOXCPM_BACKEND_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        logger.info("Started local VoxCPM backend: pid=%s log=%s", proc.pid, VOXCPM_BACKEND_LOG_PATH)
        return {"started": True, "pid": proc.pid, "reason": "launched"}


def _check_voxcpm_backend(api_url: str) -> Dict[str, Any]:
    """检查 VoxCPM 服务健康状态。"""

    return _http_json(method="GET", url=f"{api_url.rstrip('/')}/api/health", timeout_sec=5.0)


def _ensure_voxcpm_backend_ready(api_url: str) -> Dict[str, Any]:
    """确认 VoxCPM 服务可连通；本机地址先尝试按需拉起。"""

    if _is_local_voxcpm_api(api_url):
        try:
            _start_local_voxcpm_backend()
        except Exception as exc:
            logger.warning("Local VoxCPM backend auto-start failed: %s", exc)
    return _check_voxcpm_backend(api_url)


def _decode_base64_audio_to_wav(audio_base64: str, output_path: Path) -> None:
    """把 VoxCPM 返回的 base64 WAV 落盘。"""

    raw = base64.b64decode(audio_base64.encode("utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)


def _resolve_existing_optional_path(raw: Any) -> Optional[Path]:
    """把 manifest 里的可选路径解析成存在的文件。"""

    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.exists() else None


def _build_segment_result(*, start_sec: float, segment_manifest: Dict[str, Any]) -> Any:
    """构造给时间轴混音使用的最小 segment result 对象。"""

    return type(
        "VoxSegmentResult",
        (),
        {
            "start_sec": float(start_sec),
            "manifest": dict(segment_manifest),
        },
    )()


def _call_voxcpm_tts(
    *,
    api_url: str,
    text: str,
    prompt_audio_path: Path,
    prompt_text: str,
    cfg_value: float,
    inference_timesteps: int,
) -> Dict[str, Any]:
    """调用 VoxCPM 单句 TTS 接口。"""

    payload = {
        "text": text,
        "prompt_audio": str(prompt_audio_path.resolve()),
        "prompt_text": prompt_text,
        "cfg_value": float(cfg_value),
        "inference_timesteps": int(inference_timesteps),
        "normalize": False,
        "denoise": False,
    }
    return _http_json(
        method="POST",
        url=f"{api_url.rstrip('/')}/api/tts",
        payload=payload,
        timeout_sec=3600.0,
    )


def _is_voxcpm_unstable_generation_error(exc: Exception) -> bool:
    """判断是否为 VoxCPM 明确要求缩短文本的可恢复错误。"""

    message = str(exc or "").strip().lower()
    if not message:
        return False
    return (
        "generation remained unstable" in message
        or "please shorten the text" in message
        or "duration limit" in message
    )


def _write_voxcpm_retry_concat_wav(
    *,
    chunk_audio_base64_list: List[str],
    output_path: Path,
    gap_sec: float = DEFAULT_VOXCPM_RETRY_GAP_SEC,
) -> None:
    """把拆小重试得到的多段音频拼回一个 wav，供主链路继续消费。"""

    sample_rate: Optional[int] = None
    stitched_parts: List[np.ndarray] = []
    safe_gap_sec = max(0.0, float(gap_sec))

    for audio_base64 in list(chunk_audio_base64_list or []):
        raw = base64.b64decode(str(audio_base64 or "").encode("utf-8"))
        with sf.SoundFile(io.BytesIO(raw)) as sound_file:
            wav = sound_file.read(dtype="float32")
            wav_sr = int(sound_file.samplerate or 0)
        if wav_sr <= 0:
            continue
        wav_array = np.asarray(wav, dtype=np.float32)
        if wav_array.ndim > 1:
            wav_array = np.mean(wav_array, axis=1)
        if wav_array.size == 0:
            continue
        if sample_rate is None:
            sample_rate = wav_sr
        elif wav_sr != sample_rate:
            wav_array = resample_mono_audio(wav_array, wav_sr, sample_rate)
        if stitched_parts and safe_gap_sec > 0 and sample_rate:
            stitched_parts.append(np.zeros(int(round(sample_rate * safe_gap_sec)), dtype=np.float32))
        stitched_parts.append(wav_array)

    if sample_rate is None or not stitched_parts:
        raise RuntimeError("VoxCPM unstable retry produced no valid audio")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stitched_audio = np.concatenate(stitched_parts).astype(np.float32, copy=False)
    peak = float(np.max(np.abs(stitched_audio))) if stitched_audio.size > 0 else 0.0
    if peak > 0.99:
        stitched_audio = stitched_audio / peak * 0.99
    sf.write(str(output_path), stitched_audio, sample_rate)


def _call_voxcpm_tts_with_unstable_retry(
    *,
    api_url: str,
    text: str,
    prompt_audio_path: Path,
    prompt_text: str,
    cfg_value: float,
    inference_timesteps: int,
    retry_output_path: Path,
) -> Dict[str, Any]:
    """先正常调用 VoxCPM；若明确要求缩短文本，则自动拆小重试并拼回单段音频。"""

    try:
        return _call_voxcpm_tts(
            api_url=api_url,
            text=text,
            prompt_audio_path=prompt_audio_path,
            prompt_text=prompt_text,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
        )
    except Exception as exc:
        if not _is_voxcpm_unstable_generation_error(exc):
            raise
        retry_segments = _split_voxcpm_text_into_complete_sentences(text)
        retry_segments = _merge_voxcpm_open_quote_sentences(retry_segments)
        retry_segments = _merge_voxcpm_adjacent_ascii_sentences(retry_segments)
        retry_segments = _merge_voxcpm_quote_adjacent_ascii_group(retry_segments)
        if len(retry_segments) <= 1:
            raise
        retry_audio_base64_list: List[str] = []
        for segment_text in retry_segments:
            segment_text_clean = str(segment_text or "").strip()
            if not segment_text_clean:
                continue
            response = _call_voxcpm_tts(
                api_url=api_url,
                text=segment_text_clean,
                prompt_audio_path=prompt_audio_path,
                prompt_text=prompt_text,
                cfg_value=cfg_value,
                inference_timesteps=inference_timesteps,
            )
            audio_base64 = str(response.get("audio_base64") or "").strip()
            if not audio_base64:
                raise RuntimeError("VoxCPM unstable retry returned empty audio")
            retry_audio_base64_list.append(audio_base64)
        if len(retry_audio_base64_list) <= 1:
            raise
        _write_voxcpm_retry_concat_wav(
            chunk_audio_base64_list=retry_audio_base64_list,
            output_path=retry_output_path,
        )
        return {"audio_base64": base64.b64encode(retry_output_path.read_bytes()).decode("utf-8")}


def _soft_align_segment(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> Dict[str, Any]:
    """对 VoxCPM 输出做轻量整理：只裁静音，不强制压缩到字幕窗。"""

    trimmed_input_path = input_path
    raw_duration = max(0.01, audio_duration(input_path))
    trim_meta = {
        "trimmed_input": False,
        "trimmed_raw_duration_sec": round(raw_duration, 3),
        "trimmed_output_duration_sec": round(raw_duration, 3),
    }
    if raw_duration > 0.20:
        trimmed_probe_path = input_path.parent / f"{input_path.stem}_trim.wav"
        try:
            before_sec, after_sec = trim_silence_edges(
                input_path=input_path,
                output_path=trimmed_probe_path,
                threshold_db=-35.0,
                pad_sec=0.05,
                min_keep_sec=0.10,
            )
            if after_sec > 0 and after_sec + 0.02 < before_sec:
                trimmed_input_path = trimmed_probe_path
                trim_meta = {
                    "trimmed_input": True,
                    "trimmed_raw_duration_sec": round(before_sec, 3),
                    "trimmed_output_duration_sec": round(after_sec, 3),
                }
        except Exception:
            trimmed_input_path = input_path

    actual_duration = max(0.01, audio_duration(trimmed_input_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if trimmed_input_path.resolve() == output_path.resolve():
        pass
    else:
        shutil.copy2(trimmed_input_path, output_path)
    return {
        "mode": "natural_trimmed" if trim_meta["trimmed_input"] else "natural_passthrough",
        "raw_duration_sec": round(actual_duration, 3),
        "aligned_duration_sec": round(actual_duration, 3),
        "target_duration_sec": round(max(0.05, float(target_duration_sec)), 3),
        **trim_meta,
    }


def _format_ass_time(seconds_value: float) -> str:
    """把秒数格式化成 ASS 时间戳 `H:MM:SS.cc`。"""

    total_centiseconds = max(0, int(round(float(seconds_value or 0.0) * 100.0)))
    hours, rem = divmod(total_centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    """转义 ASS 正文，避免花括号被误识别成 override block。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    normalized = normalized.replace("{", "｛").replace("}", "｝")
    lines = [line.strip() for line in normalized.split("\n")]
    return r"\N".join(line for line in lines if line)


def _estimate_ass_display_units(char: str) -> int:
    """粗估单字符显示宽度，供 120 字号的中部字幕换行使用。"""

    value = str(char or "")
    if not value:
        return 0
    if value.isspace():
        return 1
    east_asian = unicodedata.east_asian_width(value)
    if east_asian in {"F", "W"}:
        return 2
    return 1


def _wrap_voxcpm_ass_text_lines(text: str, *, max_units_per_line: int = 24) -> List[str]:
    """把字幕按安全宽度折成多行，避免 120 字号时横向超界且垂直行数过多。"""

    safe_max_units = max(6, int(max_units_per_line))
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    wrapped_lines: List[str] = []
    break_chars = set(" ，。、！？；：,.!?;:)]）】》」』、】【>」")
    for paragraph in normalized.split("\n"):
        buffer = ""
        buffer_units = 0
        last_break_index = -1
        raw_paragraph = paragraph.strip()
        if not raw_paragraph:
            continue
        for char in raw_paragraph:
            char_units = _estimate_ass_display_units(char)
            if buffer and buffer_units + char_units > safe_max_units:
                if 0 < last_break_index < len(buffer):
                    line = buffer[:last_break_index].rstrip()
                    remain = buffer[last_break_index:].lstrip() + char
                else:
                    line = buffer.rstrip()
                    remain = char
                if line:
                    wrapped_lines.append(line)
                buffer = remain
                buffer_units = sum(_estimate_ass_display_units(item) for item in buffer)
                last_break_index = -1
                for idx, item in enumerate(buffer, start=1):
                    if item in break_chars or item.isspace():
                        last_break_index = idx
                continue
            buffer += char
            buffer_units += char_units
            if char in break_chars or char.isspace():
                last_break_index = len(buffer)
        if buffer.strip():
            wrapped_lines.append(buffer.strip())
    return wrapped_lines


def _chunk_voxcpm_wrapped_lines(
    wrapped_lines: List[str],
    *,
    max_lines_per_page: int = DEFAULT_VOXCPM_MAX_LINES_PER_PAGE,
) -> List[List[str]]:
    """把超长多行字幕分页，避免单页行数过多导致中部字幕超出画面。"""

    safe_max_lines = max(1, int(max_lines_per_page))
    pages: List[List[str]] = []
    for start in range(0, len(wrapped_lines), safe_max_lines):
        page = [str(line or "").strip() for line in wrapped_lines[start : start + safe_max_lines] if str(line or "").strip()]
        if page:
            pages.append(page)
    return pages


def _build_voxcpm_typewriter_dialogues_for_lines(
    *,
    start_sec: float,
    end_sec: float,
    wrapped_lines: List[str],
) -> List[str]:
    """按给定多行文本生成一页打字机 Dialogue。"""

    if not wrapped_lines:
        return []

    reveal_states: List[str] = []
    rendered_prefix_lines: List[str] = []
    for line in wrapped_lines:
        current_line = ""
        for char in line:
            current_line += char
            reveal_states.append(r"\N".join(rendered_prefix_lines + [current_line]))
        rendered_prefix_lines.append(line)

    if not reveal_states:
        return []

    start_centiseconds = max(0, int(round(float(start_sec or 0.0) * 100.0)))
    end_centiseconds = max(start_centiseconds + 1, int(round(float(end_sec or 0.0) * 100.0)))
    total_centiseconds = max(1, end_centiseconds - start_centiseconds)
    safe_hold_centiseconds = min(
        max(0, int(round(DEFAULT_VOXCPM_TYPEWRITER_HOLD_SEC * 100.0))),
        max(0, total_centiseconds - 1),
    )
    if len(reveal_states) <= 1:
        safe_hold_centiseconds = 0
    else:
        safe_hold_centiseconds = min(
            safe_hold_centiseconds,
            max(0, int(math.floor(total_centiseconds * 0.35))),
        )
    reveal_centiseconds = max(1, total_centiseconds - safe_hold_centiseconds)
    step_count = min(len(reveal_states), reveal_centiseconds)
    dialogues: List[str] = []

    for step_index in range(step_count):
        step_start_cs = start_centiseconds + math.floor(reveal_centiseconds * step_index / step_count)
        step_end_cs = start_centiseconds + math.floor(reveal_centiseconds * (step_index + 1) / step_count)
        if step_end_cs <= step_start_cs:
            continue
        reveal_index = math.ceil(len(reveal_states) * (step_index + 1) / step_count) - 1
        reveal_text = _escape_ass_text(reveal_states[max(0, reveal_index)])
        if not reveal_text:
            continue
        dialogues.append(
            f"Dialogue: 0,{_format_ass_time(step_start_cs / 100.0)},{_format_ass_time(step_end_cs / 100.0)},Default,,0,0,0,,{reveal_text}"
        )
    if safe_hold_centiseconds > 0:
        hold_start_cs = start_centiseconds + reveal_centiseconds
        final_text = _escape_ass_text(r"\N".join(wrapped_lines))
        if final_text and end_centiseconds > hold_start_cs:
            dialogues.append(
                f"Dialogue: 0,{_format_ass_time(hold_start_cs / 100.0)},{_format_ass_time(end_centiseconds / 100.0)},Default,,0,0,0,,{final_text}"
            )
    return dialogues


def _build_voxcpm_typewriter_dialogues(*, start_sec: float, end_sec: float, text: str) -> List[str]:
    """把一条字幕拆成多条 ASS Dialogue，形成从左到右、从上到下的分页打字机效果。"""

    wrapped_lines = _wrap_voxcpm_ass_text_lines(text)
    if not wrapped_lines:
        return []
    pages = _chunk_voxcpm_wrapped_lines(wrapped_lines)
    if not pages:
        return []

    start_centiseconds = max(0, int(round(float(start_sec or 0.0) * 100.0)))
    end_centiseconds = max(start_centiseconds + 1, int(round(float(end_sec or 0.0) * 100.0)))
    total_centiseconds = max(1, end_centiseconds - start_centiseconds)
    page_weights = [max(1, sum(len(line) for line in page)) for page in pages]
    total_weight = max(1, sum(page_weights))
    dialogues: List[str] = []

    allocated_centiseconds = 0
    for page_index, page_lines in enumerate(pages):
        page_start_cs = start_centiseconds + allocated_centiseconds
        if page_index == len(pages) - 1:
            page_end_cs = end_centiseconds
        else:
            page_span_cs = max(1, int(round(total_centiseconds * (page_weights[page_index] / total_weight))))
            page_end_cs = min(end_centiseconds, page_start_cs + page_span_cs)
        if page_end_cs <= page_start_cs:
            page_end_cs = min(end_centiseconds, page_start_cs + 1)
        dialogues.extend(
            _build_voxcpm_typewriter_dialogues_for_lines(
                start_sec=page_start_cs / 100.0,
                end_sec=page_end_cs / 100.0,
                wrapped_lines=page_lines,
            )
        )
        allocated_centiseconds = max(0, page_end_cs - start_centiseconds)
    return dialogues


def _build_voxcpm_typewriter_dialogues_with_layout(
    *,
    start_sec: float,
    end_sec: float,
    text: str,
    layout: Dict[str, int],
) -> List[str]:
    """按画幅配置生成分页打字机 Dialogue，避免不同分辨率下字幕越界。"""

    wrapped_lines = _wrap_voxcpm_ass_text_lines(
        text,
        max_units_per_line=int(layout.get("max_units_per_line", 24)),
    )
    if not wrapped_lines:
        return []
    pages = _chunk_voxcpm_wrapped_lines(
        wrapped_lines,
        max_lines_per_page=int(layout.get("max_lines_per_page", DEFAULT_VOXCPM_MAX_LINES_PER_PAGE)),
    )
    if not pages:
        return []

    start_centiseconds = max(0, int(round(float(start_sec or 0.0) * 100.0)))
    end_centiseconds = max(start_centiseconds + 1, int(round(float(end_sec or 0.0) * 100.0)))
    total_centiseconds = max(1, end_centiseconds - start_centiseconds)
    page_weights = [max(1, sum(len(line) for line in page)) for page in pages]
    total_weight = max(1, sum(page_weights))
    dialogues: List[str] = []

    allocated_centiseconds = 0
    for page_index, page_lines in enumerate(pages):
        page_start_cs = start_centiseconds + allocated_centiseconds
        if page_index == len(pages) - 1:
            page_end_cs = end_centiseconds
        else:
            page_span_cs = max(1, int(round(total_centiseconds * (page_weights[page_index] / total_weight))))
            page_end_cs = min(end_centiseconds, page_start_cs + page_span_cs)
        if page_end_cs <= page_start_cs:
            page_end_cs = min(end_centiseconds, page_start_cs + 1)
        dialogues.extend(
            _build_voxcpm_typewriter_dialogues_for_lines(
                start_sec=page_start_cs / 100.0,
                end_sec=page_end_cs / 100.0,
                wrapped_lines=page_lines,
            )
        )
        allocated_centiseconds = max(0, page_end_cs - start_centiseconds)
    return dialogues


def _build_voxcpm_centered_ass_from_rows(
    rows: List[Dict[str, Any]],
    *,
    source_name: str,
    subtitle_video_preset: str = DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET,
) -> str:
    """按 6 号面板所选画幅导出居中黑底字幕 ASS，并使用安全换行 + 打字机效果。"""

    layout = _get_voxcpm_subtitle_video_layout(subtitle_video_preset)

    header_lines = [
        "[Script Info]",
        f"; Converted from {source_name}",
        "; Style: centered typewriter subtitles on black-background VoxCPM video",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        f"PlayResX: {int(layout['width'])}",
        f"PlayResY: {int(layout['height'])}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            "Style: Default,Arial Unicode MS,"
            f"{int(layout['font_size'])},&H00FFFFFF,&H000000FF,&H000066FF,&HEEFFFF00,-1,0,0,0,100,100,0,0,4,4,0,5,"
            f"{int(layout['margin_l'])},{int(layout['margin_r'])},{int(layout['margin_v'])},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    dialogue_lines: List[str] = []
    for row in rows:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        if end_sec <= start_sec:
            continue
        dialogue_lines.extend(
            _build_voxcpm_typewriter_dialogues_with_layout(
                start_sec=start_sec,
                end_sec=end_sec,
                text=str(row.get("text") or ""),
                layout=layout,
            )
        )
    return "\n".join(header_lines + dialogue_lines) + "\n"


def _apply_voxcpm_final_script_variant(
    rows: List[Dict[str, Any]],
    variant: str,
    *,
    target_lang: str = "",
) -> List[Dict[str, Any]]:
    """把最终输出字幕按粤语目标语的脚本开关转换。"""

    if not _is_voxcpm_cantonese_target_lang(target_lang):
        return list(rows or [])
    normalized_variant = _normalize_voxcpm_subtitle_script_variant(variant)
    if normalized_variant == "traditional":
        return list(rows or [])
    return convert_chinese_script_rows(rows, normalized_variant)


def _compose_natural_sequence_mix(
    *,
    segment_manifests: List[Dict[str, Any]],
    output_wav: Path,
    gap_sec: float = DEFAULT_VOXCPM_NATURAL_GAP_SEC,
) -> List[Dict[str, Any]]:
    """按真实生成时长顺序拼接 6 号面板音频，并重建最终字幕时间轴。"""

    valid_segments: List[Tuple[Dict[str, Any], Path]] = []
    for manifest in segment_manifests:
        path_text = str(((manifest.get("paths") or {}).get("dubbed_vocals")) or "").strip()
        if not path_text:
            continue
        wav_path = Path(path_text).expanduser()
        if wav_path.exists():
            valid_segments.append((manifest, wav_path))
    if not valid_segments:
        raise RuntimeError("VoxCPM no valid segment audio to compose")

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    safe_gap_sec = max(0.0, float(gap_sec))
    first_audio, sample_rate = load_mono_audio(valid_segments[0][1])
    if sample_rate <= 0 or first_audio.size == 0:
        raise RuntimeError("VoxCPM first segment audio invalid")

    stitched_parts: List[np.ndarray] = []
    final_rows: List[Dict[str, Any]] = []
    cursor_sec = 0.0
    gap_template = np.zeros(max(0, int(round(sample_rate * safe_gap_sec))), dtype=np.float32)

    for index, (manifest, wav_path) in enumerate(valid_segments):
        wav, wav_sr = load_mono_audio(wav_path)
        if wav.size == 0:
            continue
        if wav_sr != sample_rate:
            wav = resample_mono_audio(wav, wav_sr, sample_rate)
        wav = np.asarray(wav, dtype=np.float32)
        duration_sec = max(0.01, float(len(wav) / sample_rate))
        start_sec = cursor_sec
        end_sec = start_sec + duration_sec
        final_rows.append(
            {
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "text": str(manifest.get("text") or "").strip(),
                "speaker_id": str(manifest.get("speaker_id") or "").strip() or "Speaker 1",
            }
        )
        stitched_parts.append(wav)
        cursor_sec = end_sec
        if index < len(valid_segments) - 1 and gap_template.size > 0:
            stitched_parts.append(gap_template.copy())
            cursor_sec += safe_gap_sec

    if not stitched_parts:
        raise RuntimeError("VoxCPM no stitched audio generated")

    stitched_audio = np.concatenate(stitched_parts).astype(np.float32, copy=False)
    peak = float(np.max(np.abs(stitched_audio))) if stitched_audio.size > 0 else 0.0
    if peak > 0.99:
        stitched_audio = stitched_audio / peak * 0.99
    sf.write(str(output_wav), stitched_audio, sample_rate)
    return final_rows


def _build_voxcpm_uploaded_speaker_ref_map(
    *,
    out_root: Path,
    speaker_ids: List[str],
    speaker_ref_files: List[UploadFile],
    speaker_ref_speaker_ids_json: str,
    target_lang: str,
) -> Dict[str, Dict[str, Any]]:
    """把 6 号面板前端上传的多 speaker 参考音转成后端统一映射。"""

    uploaded_speaker_ref_map: Dict[str, Dict[str, Any]] = {}
    if not str(speaker_ref_speaker_ids_json or "").strip():
        return uploaded_speaker_ref_map
    try:
        speaker_ids_payload = json.loads(speaker_ref_speaker_ids_json)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_speaker_ids_json: {exc}") from exc
    if not isinstance(speaker_ids_payload, list):
        raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json must be a list")
    if len(speaker_ids_payload) != len(speaker_ref_files):
        raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json count must match speaker_ref_files")

    uploaded_ref_dir = out_root / "uploaded_speaker_refs"
    uploaded_ref_dir.mkdir(parents=True, exist_ok=True)
    for speaker_id, ref_file in zip(speaker_ids_payload, speaker_ref_files):
        normalized_speaker_id = str(speaker_id or "").strip()
        if not normalized_speaker_id:
            continue
        if normalized_speaker_id not in speaker_ids:
            raise HTTPException(status_code=400, detail=f"unknown speaker_id in uploaded VoxCPM references: {normalized_speaker_id}")
        stored_path = _store_uploaded_reference_file(
            upload_dir=uploaded_ref_dir,
            file=ref_file,
            fallback_name=f"{_safe_speaker_name(normalized_speaker_id) or 'speaker'}_ref.wav",
        )
        if not stored_path:
            continue
        uploaded_speaker_ref_map[normalized_speaker_id] = {
            "ref_audio": stored_path,
            "ref_text": _speaker_ref_text_for_target_lang(target_lang),
            "duration": round(float(sf.info(stored_path).duration), 3),
            "source_count": 1,
            "reference_mode": "uploaded_partial",
            "upload_filename": Path(str(ref_file.filename or "")).name,
        }
    return uploaded_speaker_ref_map


def _build_voxcpm_video_variant_artifact_key(preset: str) -> str:
    """为补生成的视频规格构造稳定 artifact key。"""

    normalized = _normalize_voxcpm_subtitle_video_preset(preset)
    return f"video_{normalized}"


def _build_voxcpm_ass_variant_artifact_key(preset: str) -> str:
    """为补生成的 ASS 规格构造稳定 artifact key。"""

    normalized = _normalize_voxcpm_subtitle_video_preset(preset)
    return f"ass_{normalized}"


def _build_voxcpm_variant_paths(out_root: Path, preset: str) -> Dict[str, Path]:
    """根据规格返回独立命名的 ASS / 视频路径，避免覆盖默认主产物。"""

    normalized = _normalize_voxcpm_subtitle_video_preset(preset)
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ass": final_dir / f"dubbed_final_full-styled-{normalized}.ass",
        "video": final_dir / f"dubbed_video_full-{normalized}.mp4",
    }


def _build_voxcpm_video_variant_entry(task_id: str, preset: str, ass_path: Path, video_path: Path) -> Dict[str, Any]:
    """把单个字幕视频规格封装为 manifest / 前端共用的结构。"""

    normalized = _normalize_voxcpm_subtitle_video_preset(preset)
    return {
        "preset": normalized,
        "ass_artifact_key": _build_voxcpm_ass_variant_artifact_key(normalized),
        "video_artifact_key": _build_voxcpm_video_variant_artifact_key(normalized),
        "ass_url": _artifact_url(task_id, _build_voxcpm_ass_variant_artifact_key(normalized)),
        "video_url": _artifact_url(task_id, _build_voxcpm_video_variant_artifact_key(normalized)),
        "ass_path": str(ass_path.resolve()),
        "video_path": str(video_path.resolve()),
    }


def _collect_voxcpm_video_variants(
    *,
    task_id: str,
    out_root: Path,
    default_preset: str,
    default_ass_path: Optional[Path],
    default_video_path: Optional[Path],
) -> List[Dict[str, Any]]:
    """扫描并组装当前批次已生成的所有字幕视频规格。"""

    variants: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    normalized_default = _normalize_voxcpm_subtitle_video_preset(default_preset)

    if default_ass_path and default_video_path and default_ass_path.exists() and default_video_path.exists():
        variants.append(
            _build_voxcpm_video_variant_entry(
                task_id,
                normalized_default,
                default_ass_path,
                default_video_path,
            )
        )
        seen.add(normalized_default)

    for preset in VOXCPM_SUBTITLE_VIDEO_LAYOUTS.keys():
        normalized = _normalize_voxcpm_subtitle_video_preset(preset)
        if normalized in seen:
            continue
        variant_paths = _build_voxcpm_variant_paths(out_root, normalized)
        if variant_paths["ass"].exists() and variant_paths["video"].exists():
            variants.append(
                _build_voxcpm_video_variant_entry(
                    task_id,
                    normalized,
                    variant_paths["ass"],
                    variant_paths["video"],
                )
            )
            seen.add(normalized)

    variants.sort(key=lambda item: (0 if item.get("preset") == normalized_default else 1, str(item.get("preset") or "")))
    return variants


def _build_voxcpm_artifacts(
    *,
    task_id: str,
    out_root: Path,
    selected_subtitles_exists: bool,
    selected_subtitles_rebuild_exists: bool,
    selected_subtitles_translated_exists: bool,
    selected_subtitles_with_speakers_exists: bool,
    final_srt_exists: bool,
    final_srt_rebuild_exists: bool,
    final_srt_with_speaker_exists: bool,
    final_mix_exists: bool,
    default_ass_exists: bool,
    prepared_audio_exists: bool,
    video_variants: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """统一构建 6 号面板产物列表，允许多个视频规格并存。"""

    artifacts: List[Dict[str, str]] = []
    if selected_subtitles_exists:
        artifacts.append({"key": "selected_srt", "label": "Selected Subtitles SRT", "url": _artifact_url(task_id, "selected_srt")})
    if selected_subtitles_rebuild_exists:
        artifacts.append({"key": "selected_srt_rebuild", "label": "Selected Subtitles SRT (Rebuild)", "url": _artifact_url(task_id, "selected_srt_rebuild")})
    if selected_subtitles_translated_exists:
        artifacts.append({"key": "selected_srt_translated", "label": "Selected Subtitles SRT (Translated)", "url": _artifact_url(task_id, "selected_srt_translated")})
    if selected_subtitles_with_speakers_exists:
        artifacts.append({"key": "selected_srt_with_speaker", "label": "Selected Subtitles SRT (With Speakers)", "url": _artifact_url(task_id, "selected_srt_with_speaker")})
    if final_srt_exists:
        artifacts.append({"key": "srt", "label": "Dubbed Final SRT", "url": _artifact_url(task_id, "srt")})
    if final_srt_rebuild_exists:
        artifacts.append({"key": "srt_rebuild", "label": "Dubbed Final Rebuild SRT", "url": _artifact_url(task_id, "srt_rebuild")})
    if final_srt_with_speaker_exists:
        artifacts.append({"key": "srt_with_speaker", "label": "Dubbed Final SRT (With Speakers)", "url": _artifact_url(task_id, "srt_with_speaker")})
    primary_variant = video_variants[0] if video_variants else None
    if primary_variant:
        artifacts.append({"key": "video", "label": f"Dubbed Video MP4 ({primary_variant['preset']})", "url": str(primary_variant["video_url"])})
    if final_mix_exists:
        artifacts.append({"key": "mix", "label": "Dubbed Mix WAV", "url": _artifact_url(task_id, "mix")})
    if default_ass_exists:
        artifacts.append({"key": "ass", "label": "Dubbed Final ASS", "url": _artifact_url(task_id, "ass")})
    for variant in video_variants:
        preset = str(variant.get("preset") or "")
        if variant is not primary_variant:
            artifacts.append({"key": str(variant["video_artifact_key"]), "label": f"Dubbed Video MP4 ({preset})", "url": str(variant["video_url"])})
        artifacts.append({"key": str(variant["ass_artifact_key"]), "label": f"Dubbed Final ASS ({preset})", "url": str(variant["ass_url"])})
    if prepared_audio_exists:
        artifacts.append({"key": "video_audio", "label": "Dubbed Audio M4A", "url": _artifact_url(task_id, "video_audio")})
    artifacts.append({"key": "manifest", "label": "Manifest JSON", "url": _artifact_url(task_id, "manifest")})
    return artifacts


def _render_voxcpm_video_variant(
    *,
    task_id: str,
    out_root: Path,
    rows: List[Dict[str, Any]],
    final_mix_path: Path,
    source_name: str,
    preset: str,
) -> Dict[str, Any]:
    """按指定规格重新生成 ASS 与黑底字幕视频，不重跑配音。"""

    normalized = _normalize_voxcpm_subtitle_video_preset(preset)
    variant_paths = _build_voxcpm_variant_paths(out_root, normalized)
    variant_paths["ass"].write_text(
        _build_voxcpm_centered_ass_from_rows(
            rows,
            source_name=source_name,
            subtitle_video_preset=normalized,
        ),
        encoding="utf-8",
    )
    layout = _get_voxcpm_subtitle_video_layout(normalized)
    build_black_video_with_ass_subtitles(
        audio_path=final_mix_path,
        ass_subtitle_path=variant_paths["ass"],
        output_video_path=variant_paths["video"],
        width=int(layout["width"]),
        height=int(layout["height"]),
    )
    return _build_voxcpm_video_variant_entry(
        task_id,
        normalized,
        variant_paths["ass"],
        variant_paths["video"],
    )


def _build_manifest(
    *,
    task: Dict[str, Any],
    out_root: Path,
    source_audio_path: Optional[Path],
    selected_subtitles_path: Path,
    selected_subtitles_rebuild_path: Optional[Path],
    selected_subtitles_translated_path: Optional[Path],
    selected_subtitles_tts_rows: Optional[List[Dict[str, Any]]],
    selected_subtitles_with_speakers_path: Optional[Path],
    subtitles_path: Path,
    subtitles_rebuild_path: Optional[Path],
    subtitles_with_speaker_path: Optional[Path],
    final_mix_path: Path,
    final_video_path: Optional[Path],
    prepared_audio_path: Optional[Path],
    final_ass_path: Optional[Path],
    ref_audio_path: Optional[Path],
    ref_text: str,
    cfg_value: float,
    inference_timesteps: int,
    subtitle_script_variant: str = DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT,
    subtitle_video_preset: str = DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET,
    translate_base_url: str = DEFAULT_TRANSLATE_BASE_URL,
    translate_model: str = DEFAULT_TRANSLATE_MODEL,
    speaker_ref_map: Optional[Dict[str, Dict[str, Any]]] = None,
    speaker_reference_mode: str = "",
) -> Dict[str, Any]:
    """写 manifest，供批次加载与 resume 复用。"""
    normalized_video_preset = _normalize_voxcpm_subtitle_video_preset(subtitle_video_preset)
    video_variants = _collect_voxcpm_video_variants(
        task_id=task["id"],
        out_root=out_root,
        default_preset=normalized_video_preset,
        default_ass_path=final_ass_path,
        default_video_path=final_video_path,
    )
    artifacts = _build_voxcpm_artifacts(
        task_id=task["id"],
        out_root=out_root,
        selected_subtitles_exists=bool(selected_subtitles_path and selected_subtitles_path.exists()),
        selected_subtitles_rebuild_exists=bool(selected_subtitles_rebuild_path and selected_subtitles_rebuild_path.exists()),
        selected_subtitles_translated_exists=bool(selected_subtitles_translated_path and selected_subtitles_translated_path.exists()),
        selected_subtitles_with_speakers_exists=bool(selected_subtitles_with_speakers_path and selected_subtitles_with_speakers_path.exists()),
        final_srt_exists=subtitles_path.exists(),
        final_srt_rebuild_exists=bool(subtitles_rebuild_path and subtitles_rebuild_path.exists()),
        final_srt_with_speaker_exists=bool(subtitles_with_speaker_path and subtitles_with_speaker_path.exists()),
        final_mix_exists=final_mix_path.exists(),
        default_ass_exists=bool(final_ass_path and final_ass_path.exists()),
        prepared_audio_exists=bool(prepared_audio_path and prepared_audio_path.exists()),
        video_variants=video_variants,
    )
    primary_video_entry = next((item for item in video_variants if item.get("preset") == normalized_video_preset), video_variants[0] if video_variants else None)

    manifest = {
        "task_id": task["id"],
        "batch_id": task["batch_id"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "status": task["status"],
        "stage": task["stage"],
        "progress": task["progress"],
        "project_filename": task["project_filename"],
        "input_media_path": task["input_media_path"],
        "subtitle_mode": task["subtitle_mode"],
        "selected_subtitle_mode": task.get("selected_subtitle_mode"),
        "source_lang": task["source_lang"],
        "target_lang": task["target_lang"],
        "voxcpm_api_url": task["voxcpm_api_url"],
        "translate_base_url": str(translate_base_url or task.get("translate_base_url") or DEFAULT_TRANSLATE_BASE_URL),
        "translate_model": str(translate_model or task.get("translate_model") or DEFAULT_TRANSLATE_MODEL),
        "ref_audio_path": str(ref_audio_path.resolve()) if ref_audio_path and ref_audio_path.exists() else "",
        "ref_text": ref_text,
        "speaker_ids": list(task.get("speaker_ids") or []),
        "speaker_reference_mode": str(speaker_reference_mode or task.get("speaker_reference_mode") or ""),
        "speaker_ref_map": speaker_ref_map or {},
        "source_subtitles_count": task["source_subtitles_count"],
        "translated_subtitles_count": task["translated_subtitles_count"],
        "processed_segments": task.get("processed_segments", 0),
        "segment_count": task.get("total_segments", 0),
        "cfg_value": float(cfg_value),
        "inference_timesteps": int(inference_timesteps),
        "selected_subtitles_tts_rows": list(selected_subtitles_tts_rows or []),
        "subtitle_script_variant": _normalize_voxcpm_subtitle_script_variant(subtitle_script_variant),
        "subtitle_video_preset": normalized_video_preset,
        "generated_subtitle_video_presets": [str(item.get("preset") or "") for item in video_variants],
        "subtitle_video_variants": video_variants,
        "preferred_video_artifact_key": str(primary_video_entry.get("video_artifact_key") if primary_video_entry else "video"),
        "paths": {
            "source_audio": str(source_audio_path.resolve()) if source_audio_path and source_audio_path.exists() else None,
            "selected_subtitles": str(selected_subtitles_path.resolve()) if selected_subtitles_path.exists() else None,
            "selected_subtitles_rebuild": str(selected_subtitles_rebuild_path.resolve()) if selected_subtitles_rebuild_path and selected_subtitles_rebuild_path.exists() else None,
            "selected_subtitles_translated": str(selected_subtitles_translated_path.resolve()) if selected_subtitles_translated_path and selected_subtitles_translated_path.exists() else None,
            "selected_subtitles_with_speakers": str(selected_subtitles_with_speakers_path.resolve()) if selected_subtitles_with_speakers_path and selected_subtitles_with_speakers_path.exists() else None,
            "dubbed_final_srt": str(subtitles_path.resolve()) if subtitles_path.exists() else None,
            "dubbed_final_srt_rebuild": str(subtitles_rebuild_path.resolve()) if subtitles_rebuild_path and subtitles_rebuild_path.exists() else None,
            "dubbed_final_srt_with_speakers": str(subtitles_with_speaker_path.resolve()) if subtitles_with_speaker_path and subtitles_with_speaker_path.exists() else None,
            "dubbed_mix": str(final_mix_path.resolve()) if final_mix_path.exists() else None,
            "dubbed_final_ass": str(final_ass_path.resolve()) if final_ass_path and final_ass_path.exists() else None,
            "dubbed_audio_for_video": str(prepared_audio_path.resolve()) if prepared_audio_path and prepared_audio_path.exists() else None,
            "dubbed_video_full": str(final_video_path.resolve()) if final_video_path and final_video_path.exists() else None,
            "subtitle_video_variants": {
                str(item.get("preset") or ""): {
                    "ass": str(item.get("ass_path") or ""),
                    "video": str(item.get("video_path") or ""),
                }
                for item in video_variants
            },
            "manifest": str((out_root / "manifest.json").resolve()),
        },
        "artifacts": artifacts,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _persist_voxcpm_task_manifest(
    *,
    task_id: str,
    out_root: Path,
    source_audio_path: Optional[Path],
    selected_subtitles_path: Path,
    selected_subtitles_rebuild_path: Optional[Path],
    selected_subtitles_translated_path: Optional[Path],
    subtitles_rebuild_path: Optional[Path],
    selected_subtitles_with_speakers_path: Optional[Path],
    subtitles_path: Path,
    subtitles_with_speaker_path: Optional[Path],
    final_mix_path: Path,
    final_video_path: Optional[Path],
    prepared_audio_path: Optional[Path],
    final_ass_path: Optional[Path],
    ref_audio_path: Optional[Path],
    ref_text: str,
    cfg_value: float,
    inference_timesteps: int,
    selected_subtitles_tts_rows: Optional[List[Dict[str, Any]]] = None,
    subtitle_script_variant: str = DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT,
    subtitle_video_preset: str = DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET,
    speaker_ref_map: Optional[Dict[str, Dict[str, Any]]] = None,
    speaker_reference_mode: str = "",
) -> Optional[Dict[str, Any]]:
    """把当前 VoxCPM 任务快照写回 manifest，供 load-batch 与 resume 复用。"""

    task = _task_store.get(task_id)
    if task is None:
        return None
    manifest = _build_manifest(
        task=task,
        out_root=out_root,
        source_audio_path=source_audio_path,
        selected_subtitles_path=selected_subtitles_path,
        selected_subtitles_rebuild_path=selected_subtitles_rebuild_path,
        selected_subtitles_translated_path=selected_subtitles_translated_path,
        selected_subtitles_tts_rows=selected_subtitles_tts_rows,
        subtitles_rebuild_path=subtitles_rebuild_path,
        selected_subtitles_with_speakers_path=selected_subtitles_with_speakers_path,
        subtitles_path=subtitles_path,
        subtitles_with_speaker_path=subtitles_with_speaker_path,
        final_mix_path=final_mix_path,
        final_video_path=final_video_path,
        prepared_audio_path=prepared_audio_path,
        final_ass_path=final_ass_path,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        cfg_value=cfg_value,
        inference_timesteps=inference_timesteps,
        subtitle_script_variant=subtitle_script_variant,
        subtitle_video_preset=subtitle_video_preset,
        speaker_ref_map=speaker_ref_map,
        speaker_reference_mode=speaker_reference_mode,
    )
    _annotate_voxcpm_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=False)
    return manifest


def _load_manifest(batch_id: str) -> Optional[Dict[str, Any]]:
    """加载已存在的 VoxCPM 批次 manifest。"""

    manifest_path = _resolve_output_dir(batch_id) / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        payload["_manifest_path"] = str(manifest_path.resolve())
    return payload if isinstance(payload, dict) else None


def _load_selected_subtitles_from_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 manifest 恢复 TTS 真实输入字幕，优先读取拆分后的内部文件。"""

    manifest_rows = list(manifest.get("selected_subtitles_tts_rows") or [])
    rows: List[Dict[str, Any]] = []
    for item in manifest_rows:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if not text.strip():
            continue
        rows.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
                "speaker_id": str(item.get("speaker_id") or "").strip(),
            }
        )
    if rows:
        return rows

    paths = dict(manifest.get("paths") or {})
    selected_path = _resolve_existing_optional_path(
        paths.get("selected_subtitles_translated") or paths.get("selected_subtitles_rebuild") or paths.get("selected_subtitles")
    )
    if selected_path is None:
        return []
    try:
        items = parse_srt(selected_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    fallback_rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        fallback_rows.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
            }
        )
    return fallback_rows


def _segment_row_matches_manifest(row: Dict[str, Any], segment_manifest: Dict[str, Any]) -> bool:
    """判断磁盘 segment 结果是否仍对应当前行。"""

    if str(row.get("text") or "").strip() != str(segment_manifest.get("text") or "").strip():
        return False
    expected_start = float(row.get("start", 0.0) or 0.0)
    expected_end = float(row.get("end", 0.0) or 0.0)
    actual_start = float(segment_manifest.get("start_sec", 0.0) or 0.0)
    actual_end = float(segment_manifest.get("end_sec", 0.0) or 0.0)
    return abs(expected_start - actual_start) <= 0.02 and abs(expected_end - actual_end) <= 0.02


def _collect_resumable_segment_results(
    *,
    segment_root: Path,
    selected_rows: List[Dict[str, Any]],
) -> Tuple[Set[int], List[Dict[str, Any]]]:
    """扫描已完成 segment，只复用 manifest 与 wav 都完整且内容匹配的条目。"""

    completed_indices: Set[int] = set()
    reusable_results: List[Dict[str, Any]] = []
    for index, row in enumerate(selected_rows, start=1):
        segment_dir = segment_root / f"segment_{index:04d}"
        manifest_path = segment_dir / "manifest.json"
        final_segment_path = segment_dir / f"seg_{index:04d}.wav"
        if not manifest_path.exists() or not final_segment_path.exists():
            continue
        try:
            segment_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _segment_row_matches_manifest(row, segment_manifest):
            continue
        reusable = dict(segment_manifest)
        reusable["_segment_index"] = index
        reusable["tts_audio_path"] = str(final_segment_path.resolve())
        completed_indices.add(index)
        reusable_results.append(reusable)
    return completed_indices, reusable_results


def _reset_voxcpm_output_for_fresh_run(*, out_root: Path) -> None:
    """新任务非 resume 时清掉旧生成产物，避免 segment 编号和新字幕错位。"""

    for child in list(out_root.iterdir()):
        if child.name == "uploaded_speaker_refs":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _prune_voxcpm_resume_segments(
    *,
    segment_root: Path,
    completed_indices: Set[int],
) -> None:
    """resume 前删掉所有不可复用的旧 segment 目录，避免旧 manifest 混入新一轮任务。"""

    if not segment_root.exists():
        return
    for segment_dir in list(segment_root.glob("segment_*")):
        if not segment_dir.is_dir():
            continue
        try:
            index = int(segment_dir.name.split("_")[-1])
        except Exception:
            shutil.rmtree(segment_dir, ignore_errors=True)
            continue
        if index not in completed_indices:
            shutil.rmtree(segment_dir, ignore_errors=True)


def _infer_voxcpm_resume_state(
    manifest: Dict[str, Any],
    *,
    out_root: Path,
) -> Dict[str, Any]:
    """根据当前磁盘产物推断 VoxCPM 批次是否可恢复。"""

    status = str(manifest.get("status") or "").strip().lower()
    selected_rows = _load_selected_subtitles_from_manifest(manifest)
    total_segments = int(manifest.get("segment_count") or manifest.get("processed_segments") or len(selected_rows) or 0)
    if total_segments <= 0:
        total_segments = len(selected_rows)

    completed_indices, _ = _collect_resumable_segment_results(
        segment_root=out_root / "segments",
        selected_rows=selected_rows,
    )
    completed_segments = len(completed_indices)

    final_srt_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_final_srt"))
    if final_srt_path is not None:
        return {
            "resumable": False,
            "resume_stage": "completed",
            "completed_segments": total_segments if total_segments > 0 else completed_segments,
            "total_segments": total_segments,
        }

    selected_subtitles_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("selected_subtitles"))
    if selected_subtitles_path is not None and selected_rows:
        if completed_segments > 0 and total_segments > completed_segments:
            return {
                "resumable": True,
                "resume_stage": "dubbing_partial",
                "completed_segments": completed_segments,
                "total_segments": total_segments,
            }
        return {
            "resumable": True,
            "resume_stage": "prepared",
            "completed_segments": completed_segments,
            "total_segments": total_segments,
        }

    return {
        "resumable": status in {"failed", "cancelled"} and bool(selected_rows),
        "resume_stage": "unavailable",
        "completed_segments": completed_segments,
        "total_segments": total_segments,
    }


def _annotate_voxcpm_task_with_resume_state(
    task: Dict[str, Any],
    *,
    manifest: Dict[str, Any],
    out_root: Path,
    from_disk: bool = False,
) -> Dict[str, Any]:
    """把恢复信息附着到任务记录；从磁盘恢复 stale running 时转成 interrupted failed。"""

    resume_state = _infer_voxcpm_resume_state(manifest, out_root=out_root)
    task["resumable"] = bool(resume_state.get("resumable"))
    task["resume_stage"] = str(resume_state.get("resume_stage") or "")
    task["processed_segments"] = int(resume_state.get("completed_segments") or task.get("processed_segments") or 0)
    task["total_segments"] = int(resume_state.get("total_segments") or task.get("total_segments") or 0)

    status = str(task.get("status") or "").strip().lower()
    if from_disk and status in {"queued", "running"} and task.get("resume_stage") != "completed":
        task["status"] = "failed"
        task["stage"] = "failed"
        task["error"] = "Interrupted VoxCPM job loaded from disk. Use resume to continue."
    return task


def _build_voxcpm_resume_context(
    *,
    manifest: Dict[str, Any],
    out_root: Path,
) -> Dict[str, Any]:
    """从磁盘 batch 构造 resume 所需上下文。"""

    selected_rows = _load_selected_subtitles_from_manifest(manifest)
    if not selected_rows:
        raise HTTPException(status_code=409, detail="Resume selected subtitles missing or empty")
    completed_indices, reusable_segment_results = _collect_resumable_segment_results(
        segment_root=out_root / "segments",
        selected_rows=selected_rows,
    )
    source_audio_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("source_audio"))
    speaker_ref_map = {
        str(speaker_id): dict(meta)
        for speaker_id, meta in dict(manifest.get("speaker_ref_map") or {}).items()
    }
    ref_audio_path = _resolve_existing_optional_path(manifest.get("ref_audio_path"))
    if ref_audio_path is None and not speaker_ref_map:
        raise HTTPException(status_code=409, detail="Resume reference audio missing")
    return {
        "selected_rows": selected_rows,
        "completed_segment_indices": completed_indices,
        "reusable_segment_results": reusable_segment_results,
        "source_audio_path": str(source_audio_path.resolve()) if source_audio_path is not None else "",
        "ref_audio_path": str(ref_audio_path.resolve()) if ref_audio_path is not None else "",
        "ref_text": str(manifest.get("ref_text") or ""),
        "speaker_ref_map": speaker_ref_map,
        "speaker_reference_mode": str(manifest.get("speaker_reference_mode") or ""),
        "selected_subtitle_mode": str(manifest.get("selected_subtitle_mode") or manifest.get("subtitle_mode") or "translated"),
        "subtitle_script_variant": str(manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
        "subtitle_video_preset": str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
        "cfg_value": float(manifest.get("cfg_value") or DEFAULT_VOXCPM_CFG_VALUE),
        "inference_timesteps": int(manifest.get("inference_timesteps") or DEFAULT_VOXCPM_INFERENCE_TIMESTEPS),
    }


def _resolve_artifact(task: Dict[str, Any], artifact: str) -> Path:
    """根据 artifact key 解析文件路径。"""

    manifest_path = Path(str(task.get("batch_manifest_path") or "")).expanduser()
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = dict(manifest.get("paths") or {})
    mapping = {
        "selected_srt": paths.get("selected_subtitles"),
        "selected_srt_rebuild": paths.get("selected_subtitles_rebuild"),
        "selected_srt_translated": paths.get("selected_subtitles_translated"),
        "selected_srt_with_speaker": paths.get("selected_subtitles_with_speakers"),
        "srt": paths.get("dubbed_final_srt"),
        "srt_rebuild": paths.get("dubbed_final_srt_rebuild"),
        "srt_with_speaker": paths.get("dubbed_final_srt_with_speakers"),
        "mix": paths.get("dubbed_mix"),
        "ass": paths.get("dubbed_final_ass"),
        "video_audio": paths.get("dubbed_audio_for_video"),
        "video": paths.get("dubbed_video_full"),
        "manifest": str(manifest_path) if manifest_path.exists() else None,
    }
    variant_map = dict((manifest.get("paths") or {}).get("subtitle_video_variants") or {})
    for preset, variant_paths in variant_map.items():
        variant_payload = dict(variant_paths or {})
        mapping[_build_voxcpm_video_variant_artifact_key(str(preset))] = variant_payload.get("video")
        mapping[_build_voxcpm_ass_variant_artifact_key(str(preset))] = variant_payload.get("ass")
    resolved = mapping.get(artifact)
    if not resolved:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = Path(str(resolved)).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact file missing: {path}")
    return path


def _task_to_public(task: Dict[str, Any]) -> Dict[str, Any]:
    """返回给前端的公开任务视图。"""

    payload = dict(task)
    payload.pop("process", None)
    return payload


def _create_task_payload(
    *,
    task_id: str,
    project_filename: str,
    input_media_path: Optional[Path],
    subtitle_mode: str,
    source_lang: str,
    target_lang: str,
    source_count: int,
    translated_count: int,
    out_root: Path,
    voxcpm_api_url: str,
    subtitle_script_variant: str = DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT,
    subtitle_video_preset: str = DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET,
    speaker_ids: Optional[List[str]] = None,
    translate_base_url: str = DEFAULT_TRANSLATE_BASE_URL,
    translate_model: str = DEFAULT_TRANSLATE_MODEL,
) -> Dict[str, Any]:
    """创建 6 号面板任务基础 payload。"""

    normalized_target_lang = str(target_lang or "").strip()
    normalized_script_variant = _normalize_voxcpm_subtitle_script_variant(subtitle_script_variant)
    normalized_subtitle_video_preset = _normalize_voxcpm_subtitle_video_preset(subtitle_video_preset)
    if not _is_voxcpm_cantonese_target_lang(normalized_target_lang):
        normalized_script_variant = "traditional"

    return {
        "id": task_id,
        "short_id": task_id.split("_")[0],
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "stdout_tail": [],
        "artifacts": [],
        "error": "",
        "batch_id": task_id,
        "batch_manifest_path": str((out_root / "manifest.json").resolve()),
        "processed_segments": 0,
        "total_segments": 0,
        "manual_review_segments": 0,
        "project_filename": project_filename,
        "input_media_path": str(input_media_path) if input_media_path else "",
        "subtitle_mode": subtitle_mode,
        "selected_subtitle_mode": "",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_subtitles_count": int(source_count),
        "translated_subtitles_count": int(translated_count),
        "speaker_ids": list(speaker_ids or []),
        "speaker_reference_mode": "",
        "result_audio": None,
        "result_srt": None,
        "out_root": str(out_root.resolve()),
        "voxcpm_api_url": voxcpm_api_url or DEFAULT_VOXCPM_API_URL,
        "translate_base_url": str(translate_base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL,
        "translate_model": str(translate_model or "").strip() or DEFAULT_TRANSLATE_MODEL,
        "subtitle_script_variant": normalized_script_variant,
        "subtitle_video_preset": normalized_subtitle_video_preset,
        "resume_stage": "",
        "resumable": False,
        "input_media_url": f"/dubbing/uploads/{Path(str(input_media_path)).name}" if input_media_path else "",
    }


def _run_voxcpm_job(
    *,
    task_id: str,
    input_media_path: Optional[Path],
    source_rows: List[Dict[str, Any]],
    translated_rows: List[Dict[str, Any]],
    subtitle_mode: str,
    source_lang: str,
    target_lang: str,
    api_key: str,
    translate_base_url: str,
    translate_model: str,
    translate_system_prompt: str,
    ref_audio_path: Optional[Path],
    ref_text: str,
    uploaded_speaker_ref_map: Optional[Dict[str, Dict[str, Any]]] = None,
    voxcpm_api_url: str,
    cfg_value: float,
    inference_timesteps: int,
    subtitle_script_variant: str = DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT,
    subtitle_video_preset: str = DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET,
    resume_context: Optional[Dict[str, Any]] = None,
) -> None:
    """执行 6 号 VoxCPM 配音主流程。"""

    # 6 号面板内部统一使用“净正文 + sidecar speaker_id”结构，避免 speaker 标签混入翻译或配音。
    source_rows = _normalize_voxcpm_internal_rows(source_rows)
    translated_rows = _normalize_voxcpm_internal_rows(translated_rows)

    out_root = _resolve_output_dir(task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    resume_context = dict(resume_context or {})
    if resume_context:
        _prune_voxcpm_resume_segments(
            segment_root=out_root / "segments",
            completed_indices=set(int(item) for item in list(resume_context.get("completed_segment_indices") or [])),
        )
    else:
        _reset_voxcpm_output_for_fresh_run(out_root=out_root)
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = out_root / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    source_audio_path = out_root / "source_audio.wav"
    selected_subtitles_path = out_root / "selected_subtitles.srt"
    selected_subtitles_rebuild_path = out_root / "selected_subtitles_rebuild.srt"
    selected_subtitles_with_speakers_path = out_root / "selected_subtitles_with_speakers.srt"
    final_srt_path = final_dir / "dubbed_final_full.srt"
    final_rebuild_srt_path = final_dir / "dubbed_final_full-rebuild.srt"
    final_srt_with_speakers_path = final_dir / "dubbed_final_full_with_speakers.srt"
    final_mix_path = final_dir / "dubbed_mix_full.wav"
    final_ass_path = final_dir / "dubbed_final_full-styled.ass"
    selected_subtitles_translated_path = out_root / "selected_subtitles_translated.srt"
    normalized_script_variant = _normalize_voxcpm_subtitle_script_variant(
        str(resume_context.get("subtitle_script_variant") or subtitle_script_variant or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT)
    )
    normalized_subtitle_video_preset = _normalize_voxcpm_subtitle_video_preset(
        str(resume_context.get("subtitle_video_preset") or subtitle_video_preset or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET)
    )
    if not _is_voxcpm_cantonese_target_lang(target_lang):
        normalized_script_variant = "traditional"
    has_input_media = input_media_path is not None and str(input_media_path).strip() != "" and Path(str(input_media_path)).exists()
    uploaded_speaker_ref_map = {
        str(speaker_id): dict(meta)
        for speaker_id, meta in dict(uploaded_speaker_ref_map or {}).items()
    }

    _set_task(task_id, stage="initializing", progress=5.0)
    _ensure_voxcpm_backend_ready(voxcpm_api_url)
    if resume_context:
        resumed_source_audio = _resolve_existing_optional_path(resume_context.get("source_audio_path"))
        if resumed_source_audio is not None and resumed_source_audio.resolve() != source_audio_path.resolve():
            source_audio_path.write_bytes(resumed_source_audio.read_bytes())
        selected_rows = [dict(item) for item in list(resume_context.get("selected_rows") or [])]
        translated_rows_for_output = [dict(item) for item in list(resume_context.get("translated_rows") or [])]
        selected_mode = str(resume_context.get("selected_subtitle_mode") or subtitle_mode or "translated")
        ref_audio_path = Path(str(resume_context.get("ref_audio_path") or ref_audio_path or "")).expanduser() if str(resume_context.get("ref_audio_path") or ref_audio_path or "").strip() else None
        ref_text = str(resume_context.get("ref_text") or ref_text)
        uploaded_speaker_ref_map = {
            str(speaker_id): dict(meta)
            for speaker_id, meta in dict(resume_context.get("speaker_ref_map") or uploaded_speaker_ref_map or {}).items()
        }
        cfg_value = float(resume_context.get("cfg_value") or cfg_value)
        inference_timesteps = int(resume_context.get("inference_timesteps") or inference_timesteps)
        normalized_script_variant = _normalize_voxcpm_subtitle_script_variant(
            str(resume_context.get("subtitle_script_variant") or normalized_script_variant)
        )
        normalized_subtitle_video_preset = _normalize_voxcpm_subtitle_video_preset(
            str(resume_context.get("subtitle_video_preset") or normalized_subtitle_video_preset)
        )
        if not _is_voxcpm_cantonese_target_lang(target_lang):
            normalized_script_variant = "traditional"
    else:
        if has_input_media:
            extract_source_audio(Path(str(input_media_path)), source_audio_path)
        translation_rebuild_rows = _build_voxcpm_translation_rebuild_rows(_normalize_speaker_ids_for_rows(source_rows))
        selected_rows, translated_rows_for_output, selected_mode = _translate_subtitles_if_needed(
            subtitle_mode=subtitle_mode,
            source_rows=source_rows,
            translated_rows=translated_rows,
            translation_rows=translation_rebuild_rows,
            source_lang=source_lang,
            target_lang=target_lang,
            api_key=api_key,
            translate_base_url=translate_base_url,
            translate_model=translate_model,
            translate_system_prompt=translate_system_prompt,
        )
    selected_source_rows = _normalize_speaker_ids_for_rows(selected_rows)
    if not resume_context:
        selected_subtitles_path.write_text(format_srt(selected_source_rows), encoding="utf-8")
    translation_rebuild_rows = _build_voxcpm_translation_rebuild_rows(selected_source_rows)
    if translation_rebuild_rows:
        selected_subtitles_rebuild_path.write_text(format_srt(translation_rebuild_rows), encoding="utf-8")
    translated_rows_for_output = [dict(item) for item in list(translated_rows_for_output or [])]
    if translated_rows_for_output:
        selected_subtitles_translated_path.write_text(
            format_srt(_normalize_speaker_ids_for_rows(translated_rows_for_output)),
            encoding="utf-8",
        )
        tts_source_rows = _normalize_speaker_ids_for_rows(translated_rows_for_output)
    else:
        tts_source_rows = _normalize_speaker_ids_for_rows(translation_rebuild_rows or selected_source_rows)
        if not resume_context and selected_subtitles_translated_path.exists():
            selected_subtitles_translated_path.unlink()
    selected_rows = _split_voxcpm_rows_before_tts(tts_source_rows)
    selected_subtitles_with_speakers_path.write_text(
        format_srt(_build_speaker_prefixed_rows(selected_rows)),
        encoding="utf-8",
    )
    detected_speaker_ids = _collect_detected_speaker_ids(selected_rows)

    speaker_ref_map: Dict[str, Dict[str, Any]] = {}
    reference_mode = "single"
    if uploaded_speaker_ref_map:
        speaker_ref_map = {
            speaker_id: dict(uploaded_speaker_ref_map[speaker_id])
            for speaker_id in detected_speaker_ids
            if speaker_id in uploaded_speaker_ref_map
        }
        missing_speakers = [
            speaker_id
            for speaker_id in detected_speaker_ids
            if speaker_id not in speaker_ref_map
        ]
        if missing_speakers:
            uploaded_source_filenames = [
                Path(str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "")).name
                for meta in speaker_ref_map.values()
                if str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "").strip()
            ]
            speaker_gender_hints: Dict[str, str] = {}
            if has_input_media and source_audio_path.exists():
                speaker_gender_hints = _infer_missing_speaker_gender_hints(
                    vocals_path=source_audio_path,
                    subtitles=selected_rows,
                    missing_speaker_ids=missing_speakers,
                    out_root=out_root,
                )
            _validate_preset_ref_voices_available(
                target_lang=target_lang,
                missing_speaker_ids=missing_speakers,
                excluded_source_filenames=uploaded_source_filenames,
            )
            preset_map = _pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=missing_speakers,
                target_lang=target_lang,
                out_root=out_root,
                speaker_gender_hints=speaker_gender_hints,
                excluded_source_filenames=uploaded_source_filenames,
            )
            speaker_ref_map.update(preset_map)
            reference_mode = "uploaded_mixed"
        else:
            reference_mode = "uploaded_strict"
    elif ref_audio_path is not None and ref_audio_path.exists():
        reference_mode = "single"
    else:
        _validate_preset_ref_voices_available(
            target_lang=target_lang,
            missing_speaker_ids=detected_speaker_ids,
            excluded_source_filenames=[],
        )
        speaker_ref_map = _pick_preset_ref_voices_for_missing_speakers(
            missing_speaker_ids=detected_speaker_ids,
            target_lang=target_lang,
            out_root=out_root,
            speaker_gender_hints={},
            excluded_source_filenames=[],
        )
        reference_mode = "preset_only"

    total_segments = len(selected_rows)
    _set_task(task_id, stage="dubbing:generating", progress=10.0, total_segments=total_segments)
    _persist_voxcpm_task_manifest(
        task_id=task_id,
        out_root=out_root,
        source_audio_path=source_audio_path if source_audio_path.exists() else None,
        selected_subtitles_path=selected_subtitles_path,
        selected_subtitles_rebuild_path=selected_subtitles_rebuild_path if selected_subtitles_rebuild_path.exists() else None,
        selected_subtitles_translated_path=selected_subtitles_translated_path if selected_subtitles_translated_path.exists() else None,
        selected_subtitles_tts_rows=selected_rows,
        subtitles_rebuild_path=final_rebuild_srt_path,
        selected_subtitles_with_speakers_path=selected_subtitles_with_speakers_path,
        subtitles_path=final_srt_path,
        subtitles_with_speaker_path=final_srt_with_speakers_path,
        final_mix_path=final_mix_path,
        final_video_path=None,
        prepared_audio_path=None,
        final_ass_path=None,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        cfg_value=cfg_value,
        inference_timesteps=inference_timesteps,
        subtitle_script_variant=normalized_script_variant,
        speaker_ref_map=speaker_ref_map,
        speaker_reference_mode=reference_mode,
        subtitle_video_preset=normalized_subtitle_video_preset,
    )

    segment_results: List[Any] = []
    completed_segment_indices = set(int(item) for item in list(resume_context.get("completed_segment_indices") or []))
    for reusable in list(resume_context.get("reusable_segment_results") or []):
        segment_results.append(
            _build_segment_result(
                start_sec=float(reusable.get("start_sec", 0.0) or 0.0),
                segment_manifest=reusable,
            )
        )
    for index, row in enumerate(selected_rows, start=1):
        if index in completed_segment_indices:
            _set_task(
                task_id,
                processed_segments=len([item for item in completed_segment_indices if item <= index]),
                progress=min(85.0, 10.0 + (len([item for item in completed_segment_indices if item <= index]) / max(total_segments, 1)) * 70.0),
            )
            continue
        seg_dir = segments_dir / f"segment_{index:04d}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        raw_path = seg_dir / f"seg_{index:04d}_raw.wav"
        final_path = seg_dir / f"seg_{index:04d}.wav"
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        base_target_duration = max(0.05, end_sec - start_sec)
        speaker_id = str(row.get("speaker_id") or "").strip() or "Speaker 1"
        ref_meta = speaker_ref_map.get(speaker_id)
        if ref_meta:
            current_ref_audio_path = Path(str(ref_meta.get("ref_audio") or "")).expanduser()
            current_ref_text = str(ref_meta.get("ref_text") or "").strip() or _speaker_ref_text_for_target_lang(target_lang)
        else:
            if ref_audio_path is None:
                raise RuntimeError(f"reference audio missing for speaker {speaker_id}")
            current_ref_audio_path = ref_audio_path
            current_ref_text = ref_text
        response = _call_voxcpm_tts_with_unstable_retry(
            api_url=voxcpm_api_url,
            text=str(row.get("text") or "").strip(),
            prompt_audio_path=current_ref_audio_path,
            prompt_text=current_ref_text,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            retry_output_path=seg_dir / f"seg_{index:04d}_retry_concat.wav",
        )
        audio_base64 = str(response.get("audio_base64") or "").strip()
        if not audio_base64:
            raise RuntimeError(f"VoxCPM segment {index:04d} returned empty audio")
        _decode_base64_audio_to_wav(audio_base64, raw_path)
        align_meta = _soft_align_segment(
            input_path=raw_path,
            output_path=final_path,
            target_duration_sec=base_target_duration,
        )
        align_meta["base_target_duration_sec"] = round(base_target_duration, 3)
        align_meta["effective_target_duration_sec"] = round(base_target_duration, 3)
        align_meta["borrowed_gap_sec"] = 0.0
        segment_manifest = {
            "id": f"seg_{index:04d}",
            "start_sec": start_sec,
            "end_sec": end_sec,
            "text": str(row.get("text") or "").strip(),
            "speaker_id": speaker_id,
            "paths": {
                "dubbed_vocals": str(final_path.resolve()),
                "dubbed_mix": str(final_path.resolve()),
            },
            "align": align_meta,
        }
        (seg_dir / "manifest.json").write_text(json.dumps(segment_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        segment_results.append(
            _build_segment_result(
                start_sec=start_sec,
                segment_manifest=segment_manifest,
            )
        )
        completed_segment_indices.add(index)
        _set_task(
            task_id,
            processed_segments=len(completed_segment_indices),
            progress=min(85.0, 10.0 + (len(completed_segment_indices) / max(total_segments, 1)) * 70.0),
        )
        _persist_voxcpm_task_manifest(
            task_id=task_id,
            out_root=out_root,
            source_audio_path=source_audio_path if source_audio_path.exists() else None,
            selected_subtitles_path=selected_subtitles_path,
            selected_subtitles_rebuild_path=selected_subtitles_rebuild_path if selected_subtitles_rebuild_path.exists() else None,
            selected_subtitles_translated_path=selected_subtitles_translated_path if selected_subtitles_translated_path.exists() else None,
            selected_subtitles_tts_rows=selected_rows,
            subtitles_rebuild_path=final_rebuild_srt_path,
            selected_subtitles_with_speakers_path=selected_subtitles_with_speakers_path,
            subtitles_path=final_srt_path,
            subtitles_with_speaker_path=final_srt_with_speakers_path,
            final_mix_path=final_mix_path,
            final_video_path=None,
            prepared_audio_path=None,
            final_ass_path=None,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            subtitle_script_variant=normalized_script_variant,
            subtitle_video_preset=normalized_subtitle_video_preset,
            speaker_ref_map=speaker_ref_map,
            speaker_reference_mode=reference_mode,
        )

    ordered_segment_manifests = [item.manifest for item in sorted(segment_results, key=lambda item: float(item.start_sec))]
    final_rows = _compose_natural_sequence_mix(
        segment_manifests=ordered_segment_manifests,
        output_wav=final_mix_path,
    )
    final_rows_for_output = _apply_voxcpm_final_script_variant(final_rows, normalized_script_variant, target_lang=target_lang)
    final_srt_path.write_text(format_srt(final_rows_for_output), encoding="utf-8")
    final_rebuild_rows = _rebalance_omnivoice_final_srt_rows(final_rows_for_output, max_chars=20)
    final_rebuild_srt_path.write_text(format_srt(final_rebuild_rows), encoding="utf-8")
    final_srt_with_speakers_path.write_text(
        format_srt(
            _build_speaker_prefixed_rows(final_rows_for_output)
        ),
        encoding="utf-8",
    )
    final_ass_path.write_text(
        _build_voxcpm_centered_ass_from_rows(
            final_rows_for_output,
            source_name=selected_subtitles_path.name,
            subtitle_video_preset=normalized_subtitle_video_preset,
        ),
        encoding="utf-8",
    )

    final_video_path: Optional[Path] = None
    prepared_audio_path: Optional[Path] = None
    _set_task(task_id, stage="dubbing:building_black_video", progress=92.0)
    final_video_path = final_dir / "dubbed_video_full.mp4"
    layout = _get_voxcpm_subtitle_video_layout(normalized_subtitle_video_preset)
    build_black_video_with_ass_subtitles(
        audio_path=final_mix_path,
        ass_subtitle_path=final_ass_path,
        output_video_path=final_video_path,
        width=int(layout["width"]),
        height=int(layout["height"]),
    )

    task = _task_store.get(task_id)
    if task is None:
        raise RuntimeError("VoxCPM task disappeared from store")
    task.update(
        {
            "status": "completed",
            "stage": "completed",
            "progress": 100.0,
            "processed_segments": total_segments,
            "total_segments": total_segments,
            "selected_subtitle_mode": selected_mode,
            "speaker_ids": detected_speaker_ids,
            "speaker_reference_mode": reference_mode,
            "subtitle_script_variant": normalized_script_variant,
            "subtitle_video_preset": normalized_subtitle_video_preset,
            "result_audio": str(final_mix_path.resolve()),
            "result_srt": str(final_srt_path.resolve()),
            "result_video": str(final_video_path.resolve()) if final_video_path else None,
        }
    )
    manifest = _build_manifest(
        task=task,
        out_root=out_root,
        source_audio_path=source_audio_path if source_audio_path.exists() else None,
        selected_subtitles_path=selected_subtitles_path,
        selected_subtitles_rebuild_path=selected_subtitles_rebuild_path if selected_subtitles_rebuild_path.exists() else None,
        selected_subtitles_translated_path=selected_subtitles_translated_path if selected_subtitles_translated_path.exists() else None,
        selected_subtitles_tts_rows=selected_rows,
        subtitles_rebuild_path=final_rebuild_srt_path,
        selected_subtitles_with_speakers_path=selected_subtitles_with_speakers_path,
        subtitles_path=final_srt_path,
        subtitles_with_speaker_path=final_srt_with_speakers_path,
        final_mix_path=final_mix_path,
        final_video_path=final_video_path,
        prepared_audio_path=prepared_audio_path,
        final_ass_path=final_ass_path,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        cfg_value=cfg_value,
        inference_timesteps=inference_timesteps,
        subtitle_script_variant=normalized_script_variant,
        subtitle_video_preset=normalized_subtitle_video_preset,
        speaker_ref_map=speaker_ref_map,
        speaker_reference_mode=reference_mode,
    )
    task["artifacts"] = list(manifest.get("artifacts") or [])
    task["subtitle_video_variants"] = list(manifest.get("subtitle_video_variants") or [])
    task["generated_subtitle_video_presets"] = list(manifest.get("generated_subtitle_video_presets") or [])
    task["preferred_video_artifact_key"] = str(manifest.get("preferred_video_artifact_key") or "video")
    task["resumable"] = False
    task["resume_stage"] = "completed"
    _set_task(task_id, status="completed", stage="completed", progress=100.0)


def _background_runner(task_id: str, **kwargs: Any) -> None:
    """后台线程统一入口。"""

    try:
        _run_voxcpm_job(task_id=task_id, **kwargs)
    except Exception as exc:
        logger.error("VoxCPM task %s failed: %s\n%s", task_id, exc, traceback.format_exc())
        task = _task_store.get(task_id)
        if task is not None:
            out_root = Path(str(task.get("out_root") or _resolve_output_dir(task_id))).expanduser()
            manifest = _load_manifest(task_id)
            _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))
            if manifest is not None:
                _annotate_voxcpm_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=False)
            else:
                _set_task(task_id, resumable=True, resume_stage="dubbing")


@router.get("/backend-status")
async def get_voxcpm_backend_status(voxcpm_api_url: str = DEFAULT_VOXCPM_API_URL) -> Dict[str, Any]:
    """检查 VoxCPM 后端状态。"""

    try:
        payload = _ensure_voxcpm_backend_ready(voxcpm_api_url or DEFAULT_VOXCPM_API_URL)
    except Exception as exc:
        return {"ready": False, "detail": str(exc), "api_url": voxcpm_api_url or DEFAULT_VOXCPM_API_URL}
    return {"ready": True, "detail": payload.get("status") or "ok", "device": payload.get("device"), "api_url": voxcpm_api_url or DEFAULT_VOXCPM_API_URL}


@router.post("/parse-podcast-script")
async def parse_voxcpm_podcast_script(
    script_file: UploadFile = File(...),
) -> Dict[str, Any]:
    """解析 6 号面板上传的播客脚本，返回结构化台词行。"""

    filename = str(script_file.filename or "").strip()
    if not filename.lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Podcast script only supports .md or .txt files")
    content_bytes = await script_file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Podcast script file is empty")
    try:
        content_text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_text = content_bytes.decode("utf-8-sig", errors="ignore")
    try:
        parsed = parse_podcast_script_text(content_text, source_name=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "filename": filename,
        "title": str(parsed.get("title") or ""),
        "source_label": str(parsed.get("source_label") or ""),
        "rows": list(parsed.get("rows") or []),
        "speaker_ids": list(parsed.get("speaker_ids") or []),
        "detected_mode": str(parsed.get("detected_mode") or "single"),
        "skipped_blocks_count": int(parsed.get("skipped_blocks_count") or 0),
    }


@router.post("/start-from-project")
async def start_voxcpm_from_project(
    filename: str = Form(""),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    source_subtitles_json: str = Form(""),
    translated_subtitles_json: str = Form(""),
    subtitle_mode: str = Form("auto"),
    source_lang: str = Form("Chinese"),
    target_lang: str = Form("Chinese"),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
    voxcpm_api_url: str = Form(DEFAULT_VOXCPM_API_URL),
    speaker_ref_files: List[UploadFile] = File([]),
    speaker_ref_speaker_ids_json: str = Form(""),
    cfg_value: float = Form(DEFAULT_VOXCPM_CFG_VALUE),
    inference_timesteps: int = Form(DEFAULT_VOXCPM_INFERENCE_TIMESTEPS),
    subtitle_script_variant: str = Form(DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
    subtitle_video_preset: str = Form(DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
) -> Dict[str, Any]:
    """从当前项目启动 VoxCPM 配音。"""

    active = _task_store.list_active_ids()
    if active:
        raise HTTPException(status_code=409, detail="Another VoxCPM job is already running")

    input_media_path: Optional[Path] = None
    try:
        input_media_path = _resolve_project_media_path(filename, task_id)
    except HTTPException as exc:
        if exc.status_code not in {400, 404}:
            raise
        input_media_path = None
    display_name = _sanitize_filename(original_filename or filename or "voxcpm_subtitle_only")
    source_rows = _normalize_subtitles_payload(source_subtitles_json, field_name="source_subtitles_json")
    translated_rows = _normalize_subtitles_payload(translated_subtitles_json, field_name="translated_subtitles_json")
    source_rows, _ = normalize_subtitles_with_speakers(source_rows)
    translated_rows, _ = normalize_subtitles_with_speakers(translated_rows)
    if not source_rows and not translated_rows:
        raise HTTPException(status_code=400, detail="VoxCPM requires project subtitles")
    effective_rows = translated_rows if translated_rows else source_rows
    normalized_rows = _normalize_speaker_ids_for_rows(effective_rows)
    speaker_ids = _collect_detected_speaker_ids(normalized_rows)

    resolved_task_id = _build_task_id()
    out_root = _resolve_output_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    uploaded_speaker_ref_map = _build_voxcpm_uploaded_speaker_ref_map(
        out_root=out_root,
        speaker_ids=speaker_ids,
        speaker_ref_files=speaker_ref_files,
        speaker_ref_speaker_ids_json=speaker_ref_speaker_ids_json,
        target_lang=target_lang,
    )

    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=display_name,
        input_media_path=input_media_path,
        subtitle_mode=subtitle_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        source_count=len(source_rows),
        translated_count=len(translated_rows),
        out_root=out_root,
        voxcpm_api_url=voxcpm_api_url or DEFAULT_VOXCPM_API_URL,
        subtitle_script_variant=subtitle_script_variant,
        subtitle_video_preset=subtitle_video_preset,
        speaker_ids=speaker_ids,
        translate_base_url=translate_base_url,
        translate_model=translate_model,
    )
    task["speaker_reference_mode"] = "uploaded_partial" if uploaded_speaker_ref_map else "preset_only"
    _task_store.create(resolved_task_id, task)

    thread = threading.Thread(
        target=_background_runner,
        kwargs=dict(
            task_id=resolved_task_id,
            input_media_path=input_media_path,
            source_rows=source_rows,
            translated_rows=translated_rows,
            subtitle_mode=subtitle_mode,
            source_lang=source_lang,
            target_lang=target_lang,
            api_key=api_key,
            translate_base_url=translate_base_url,
            translate_model=translate_model,
            translate_system_prompt=translate_system_prompt,
            ref_audio_path=None,
            ref_text="",
            uploaded_speaker_ref_map=uploaded_speaker_ref_map,
            voxcpm_api_url=voxcpm_api_url or DEFAULT_VOXCPM_API_URL,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            subtitle_script_variant=subtitle_script_variant,
            subtitle_video_preset=subtitle_video_preset,
        ),
        daemon=True,
    )
    task["process"] = thread
    thread.start()
    return {
        "task_id": resolved_task_id,
        "id": resolved_task_id,
        "short_id": resolved_task_id.split("_")[0],
        "status": "queued",
        "stage": "queued",
        "project_filename": display_name,
        "message": "VoxCPM task started",
    }


@router.get("/status/{task_id}")
async def get_voxcpm_status(task_id: str) -> Dict[str, Any]:
    """查询 VoxCPM 任务状态。"""

    task = _task_store.get_public(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="VoxCPM task not found")
    return task


@router.get("/batches")
async def list_voxcpm_batches() -> Dict[str, Any]:
    """列出 VoxCPM 历史批次。"""

    collected: List[Dict[str, Any]] = []
    for manifest_path in sorted(OUTPUT_ROOT.glob("voxcpm_*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        collected.append(
            {
                "batch_id": str(manifest.get("batch_id") or manifest_path.parent.name.removeprefix("voxcpm_")),
                "task_id": str(manifest.get("task_id") or ""),
                "project_filename": str(manifest.get("project_filename") or ""),
                "status": str(manifest.get("status") or ""),
                "created_at": str(manifest.get("created_at") or ""),
                "target_lang": str(manifest.get("target_lang") or ""),
                "subtitle_mode": str(manifest.get("subtitle_mode") or ""),
                "resumable": bool(_infer_voxcpm_resume_state(manifest, out_root=manifest_path.parent).get("resumable")),
                "subtitle_video_preset": str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
                "generated_subtitle_video_presets": list(manifest.get("generated_subtitle_video_presets") or []),
            }
        )
    return {"items": collected}


@router.post("/load-batch")
async def load_voxcpm_batch(batch_id: str = Form(...)) -> Dict[str, Any]:
    """从磁盘恢复 VoxCPM 批次视图。"""

    manifest = _load_manifest(batch_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="VoxCPM batch folder not found")
    resolved_task_id = str(manifest.get("task_id") or manifest.get("batch_id") or batch_id).strip() or batch_id
    out_root = _resolve_output_dir(resolved_task_id)
    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=str(manifest.get("project_filename") or out_root.name),
        input_media_path=_resolve_existing_optional_path(manifest.get("input_media_path")),
        subtitle_mode=str(manifest.get("subtitle_mode") or "translated"),
        source_lang=str(manifest.get("source_lang") or "auto"),
        target_lang=str(manifest.get("target_lang") or "Chinese"),
        source_count=int(manifest.get("source_subtitles_count") or 0),
        translated_count=int(manifest.get("translated_subtitles_count") or 0),
        out_root=out_root,
        voxcpm_api_url=str(manifest.get("voxcpm_api_url") or DEFAULT_VOXCPM_API_URL),
        subtitle_script_variant=str(manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
        subtitle_video_preset=str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
        speaker_ids=list(manifest.get("speaker_ids") or []),
        translate_base_url=str(manifest.get("translate_base_url") or DEFAULT_TRANSLATE_BASE_URL),
        translate_model=str(manifest.get("translate_model") or DEFAULT_TRANSLATE_MODEL),
    )
    task.update(
        {
            "status": str(manifest.get("status") or "completed"),
            "stage": str(manifest.get("stage") or "completed"),
            "progress": float(manifest.get("progress") or 100.0),
            "selected_subtitle_mode": str(manifest.get("selected_subtitle_mode") or ""),
            "processed_segments": int(manifest.get("processed_segments") or 0),
            "total_segments": int(manifest.get("segment_count") or 0),
            "speaker_ids": list(manifest.get("speaker_ids") or []),
            "speaker_reference_mode": str(manifest.get("speaker_reference_mode") or ""),
            "subtitle_script_variant": str(manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
            "subtitle_video_preset": str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
            "artifacts": list(manifest.get("artifacts") or []),
            "subtitle_video_variants": list(manifest.get("subtitle_video_variants") or []),
            "generated_subtitle_video_presets": list(manifest.get("generated_subtitle_video_presets") or []),
            "preferred_video_artifact_key": str(manifest.get("preferred_video_artifact_key") or "video"),
            "result_audio": str((manifest.get("paths") or {}).get("dubbed_mix") or "") or None,
            "result_srt": str((manifest.get("paths") or {}).get("dubbed_final_srt") or "") or None,
            "result_video": str((manifest.get("paths") or {}).get("dubbed_video_full") or "") or None,
            "batch_manifest_path": str(manifest.get("_manifest_path") or task["batch_manifest_path"]),
            "out_root": str(out_root.resolve()),
        }
    )
    _annotate_voxcpm_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=True)
    _task_store.create(resolved_task_id, task)
    return _task_to_public(task)


@router.post("/resume/{task_id}")
async def resume_voxcpm_task(task_id: str) -> Dict[str, Any]:
    """从失败批次重新恢复 VoxCPM 任务。"""

    active = [active_id for active_id in _task_store.list_active_ids() if active_id != task_id]
    if active:
        raise HTTPException(status_code=409, detail="Another VoxCPM job is already running")
    manifest = _load_manifest(task_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="VoxCPM batch not found")
    if str(manifest.get("status") or "").strip().lower() == "completed":
        raise HTTPException(status_code=409, detail="Completed VoxCPM task does not need resume")
    manifest_path_text = str(manifest.get("_manifest_path") or "").strip()
    manifest_path = Path(manifest_path_text).expanduser().resolve() if manifest_path_text else None
    out_root = manifest_path.parent if manifest_path and manifest_path.exists() else _resolve_output_dir(task_id)
    resume_state = _infer_voxcpm_resume_state(manifest, out_root=out_root)
    if str(resume_state.get("resume_stage") or "") == "completed":
        raise HTTPException(status_code=409, detail="Completed VoxCPM task does not need resume")
    if not bool(resume_state.get("resumable")):
        raise HTTPException(status_code=409, detail="VoxCPM batch is not resumable")
    resume_context = _build_voxcpm_resume_context(manifest=manifest, out_root=out_root)

    input_media_path = _resolve_existing_optional_path(manifest.get("input_media_path"))

    resolved_task_id = str(manifest.get("task_id") or manifest.get("batch_id") or task_id).strip() or task_id
    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=str(manifest.get("project_filename") or out_root.name),
        input_media_path=input_media_path,
        subtitle_mode=str(manifest.get("subtitle_mode") or "translated"),
        source_lang=str(manifest.get("source_lang") or "auto"),
        target_lang=str(manifest.get("target_lang") or "Chinese"),
        source_count=int(manifest.get("source_subtitles_count") or 0),
        translated_count=int(manifest.get("translated_subtitles_count") or 0),
        out_root=out_root,
        voxcpm_api_url=str(manifest.get("voxcpm_api_url") or DEFAULT_VOXCPM_API_URL),
        subtitle_script_variant=str(manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
        subtitle_video_preset=str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
        speaker_ids=list(manifest.get("speaker_ids") or []),
        translate_base_url=str(manifest.get("translate_base_url") or DEFAULT_TRANSLATE_BASE_URL),
        translate_model=str(manifest.get("translate_model") or DEFAULT_TRANSLATE_MODEL),
    )
    task["status"] = "queued"
    task["stage"] = "queued"
    task["progress"] = 0.0
    task["selected_subtitle_mode"] = str(resume_context.get("selected_subtitle_mode") or "")
    task["processed_segments"] = int(resume_state.get("completed_segments") or 0)
    task["total_segments"] = int(resume_state.get("total_segments") or 0)
    task["resume_stage"] = str(resume_state.get("resume_stage") or "")
    task["resumable"] = True
    task["error"] = ""
    _task_store.create(resolved_task_id, task)

    thread = threading.Thread(
        target=_background_runner,
        kwargs=dict(
            task_id=resolved_task_id,
            input_media_path=input_media_path,
            source_rows=[],
            translated_rows=[],
            subtitle_mode=str(task.get("subtitle_mode") or "translated"),
            source_lang=str(task.get("source_lang") or "auto"),
            target_lang=str(task.get("target_lang") or "Chinese"),
            api_key="",
            translate_base_url=str(manifest.get("translate_base_url") or task.get("translate_base_url") or DEFAULT_TRANSLATE_BASE_URL),
            translate_model=str(manifest.get("translate_model") or task.get("translate_model") or DEFAULT_TRANSLATE_MODEL),
            translate_system_prompt="",
            ref_audio_path=Path(str(resume_context.get("ref_audio_path") or "")).expanduser(),
            ref_text=str(resume_context.get("ref_text") or ""),
            voxcpm_api_url=str(manifest.get("voxcpm_api_url") or DEFAULT_VOXCPM_API_URL),
            cfg_value=float(resume_context.get("cfg_value") or DEFAULT_VOXCPM_CFG_VALUE),
            inference_timesteps=int(resume_context.get("inference_timesteps") or DEFAULT_VOXCPM_INFERENCE_TIMESTEPS),
            subtitle_script_variant=str(resume_context.get("subtitle_script_variant") or manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
            subtitle_video_preset=str(resume_context.get("subtitle_video_preset") or manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
            resume_context=resume_context,
        ),
        daemon=True,
    )
    task["process"] = thread
    thread.start()
    return {
        "task_id": resolved_task_id,
        "id": resolved_task_id,
        "short_id": resolved_task_id.split("_")[0],
        "status": "queued",
        "stage": "queued",
        "project_filename": task["project_filename"],
        "resume_stage": task["resume_stage"],
        "message": "VoxCPM task resumed",
    }


@router.post("/render-video-variant")
async def render_voxcpm_video_variant(
    batch_id: str = Form(...),
    subtitle_video_preset: str = Form(...),
) -> Dict[str, Any]:
    """对已完成的 6 号面板批次补生成指定规格的 ASS 与黑底字幕视频。"""

    manifest = _load_manifest(batch_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="VoxCPM batch folder not found")
    if str(manifest.get("status") or "").strip().lower() != "completed":
        raise HTTPException(status_code=409, detail="Only completed VoxCPM batches can render extra video variants")

    resolved_task_id = str(manifest.get("task_id") or manifest.get("batch_id") or batch_id).strip() or batch_id
    out_root = _resolve_output_dir(resolved_task_id)
    normalized_preset = _normalize_voxcpm_subtitle_video_preset(subtitle_video_preset)
    existing_variants = list(manifest.get("subtitle_video_variants") or [])
    if any(str(item.get("preset") or "") == normalized_preset for item in existing_variants):
        task = _task_store.get_copy(resolved_task_id) or {}
        task.update(
            {
                "id": resolved_task_id,
                "task_id": resolved_task_id,
                "artifacts": list(manifest.get("artifacts") or []),
                "subtitle_video_variants": existing_variants,
                "generated_subtitle_video_presets": list(manifest.get("generated_subtitle_video_presets") or []),
                "preferred_video_artifact_key": str(manifest.get("preferred_video_artifact_key") or _build_voxcpm_video_variant_artifact_key(normalized_preset)),
                "result_video": str((manifest.get("paths") or {}).get("dubbed_video_full") or "") or None,
            }
        )
        return _task_to_public(task)

    final_mix_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_mix"))
    final_srt_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_final_srt"))
    final_rebuild_srt_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_final_srt_rebuild"))
    default_ass_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_final_ass"))
    default_video_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_video_full"))
    selected_with_speaker_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("selected_subtitles_with_speakers"))
    final_srt_with_speakers_path = _resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_final_srt_with_speakers"))
    if final_mix_path is None or not final_mix_path.exists():
        raise HTTPException(status_code=409, detail="Completed batch final mix missing")
    if final_srt_path is None or not final_srt_path.exists():
        raise HTTPException(status_code=409, detail="Completed batch final subtitles missing")

    final_rows = parse_srt(final_srt_path.read_text(encoding="utf-8"))
    if not final_rows:
        raise HTTPException(status_code=409, detail="Completed batch final subtitles empty")

    variant_entry = _render_voxcpm_video_variant(
        task_id=resolved_task_id,
        out_root=out_root,
        rows=final_rows,
        final_mix_path=final_mix_path,
        source_name=final_srt_path.name,
        preset=normalized_preset,
    )
    manifest = _build_manifest(
        task={
            "id": resolved_task_id,
            "batch_id": str(manifest.get("batch_id") or resolved_task_id),
            "created_at": str(manifest.get("created_at") or ""),
            "updated_at": _iso_now(),
            "status": str(manifest.get("status") or "completed"),
            "stage": str(manifest.get("stage") or "completed"),
            "progress": float(manifest.get("progress") or 100.0),
            "project_filename": str(manifest.get("project_filename") or out_root.name),
            "input_media_path": str(manifest.get("input_media_path") or ""),
            "subtitle_mode": str(manifest.get("subtitle_mode") or "translated"),
            "selected_subtitle_mode": str(manifest.get("selected_subtitle_mode") or ""),
            "source_lang": str(manifest.get("source_lang") or "auto"),
            "target_lang": str(manifest.get("target_lang") or "Chinese"),
            "voxcpm_api_url": str(manifest.get("voxcpm_api_url") or DEFAULT_VOXCPM_API_URL),
            "speaker_ids": list(manifest.get("speaker_ids") or []),
            "speaker_reference_mode": str(manifest.get("speaker_reference_mode") or ""),
            "source_subtitles_count": int(manifest.get("source_subtitles_count") or 0),
            "translated_subtitles_count": int(manifest.get("translated_subtitles_count") or 0),
            "processed_segments": int(manifest.get("processed_segments") or manifest.get("segment_count") or 0),
            "total_segments": int(manifest.get("segment_count") or 0),
        },
        out_root=out_root,
        source_audio_path=_resolve_existing_optional_path((manifest.get("paths") or {}).get("source_audio")),
        selected_subtitles_path=Path(str((manifest.get("paths") or {}).get("selected_subtitles") or final_srt_path)),
        selected_subtitles_rebuild_path=_resolve_existing_optional_path((manifest.get("paths") or {}).get("selected_subtitles_rebuild")),
        selected_subtitles_translated_path=_resolve_existing_optional_path((manifest.get("paths") or {}).get("selected_subtitles_translated")),
        selected_subtitles_tts_rows=list(manifest.get("selected_subtitles_tts_rows") or []),
        subtitles_rebuild_path=final_rebuild_srt_path,
        selected_subtitles_with_speakers_path=selected_with_speaker_path,
        subtitles_path=final_srt_path,
        subtitles_with_speaker_path=final_srt_with_speakers_path,
        final_mix_path=final_mix_path,
        final_video_path=default_video_path,
        prepared_audio_path=_resolve_existing_optional_path((manifest.get("paths") or {}).get("dubbed_audio_for_video")),
        final_ass_path=default_ass_path,
        ref_audio_path=_resolve_existing_optional_path(manifest.get("ref_audio_path")),
        ref_text=str(manifest.get("ref_text") or ""),
        cfg_value=float(manifest.get("cfg_value") or DEFAULT_VOXCPM_CFG_VALUE),
        inference_timesteps=int(manifest.get("inference_timesteps") or DEFAULT_VOXCPM_INFERENCE_TIMESTEPS),
        subtitle_script_variant=str(manifest.get("subtitle_script_variant") or DEFAULT_VOXCPM_SUBTITLE_SCRIPT_VARIANT),
        subtitle_video_preset=str(manifest.get("subtitle_video_preset") or DEFAULT_VOXCPM_SUBTITLE_VIDEO_PRESET),
        speaker_ref_map=dict(manifest.get("speaker_ref_map") or {}),
        speaker_reference_mode=str(manifest.get("speaker_reference_mode") or ""),
    )
    manifest["preferred_video_artifact_key"] = str(variant_entry.get("video_artifact_key") or "video")
    manifest["updated_at"] = _iso_now()
    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    task = _task_store.get_copy(resolved_task_id) or {}
    task.update(
        {
            "id": resolved_task_id,
            "task_id": resolved_task_id,
            "status": "completed",
            "stage": "completed",
            "progress": 100.0,
            "artifacts": list(manifest.get("artifacts") or []),
            "subtitle_video_variants": list(manifest.get("subtitle_video_variants") or []),
            "generated_subtitle_video_presets": list(manifest.get("generated_subtitle_video_presets") or []),
            "preferred_video_artifact_key": str(manifest.get("preferred_video_artifact_key") or "video"),
            "result_audio": str((manifest.get("paths") or {}).get("dubbed_mix") or "") or None,
            "result_srt": str((manifest.get("paths") or {}).get("dubbed_final_srt") or "") or None,
            "result_video": str((manifest.get("paths") or {}).get("dubbed_video_full") or "") or None,
            "batch_manifest_path": str(manifest_path.resolve()),
            "out_root": str(out_root.resolve()),
        }
    )
    _task_store.create(resolved_task_id, task)
    return _task_to_public(task)


@router.get("/artifact/{task_id}/{artifact}")
async def download_voxcpm_artifact(task_id: str, artifact: str):
    """下载 VoxCPM 批次产物。"""

    task = _task_store.get_copy(task_id)
    if not task:
        manifest = _load_manifest(task_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="VoxCPM task not found")
        task = {
            "batch_manifest_path": str(manifest.get("_manifest_path") or ""),
        }
    path = _resolve_artifact(task, artifact)
    return FileResponse(path, filename=path.name)
