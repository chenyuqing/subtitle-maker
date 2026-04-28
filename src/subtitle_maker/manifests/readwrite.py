from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import BatchManifestView, BatchReplayOptions, SegmentManifestView


DEFAULT_INDEX_TTS_API_URL = "http://127.0.0.1:8010"
DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC = 15
MIN_SOURCE_SHORT_MERGE_TARGET_SEC = 6
MAX_SOURCE_SHORT_MERGE_TARGET_SEC = 20


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """宽松解析 manifest 中的布尔字段。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_short_merge_target_seconds(value: Any, *, mode: str) -> int:
    """兼容历史字数阈值，把展示值统一为秒数。"""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode != "seconds" and parsed > MAX_SOURCE_SHORT_MERGE_TARGET_SEC:
        return DEFAULT_SOURCE_SHORT_MERGE_TARGET_SEC
    return max(MIN_SOURCE_SHORT_MERGE_TARGET_SEC, min(MAX_SOURCE_SHORT_MERGE_TARGET_SEC, parsed))


def _normalize_time_ranges(raw: Any) -> List[Dict[str, float]]:
    """把不同来源的 range 字段统一成 `start_sec/end_sec` 结构。"""

    output: List[Dict[str, float]] = []
    for item in list(raw or []):
        if not isinstance(item, dict):
            continue
        try:
            start_sec = float(item.get("start_sec"))
            end_sec = float(item.get("end_sec"))
        except (TypeError, ValueError):
            continue
        if end_sec <= start_sec:
            continue
        output.append({"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)})
    return output


def _read_json(path: Path) -> Dict[str, Any]:
    """读取 JSON manifest 文件。"""

    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """以统一格式落盘 manifest JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def resolve_output_path(path_text: Any, *, repo_root: Optional[Path] = None) -> Optional[Path]:
    """解析 manifest 中的产物路径，兼容相对仓库根目录的旧写法。"""

    if not path_text:
        return None
    raw = Path(str(path_text)).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if repo_root is None:
        return raw.resolve()
    return (repo_root.expanduser().resolve() / raw).resolve()


def resolve_preferred_segment_subtitle_path(
    *,
    job_dir: Path,
    paths: Dict[str, Any],
    subtitle_key: str,
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    """优先返回 segment/subtitles 下的最新字幕；缺失时再回退 manifest 历史路径。"""

    normalized_job_dir = job_dir.expanduser().resolve()
    subtitle_name_by_key = {
        "source_srt": "source.srt",
        "translated_srt": "translated.srt",
        "dubbed_final_srt": "dubbed_final.srt",
    }
    subtitle_name = subtitle_name_by_key.get(str(subtitle_key or "").strip())
    if not subtitle_name:
        raise ValueError(f"unsupported subtitle key: {subtitle_key}")
    canonical_path = normalized_job_dir / "subtitles" / subtitle_name
    if canonical_path.exists():
        return canonical_path
    manifest_path = resolve_output_path(paths.get(subtitle_key), repo_root=repo_root)
    if manifest_path and manifest_path.exists():
        return manifest_path
    return None


def _normalize_range_pairs(ranges: Sequence[Tuple[float, float]]) -> List[Dict[str, float]]:
    """把 `(start, end)` 区间列表转换为 manifest 统一字典结构。"""

    output: List[Dict[str, float]] = []
    for start_sec, end_sec in ranges:
        output.append({"start_sec": round(float(start_sec), 3), "end_sec": round(float(end_sec), 3)})
    return output


def _serialize_optional_paths(paths: Dict[str, Optional[Path]]) -> Dict[str, Optional[str]]:
    """把 `Path | None` 映射统一序列化为 manifest 可写结构。"""

    output: Dict[str, Optional[str]] = {}
    for key, value in paths.items():
        output[key] = str(value) if value else None
    return output


def _build_batch_options(raw: Dict[str, Any]) -> BatchReplayOptions:
    """从 batch manifest 提取统一 replay 配置。"""

    legacy_inferred: Dict[str, bool] = {}
    target_lang = str(raw.get("target_lang") or "")
    if not target_lang:
        legacy_inferred["target_lang"] = True
    pipeline_version = str(raw.get("pipeline_version") or "v1")
    if "pipeline_version" not in raw:
        legacy_inferred["pipeline_version"] = True
    return BatchReplayOptions(
        target_lang=target_lang,
        pipeline_version=pipeline_version,
        rewrite_translation=_coerce_bool(raw.get("rewrite_translation"), default=True),
        timing_mode=str(raw.get("timing_mode") or "strict"),
        grouping_strategy=str(raw.get("grouping_strategy") or "sentence"),
        input_srt_kind=str(raw.get("input_srt_kind") or raw.get("subtitle_mode") or "source"),
        index_tts_api_url=str(raw.get("index_tts_api_url") or DEFAULT_INDEX_TTS_API_URL),
        auto_pick_ranges=_coerce_bool(raw.get("auto_pick_ranges"), default=False),
        time_ranges=_normalize_time_ranges(raw.get("requested_time_ranges") or raw.get("requested_ranges") or []),
        source_short_merge_enabled=_coerce_bool(raw.get("source_short_merge_enabled"), default=False),
        source_short_merge_threshold=_normalize_short_merge_target_seconds(
            raw.get("source_short_merge_threshold"),
            mode=str(raw.get("source_short_merge_threshold_mode") or ""),
        ),
        source_short_merge_threshold_mode="seconds",
        translated_short_merge_enabled=_coerce_bool(raw.get("translated_short_merge_enabled"), default=False),
        translated_short_merge_threshold=_normalize_short_merge_target_seconds(
            raw.get("translated_short_merge_threshold"),
            mode=str(raw.get("translated_short_merge_threshold_mode") or ""),
        ),
        translated_short_merge_threshold_mode="seconds",
        dub_audio_leveling_enabled=_coerce_bool(raw.get("dub_audio_leveling_enabled"), default=True),
        dub_audio_leveling_target_rms=float(raw.get("dub_audio_leveling_target_rms") or 0.12),
        dub_audio_leveling_activity_threshold_db=float(raw.get("dub_audio_leveling_activity_threshold_db") or -35.0),
        dub_audio_leveling_max_gain_db=float(raw.get("dub_audio_leveling_max_gain_db") or 8.0),
        dub_audio_leveling_peak_ceiling=float(raw.get("dub_audio_leveling_peak_ceiling") or 0.95),
        grouped_synthesis=_coerce_bool(raw.get("grouped_synthesis"), default=False),
        force_fit_timing=_coerce_bool(raw.get("force_fit_timing"), default=False),
        tts_backend=str(raw.get("tts_backend") or "index-tts"),
        fallback_tts_backend=str(raw.get("fallback_tts_backend") or "none"),
        omnivoice_root=str(raw.get("omnivoice_root") or ""),
        omnivoice_python_bin=str(raw.get("omnivoice_python_bin") or ""),
        omnivoice_model=str(raw.get("omnivoice_model") or ""),
        omnivoice_device=str(raw.get("omnivoice_device") or "auto"),
        omnivoice_via_api=_coerce_bool(raw.get("omnivoice_via_api"), default=True),
        omnivoice_api_url=str(raw.get("omnivoice_api_url") or "http://127.0.0.1:8020"),
        legacy_inferred=legacy_inferred,
    )


def _build_segment_options(raw: Dict[str, Any]) -> BatchReplayOptions:
    """从 segment manifest 提取 replay 配置，并兼容旧字段缺失。"""

    rows = list(raw.get("segments") or [])
    inferred_grouped_synthesis = any(str(row.get("group_id") or "").strip() for row in rows) or any(
        bool(row.get("skip_compose")) for row in rows
    )
    pipeline_version = str(raw.get("pipeline_version") or "v1").strip().lower() or "v1"
    input_srt_kind = str(raw.get("input_srt_kind") or "source").strip().lower() or "source"
    if "force_fit_timing" in raw:
        force_fit_timing = _coerce_bool(raw.get("force_fit_timing"), default=False)
    else:
        # 老 manifest 缺字段时沿用当前 review redub 的保守推断。
        force_fit_timing = False if pipeline_version == "v2" or input_srt_kind == "translated" else True
    return BatchReplayOptions(
        target_lang=str(raw.get("target_lang") or ""),
        pipeline_version=pipeline_version,
        rewrite_translation=_coerce_bool(raw.get("rewrite_translation"), default=True),
        timing_mode=str(raw.get("timing_mode") or "strict"),
        grouping_strategy=str(raw.get("grouping_strategy") or "sentence"),
        input_srt_kind=input_srt_kind,
        index_tts_api_url=str(raw.get("index_tts_api_url") or DEFAULT_INDEX_TTS_API_URL),
        auto_pick_ranges=_coerce_bool(raw.get("auto_pick_ranges"), default=False),
        time_ranges=_normalize_time_ranges(raw.get("requested_time_ranges") or raw.get("requested_ranges") or []),
        source_short_merge_enabled=_coerce_bool(raw.get("source_short_merge_enabled"), default=False),
        source_short_merge_threshold=_normalize_short_merge_target_seconds(
            raw.get("source_short_merge_threshold"),
            mode=str(raw.get("source_short_merge_threshold_mode") or ""),
        ),
        source_short_merge_threshold_mode="seconds",
        translated_short_merge_enabled=_coerce_bool(raw.get("translated_short_merge_enabled"), default=False),
        translated_short_merge_threshold=_normalize_short_merge_target_seconds(
            raw.get("translated_short_merge_threshold"),
            mode=str(raw.get("translated_short_merge_threshold_mode") or ""),
        ),
        translated_short_merge_threshold_mode="seconds",
        dub_audio_leveling_enabled=_coerce_bool(raw.get("dub_audio_leveling_enabled"), default=True),
        dub_audio_leveling_target_rms=float(raw.get("dub_audio_leveling_target_rms") or 0.12),
        dub_audio_leveling_activity_threshold_db=float(raw.get("dub_audio_leveling_activity_threshold_db") or -35.0),
        dub_audio_leveling_max_gain_db=float(raw.get("dub_audio_leveling_max_gain_db") or 8.0),
        dub_audio_leveling_peak_ceiling=float(raw.get("dub_audio_leveling_peak_ceiling") or 0.95),
        grouped_synthesis=_coerce_bool(raw.get("grouped_synthesis"), default=inferred_grouped_synthesis),
        force_fit_timing=force_fit_timing,
        tts_backend=str(raw.get("tts_backend") or "index-tts"),
        fallback_tts_backend=str(raw.get("fallback_tts_backend") or "none"),
        omnivoice_root=str(raw.get("omnivoice_root") or ""),
        omnivoice_python_bin=str(raw.get("omnivoice_python_bin") or ""),
        omnivoice_model=str(raw.get("omnivoice_model") or ""),
        omnivoice_device=str(raw.get("omnivoice_device") or "auto"),
        omnivoice_via_api=_coerce_bool(raw.get("omnivoice_via_api"), default=True),
        omnivoice_api_url=str(raw.get("omnivoice_api_url") or "http://127.0.0.1:8020"),
        legacy_inferred={},
    )


def load_batch_manifest(manifest_path: Path) -> BatchManifestView:
    """读取 batch manifest，并返回统一视图。"""

    resolved = manifest_path.expanduser().resolve()
    raw = _read_json(resolved)
    return BatchManifestView(
        manifest_path=resolved,
        raw=raw,
        paths=dict(raw.get("paths") or {}),
        options=_build_batch_options(raw),
    )


def load_segment_manifest(manifest_path: Path) -> SegmentManifestView:
    """读取 segment manifest，并返回统一视图。"""

    resolved = manifest_path.expanduser().resolve()
    raw = _read_json(resolved)
    return SegmentManifestView(
        manifest_path=resolved,
        raw=raw,
        paths=dict(raw.get("paths") or {}),
        options=_build_segment_options(raw),
    )


def write_manifest_json(manifest_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """统一落盘 manifest 文件。"""

    resolved = manifest_path.expanduser().resolve()
    return _write_json(resolved, payload)


def build_skipped_segment_manifest(
    *,
    segment_index: int,
    segment_audio: Path,
    target_lang: str,
    reason: str,
    created_at: str,
) -> Dict[str, Any]:
    """构建“空字幕分段跳过”的最小 segment manifest。"""

    return {
        "manifest_version": "v1",
        "job_id": f"segment_{segment_index:04d}",
        "created_at": created_at,
        "updated_at": created_at,
        "input_media_path": str(segment_audio),
        "target_lang": target_lang,
        "status": "skipped",
        "skip_reason": reason,
        "paths": {
            "source_audio": None,
            "source_vocals": None,
            "source_bgm": None,
            "source_srt": None,
            "translated_srt": None,
            "bilingual_srt": None,
            "dubbed_final_srt": None,
            "dubbed_vocals": None,
            "dubbed_mix": None,
            "separation_report": None,
            "log_jsonl": None,
        },
        "stats": {
            "total": 0,
            "done": 0,
            "failed": 0,
            "manual_review": 0,
        },
        "segments": [],
        "manual_review": [],
    }


def build_batch_manifest(
    *,
    batch_id: str,
    created_at: str,
    input_media_path: Path,
    options: BatchReplayOptions,
    input_srt_path: Optional[Path],
    segment_minutes: float,
    range_strategy: str,
    requested_ranges: Sequence[Tuple[float, float]],
    effective_ranges: Sequence[Tuple[float, float]],
    batch_dir: Path,
    preferred_audio: Optional[Path],
    merged_vocals: Optional[Path],
    merged_mix: Optional[Path],
    merged_bgm: Optional[Path],
    final_dir: Path,
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """构建长视频批处理 manifest。"""

    requested_range_dicts = _normalize_range_pairs(requested_ranges)
    effective_range_dicts = _normalize_range_pairs(effective_ranges)
    return {
        "batch_id": batch_id,
        "created_at": created_at,
        "input_media_path": str(input_media_path),
        "target_lang": options.target_lang,
        "pipeline_version": options.pipeline_version,
        "rewrite_translation": bool(options.rewrite_translation),
        "timing_mode": options.timing_mode,
        "grouping_strategy": options.grouping_strategy,
        "source_short_merge_enabled": bool(options.source_short_merge_enabled),
        "source_short_merge_threshold": int(options.source_short_merge_threshold),
        "source_short_merge_threshold_mode": options.source_short_merge_threshold_mode or "seconds",
        "translated_short_merge_enabled": bool(options.translated_short_merge_enabled),
        "translated_short_merge_threshold": int(options.translated_short_merge_threshold),
        "translated_short_merge_threshold_mode": options.translated_short_merge_threshold_mode or "seconds",
        "dub_audio_leveling_enabled": bool(options.dub_audio_leveling_enabled),
        "dub_audio_leveling_target_rms": float(options.dub_audio_leveling_target_rms),
        "dub_audio_leveling_activity_threshold_db": float(options.dub_audio_leveling_activity_threshold_db),
        "dub_audio_leveling_max_gain_db": float(options.dub_audio_leveling_max_gain_db),
        "dub_audio_leveling_peak_ceiling": float(options.dub_audio_leveling_peak_ceiling),
        "grouped_synthesis": bool(options.grouped_synthesis),
        "force_fit_timing": bool(options.force_fit_timing),
        "input_srt_kind": options.input_srt_kind,
        "index_tts_api_url": options.index_tts_api_url,
        "tts_backend": options.tts_backend,
        "fallback_tts_backend": options.fallback_tts_backend,
        "omnivoice_root": options.omnivoice_root,
        "omnivoice_python_bin": options.omnivoice_python_bin,
        "omnivoice_model": options.omnivoice_model,
        "omnivoice_device": options.omnivoice_device,
        "omnivoice_via_api": bool(options.omnivoice_via_api),
        "omnivoice_api_url": options.omnivoice_api_url,
        "auto_pick_ranges": bool(options.auto_pick_ranges),
        "input_srt": str(input_srt_path) if input_srt_path else None,
        "segment_minutes": segment_minutes,
        "range_strategy": range_strategy,
        # 新旧字段同时保留，避免历史调用方和新 reader 之间脱节。
        "requested_ranges": requested_range_dicts,
        "requested_time_ranges": requested_range_dicts,
        "effective_ranges": effective_range_dicts,
        "effective_time_ranges": effective_range_dicts,
        "segments_total": len(segments),
        "paths": {
            "batch_dir": str(batch_dir),
            "preferred_audio": str(preferred_audio) if preferred_audio else None,
            "dubbed_vocals_full": str(merged_vocals) if merged_vocals else None,
            "dubbed_mix_full": str(merged_mix) if merged_mix else None,
            "source_bgm_full": str(merged_bgm) if merged_bgm else None,
            "source_full_srt": str(final_dir / "source_full.srt") if (final_dir / "source_full.srt").exists() else None,
            "dubbed_final_full_srt": (
                str(final_dir / "dubbed_final_full.srt") if (final_dir / "dubbed_final_full.srt").exists() else None
            ),
            "translated_full_srt": (
                str(final_dir / "translated_full.srt") if (final_dir / "translated_full.srt").exists() else None
            ),
        },
        "segments": list(segments),
    }


def build_segment_manifest(
    *,
    job_id: str,
    created_at: str,
    updated_at: str,
    input_media_path: Path,
    target_lang: str,
    options: BatchReplayOptions,
    separation_status: str,
    paths: Dict[str, Optional[Path]],
    segment_records: List[Dict[str, Any]],
    manual_review: List[Dict[str, Any]],
    requested_time_ranges: Optional[List[Dict[str, float]]] = None,
    effective_time_ranges: Optional[List[Dict[str, float]]] = None,
    range_strategy: str = "all",
) -> Dict[str, Any]:
    """构建单段成功 manifest。"""

    done_count = sum(1 for item in segment_records if item.get("status") == "done")
    failed_count = sum(1 for item in segment_records if item.get("status") == "failed")
    return {
        "manifest_version": "v1",
        "job_id": job_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "input_media_path": str(input_media_path),
        "target_lang": target_lang,
        "pipeline_version": options.pipeline_version,
        "rewrite_translation": bool(options.rewrite_translation),
        "input_srt_kind": options.input_srt_kind,
        "tts_backend": options.tts_backend,
        "fallback_tts_backend": options.fallback_tts_backend,
        "index_tts_api_url": options.index_tts_api_url,
        "omnivoice_root": options.omnivoice_root,
        "omnivoice_python_bin": options.omnivoice_python_bin,
        "omnivoice_model": options.omnivoice_model,
        "omnivoice_device": options.omnivoice_device,
        "omnivoice_via_api": bool(options.omnivoice_via_api),
        "omnivoice_api_url": options.omnivoice_api_url,
        "timing_mode": options.timing_mode,
        "grouping_strategy": options.grouping_strategy,
        "source_short_merge_enabled": bool(options.source_short_merge_enabled),
        "source_short_merge_threshold": int(options.source_short_merge_threshold),
        "source_short_merge_threshold_mode": options.source_short_merge_threshold_mode or "seconds",
        "translated_short_merge_enabled": bool(options.translated_short_merge_enabled),
        "translated_short_merge_threshold": int(options.translated_short_merge_threshold),
        "translated_short_merge_threshold_mode": options.translated_short_merge_threshold_mode or "seconds",
        "dub_audio_leveling_enabled": bool(options.dub_audio_leveling_enabled),
        "dub_audio_leveling_target_rms": float(options.dub_audio_leveling_target_rms),
        "dub_audio_leveling_activity_threshold_db": float(options.dub_audio_leveling_activity_threshold_db),
        "dub_audio_leveling_max_gain_db": float(options.dub_audio_leveling_max_gain_db),
        "dub_audio_leveling_peak_ceiling": float(options.dub_audio_leveling_peak_ceiling),
        "grouped_synthesis": bool(options.grouped_synthesis),
        "force_fit_timing": bool(options.force_fit_timing),
        "auto_pick_ranges": bool(options.auto_pick_ranges),
        "range_strategy": range_strategy,
        "requested_time_ranges": list(requested_time_ranges or options.time_ranges),
        "effective_time_ranges": list(effective_time_ranges or []),
        "separation_status": separation_status,
        "paths": _serialize_optional_paths(paths),
        "stats": {
            "total": len(segment_records),
            "done": done_count,
            "failed": failed_count,
            "manual_review": len(manual_review),
        },
        "segments": segment_records,
        "manual_review": manual_review,
    }


def build_failed_segment_manifest(
    *,
    job_id: str,
    created_at: str,
    updated_at: str,
    input_media_path: Path,
    target_lang: str,
    options: BatchReplayOptions,
    separation_status: str,
    paths: Dict[str, Optional[Path]],
    segment_records: List[Dict[str, Any]],
    manual_review: List[Dict[str, Any]],
    error_text: str,
    requested_time_ranges: Optional[List[Dict[str, float]]] = None,
    effective_time_ranges: Optional[List[Dict[str, float]]] = None,
    range_strategy: str = "all",
) -> Dict[str, Any]:
    """构建单段失败 manifest。"""

    done_count = sum(1 for item in segment_records if item.get("status") == "done")
    failed_count = max(1, sum(1 for item in segment_records if item.get("status") == "failed"))
    return {
        "manifest_version": "v1",
        "job_id": job_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "input_media_path": str(input_media_path),
        "target_lang": target_lang,
        "pipeline_version": options.pipeline_version,
        "rewrite_translation": bool(options.rewrite_translation),
        "input_srt_kind": options.input_srt_kind,
        "tts_backend": options.tts_backend,
        "fallback_tts_backend": options.fallback_tts_backend,
        "index_tts_api_url": options.index_tts_api_url,
        "omnivoice_root": options.omnivoice_root,
        "omnivoice_python_bin": options.omnivoice_python_bin,
        "omnivoice_model": options.omnivoice_model,
        "omnivoice_device": options.omnivoice_device,
        "omnivoice_via_api": bool(options.omnivoice_via_api),
        "omnivoice_api_url": options.omnivoice_api_url,
        "timing_mode": options.timing_mode,
        "grouping_strategy": options.grouping_strategy,
        "source_short_merge_enabled": bool(options.source_short_merge_enabled),
        "source_short_merge_threshold": int(options.source_short_merge_threshold),
        "source_short_merge_threshold_mode": options.source_short_merge_threshold_mode or "seconds",
        "translated_short_merge_enabled": bool(options.translated_short_merge_enabled),
        "translated_short_merge_threshold": int(options.translated_short_merge_threshold),
        "translated_short_merge_threshold_mode": options.translated_short_merge_threshold_mode or "seconds",
        "dub_audio_leveling_enabled": bool(options.dub_audio_leveling_enabled),
        "dub_audio_leveling_target_rms": float(options.dub_audio_leveling_target_rms),
        "dub_audio_leveling_activity_threshold_db": float(options.dub_audio_leveling_activity_threshold_db),
        "dub_audio_leveling_max_gain_db": float(options.dub_audio_leveling_max_gain_db),
        "dub_audio_leveling_peak_ceiling": float(options.dub_audio_leveling_peak_ceiling),
        "grouped_synthesis": bool(options.grouped_synthesis),
        "force_fit_timing": bool(options.force_fit_timing),
        "auto_pick_ranges": bool(options.auto_pick_ranges),
        "range_strategy": range_strategy,
        "requested_time_ranges": list(requested_time_ranges or options.time_ranges),
        "effective_time_ranges": list(effective_time_ranges or []),
        "separation_status": separation_status,
        "status": "failed",
        "error": error_text,
        "paths": _serialize_optional_paths(paths),
        "stats": {
            "total": len(segment_records),
            "done": done_count,
            "failed": failed_count,
            "manual_review": len(manual_review),
        },
        "segments": segment_records,
        "manual_review": manual_review,
    }
