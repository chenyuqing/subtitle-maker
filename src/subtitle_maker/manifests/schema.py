from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BatchReplayOptions:
    """批处理 replay 关键配置。"""

    target_lang: str
    pipeline_version: str
    rewrite_translation: bool
    timing_mode: str
    grouping_strategy: str
    input_srt_kind: str
    index_tts_api_url: str
    auto_pick_ranges: bool
    time_ranges: List[Dict[str, float]] = field(default_factory=list)
    source_short_merge_enabled: bool = False
    source_short_merge_threshold: int = 15
    source_short_merge_threshold_mode: str = "seconds"
    translated_short_merge_enabled: bool = False
    translated_short_merge_threshold: int = 15
    translated_short_merge_threshold_mode: str = "seconds"
    dub_audio_leveling_enabled: bool = True
    dub_audio_leveling_target_rms: float = 0.12
    dub_audio_leveling_activity_threshold_db: float = -35.0
    dub_audio_leveling_max_gain_db: float = 8.0
    dub_audio_leveling_peak_ceiling: float = 0.95
    grouped_synthesis: bool = False
    force_fit_timing: bool = False
    tts_backend: str = "index-tts"
    fallback_tts_backend: str = "none"
    omnivoice_root: str = ""
    omnivoice_python_bin: str = ""
    omnivoice_model: str = ""
    omnivoice_device: str = "auto"
    omnivoice_via_api: bool = True
    omnivoice_api_url: str = "http://127.0.0.1:8020"
    legacy_inferred: Dict[str, bool] = field(default_factory=dict)


@dataclass
class BatchManifestView:
    """批处理 manifest 的标准读取视图。"""

    manifest_path: Path
    raw: Dict[str, Any]
    paths: Dict[str, Optional[str]]
    options: BatchReplayOptions

    @property
    def batch_id(self) -> str:
        """返回批次 ID。"""

        return str(self.raw.get("batch_id") or "")

    @property
    def input_media_path(self) -> str:
        """返回源媒体路径文本。"""

        return str(self.raw.get("input_media_path") or "")

    @property
    def segments(self) -> List[Dict[str, Any]]:
        """返回批次分段摘要列表。"""

        return list(self.raw.get("segments") or [])

    @property
    def segments_total(self) -> int:
        """返回分段总数。"""

        raw_total = self.raw.get("segments_total")
        if raw_total is None:
            return len(self.segments)
        return int(raw_total or 0)


@dataclass
class SegmentManifestView:
    """单段 manifest 的标准读取视图。"""

    manifest_path: Path
    raw: Dict[str, Any]
    paths: Dict[str, Optional[str]]
    options: BatchReplayOptions

    @property
    def job_id(self) -> str:
        """返回单段任务 ID。"""

        return str(self.raw.get("job_id") or "")

    @property
    def input_media_path(self) -> str:
        """返回单段输入媒体路径文本。"""

        return str(self.raw.get("input_media_path") or "")

    @property
    def segment_rows(self) -> List[Dict[str, Any]]:
        """返回单段字幕/合成记录。"""

        return list(self.raw.get("segments") or [])

    @property
    def status(self) -> str:
        """返回单段状态。"""

        return str(self.raw.get("status") or "")
