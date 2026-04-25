"""媒体领域模块导出。"""

from .compose import (
    build_full_timeline_bgm,
    build_full_timeline_mix,
    build_full_timeline_vocals,
    compose_vocals_master,
    concat_generated_wavs,
    concat_wav_files,
    merge_bilingual_srt_files,
    merge_srt_files,
    mix_vocals_with_bgm,
    mix_with_bgm,
)
from .probe import audio_duration, ffprobe_duration, load_mono_audio, resample_mono_audio
from .segment import (
    choose_boundaries,
    cut_audio_segment,
    detect_silence_endpoints,
    detect_speech_time_ranges,
    extract_source_audio,
    map_global_ranges_to_segment,
    normalize_time_ranges,
)

__all__ = [
    "audio_duration",
    "ffprobe_duration",
    "load_mono_audio",
    "resample_mono_audio",
    "choose_boundaries",
    "cut_audio_segment",
    "detect_silence_endpoints",
    "detect_speech_time_ranges",
    "extract_source_audio",
    "map_global_ranges_to_segment",
    "normalize_time_ranges",
    "build_full_timeline_bgm",
    "build_full_timeline_mix",
    "build_full_timeline_vocals",
    "compose_vocals_master",
    "concat_generated_wavs",
    "concat_wav_files",
    "merge_bilingual_srt_files",
    "merge_srt_files",
    "mix_vocals_with_bgm",
    "mix_with_bgm",
]

