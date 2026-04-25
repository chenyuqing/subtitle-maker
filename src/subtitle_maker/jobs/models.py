from __future__ import annotations

from typing import Any, Dict, Literal, TypedDict


TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class JobArtifact(TypedDict):
    """任务产物的最小公开描述。"""

    key: str
    label: str
    url: str


class JobErrorPayload(TypedDict, total=False):
    """统一任务错误的轻量结构。"""

    code: str
    message: str
    detail: str
    recoverable: bool


class JobRecord(TypedDict, total=False):
    """当前 Job Store 使用的最小任务记录结构。"""

    id: str
    short_id: str
    status: TaskStatus
    stage: str
    progress: float
    created_at: str
    updated_at: str
    out_root: str
    stdout_tail: list[str]
    artifacts: list[JobArtifact]
    error: str | JobErrorPayload
    batch_id: str
    batch_manifest_path: str
    processed_segments: int
    total_segments: int | None
    manual_review_segments: int
    target_lang: str
    pipeline_version: str
    rewrite_translation: bool
    timing_mode: str
    grouping_strategy: str
    source_short_merge_enabled: bool
    source_short_merge_threshold: int
    subtitle_mode: str
    index_tts_api_url: str
    auto_pick_ranges: bool
    grouped_synthesis: bool
    force_fit_timing: bool
    tts_backend: str
    input_media_url: str | None
    result_audio: str | None
    result_srt: str | None


class PublicJobRecord(TypedDict, total=False):
    """返回给 API 和前端轮询的公开任务视图。"""

    id: str
    short_id: str
    status: TaskStatus
    stage: str
    progress: float
    created_at: str
    updated_at: str
    stdout_tail: list[str]
    artifacts: list[JobArtifact]
    error: str | JobErrorPayload
    batch_id: str
    batch_manifest_path: str
    processed_segments: int
    total_segments: int | None
    manual_review_segments: int
    target_lang: str
    pipeline_version: str
    rewrite_translation: bool
    timing_mode: str
    grouping_strategy: str
    source_short_merge_enabled: bool
    source_short_merge_threshold: int
    subtitle_mode: str
    index_tts_api_url: str
    auto_pick_ranges: bool
    grouped_synthesis: bool
    force_fit_timing: bool
    tts_backend: str
    input_media_url: str | None
    result_audio: str | None
    result_srt: str | None


class DubbingTaskRecord(JobRecord, total=False):
    """兼容旧命名的 Auto Dubbing 任务记录类型。"""


TaskPayload = Dict[str, Any]
