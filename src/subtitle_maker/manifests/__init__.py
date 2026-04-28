"""Manifest 读写与兼容工具。"""

from .readwrite import (
    build_batch_manifest,
    build_failed_segment_manifest,
    build_segment_manifest,
    build_skipped_segment_manifest,
    load_batch_manifest,
    load_segment_manifest,
    resolve_output_path,
    resolve_preferred_segment_subtitle_path,
    write_manifest_json,
)
from .schema import BatchManifestView, BatchReplayOptions, SegmentManifestView

__all__ = [
    "BatchManifestView",
    "BatchReplayOptions",
    "SegmentManifestView",
    "build_batch_manifest",
    "build_failed_segment_manifest",
    "build_segment_manifest",
    "build_skipped_segment_manifest",
    "load_batch_manifest",
    "load_segment_manifest",
    "resolve_output_path",
    "resolve_preferred_segment_subtitle_path",
    "write_manifest_json",
]
