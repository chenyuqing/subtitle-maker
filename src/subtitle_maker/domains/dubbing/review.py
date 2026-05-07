from __future__ import annotations

from dataclasses import dataclass

from subtitle_maker.manifests import SegmentManifestView


@dataclass(frozen=True)
class SegmentRedubRuntimeOptions:
    """局部重配时需要从 manifest 恢复的最小运行时参数。"""

    rewrite_translation: bool
    grouped_synthesis: bool
    force_fit_timing: bool
    tts_backend: str
    index_tts_api_url: str


def resolve_segment_redub_runtime_options(
    *,
    segment_manifest: SegmentManifestView,
    fallback_rewrite_translation: bool,
    fallback_index_tts_api_url: str,
) -> SegmentRedubRuntimeOptions:
    """从 segment manifest 恢复 redub 运行时参数。

    Auto Dubbing 已固定只走 index-tts。这里仍兼容读取历史 manifest，
    但 redub 会强制收口到 index-tts，避免旧底座字段重新渗回当前链路。
    """

    options = segment_manifest.options
    rewrite_translation = (
        options.rewrite_translation
        if "rewrite_translation" in segment_manifest.raw
        else fallback_rewrite_translation
    )
    index_tts_api_url = (
        str(options.index_tts_api_url or "").strip()
        if "index_tts_api_url" in segment_manifest.raw
        else fallback_index_tts_api_url
    ) or fallback_index_tts_api_url
    return SegmentRedubRuntimeOptions(
        rewrite_translation=bool(rewrite_translation),
        grouped_synthesis=bool(options.grouped_synthesis),
        force_fit_timing=bool(options.force_fit_timing),
        tts_backend="index-tts",
        index_tts_api_url=index_tts_api_url,
    )
