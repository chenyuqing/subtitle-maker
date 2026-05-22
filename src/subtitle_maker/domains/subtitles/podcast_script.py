from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .srt import infer_cjk_mode_from_lines, subtitle_text_units

PODCAST_ROLE_LINE_RE = re.compile(
    r"^\s*\*\*(?P<speaker>[A-Za-z][A-Za-z0-9 _+\-]{0,39})\s*:\*\*\s*(?:【(?P<emotion>[^】]+)】\s*)?(?P<text>.*)$"
)


def _is_podcast_skip_line(text: str) -> bool:
    """判断当前 Markdown 行是否属于非配音内容。"""

    stripped = str(text or "").strip()
    normalized_summary = stripped.replace(" ", "")
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    if stripped.startswith(">"):
        return True
    if stripped == "---":
        return True
    if stripped.startswith("|") and stripped.endswith("|"):
        return True
    if "顿悟预告" in stripped:
        return True
    if stripped.startswith("## 制作备注"):
        return True
    if stripped.startswith("**一句话总结：**"):
        return True
    if normalized_summary.startswith("(**一句话总结：**)") or normalized_summary.startswith("（**一句话总结：**）"):
        return True
    if re.match(r"^[（(].*(音乐|音效|BGM|淡入|淡出|转换).*[）)]$", stripped, re.IGNORECASE):
        return True
    return False


def _build_podcast_row(
    *,
    speaker_id: str,
    text_lines: List[str],
    emotion: str,
    start_sec: float,
    gap_sec: float,
    cjk_mode: bool,
) -> Dict[str, Any] | None:
    """把单个播客脚本片段收敛成 6 号面板可消费的结构化行。"""

    merged_text = re.sub(r"\s+", " ", " ".join(str(line or "").strip() for line in text_lines if str(line or "").strip())).strip()
    if not merged_text:
        return None
    text_units = max(1, subtitle_text_units(merged_text, cjk_mode=cjk_mode))
    # 这里生成的是“估算朗读时长”，不是精确字幕时间轴；它只用于 6 号面板初始配音节奏。
    duration_sec = max(1.2, round(text_units / (4.6 if cjk_mode else 14.0), 3))
    end_sec = round(start_sec + duration_sec, 3)
    row: Dict[str, Any] = {
        "start": round(start_sec, 3),
        "end": end_sec,
        "text": merged_text,
        "speaker_id": speaker_id,
    }
    if emotion:
        row["emotion"] = emotion
    row["_next_start"] = round(end_sec + gap_sec, 3)
    return row


def parse_podcast_script_text(
    text: str,
    *,
    source_name: str = "",
    gap_sec: float = 0.18,
) -> Dict[str, Any]:
    """解析播客脚本 Markdown，输出 6 号面板可直接消费的结构化台词行。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    title = ""
    source_label = ""
    body_lines = normalized.splitlines()
    cjk_mode = infer_cjk_mode_from_lines(body_lines)

    rows: List[Dict[str, Any]] = []
    speaker_ids: List[str] = []
    seen_speakers: set[str] = set()
    skipped_blocks_count = 0
    current_speaker = ""
    current_emotion = ""
    current_text_lines: List[str] = []
    current_start_sec = 0.0
    stop_after_notes = False

    def flush_current() -> None:
        nonlocal current_speaker, current_emotion, current_text_lines, current_start_sec
        if not current_speaker:
            current_text_lines = []
            current_emotion = ""
            return
        row = _build_podcast_row(
            speaker_id=current_speaker,
            text_lines=current_text_lines,
            emotion=current_emotion,
            start_sec=current_start_sec,
            gap_sec=gap_sec,
            cjk_mode=cjk_mode,
        )
        current_text_lines = []
        current_emotion = ""
        if row is None:
            current_speaker = ""
            return
        current_start_sec = float(row.pop("_next_start"))
        rows.append(row)
        if current_speaker not in seen_speakers:
            seen_speakers.add(current_speaker)
            speaker_ids.append(current_speaker)
        current_speaker = ""

    for raw_line in body_lines:
        stripped = str(raw_line or "").strip()
        if not stripped:
            continue
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if not source_label and stripped.startswith(">"):
            source_label = stripped.lstrip("> ").strip()
        if stripped.startswith("## 制作备注"):
            flush_current()
            stop_after_notes = True
            skipped_blocks_count += 1
            break
        matched = PODCAST_ROLE_LINE_RE.match(stripped)
        if matched:
            flush_current()
            current_speaker = str(matched.group("speaker") or "").strip()
            current_emotion = str(matched.group("emotion") or "").strip()
            first_text = str(matched.group("text") or "").strip()
            current_text_lines = [first_text] if first_text else []
            continue
        if _is_podcast_skip_line(stripped):
            flush_current()
            skipped_blocks_count += 1
            continue
        if current_speaker:
            current_text_lines.append(stripped)

    if not stop_after_notes:
        flush_current()

    if not rows:
        raise ValueError("Could not parse any podcast dialogue rows from script")

    return {
        "title": title or Path(str(source_name or "podcast_script")).stem,
        "source_label": source_label,
        "rows": rows,
        "speaker_ids": speaker_ids,
        "detected_mode": "multi" if len(speaker_ids) > 1 else "single",
        "skipped_blocks_count": skipped_blocks_count,
    }
