"""配音领域模块导出。"""

from .alignment import (
    allocate_balanced_durations,
    apply_atempo,
    apply_short_fade_edges,
    build_atempo_filter_chain,
    compute_effective_target_duration,
    estimate_line_speech_weight,
    fit_audio_to_duration,
    split_waveform_by_durations,
    trim_audio_to_max_duration,
    trim_silence_edges,
)
from .pipeline import (
    build_synthesis_groups,
    synthesize_segments,
    synthesize_segments_grouped,
    synthesize_text_once,
)
from .references import (
    build_subtitle_reference_map,
    extract_reference_audio,
    extract_reference_audio_from_offset,
    extract_reference_audio_from_window,
)
from .review import SegmentRedubRuntimeOptions, resolve_segment_redub_runtime_options

__all__ = [
    "SegmentRedubRuntimeOptions",
    "allocate_balanced_durations",
    "apply_atempo",
    "apply_short_fade_edges",
    "build_atempo_filter_chain",
    "build_subtitle_reference_map",
    "build_synthesis_groups",
    "compute_effective_target_duration",
    "estimate_line_speech_weight",
    "extract_reference_audio",
    "extract_reference_audio_from_offset",
    "extract_reference_audio_from_window",
    "fit_audio_to_duration",
    "resolve_segment_redub_runtime_options",
    "split_waveform_by_durations",
    "synthesize_segments",
    "synthesize_segments_grouped",
    "synthesize_text_once",
    "trim_audio_to_max_duration",
    "trim_silence_edges",
]
