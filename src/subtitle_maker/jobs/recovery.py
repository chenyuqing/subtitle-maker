from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from subtitle_maker.manifests import load_batch_manifest
from subtitle_maker.manifests.readwrite import load_segment_manifest

from .models import JobArtifact, TaskPayload


def _normalize_batch_id(batch_id: str) -> str:
    """统一 longdub 批次目录名。"""

    raw = (batch_id or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("longdub_") else f"longdub_{raw}"


def find_batch_manifest_by_name(*, output_root: Path, batch_id: str) -> Optional[Path]:
    """根据 longdub 批次目录名回查 batch manifest。"""

    normalized = _normalize_batch_id(batch_id)
    if not normalized:
        return None
    candidates = sorted(
        output_root.glob(f"web_*/{normalized}/batch_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def find_batch_dir_by_name(*, output_root: Path, batch_id: str) -> Optional[Path]:
    """根据批次目录名回查 longdub 目录（允许无 batch manifest）。"""

    normalized = _normalize_batch_id(batch_id)
    if not normalized:
        return None
    candidates = sorted(
        (item for item in output_root.glob(f"web_*/{normalized}") if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def list_available_batches(*, output_root: Path, limit: int = 200) -> List[Dict[str, Any]]:
    """列出当前可加载的 longdub 批次目录（含中断批次）。"""

    batch_dirs = [item for item in output_root.glob("web_*/longdub_*") if item.is_dir()]
    batch_dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    results: List[Dict[str, Any]] = []
    for batch_dir in batch_dirs[: max(1, int(limit))]:
        manifest_path = batch_dir / "batch_manifest.json"
        has_manifest = manifest_path.exists()
        updated_at = int(manifest_path.stat().st_mtime if has_manifest else batch_dir.stat().st_mtime)
        results.append(
            {
                "batch_id": batch_dir.name,
                "web_dir": batch_dir.parent.name,
                "updated_at": updated_at,
                "manifest_path": str(manifest_path) if has_manifest else None,
                "has_manifest": has_manifest,
                "status": "completed" if has_manifest else "incomplete",
            }
        )
    return results


def build_batch_artifacts(
    *,
    task_id: str,
    manifest_path: Path,
    artifact_url_builder: Callable[[str, str], str],
) -> List[JobArtifact]:
    """根据 batch manifest 生成可公开下载的产物列表。"""

    batch_manifest = load_batch_manifest(manifest_path)
    paths = batch_manifest.paths
    input_media_path = batch_manifest.input_media_path
    candidates = [
        ("input_media", "Source Media", input_media_path),
        ("preferred_audio", "Preferred Audio", paths.get("preferred_audio")),
        ("video", "Dubbed Video MP4", paths.get("dubbed_video_full")),
        ("mix", "Mixed Audio WAV", paths.get("dubbed_mix_full")),
        ("vocals", "Vocals WAV", paths.get("dubbed_vocals_full")),
        ("bilingual_srt", "Bilingual SRT", paths.get("dubbed_final_full_srt")),
        ("translated_srt", "Translated SRT", paths.get("translated_full_srt")),
        ("source_srt", "Source SRT", paths.get("source_full_srt")),
        ("manifest", "Batch Manifest", str(manifest_path)),
    ]
    artifacts: List[JobArtifact] = []
    seen_paths = set()
    for key, label, path_text in candidates:
        if not path_text:
            continue
        path = Path(path_text).expanduser()
        if not path.exists():
            continue
        resolved = str(path.resolve())
        if key != "manifest" and resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        artifacts.append({"key": key, "label": label, "url": artifact_url_builder(task_id, key)})
    return artifacts


def build_batch_task_updates(
    *,
    task_id: str,
    manifest_path: Path,
    artifact_url_builder: Callable[[str, str], str],
) -> TaskPayload:
    """从 batch manifest 生成可回填到 Job Store 的字段集合。"""

    manifest = load_batch_manifest(manifest_path)
    artifacts = build_batch_artifacts(
        task_id=task_id,
        manifest_path=manifest_path,
        artifact_url_builder=artifact_url_builder,
    )
    paths = manifest.paths
    options = manifest.options
    input_media_path = manifest.input_media_path
    input_media_exists = False
    if input_media_path:
        try:
            input_media_exists = Path(str(input_media_path)).expanduser().exists()
        except Exception:
            input_media_exists = False

    # 统计 batch 级成功/人工复核数量，并探测是否存在真实可用音频（非 missing 占位）。
    total_done = 0
    total_segments = 0
    total_manual_review = 0
    has_non_missing_segment_audio = False
    for segment in manifest.segments:
        summary = segment.get("summary") or {}
        total_done += int(summary.get("done", 0) or 0)
        total_segments += int(summary.get("total", 0) or 0)
        total_manual_review += int(summary.get("manual_review", 0) or 0)
        if has_non_missing_segment_audio:
            continue
        job_dir = str(segment.get("job_dir") or "").strip()
        if not job_dir:
            continue
        segment_manifest_path = Path(job_dir).expanduser() / "manifest.json"
        if not segment_manifest_path.exists():
            continue
        try:
            segment_manifest = load_segment_manifest(segment_manifest_path)
        except Exception:
            continue
        for row in segment_manifest.segment_rows:
            audio_path_text = str(row.get("tts_audio_path") or "").strip()
            if not audio_path_text:
                continue
            audio_path = Path(audio_path_text).expanduser()
            if not audio_path.exists():
                continue
            if audio_path.name.endswith("_missing.wav"):
                continue
            has_non_missing_segment_audio = True
            break

    updates: TaskPayload = {
        "batch_id": manifest.batch_id,
        "batch_manifest_path": str(manifest_path),
        "processed_segments": manifest.segments_total,
        "total_segments": manifest.segments_total,
        "manual_review_segments": total_manual_review,
        "artifacts": artifacts,
        "input_path": str(input_media_path) if input_media_path else "",
        "input_media_url": artifact_url_builder(task_id, "input_media") if input_media_exists else None,
        "target_lang": options.target_lang,
        "dubbing_mode": options.dubbing_mode,
        "rewrite_translation": options.rewrite_translation,
        "timing_mode": options.timing_mode,
        "grouping_strategy": options.grouping_strategy,
        "source_short_merge_enabled": options.source_short_merge_enabled,
        "source_short_merge_threshold": options.source_short_merge_threshold,
        "translated_short_merge_enabled": options.translated_short_merge_enabled,
        "translated_short_merge_threshold": options.translated_short_merge_threshold,
        "dub_audio_leveling_enabled": options.dub_audio_leveling_enabled,
        "dub_audio_leveling_target_rms": options.dub_audio_leveling_target_rms,
        "dub_audio_leveling_activity_threshold_db": options.dub_audio_leveling_activity_threshold_db,
        "dub_audio_leveling_max_gain_db": options.dub_audio_leveling_max_gain_db,
        "dub_audio_leveling_peak_ceiling": options.dub_audio_leveling_peak_ceiling,
        "segment_minutes": float(manifest.raw.get("segment_minutes", 8.0) or 8.0),
        "min_segment_minutes": float(manifest.raw.get("min_segment_minutes", 4.0) or 4.0),
        "subtitle_mode": options.input_srt_kind,
        "index_tts_api_url": options.index_tts_api_url,
        "time_ranges": options.time_ranges,
        "grouped_synthesis": options.grouped_synthesis,
        "force_fit_timing": options.force_fit_timing,
        "tts_backend": options.tts_backend,
        "single_ref_audio": options.single_ref_audio,
        "single_ref_text": options.single_ref_text,
        "speaker_ref_map": options.speaker_ref_map,
        "translate_system_prompt": options.translate_system_prompt,
        "tts_model_path": options.tts_model_path,
    }

    # 只有“全量 manual_review 且没有任何真实音频产物”时，才判定为失败。
    if (
        total_done <= 0
        and total_segments > 0
        and total_manual_review >= total_segments
        and not has_non_missing_segment_audio
    ):
        updates.update(
            status="failed",
            stage="failed",
            progress=100.0,
            error=(
                "TTS synthesis failed for all subtitle segments "
                "(all segments fell back to manual_review/silent placeholders)."
            ),
        )
        return updates

    result_audio = None
    if paths.get("preferred_audio") and Path(paths["preferred_audio"]).exists():
        result_audio = artifact_url_builder(task_id, "preferred_audio")
    elif paths.get("dubbed_mix_full") and Path(paths["dubbed_mix_full"]).exists():
        result_audio = artifact_url_builder(task_id, "mix")
    elif paths.get("dubbed_vocals_full") and Path(paths["dubbed_vocals_full"]).exists():
        result_audio = artifact_url_builder(task_id, "vocals")

    updates.update(
        status="completed",
        stage="finished",
        progress=100.0,
        result_audio=result_audio,
        result_srt=artifact_url_builder(task_id, "bilingual_srt") if paths.get("dubbed_final_full_srt") else None,
    )
    return updates


def build_loaded_batch_task(
    *,
    task_id: str,
    manifest_path: Path,
    created_at: str,
    default_short_merge_threshold: int,
    default_index_tts_api_url: str,
    artifact_url_builder: Callable[[str, str], str],
) -> TaskPayload:
    """构造 `load-batch` 场景的完整内存任务记录。"""

    out_root = manifest_path.parents[1]
    task: TaskPayload = {
        "id": task_id,
        "short_id": task_id.split("-")[0],
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": created_at,
        "updated_at": created_at,
        "source_lang": "auto",
        "target_lang": "",
        "time_ranges": [],
        "timing_mode": "strict",
        "grouping_strategy": "sentence",
        "source_short_merge_enabled": False,
        "source_short_merge_threshold": default_short_merge_threshold,
        "translated_short_merge_enabled": False,
        "translated_short_merge_threshold": default_short_merge_threshold,
        "dub_audio_leveling_enabled": True,
        "dub_audio_leveling_target_rms": 0.12,
        "dub_audio_leveling_activity_threshold_db": -35.0,
        "dub_audio_leveling_max_gain_db": 8.0,
        "dub_audio_leveling_peak_ceiling": 0.95,
        "subtitle_mode": "source",
        "dubbing_mode": "single",
        "rewrite_translation": True,
        "index_tts_api_url": default_index_tts_api_url,
        "tts_backend": "index-tts",
        "single_ref_audio": "",
        "single_ref_text": "",
        "speaker_ref_map": [],
        "translate_system_prompt": "",
        "tts_model_path": "",
        "processed_segments": 0,
        "total_segments": None,
        "manual_review_segments": 0,
        "artifacts": [],
        "stdout_tail": [],
        "input_path": "",
        "input_srt": None,
        "upload_dir": "",
        "out_root": str(out_root),
        "command": [],
        "process": None,
    }
    task.update(
        build_batch_task_updates(
            task_id=task_id,
            manifest_path=manifest_path,
            artifact_url_builder=artifact_url_builder,
        )
    )
    return task
