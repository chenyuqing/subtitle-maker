"""字幕领域纯规则模块导出。"""

from .timeline import allocate_text_segment_times
from .sentence_split import (
    build_asr_gap_clusters,
    choose_asr_sentence_split_index,
    expand_block_with_punctuation_splits,
    has_internal_explicit_break_boundary,
    split_cluster_into_punctuation_blocks,
    split_cluster_into_sentence_blocks,
    split_oversized_asr_sentence_block,
    split_subtitle_item_by_punctuation,
    split_text_on_punctuation_boundaries,
)
from .short_merge import merge_short_source_subtitles, source_short_merge_tolerance_seconds
from .deepgram import deepgram_json_to_subtitles
from .srt_import import optimize_srt_import_subtitles
from .srt import infer_cjk_mode_from_lines, subtitle_group_text
from .podcast_script import parse_podcast_script_text
from .speakers import (
    build_segment_speaker_metadata_from_subtitles,
    normalize_subtitles_with_speakers,
    parse_speaker_ref_map_json,
    parse_speaker_reference_specs_json,
    strip_speaker_prefix,
)
from .zh_script import convert_chinese_script_rows, convert_chinese_script_text

__all__ = [
    "allocate_text_segment_times",
    "build_asr_gap_clusters",
    "choose_asr_sentence_split_index",
    "expand_block_with_punctuation_splits",
    "has_internal_explicit_break_boundary",
    "infer_cjk_mode_from_lines",
    "merge_short_source_subtitles",
    "build_segment_speaker_metadata_from_subtitles",
    "deepgram_json_to_subtitles",
    "normalize_subtitles_with_speakers",
    "parse_speaker_ref_map_json",
    "parse_speaker_reference_specs_json",
    "parse_podcast_script_text",
    "optimize_srt_import_subtitles",
    "source_short_merge_tolerance_seconds",
    "strip_speaker_prefix",
    "convert_chinese_script_rows",
    "convert_chinese_script_text",
    "subtitle_group_text",
    "split_cluster_into_punctuation_blocks",
    "split_cluster_into_sentence_blocks",
    "split_oversized_asr_sentence_block",
    "split_subtitle_item_by_punctuation",
    "split_text_on_punctuation_boundaries",
]
