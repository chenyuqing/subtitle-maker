from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AutoDubbingCommandConfig:
    """Web Auto Dubbing 启动命令的标准配置。"""

    python_executable: str
    tool_path: Path
    input_media: Path
    target_lang: str
    out_dir: Path
    segment_minutes: float
    min_segment_minutes: float
    timing_mode: str
    grouping_strategy: str
    short_merge_enabled: bool
    short_merge_threshold: int
    translate_base_url: str
    translate_model: str
    index_tts_api_url: str
    fallback_tts_backend: str
    omnivoice_root: str
    omnivoice_python_bin: str
    omnivoice_model: str
    omnivoice_device: str
    auto_pick_ranges: bool
    auto_pick_min_silence_sec: float
    auto_pick_min_speech_sec: float
    translated_short_merge_enabled: bool = False
    translated_short_merge_threshold: int = 15
    dub_audio_leveling_enabled: bool = True
    dub_audio_leveling_target_rms: float = 0.12
    dub_audio_leveling_activity_threshold_db: float = -35.0
    dub_audio_leveling_max_gain_db: float = 8.0
    dub_audio_leveling_peak_ceiling: float = 0.95
    resume_batch_dir: Optional[Path] = None
    input_srt: Optional[Path] = None
    input_srt_kind: str = "source"
    time_ranges: List[Dict[str, float]] = field(default_factory=list)
    source_lang: str = "auto"
    pipeline_version: str = "v1"
    rewrite_translation: bool = True
    merge_track: str = "auto"
    tts_backend: str = "index-tts"
    index_tts_via_api: bool = True
    index_tts_api_release_after_job: bool = True
    index_max_text_tokens: int = 40
    omnivoice_via_api: bool = True
    omnivoice_api_url: str = "http://127.0.0.1:8020"
    unbuffered: bool = True


@dataclass
class SegmentRedubCommandConfig:
    """Review save-and-redub 的单段重跑命令配置。"""

    python_executable: str
    tool_path: Path
    segment_job_dir: Path
    out_dir: Path
    input_media: Path
    target_lang: str
    translated_srt: Path
    index_tts_api_url: str
    fallback_tts_backend: str
    omnivoice_root: str
    omnivoice_python_bin: str
    omnivoice_model: str
    omnivoice_device: str
    omnivoice_via_api: bool = True
    omnivoice_api_url: str = "http://127.0.0.1:8020"
    pipeline_version: str = "v1"
    rewrite_translation: bool = True
    grouped_synthesis: bool = False
    force_fit_timing: bool = False
    redub_local_indices: List[int] = field(default_factory=list)
    input_srt_kind: str = "translated"
    tts_backend: str = "index-tts"
    index_tts_via_api: bool = True
    index_tts_api_release_after_job: bool = True
    preserve_synthesis_mode: bool = True


def _append_flag(cmd: List[str], flag: str, value: str) -> None:
    """追加标准 `--flag value` 形式参数。"""

    cmd.extend([flag, value])


def _needs_omnivoice_runtime(tts_backend: str, fallback_tts_backend: str) -> bool:
    """判断当前命令是否需要透传 OmniVoice 运行参数。"""

    primary = str(tts_backend or "").strip().lower()
    fallback = str(fallback_tts_backend or "").strip().lower()
    # 只要主后端或备胎任一使用 OmniVoice，都必须把运行参数透传给 CLI。
    return primary == "omnivoice" or fallback == "omnivoice"


def build_auto_dubbing_command(config: AutoDubbingCommandConfig) -> List[str]:
    """构建长视频自动配音 CLI 命令。"""

    cmd = [config.python_executable]
    if config.unbuffered:
        # 使用无缓冲输出，保证前端能持续收到阶段日志。
        cmd.append("-u")
    cmd.extend(
        [
            str(config.tool_path),
            "--input-media",
            str(config.input_media),
            "--target-lang",
            config.target_lang,
            "--out-dir",
            str(config.out_dir),
            "--segment-minutes",
            str(config.segment_minutes),
            "--min-segment-minutes",
            str(config.min_segment_minutes),
            "--merge-track",
            config.merge_track,
            "--timing-mode",
            config.timing_mode,
            "--grouping-strategy",
            config.grouping_strategy,
            "--source-short-merge-enabled",
            "true" if config.short_merge_enabled else "false",
            "--source-short-merge-threshold",
            str(config.short_merge_threshold),
            "--translated-short-merge-enabled",
            "true" if config.translated_short_merge_enabled else "false",
            "--translated-short-merge-threshold",
            str(config.translated_short_merge_threshold),
            "--dub-audio-leveling-enabled",
            "true" if config.dub_audio_leveling_enabled else "false",
            "--dub-audio-leveling-target-rms",
            str(config.dub_audio_leveling_target_rms),
            "--dub-audio-leveling-activity-threshold-db",
            str(config.dub_audio_leveling_activity_threshold_db),
            "--dub-audio-leveling-max-gain-db",
            str(config.dub_audio_leveling_max_gain_db),
            "--dub-audio-leveling-peak-ceiling",
            str(config.dub_audio_leveling_peak_ceiling),
            "--tts-backend",
            config.tts_backend,
            "--fallback-tts-backend",
            config.fallback_tts_backend,
            "--index-tts-via-api",
            "true" if config.index_tts_via_api else "false",
            "--index-tts-api-url",
            config.index_tts_api_url,
            "--index-tts-api-release-after-job",
            "true" if config.index_tts_api_release_after_job else "false",
            "--index-max-text-tokens",
            str(config.index_max_text_tokens),
            "--translate-base-url",
            config.translate_base_url,
            "--translate-model",
            config.translate_model,
            "--auto-pick-ranges",
            "true" if config.auto_pick_ranges else "false",
            "--auto-pick-min-silence-sec",
            str(config.auto_pick_min_silence_sec),
            "--auto-pick-min-speech-sec",
            str(config.auto_pick_min_speech_sec),
        ]
    )
    if _needs_omnivoice_runtime(config.tts_backend, config.fallback_tts_backend):
        # 主后端或备胎使用 OmniVoice 时，都要显式透传运行参数，避免命令回放失败。
        _append_flag(cmd, "--omnivoice-via-api", "true" if config.omnivoice_via_api else "false")
        _append_flag(cmd, "--omnivoice-api-url", config.omnivoice_api_url)
        _append_flag(cmd, "--omnivoice-root", config.omnivoice_root)
        _append_flag(cmd, "--omnivoice-python-bin", config.omnivoice_python_bin)
        _append_flag(cmd, "--omnivoice-model", config.omnivoice_model)
        _append_flag(cmd, "--omnivoice-device", config.omnivoice_device)
    if config.resume_batch_dir is not None:
        # 断点续跑时显式透传 batch 目录，复用 long-video CLI 的 resume 逻辑。
        _append_flag(cmd, "--resume-batch-dir", str(config.resume_batch_dir))
    if config.input_srt is not None:
        _append_flag(cmd, "--input-srt", str(config.input_srt))
        _append_flag(cmd, "--input-srt-kind", config.input_srt_kind)
    if config.time_ranges:
        _append_flag(cmd, "--time-ranges-json", json.dumps(config.time_ranges, ensure_ascii=False))
    if config.source_lang and config.source_lang != "auto":
        _append_flag(cmd, "--asr-language", config.source_lang)
    if config.pipeline_version == "v2":
        # V2 仍通过显式开关透传，避免下游默认值漂移。
        _append_flag(cmd, "--v2-mode", "true")
        _append_flag(cmd, "--v2-rewrite-translation", "true" if config.rewrite_translation else "false")
    return cmd


def build_segment_redub_command(config: SegmentRedubCommandConfig) -> List[str]:
    """构建 review 场景的单段重配命令。"""

    cmd = [
        config.python_executable,
        str(config.tool_path),
        "--resume-job-dir",
        str(config.segment_job_dir),
        "--out-dir",
        str(config.out_dir),
        "--input-media",
        str(config.input_media),
        "--target-lang",
        config.target_lang,
        "--input-srt",
        str(config.translated_srt),
        "--input-srt-kind",
        config.input_srt_kind,
        "--tts-backend",
        config.tts_backend,
        "--fallback-tts-backend",
        config.fallback_tts_backend,
        "--index-tts-via-api",
        "true" if config.index_tts_via_api else "false",
        "--index-tts-api-url",
        config.index_tts_api_url,
        "--index-tts-api-release-after-job",
        "true" if config.index_tts_api_release_after_job else "false",
        "--grouped-synthesis",
        "true" if config.grouped_synthesis else "false",
        "--force-fit-timing",
        "true" if config.force_fit_timing else "false",
        "--translated-input-preserve-synthesis-mode",
        "true" if config.preserve_synthesis_mode else "false",
    ]
    if _needs_omnivoice_runtime(config.tts_backend, config.fallback_tts_backend):
        _append_flag(cmd, "--omnivoice-via-api", "true" if config.omnivoice_via_api else "false")
        _append_flag(cmd, "--omnivoice-api-url", config.omnivoice_api_url)
        _append_flag(cmd, "--omnivoice-root", config.omnivoice_root)
        _append_flag(cmd, "--omnivoice-python-bin", config.omnivoice_python_bin)
        _append_flag(cmd, "--omnivoice-model", config.omnivoice_model)
        _append_flag(cmd, "--omnivoice-device", config.omnivoice_device)
    # grouped 片段共享同一份音频，局部重配必须整段重跑。
    if config.redub_local_indices and not config.grouped_synthesis:
        normalized_indices = sorted({int(index) for index in config.redub_local_indices if int(index) > 0})
        if normalized_indices:
            _append_flag(cmd, "--redub-line-indices-json", json.dumps(normalized_indices))
    if config.pipeline_version == "v2":
        _append_flag(cmd, "--v2-mode", "true")
        _append_flag(cmd, "--v2-rewrite-translation", "true" if config.rewrite_translation else "false")
    return cmd
