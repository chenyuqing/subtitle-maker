from __future__ import annotations

from typing import List, Tuple

from .srt import subtitle_text_units


def allocate_text_segment_times(
    *,
    start_sec: float,
    end_sec: float,
    segments: List[str],
    cjk_mode: bool,
) -> List[Tuple[float, float]]:
    """按文本负载把原 cue 时长分配给多个子片段。"""
    if not segments:
        return []
    if len(segments) == 1:
        return [(float(start_sec), float(end_sec))]

    total_duration = max(0.05, float(end_sec) - float(start_sec))
    weights = [max(1, subtitle_text_units(segment, cjk_mode=cjk_mode)) for segment in segments]
    total_weight = max(1, sum(weights))
    min_piece_sec = 0.25
    if total_duration < min_piece_sec * len(segments):
        return []

    spans: List[Tuple[float, float]] = []
    cursor = float(start_sec)
    consumed_weight = 0
    for index, weight in enumerate(weights):
        consumed_weight += weight
        if index == len(weights) - 1:
            seg_end = float(end_sec)
        else:
            target_end = float(start_sec) + total_duration * (consumed_weight / float(total_weight))
            remaining_slots = len(weights) - index - 1
            max_end = float(end_sec) - min_piece_sec * remaining_slots
            seg_end = max(cursor + min_piece_sec, min(max_end, target_end))
        spans.append((cursor, seg_end))
        cursor = seg_end
    return spans

