from __future__ import annotations

from typing import Any, Dict, List, Optional

from .sentence_split import (
    build_asr_gap_clusters,
    split_cluster_into_sentence_blocks,
)
from .srt import (
    ends_with_connector,
    infer_cjk_mode_from_lines,
    is_orphan_like_line,
    is_sentence_end,
    starts_with_connector,
    subtitle_group_text,
)

DEFAULT_SRT_IMPORT_GAP_THRESHOLD_SEC = 1.0
DEFAULT_SRT_IMPORT_SPEAKER_MODE = "auto"
DEFAULT_SRT_IMPORT_MAX_LINE_WIDTH = 25
DEFAULT_SRT_IMPORT_MAX_BLOCK_DURATION_SEC = 12.0


def _normalize_text(value: Any) -> str:
    """把导入后的字幕正文清洗成可合并的单行文本。"""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return " ".join(text.split())


def _coerce_float(value: Any) -> Optional[float]:
    """宽松把时间字段转成浮点秒，便于导入优化统一处理。"""

    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def optimize_srt_import_subtitles(
    subtitles: List[Dict[str, Any]],
    *,
    gap_threshold_sec: float = DEFAULT_SRT_IMPORT_GAP_THRESHOLD_SEC,
    speaker_mode: str = DEFAULT_SRT_IMPORT_SPEAKER_MODE,
    max_line_width: int = DEFAULT_SRT_IMPORT_MAX_LINE_WIDTH,
    max_block_duration_sec: float = DEFAULT_SRT_IMPORT_MAX_BLOCK_DURATION_SEC,
    enforce_merge_duration_guard: bool = False,
) -> List[Dict[str, Any]]:
    """对手工 SRT 导入做优化。

    speaker_mode 说明：
    - auto：先看字幕里是否只有一个 speaker，再自动走单 speaker 或多 speaker 逻辑。
    - single：忽略 speaker 边界，直接按停顿和句末标点做简化分句。
    - multi：保留 speaker 维度，再做句块收敛与碎片修补。
    """

    if len(subtitles) <= 1:
        return [dict(item) for item in subtitles]

    normalized: List[Dict[str, Any]] = []
    for item in subtitles:
        start = _coerce_float(item.get("start"))
        end = _coerce_float(item.get("end"))
        text = _normalize_text(item.get("text"))
        if start is None or end is None or end <= start or not text:
            continue
        speaker_id = str(item.get("speaker_id") or "").strip()
        normalized.append(
            {
                "start": float(start),
                "end": float(end),
                "text": text,
                "speaker_id": speaker_id,
            }
        )

    if len(normalized) <= 1:
        return normalized

    normalized_speaker_mode = str(speaker_mode or DEFAULT_SRT_IMPORT_SPEAKER_MODE).strip().lower()
    if normalized_speaker_mode not in {"auto", "single", "multi"}:
        raise ValueError("speaker_mode must be one of: auto, single, multi")
    if normalized_speaker_mode == "auto":
        unique_speakers = {
            str(item.get("speaker_id") or "").strip()
            for item in normalized
            if str(item.get("speaker_id") or "").strip()
        }
        normalized_speaker_mode = "single" if len(unique_speakers) <= 1 else "multi"

    def merge_block_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """把一个句块合并成单条字幕，尽量保持句子完整。"""

        speaker_id = str(items[0].get("speaker_id") or "").strip()
        cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in items])
        merged_text = subtitle_group_text(items, cjk_mode=cjk_mode)
        merged_item: Dict[str, Any] = {
            "start": round(float(items[0]["start"]), 3),
            "end": round(float(items[-1]["end"]), 3),
            "text": merged_text,
        }
        if speaker_id:
            merged_item["speaker_id"] = speaker_id
        return merged_item

    def merge_two_items(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        """把两条相邻字幕重新合成一条。"""

        cjk_mode = infer_cjk_mode_from_lines([(left.get("text") or ""), (right.get("text") or "")])
        merged_item: Dict[str, Any] = {
            "start": round(float(left["start"]), 3),
            "end": round(float(right["end"]), 3),
            "text": subtitle_group_text([left, right], cjk_mode=cjk_mode),
        }
        speaker_id = str(left.get("speaker_id") or "").strip() or str(right.get("speaker_id") or "").strip()
        if speaker_id:
            merged_item["speaker_id"] = speaker_id
        return merged_item

    def split_overlong_block_by_duration(items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """仅在单句块异常过长时按时长切分，避免出现 30s+ 的单条字幕。"""

        if not items:
            return []
        if (float(items[-1]["end"]) - float(items[0]["start"])) <= max_block_duration_sec:
            return [items]

        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for item in items:
            if not current:
                current = [item]
                continue
            candidate_end = float(item["end"])
            current_start = float(current[0]["start"])
            if (candidate_end - current_start) > max_block_duration_sec:
                chunks.append(current)
                current = [item]
                continue
            current.append(item)
        if current:
            chunks.append(current)
        return chunks

    def optimize_single_speaker_mode() -> List[Dict[str, Any]]:
        """单 speaker 走简化规则，只按停顿和强句末标点收敛。"""

        default_speaker_id = next(
            (str(item.get("speaker_id") or "").strip() for item in normalized if str(item.get("speaker_id") or "").strip()),
            "Speaker 1",
        )
        merged_single: List[Dict[str, Any]] = []
        for cluster in build_asr_gap_clusters(normalized, max_gap_sec=gap_threshold_sec):
            sentence_blocks = split_cluster_into_sentence_blocks(cluster)
            for sentence_block in sentence_blocks:
                for chunk in split_overlong_block_by_duration(sentence_block):
                    if not chunk:
                        continue
                    merged_item = merge_block_items(chunk)
                    if default_speaker_id:
                        merged_item["speaker_id"] = default_speaker_id
                    merged_single.append(merged_item)
        return merged_single

    def is_fragment_like(item: Dict[str, Any]) -> bool:
        """判断句块是否像残句，优先和相邻句块合并。"""

        text = str(item.get("text") or "").strip()
        if not text:
            return False
        if is_orphan_like_line(text):
            return True
        if not is_sentence_end(text):
            return starts_with_connector(text) or len(text.replace(" ", "")) <= 2
        return False

    def can_merge_with_duration_limit(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        """限制残句修补的回并时长，避免重新并回 30s+ 长字幕。"""

        if not enforce_merge_duration_guard:
            return True
        if max_block_duration_sec <= 0:
            return True
        merged_duration = float(right["end"]) - float(left["start"])
        return merged_duration <= max_block_duration_sec

    def merge_two_items(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        """把两条相邻字幕重新合成一条。"""

        cjk_mode = infer_cjk_mode_from_lines([(left.get("text") or ""), (right.get("text") or "")])
        merged_item: Dict[str, Any] = {
            "start": round(float(left["start"]), 3),
            "end": round(float(right["end"]), 3),
            "text": subtitle_group_text([left, right], cjk_mode=cjk_mode),
        }
        speaker_id = str(left.get("speaker_id") or "").strip() or str(right.get("speaker_id") or "").strip()
        if speaker_id:
            merged_item["speaker_id"] = speaker_id
        return merged_item

    def finalize_block() -> None:
        """把当前 speaker block 拆成句块并做轻量碎片修补。"""

        nonlocal block, current_speaker_id
        if not block:
            return

        sentence_blocks: List[List[Dict[str, Any]]] = []
        for cluster in build_asr_gap_clusters(block, max_gap_sec=gap_threshold_sec):
            for sentence_block in split_cluster_into_sentence_blocks(cluster):
                sentence_blocks.extend(split_overlong_block_by_duration(sentence_block))

        sentence_items = [merge_block_items(chunk) for chunk in sentence_blocks if chunk]
        if not sentence_items:
            block = []
            current_speaker_id = None
            return

        repaired: List[Dict[str, Any]] = []
        pending: Optional[Dict[str, Any]] = None
        for item in sentence_items:
            current = dict(item)
            if pending is None:
                pending = current
                continue

            current_text = str(current.get("text") or "").strip()

            if is_fragment_like(pending) and can_merge_with_duration_limit(pending, current):
                pending = merge_two_items(pending, current)
                continue

            if (
                is_sentence_end(current_text)
                and (ends_with_connector(current_text) or is_orphan_like_line(current_text))
                and can_merge_with_duration_limit(pending, current)
            ):
                pending = merge_two_items(pending, current)
                continue

            repaired.append(pending)
            pending = current

        if pending is not None:
            if repaired and is_fragment_like(pending) and can_merge_with_duration_limit(repaired[-1], pending):
                repaired[-1] = merge_two_items(repaired[-1], pending)
            else:
                repaired.append(pending)

        merged.extend(repaired)
        block = []
        current_speaker_id = None

    if normalized_speaker_mode == "single":
        return optimize_single_speaker_mode()

    merged: List[Dict[str, Any]] = []
    block: List[Dict[str, Any]] = []
    current_speaker_id: Optional[str] = None

    for item in normalized:
        speaker_id = str(item.get("speaker_id") or "").strip()
        if not block:
            block = [item]
            current_speaker_id = speaker_id
            continue

        if speaker_id != current_speaker_id:
            finalize_block()
            block = [item]
            current_speaker_id = speaker_id
            continue

        block.append(item)

    finalize_block()
    return merged
