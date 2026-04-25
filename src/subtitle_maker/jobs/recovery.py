from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from subtitle_maker.manifests import load_batch_manifest

from .models import JobArtifact, TaskPayload


def find_batch_manifest_by_name(*, output_root: Path, batch_id: str) -> Optional[Path]:
    """根据 longdub 批次目录名回查 batch manifest。"""

    raw = (batch_id or "").strip()
    if not raw:
        return None
    normalized = raw if raw.startswith("longdub_") else f"longdub_{raw}"
    candidates = sorted(
        output_root.glob(f"web_*/{normalized}/batch_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def list_available_batches(*, output_root: Path, limit: int = 200) -> List[Dict[str, Any]]:
    """列出当前可加载的 longdub 批次目录。"""

    manifests = sorted(
        output_root.glob("web_*/longdub_*/batch_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    results: List[Dict[str, Any]] = []
    for manifest_path in manifests[: max(1, int(limit))]:
        batch_dir = manifest_path.parent
        results.append(
            {
                "batch_id": batch_dir.name,
                "web_dir": batch_dir.parent.name,
                "updated_at": int(manifest_path.stat().st_mtime),
                "manifest_path": str(manifest_path),
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

    # 统计 batch 级成功/人工复核数量，用于区分“真完成”和“全量静音兜底失败”。
    total_done = 0
    total_segments = 0
    total_manual_review = 0
    for segment in manifest.segments:
        summary = segment.get("summary") or {}
        total_done += int(summary.get("done", 0) or 0)
        total_segments += int(summary.get("total", 0) or 0)
        total_manual_review += int(summary.get("manual_review", 0) or 0)

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
        "pipeline_version": options.pipeline_version,
        "rewrite_translation": options.rewrite_translation,
        "timing_mode": options.timing_mode,
        "grouping_strategy": options.grouping_strategy,
        "source_short_merge_enabled": options.source_short_merge_enabled,
        "source_short_merge_threshold": options.source_short_merge_threshold,
        "subtitle_mode": options.input_srt_kind,
        "index_tts_api_url": options.index_tts_api_url,
        "auto_pick_ranges": options.auto_pick_ranges,
        "time_ranges": options.time_ranges,
        "grouped_synthesis": options.grouped_synthesis,
        "force_fit_timing": options.force_fit_timing,
        "tts_backend": options.tts_backend,
    }

    # 当所有片段都掉进 manual_review 且没有任何成功 TTS 时，应标记为失败而不是完成。
    if total_done <= 0 and total_segments > 0 and total_manual_review >= total_segments:
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
        "subtitle_mode": "source",
        "pipeline_version": "v1",
        "rewrite_translation": True,
        "index_tts_api_url": default_index_tts_api_url,
        "auto_pick_ranges": False,
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
