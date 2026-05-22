from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?P<speaker>(?:Speaker\s+\S+)|(?:[^:：\n]{1,80}))\s*[:：]\s*(?P<text>.+?)\s*$",
    re.IGNORECASE,
)


def strip_speaker_prefix(text: str) -> Tuple[str | None, str]:
    """从字幕正文里剥离 `Speaker N:` 这类前缀，并返回 speaker_id 与净正文。"""

    raw = str(text or "").strip()
    if not raw:
        return None, ""
    match = SPEAKER_PREFIX_RE.match(raw)
    if not match:
        return None, raw
    speaker_id = str(match.group("speaker") or "").strip()
    content = str(match.group("text") or "").strip()
    if not speaker_id or not content:
        return None, raw
    return speaker_id, content


def normalize_subtitles_with_speakers(
    subtitles: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """统一清洗字幕里的 speaker 前缀，并返回规整后的字幕与 speaker 清单。"""

    normalized: List[Dict[str, Any]] = []
    speaker_ids: List[str] = []
    seen: set[str] = set()
    for item in subtitles:
        row = dict(item)
        # 优先保留上游已经写入的 speaker_id sidecar，再回退到正文里的 Speaker 前缀。
        existing_speaker_id = str(row.get("speaker_id") or "").strip()
        raw_text = str(row.get("text") or "")
        if existing_speaker_id:
            # 上游已经显式给了 speaker_id 时，正文里的普通冒号不能再被误判成 speaker 前缀。
            row["text"] = raw_text
            final_speaker_id = existing_speaker_id
        else:
            speaker_id, clean_text = strip_speaker_prefix(raw_text)
            row["text"] = clean_text
            final_speaker_id = speaker_id
        if final_speaker_id:
            row["speaker_id"] = final_speaker_id
            if final_speaker_id not in seen:
                seen.add(final_speaker_id)
                speaker_ids.append(final_speaker_id)
        normalized.append(row)
    return normalized, speaker_ids


def build_segment_speaker_metadata_from_subtitles(
    subtitles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把已裁到 segment 局部时间轴的字幕转成 speaker sidecar 结构。"""

    metadata: List[Dict[str, Any]] = []
    for index, item in enumerate(subtitles, start=1):
        speaker_id = str(item.get("speaker_id") or "").strip()
        if not speaker_id:
            continue
        metadata.append(
            {
                "subtitle_index": index,
                "start_sec": round(float(item.get("start", 0.0) or 0.0), 3),
                "end_sec": round(float(item.get("end", 0.0) or 0.0), 3),
                "text": str(item.get("text") or "").strip(),
                "speaker_id": speaker_id,
            }
        )
    return metadata


def parse_speaker_reference_specs_json(raw: str) -> Dict[str, Dict[str, Any]]:
    """把 `speaker_ref_map_json` 解析为带 `ref_text` 的 speaker reference 结构。"""

    text = str(raw or "").strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("speaker_ref_map_json must be a list")
    output: Dict[str, Dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker_id") or "").strip()
        ref_audio_path = str(item.get("ref_audio_path") or "").strip()
        ref_text = str(item.get("ref_text") or "").strip()
        if not speaker_id:
            continue
        spec: Dict[str, Any] = {"speaker_id": speaker_id}
        if ref_audio_path:
            spec["ref_audio_path"] = Path(ref_audio_path).expanduser().resolve()
        if ref_text:
            spec["ref_text"] = ref_text
        output[speaker_id] = spec
    return output


def parse_speaker_ref_map_json(raw: str) -> Dict[str, Path]:
    """把 `speaker_ref_map_json` 解析为 `speaker_id -> ref_audio_path`。"""

    output: Dict[str, Path] = {}
    for speaker_id, spec in parse_speaker_reference_specs_json(raw).items():
        ref_audio_path = spec.get("ref_audio_path")
        if ref_audio_path is None:
            continue
        output[speaker_id] = Path(ref_audio_path).expanduser().resolve()
    return output
