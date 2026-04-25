from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from .srt import (
    asr_sentence_text_limit,
    ends_with_connector,
    ends_with_explicit_break,
    ends_with_soft_sentence_break,
    infer_cjk_mode_from_lines,
    is_orphan_like_line,
    is_sentence_end,
    soft_source_layout_text_limit,
    starts_with_connector,
    subtitle_group_duration,
    subtitle_group_text,
    subtitle_text_units,
)
from .timeline import allocate_text_segment_times


def split_text_on_punctuation_boundaries(
    text: str,
    *,
    include_soft_breaks: bool,
) -> List[str]:
    """按标点切分文本，并把标点保留在左侧片段。"""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    if include_soft_breaks:
        pattern = re.compile(r".+?(?:[.!?。！？][\"')\]]*|[,;:，、；：…])(?:\s+|$)|.+$")
    else:
        pattern = re.compile(r".+?[.!?。！？][\"')\]]*(?:\s+|$)|.+$")
    segments = [match.group(0).strip() for match in pattern.finditer(cleaned) if match.group(0).strip()]
    return segments or [cleaned]


def split_subtitle_item_by_punctuation(
    item: Dict[str, Any],
    *,
    include_soft_breaks: bool,
) -> List[Dict[str, Any]]:
    """当单个 cue 内部有标点切点时，拆成更细的字幕片段。"""
    text = (item.get("text") or "").strip()
    if not text:
        return [dict(item)]

    segments = split_text_on_punctuation_boundaries(text, include_soft_breaks=include_soft_breaks)
    if len(segments) <= 1:
        return [dict(item)]

    cjk_mode = infer_cjk_mode_from_lines([text])
    spans = allocate_text_segment_times(
        start_sec=float(item["start"]),
        end_sec=float(item["end"]),
        segments=segments,
        cjk_mode=cjk_mode,
    )
    if len(spans) != len(segments):
        return [dict(item)]

    output: List[Dict[str, Any]] = []
    for (seg_start, seg_end), seg_text in zip(spans, segments):
        piece = dict(item)
        piece["start"] = float(seg_start)
        piece["end"] = float(seg_end)
        piece["text"] = seg_text
        output.append(piece)
    return output


def expand_block_with_punctuation_splits(
    block: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> List[Dict[str, Any]]:
    """为句块补充标点级切点。"""
    output: List[Dict[str, Any]] = []
    for item in block:
        output.extend(split_subtitle_item_by_punctuation(item, include_soft_breaks=include_soft_breaks))
    return output


def split_cluster_into_punctuation_blocks(
    cluster: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> List[List[Dict[str, Any]]]:
    """按显式标点边界切成多个句块。"""
    if not cluster:
        return []

    blocks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for item in cluster:
        current.append(item)
        text = (item.get("text") or "").strip()
        if is_sentence_end(text) or (include_soft_breaks and ends_with_soft_sentence_break(text)):
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def build_asr_gap_clusters(
    subtitles: List[Dict[str, Any]],
    *,
    max_gap_sec: float,
) -> List[List[Dict[str, Any]]]:
    """先按短停顿聚类，避免跨明显停顿误合并。"""
    if not subtitles:
        return []

    clusters: List[List[Dict[str, Any]]] = []
    current = [dict(subtitles[0])]
    for raw_item in subtitles[1:]:
        item = dict(raw_item)
        gap = float(item["start"]) - float(current[-1]["end"])
        if gap <= max_gap_sec:
            current.append(item)
            continue
        clusters.append(current)
        current = [item]
    clusters.append(current)
    return clusters


def split_cluster_into_sentence_blocks(cluster: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """在短停顿簇内部优先按强句末标点收敛为句级块。"""
    return split_cluster_into_punctuation_blocks(cluster, include_soft_breaks=False)


def has_internal_explicit_break_boundary(
    block: List[Dict[str, Any]],
    *,
    include_soft_breaks: bool,
) -> bool:
    """判断句块内部是否存在可用于切分的显式标点边界。"""
    if len(block) <= 1:
        return False
    for item in block[:-1]:
        text = (item.get("text") or "").strip()
        if is_sentence_end(text):
            return True
        if include_soft_breaks and ends_with_soft_sentence_break(text):
            return True
    return False


def choose_asr_sentence_split_index(
    block: List[Dict[str, Any]],
    *,
    cjk_mode: bool,
    max_gap_sec: float,
    target_duration_sec: float,
    target_text_units: float,
    require_explicit_break: bool = False,
) -> Optional[int]:
    """为超长句挑一个尽量自然的切点，只允许落在原 ASR cue 边界上。"""
    if len(block) <= 1:
        return None

    pause_boundary_sec = max(0.25, max_gap_sec * 0.6)
    boundary_priorities: List[int] = []
    for index in range(len(block) - 1):
        boundary_text = (block[index].get("text") or "").strip()
        if is_sentence_end(boundary_text):
            boundary_priorities.append(2)
        elif ends_with_soft_sentence_break(boundary_text):
            boundary_priorities.append(1)
        else:
            boundary_priorities.append(0)

    preferred_priority = max(boundary_priorities) if boundary_priorities else 0
    best_index: Optional[int] = None
    best_score: Optional[float] = None

    for index in range(len(block) - 1):
        boundary_priority = boundary_priorities[index]
        if require_explicit_break:
            if boundary_priority == 0:
                continue
        elif preferred_priority > 0 and boundary_priority != preferred_priority:
            continue

        left = block[: index + 1]
        right = block[index + 1 :]
        left_text = subtitle_group_text(left, cjk_mode=cjk_mode)
        right_text = subtitle_group_text(right, cjk_mode=cjk_mode)
        left_duration = subtitle_group_duration(left)
        right_duration = subtitle_group_duration(right)
        left_units = subtitle_text_units(left_text, cjk_mode=cjk_mode)
        gap_after = float(block[index + 1]["start"]) - float(block[index]["end"])
        left_has_explicit_break = ends_with_explicit_break(left_text)

        score = abs(left_duration - target_duration_sec)
        score += abs(left_units - target_text_units) / max(1.0, target_text_units) * 0.35
        if boundary_priority == 2:
            score -= 1.0
        elif boundary_priority == 1:
            score -= 0.75
        elif gap_after >= pause_boundary_sec:
            score -= 0.35

        if left_duration < 1.2 or right_duration < 1.2:
            score += 0.5
        if is_orphan_like_line(left_text) or is_orphan_like_line(right_text):
            score += 0.8
        if ends_with_connector(left_text):
            score += 0.35
        if starts_with_connector(right_text) and not left_has_explicit_break:
            score += 0.35

        if best_score is None or score < best_score:
            best_score = score
            best_index = index

    return best_index


def split_oversized_asr_sentence_block(
    block: List[Dict[str, Any]],
    *,
    max_gap_sec: float,
    max_line_width: int,
) -> List[List[Dict[str, Any]]]:
    """把超长句拆成更稳妥的子句块，但仍保持句子优先。"""
    if not block:
        return []

    sentence_expanded_block = expand_block_with_punctuation_splits(
        block,
        include_soft_breaks=False,
    )
    sentence_blocks = split_cluster_into_sentence_blocks(sentence_expanded_block)
    if len(sentence_blocks) > 1:
        output: List[List[Dict[str, Any]]] = []
        for sentence_block in sentence_blocks:
            output.extend(
                split_oversized_asr_sentence_block(
                    sentence_block,
                    max_gap_sec=max_gap_sec,
                    max_line_width=max_line_width,
                )
            )
        return output

    working_block = sentence_blocks[0] if sentence_blocks else sentence_expanded_block
    cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in working_block])
    merged_text = subtitle_group_text(working_block, cjk_mode=cjk_mode)
    total_duration = subtitle_group_duration(working_block)
    total_units = subtitle_text_units(merged_text, cjk_mode=cjk_mode)
    hard_duration_sec = 9.0
    hard_text_units = asr_sentence_text_limit(max_line_width=max_line_width, cjk_mode=cjk_mode)
    soft_duration_sec = 7.2
    soft_text_units = soft_source_layout_text_limit(max_line_width=max_line_width, cjk_mode=cjk_mode)
    hard_split_needed = total_duration > hard_duration_sec or total_units > hard_text_units

    soft_split_candidate = total_duration > soft_duration_sec or total_units > soft_text_units
    if soft_split_candidate:
        comma_expanded_block = expand_block_with_punctuation_splits(
            working_block,
            include_soft_breaks=True,
        )
        if len(comma_expanded_block) > len(working_block):
            working_block = comma_expanded_block
            cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in working_block])
            merged_text = subtitle_group_text(working_block, cjk_mode=cjk_mode)
            total_duration = subtitle_group_duration(working_block)
            total_units = subtitle_text_units(merged_text, cjk_mode=cjk_mode)
            hard_text_units = asr_sentence_text_limit(max_line_width=max_line_width, cjk_mode=cjk_mode)
            soft_text_units = soft_source_layout_text_limit(max_line_width=max_line_width, cjk_mode=cjk_mode)
            hard_split_needed = total_duration > hard_duration_sec or total_units > hard_text_units

    explicit_soft_split_needed = (
        soft_split_candidate and has_internal_explicit_break_boundary(working_block, include_soft_breaks=True)
    )
    if not hard_split_needed and not explicit_soft_split_needed:
        return [working_block]
    if len(working_block) <= 1:
        return [working_block]

    target_duration_limit = hard_duration_sec if hard_split_needed else soft_duration_sec
    target_text_limit = hard_text_units if hard_split_needed else soft_text_units
    desired_parts = max(
        2,
        int(math.ceil(total_duration / max(0.1, target_duration_limit))),
        int(math.ceil(total_units / max(1.0, float(target_text_limit)))),
    )
    parts: List[List[Dict[str, Any]]] = []
    remaining = working_block
    split_applied = False

    while len(parts) < desired_parts - 1 and len(remaining) > 1:
        remaining_slots = desired_parts - len(parts)
        remaining_duration = subtitle_group_duration(remaining)
        remaining_units = subtitle_text_units(
            subtitle_group_text(remaining, cjk_mode=cjk_mode),
            cjk_mode=cjk_mode,
        )
        remaining_requires_hard_split = (
            remaining_duration > hard_duration_sec or remaining_units > hard_text_units
        )
        target_duration_sec = remaining_duration / float(remaining_slots)
        target_text_units = remaining_units / float(remaining_slots)
        split_index = choose_asr_sentence_split_index(
            remaining,
            cjk_mode=cjk_mode,
            max_gap_sec=max_gap_sec,
            target_duration_sec=target_duration_sec,
            target_text_units=target_text_units,
            require_explicit_break=not remaining_requires_hard_split,
        )
        if split_index is None:
            break
        left = remaining[: split_index + 1]
        right = remaining[split_index + 1 :]
        if not left or not right:
            break
        parts.append(left)
        remaining = right
        split_applied = True
    parts.append(remaining)

    if not split_applied:
        return [working_block]

    output: List[List[Dict[str, Any]]] = []
    for part in parts:
        if len(part) <= 1:
            output.append(part)
            continue
        output.extend(
            split_oversized_asr_sentence_block(
                part,
                max_gap_sec=max_gap_sec,
                max_line_width=max_line_width,
            )
        )
    return output

