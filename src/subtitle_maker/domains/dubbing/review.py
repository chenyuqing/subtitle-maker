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
    fallback_tts_backend: str
    index_tts_api_url: str
    omnivoice_root: str
    omnivoice_python_bin: str
    omnivoice_model: str
    omnivoice_device: str
    omnivoice_via_api: bool
    omnivoice_api_url: str


def resolve_segment_redub_runtime_options(
    *,
    segment_manifest: SegmentManifestView,
    fallback_pipeline_version: str,
    fallback_rewrite_translation: bool,
    fallback_index_tts_api_url: str,
    fallback_tts_backend: str = "none",
    fallback_omnivoice_root: str = "",
    fallback_omnivoice_python_bin: str = "",
    fallback_omnivoice_model: str = "",
    fallback_omnivoice_device: str = "auto",
    fallback_omnivoice_via_api: bool = True,
    fallback_omnivoice_api_url: str = "http://127.0.0.1:8020",
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
    fallback_tts_backend = (
        str(options.fallback_tts_backend or "").strip()
        if "fallback_tts_backend" in segment_manifest.raw
        else str(fallback_tts_backend or "none").strip()
    ) or "none"
    index_tts_api_url = (
        str(options.index_tts_api_url or "").strip()
        if "index_tts_api_url" in segment_manifest.raw
        else fallback_index_tts_api_url
    ) or fallback_index_tts_api_url
    omnivoice_root = (
        str(options.omnivoice_root or "").strip()
        if "omnivoice_root" in segment_manifest.raw
        else str(fallback_omnivoice_root or "").strip()
    )
    omnivoice_python_bin = (
        str(options.omnivoice_python_bin or "").strip()
        if "omnivoice_python_bin" in segment_manifest.raw
        else str(fallback_omnivoice_python_bin or "").strip()
    )
    omnivoice_model = (
        str(options.omnivoice_model or "").strip()
        if "omnivoice_model" in segment_manifest.raw
        else str(fallback_omnivoice_model or "").strip()
    )
    omnivoice_device = (
        str(options.omnivoice_device or "").strip()
        if "omnivoice_device" in segment_manifest.raw
        else str(fallback_omnivoice_device or "").strip()
    ) or "auto"
    omnivoice_via_api = (
        bool(options.omnivoice_via_api)
        if "omnivoice_via_api" in segment_manifest.raw
        else bool(fallback_omnivoice_via_api)
    )
    omnivoice_api_url = (
        str(options.omnivoice_api_url or "").strip()
        if "omnivoice_api_url" in segment_manifest.raw
        else str(fallback_omnivoice_api_url or "").strip()
    ) or "http://127.0.0.1:8020"
    return SegmentRedubRuntimeOptions(
        pipeline_version=pipeline_version,
        rewrite_translation=bool(rewrite_translation),
        grouped_synthesis=bool(options.grouped_synthesis),
        force_fit_timing=bool(options.force_fit_timing),
        tts_backend=tts_backend,
        fallback_tts_backend=fallback_tts_backend,
        index_tts_api_url=index_tts_api_url,
        omnivoice_root=omnivoice_root,
        omnivoice_python_bin=omnivoice_python_bin,
        omnivoice_model=omnivoice_model,
        omnivoice_device=omnivoice_device,
        omnivoice_via_api=omnivoice_via_api,
        omnivoice_api_url=omnivoice_api_url,
    )
