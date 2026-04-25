from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .srt import build_rebalanced_subtitle, ends_with_connector, extract_edge_tokens, is_sentence_end


def source_short_merge_tolerance_seconds(target_seconds: int) -> int:
    """按文档公式计算容差：round(target / 3)，且至少保留 1 秒。"""
    safe_target = max(1, int(target_seconds or 0))
    return max(1, int(round(safe_target / 3.0)))


def subtitle_item_duration_ms(item: Dict[str, Any]) -> int:
    """把单条字幕时长统一转成毫秒整数。"""
    start_sec = float(item.get("start", 0.0) or 0.0)
    end_sec = float(item.get("end", 0.0) or 0.0)
    return max(0, int(round((end_sec - start_sec) * 1000.0)))


def subtitle_items_gap_ms(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    """返回两条相邻字幕之间的静默间隔毫秒数。"""
    left_end_sec = float(left.get("end", 0.0) or 0.0)
    right_start_sec = float(right.get("start", 0.0) or 0.0)
    return int(round((right_start_sec - left_end_sec) * 1000.0))


def short_merge_ending_score(text: str) -> int:
    """给候选断点做浅层句尾打分。"""
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
    """按合法区间、自然句尾和接近目标时长选择最佳断点。"""
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
    gap_threshold_sec: float,
) -> Tuple[List[Dict[str, Any]], int]:
    """第二阶段仅做相邻短句时间窗合并，绝不为凑目标再次拆句。"""
    if len(subtitles) <= 1:
        return [dict(item) for item in subtitles], 0

    target_seconds = max(1, int(short_merge_target_seconds or 0))
    tolerance_seconds = source_short_merge_tolerance_seconds(target_seconds)
    target_ms = target_seconds * 1000
    min_ms = max(0, (target_seconds - tolerance_seconds) * 1000)
    max_ms = (target_seconds + tolerance_seconds) * 1000
    gap_threshold_ms = max(0, int(round(float(gap_threshold_sec) * 1000.0)))

    working = [dict(item) for item in subtitles]
    output: List[Dict[str, Any]] = []
    merged_pairs = 0
    index = 0

    while index < len(working):
        current = working[index]
        current_duration_ms = subtitle_item_duration_ms(current)
        if current_duration_ms > target_ms:
            output.append(dict(current))
            index += 1
            continue

        candidates: List[Dict[str, Any]] = []
        end_index = index
        while end_index < len(working):
            if end_index > index:
                candidate_tail = working[end_index]
                if subtitle_item_duration_ms(candidate_tail) > target_ms:
                    break
                if subtitle_items_gap_ms(working[end_index - 1], candidate_tail) > gap_threshold_ms:
                    break

            candidate_group = working[index : end_index + 1]
            merged_item = build_rebalanced_subtitle(candidate_group)
            merged_duration_ms = subtitle_item_duration_ms(merged_item)
            candidates.append(
                {
                    "end_idx": end_index,
                    "duration_ms": merged_duration_ms,
                    "item": merged_item,
                }
            )
            if merged_duration_ms > max_ms:
                break
            end_index += 1

        if not candidates:
            output.append(dict(current))
            index += 1
            continue

        best_candidate = choose_best_short_merge_candidate(
            candidates=candidates,
            target_ms=target_ms,
            min_ms=min_ms,
            max_ms=max_ms,
        )
        output.append(dict(best_candidate["item"]))
        merged_pairs += max(0, int(best_candidate["end_idx"]) - index)
        index = int(best_candidate["end_idx"]) + 1

    return output, merged_pairs
