from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .srt import infer_cjk_mode_from_lines, subtitle_text_units

DEFAULT_DEEPGRAM_MAX_GAP_SEC = 0.8
DEFAULT_DEEPGRAM_MIN_GROUP_DURATION_SEC = 1.2
DEFAULT_DEEPGRAM_MAX_GROUP_DURATION_SEC = 8.0


def _coerce_float(value: Any) -> Optional[float]:
    """宽松把 Deepgram 的时间字段转成浮点秒。"""

    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    """把 Deepgram 文本字段清洗成可用的字幕正文。"""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text


def _is_sentence_boundary(token: str) -> bool:
    """判断词尾是否已经到了一个可切字幕的强句末。"""

    cleaned = _normalize_text(token)
    return bool(re.search(r"[.!?。！？][\"')\]]*\s*$", cleaned))


def _join_tokens(tokens: List[str]) -> str:
    """把 words 兜底路径里的 token 串回可读文本。"""

    text = " ".join(_normalize_text(token) for token in tokens if _normalize_text(token))
    text = re.sub(r"\s+([,.;:!?，。！？、；：])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _resolve_speaker_label(
    speaker_value: Any,
    speaker_map: Dict[str, str],
) -> str:
    """把 Deepgram 原始 speaker 编号映射成稳定的 `Speaker N`。"""

    speaker_key = str(speaker_value if speaker_value is not None else "__missing__").strip()
    if not speaker_key:
        speaker_key = "__missing__"
    if speaker_key not in speaker_map:
        speaker_map[speaker_key] = f"Speaker {len(speaker_map) + 1}"
    return speaker_map[speaker_key]


def _extract_first_alternative(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 Deepgram JSON 中取出主转写 alternative。"""

    results = payload.get("results") or {}
    channels = results.get("channels") or []
    if not isinstance(channels, list) or not channels:
        return {}
    first_channel = channels[0] if isinstance(channels[0], dict) else {}
    alternatives = first_channel.get("alternatives") or []
    if not isinstance(alternatives, list) or not alternatives:
        return {}
    first_alt = alternatives[0] if isinstance(alternatives[0], dict) else {}
    return first_alt


def _extract_units_from_paragraphs(alternative: Dict[str, Any]) -> List[Dict[str, Any]]:
    """优先从 paragraphs/sentences 中提取 speaker 句级字幕单元。"""

    paragraphs = (((alternative.get("paragraphs") or {}).get("paragraphs")) or [])
    if not isinstance(paragraphs, list):
        return []

    speaker_map: Dict[str, str] = {}
    units: List[Dict[str, Any]] = []

    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            continue
        speaker_label = _resolve_speaker_label(paragraph.get("speaker"), speaker_map)
        paragraph_start = _coerce_float(paragraph.get("start"))
        paragraph_end = _coerce_float(paragraph.get("end"))
        sentences = paragraph.get("sentences") or []
        if isinstance(sentences, list) and sentences:
            for sentence in sentences:
                if not isinstance(sentence, dict):
                    continue
                text = _normalize_text(sentence.get("text") or sentence.get("transcript"))
                if not text:
                    continue
                start = _coerce_float(sentence.get("start")) or paragraph_start
                end = _coerce_float(sentence.get("end")) or paragraph_end
                if start is None:
                    start = 0.0
                if end is None:
                    end = start
                if end <= start:
                    continue
                units.append(
                    {
                        "speaker_id": speaker_label,
                        "start": float(start),
                        "end": float(end),
                        "text": text,
                    }
                )
            continue

        text = _normalize_text(paragraph.get("transcript") or paragraph.get("text"))
        if not text:
            continue
        start = paragraph_start if paragraph_start is not None else 0.0
        end = paragraph_end if paragraph_end is not None else start
        if end <= start:
            continue
        units.append(
            {
                "speaker_id": speaker_label,
                "start": float(start),
                "end": float(end),
                "text": text,
            }
        )

    return units


def _extract_units_from_words(alternative: Dict[str, Any]) -> List[Dict[str, Any]]:
    """在 paragraphs 缺失时，退回到 words 级别再做 speaker 句段切分。"""

    words = alternative.get("words") or []
    if not isinstance(words, list) or not words:
        return []

    speaker_map: Dict[str, str] = {}
    units: List[Dict[str, Any]] = []
    current_tokens: List[str] = []
    current_speaker_id: Optional[str] = None
    current_start: Optional[float] = None
    current_end: Optional[float] = None

    def flush_current() -> None:
        """把当前 token 缓冲写成一条字幕单元。"""

        nonlocal current_tokens, current_speaker_id, current_start, current_end
        if not current_tokens or current_speaker_id is None:
            current_tokens = []
            current_speaker_id = None
            current_start = None
            current_end = None
            return

        text = _join_tokens(current_tokens)
        if text and current_start is not None and current_end is not None and current_end > current_start:
            units.append(
                {
                    "speaker_id": current_speaker_id,
                    "start": float(current_start),
                    "end": float(current_end),
                    "text": text,
                }
            )

        current_tokens = []
        current_speaker_id = None
        current_start = None
        current_end = None

    for index, word in enumerate(words):
        if not isinstance(word, dict):
            continue
        token = _normalize_text(word.get("punctuated_word") or word.get("word"))
        if not token:
            continue
        start = _coerce_float(word.get("start"))
        end = _coerce_float(word.get("end"))
        if start is None or end is None or end <= start:
            continue

        speaker_label = _resolve_speaker_label(word.get("speaker"), speaker_map)
        next_gap = None
        if index + 1 < len(words) and isinstance(words[index + 1], dict):
            next_start = _coerce_float(words[index + 1].get("start"))
            if next_start is not None:
                next_gap = next_start - end

        if current_tokens:
            previous_end = current_end if current_end is not None else start
            gap = start - previous_end
            same_speaker = speaker_label == current_speaker_id
            if not same_speaker or gap > DEFAULT_DEEPGRAM_MAX_GAP_SEC:
                flush_current()

        if not current_tokens:
            current_speaker_id = speaker_label
            current_start = start
        current_tokens.append(token)
        current_end = end

        should_break = _is_sentence_boundary(token)
        if next_gap is not None and next_gap > DEFAULT_DEEPGRAM_MAX_GAP_SEC:
            should_break = True
        if should_break:
            flush_current()

    flush_current()
    return units


def _merge_speaker_units(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只在同一 speaker 内做相邻短句合并，避免把 speaker 线串掉。"""

    if len(units) <= 1:
        return [dict(item) for item in units]

    merged: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def flush_current() -> None:
        """把当前 speaker chunk 合成最终字幕项。"""

        nonlocal current
        if not current:
            return
        texts = [_normalize_text(item.get("text")) for item in current if _normalize_text(item.get("text"))]
        if not texts:
            current = []
            return
        start = float(current[0]["start"])
        end = float(current[-1]["end"])
        speaker_id = str(current[0].get("speaker_id") or "").strip() or "Speaker 1"
        merged.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": "\n".join(texts),
                "speaker_id": speaker_id,
            }
        )
        current = []

    for item in units:
        unit = {
            "start": float(item.get("start") or 0.0),
            "end": float(item.get("end") or 0.0),
            "text": _normalize_text(item.get("text")),
            "speaker_id": str(item.get("speaker_id") or "").strip() or "Speaker 1",
        }
        if not unit["text"] or unit["end"] <= unit["start"]:
            continue

        if not current:
            current.append(unit)
            continue

        prev = current[-1]
        same_speaker = unit["speaker_id"] == prev["speaker_id"]
        gap = unit["start"] - prev["end"]
        if not same_speaker or gap > DEFAULT_DEEPGRAM_MAX_GAP_SEC:
            flush_current()
            current.append(unit)
            continue

        candidate = current + [unit]
        candidate_texts = [_normalize_text(item.get("text")) for item in candidate if _normalize_text(item.get("text"))]
        candidate_text = "\n".join(candidate_texts)
        candidate_duration = float(candidate[-1]["end"]) - float(candidate[0]["start"])
        cjk_mode = infer_cjk_mode_from_lines(candidate_texts)
        candidate_units = subtitle_text_units(candidate_text, cjk_mode=cjk_mode)
        max_text_units = 80 if cjk_mode else 240

        if (
            candidate_duration <= DEFAULT_DEEPGRAM_MAX_GROUP_DURATION_SEC
            and candidate_units <= max_text_units
        ):
            current.append(unit)
            continue

        if float(prev["end"]) - float(current[0]["start"]) < DEFAULT_DEEPGRAM_MIN_GROUP_DURATION_SEC:
            flush_current()
            current.append(unit)
            continue

        flush_current()
        current.append(unit)

    flush_current()
    return merged


def deepgram_json_to_subtitles(payload: Any) -> List[Dict[str, Any]]:
    """把 Deepgram diarization JSON 规范化成当前项目可消费的字幕列表。"""

    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("Deepgram JSON payload must be an object")

    alternative = _extract_first_alternative(payload)
    if not alternative:
        return []

    units = _extract_units_from_paragraphs(alternative)
    if not units:
        units = _extract_units_from_words(alternative)
    if not units:
        return []

    merged = _merge_speaker_units(units)
    subtitles: List[Dict[str, Any]] = []
    for item in merged:
        text = _normalize_text(item.get("text"))
        if not text:
            continue
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or 0.0)
        if end <= start:
            continue
        subtitles.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "speaker_id": str(item.get("speaker_id") or "").strip() or "Speaker 1",
            }
        )
    return subtitles
