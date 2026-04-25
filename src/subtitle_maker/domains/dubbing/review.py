from __future__ import annotations

from dataclasses import dataclass

from subtitle_maker.manifests import SegmentManifestView


@dataclass(frozen=True)
class SegmentRedubRuntimeOptions:
    """局部重配时需要从 manifest 恢复的运行时参数。"""

    pipeline_version: str
    rewrite_translation: bool
    grouped_synthesis: bool
    force_fit_timing: bool
    tts_backend: str
    index_tts_api_url: str


def resolve_segment_redub_runtime_options(
    *,
    segment_manifest: SegmentManifestView,
    fallback_pipeline_version: str,
    fallback_rewrite_translation: bool,
    fallback_index_tts_api_url: str,
) -> SegmentRedubRuntimeOptions:
    """从 segment manifest 恢复 redub 运行时参数，并保留旧默认值语义。"""

    options = segment_manifest.options
    pipeline_version = str(options.pipeline_version or fallback_pipeline_version or "v1").strip().lower() or "v1"
    rewrite_translation = (
        options.rewrite_translation
        if "rewrite_translation" in segment_manifest.raw
        else fallback_rewrite_translation
    )
    tts_backend = str(options.tts_backend or "index-tts").strip() or "index-tts"
    index_tts_api_url = (
        str(options.index_tts_api_url or "").strip()
        if "index_tts_api_url" in segment_manifest.raw
        else fallback_index_tts_api_url
    ) or fallback_index_tts_api_url
    return SegmentRedubRuntimeOptions(
        pipeline_version=pipeline_version,
        rewrite_translation=bool(rewrite_translation),
        grouped_synthesis=bool(options.grouped_synthesis),
        force_fit_timing=bool(options.force_fit_timing),
        tts_backend=tts_backend,
        index_tts_api_url=index_tts_api_url,
    )
