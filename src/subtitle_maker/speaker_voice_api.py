from __future__ import annotations

import json
import shutil
import threading
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from subtitle_maker.app import legacy_runtime
from subtitle_maker.core.ffmpeg import run_cmd
from subtitle_maker.domains.media import cut_audio_segment
from subtitle_maker.jobs import TaskStore
from subtitle_maker.transcriber import format_srt

from subtitle_maker.dubbing_cli_api import (
    _build_readable_task_id,
    _parse_time_ranges_form,
    _resolve_project_media_path,
    _sanitize_filename,
)

router = APIRouter(prefix="/speaker-voice", tags=["speaker-voice"])

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = REPO_ROOT / "uploads" / "speaker_voice"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "speaker_voice"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

_task_store = TaskStore()


def _iso_now() -> str:
    """统一返回 UTC 时间戳，保持和其他任务接口一致。"""

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _set_task(task_id: str, **updates: Any) -> None:
    """更新 speaker voice 任务状态。"""

    payload = dict(updates)
    payload.setdefault("updated_at", _iso_now())
    _task_store.update(task_id, **payload)


def _build_artifact_url(task_id: str, artifact: str) -> str:
    """统一生成 speaker voice 下载链接。"""

    return f"/speaker-voice/artifact/{task_id}/{artifact}"


def _store_uploaded_media(*, upload_dir: Path, file: UploadFile) -> Path:
    """将上传媒体落盘到独立目录，只允许使用上传文件名的安全版本。"""

    if not file.filename:
        raise HTTPException(status_code=400, detail="media file is required")
    safe_name = _sanitize_filename(file.filename)
    target_path = upload_dir / safe_name
    with target_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return target_path.resolve()


def _resolve_result_dir(task_id: str) -> Path:
    """按任务 ID 解析输出目录。"""

    return (OUTPUT_ROOT / f"web_{task_id}").resolve()


def _format_range_token(seconds_value: float) -> str:
    """将秒数格式化为 MM-SS，用于输出文件名。"""

    total_seconds = max(0, int(seconds_value))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}-{seconds:02d}"


def _extract_audio_segment(*, input_media: Path, output_wav: Path, start_sec: float, end_sec: float) -> None:
    """只抽取指定区间的音频片段，避免整视频先抽音再裁切。"""

    duration_sec = max(0.05, float(end_sec) - float(start_sec))
    code, _, err = run_cmd(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{float(start_sec):.3f}",
            "-i",
            str(input_media),
            "-t",
            f"{duration_sec:.3f}",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(output_wav),
        ],
        cwd=REPO_ROOT,
    )
    if code != 0:
        raise RuntimeError(f"extract range audio failed: {err.strip()}")


def _separate_range_vocals_or_fail(
    *,
    input_media: Path,
    out_root: Path,
    start_sec: float,
    end_sec: float,
    range_index: int,
) -> Dict[str, Path]:
    """只对单个 range 做抽音 + 人声分离；失败时直接抛错。"""

    stems_dir = out_root / "stems" / f"range_{range_index:04d}"
    stems_dir.mkdir(parents=True, exist_ok=True)
    range_audio = stems_dir / "range_audio.wav"
    range_vocals = stems_dir / "range_vocals.wav"
    demucs_out = out_root / "demucs_tmp" / f"range_{range_index:04d}"
    demucs_out.mkdir(parents=True, exist_ok=True)
    separation_report = out_root / "separation_report.json"

    _extract_audio_segment(
        input_media=input_media,
        output_wav=range_audio,
        start_sec=start_sec,
        end_sec=end_sec,
    )

    attempts: List[Dict[str, Any]] = []
    for model_name in ("htdemucs", "mdx_extra_q"):
        code, _, err = run_cmd(
            [
                sys.executable,
                "-m",
                "demucs.separate",
                "-n",
                model_name,
                "-o",
                str(demucs_out),
                str(range_audio),
            ],
            cwd=REPO_ROOT,
        )
        if code != 0:
            attempts.append({"model": model_name, "ok": False, "error": err.strip() or "demucs failed"})
            continue
        candidates = list((demucs_out / model_name).glob("**/vocals.wav"))
        if not candidates:
            attempts.append({"model": model_name, "ok": False, "error": "vocals.wav not found"})
            continue
        shutil.copy2(candidates[0], range_vocals)
        existing_report = {}
        if separation_report.exists():
            try:
                existing_report = json.loads(separation_report.read_text(encoding="utf-8"))
            except Exception:
                existing_report = {}
        history = list(existing_report.get("ranges") or [])
        history.append(
            {
                "range_index": range_index,
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "status": "ok",
                "attempts": attempts + [{"model": model_name, "ok": True, "error": ""}],
            }
        )
        separation_report.write_text(
            json.dumps({"status": "ok", "ranges": history}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "range_audio": range_audio,
            "range_vocals": range_vocals,
            "separation_report": separation_report,
        }

    existing_report = {}
    if separation_report.exists():
        try:
            existing_report = json.loads(separation_report.read_text(encoding="utf-8"))
        except Exception:
            existing_report = {}
    history = list(existing_report.get("ranges") or [])
    history.append(
        {
            "range_index": range_index,
            "start_sec": float(start_sec),
            "end_sec": float(end_sec),
            "status": "failed",
            "attempts": attempts,
        }
    )
    separation_report.write_text(
        json.dumps({"status": "failed", "ranges": history}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raise RuntimeError("人声分离失败")


def _build_task_payload(*, task_id: str, input_path: Path, out_root: Path, start_mode: str) -> Dict[str, Any]:
    """创建 speaker voice 初始任务。"""

    return {
        "id": task_id,
        "short_id": task_id.split("_")[0],
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "stdout_tail": [],
        "artifacts": [],
        "error": "",
        "input_path": str(input_path),
        "out_root": str(out_root),
        "upload_dir": str(input_path.parent),
        "start_mode": start_mode,
        "result_audio": None,
    }


def _run_speaker_voice_task(task_id: str, *, input_path: Path, out_root: Path, time_ranges: List[Dict[str, float]]) -> None:
    """后台执行 speaker voice 提取任务。"""

    try:
        _set_task(task_id, status="running", stage="extract_ranges", progress=10.0)
        exports_dir = out_root / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        artifacts: List[Dict[str, str]] = []

        _set_task(task_id, stage="cut_ranges", progress=30.0)
        for index, item in enumerate(time_ranges, start=1):
            start_sec = float(item["start_sec"])
            end_sec = float(item["end_sec"])
            output_name = (
                f"speaker_voice_{index:04d}_{_format_range_token(start_sec)}_{_format_range_token(end_sec)}.wav"
            )
            output_path = exports_dir / output_name
            separated = _separate_range_vocals_or_fail(
                input_media=input_path,
                out_root=out_root,
                start_sec=start_sec,
                end_sec=end_sec,
                range_index=index,
            )
            shutil.copy2(
                separated["range_vocals"],
                output_path,
            )
            artifacts.append(
                {
                    "key": f"range_{index:04d}",
                    "label": f"Download Range {index:02d}",
                    "url": _build_artifact_url(task_id, f"range_{index:04d}"),
                }
            )
            _set_task(task_id, progress=min(92.0, 55.0 + (37.0 * index / max(1, len(time_ranges)))))

        manifest = {
            "task_id": task_id,
            "input_media_path": str(input_path),
            "created_at": _iso_now(),
            "time_ranges": list(time_ranges),
            "paths": {
                "exports_dir": str(exports_dir),
                "separation_report": str((out_root / "separation_report.json").resolve()) if (out_root / "separation_report.json").exists() else None,
            },
            "artifacts": artifacts,
        }
        (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _set_task(
            task_id,
            status="completed",
            stage="finished",
            progress=100.0,
            artifacts=artifacts,
            total_segments=len(time_ranges),
            processed_segments=len(time_ranges),
            result_audio=artifacts[0]["url"] if artifacts else None,
            batch_manifest_path=str((out_root / "manifest.json").resolve()),
        )
    except BaseException as exc:
        _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))


def _run_speaker_video_task(task_id: str, *, input_path: Path, out_root: Path, time_ranges: List[Dict[str, float]]) -> None:
    """后台执行视频片段提取任务。"""

    try:
        _set_task(task_id, status="running", stage="extract_video_ranges", progress=10.0)
        exports_dir = out_root / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        artifacts: List[Dict[str, str]] = []

        _set_task(task_id, stage="cut_video_ranges", progress=30.0)
        for index, item in enumerate(time_ranges, start=1):
            start_sec = float(item["start_sec"])
            end_sec = float(item["end_sec"])
            duration_sec = max(0.05, end_sec - start_sec)
            output_name = f"video_slice_{index:04d}_{_format_range_token(start_sec)}_{_format_range_token(end_sec)}.mp4"
            output_path = exports_dir / output_name

            # 先尝试无重编码快速切片，失败时回退重编码，保证产物可用。
            code, _, _ = run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start_sec:.3f}",
                    "-i",
                    str(input_path),
                    "-t",
                    f"{duration_sec:.3f}",
                    "-c",
                    "copy",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
            )
            if code != 0 or (not output_path.exists()) or output_path.stat().st_size <= 0:
                code2, _, err2 = run_cmd(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        f"{start_sec:.3f}",
                        "-i",
                        str(input_path),
                        "-t",
                        f"{duration_sec:.3f}",
                        "-c:v",
                        "libx264",
                        "-c:a",
                        "aac",
                        str(output_path),
                    ],
                    cwd=REPO_ROOT,
                )
                if code2 != 0 or (not output_path.exists()) or output_path.stat().st_size <= 0:
                    raise RuntimeError(f"extract video range failed: {err2.strip()}")

            artifacts.append(
                {
                    "key": f"video_range_{index:04d}",
                    "label": f"Download Video Slice {index:02d}",
                    "url": _build_artifact_url(task_id, f"video_range_{index:04d}"),
                }
            )
            _set_task(task_id, progress=min(92.0, 55.0 + (37.0 * index / max(1, len(time_ranges)))))

        manifest = {
            "task_id": task_id,
            "input_media_path": str(input_path),
            "created_at": _iso_now(),
            "time_ranges": list(time_ranges),
            "paths": {
                "exports_dir": str(exports_dir),
            },
            "artifacts": artifacts,
            "slice_mode": "video",
        }
        (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _set_task(
            task_id,
            status="completed",
            stage="finished",
            progress=100.0,
            artifacts=artifacts,
            total_segments=len(time_ranges),
            processed_segments=len(time_ranges),
            result_audio=artifacts[0]["url"] if artifacts else None,
            batch_manifest_path=str((out_root / "manifest.json").resolve()),
        )
    except BaseException as exc:
        _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))


def _queue_task(*, input_path: Path, time_ranges: List[Dict[str, float]], start_mode: str, task_id: Optional[str] = None) -> Dict[str, str]:
    """创建任务并启动后台线程。"""

    active = _task_store.list_active_ids()
    if active:
        raise HTTPException(status_code=409, detail="Another speaker voice job is already running")
    resolved_task_id = task_id or _build_readable_task_id()
    out_root = _resolve_result_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    payload = _build_task_payload(task_id=resolved_task_id, input_path=input_path, out_root=out_root, start_mode=start_mode)
    _task_store.create(resolved_task_id, payload)
    thread = threading.Thread(
        target=_run_speaker_voice_task,
        args=(resolved_task_id,),
        kwargs={"input_path": input_path, "out_root": out_root, "time_ranges": time_ranges},
        daemon=True,
    )
    thread.start()
    return {"task_id": resolved_task_id, "short_id": payload["short_id"], "status": "queued"}


def _queue_video_task(*, input_path: Path, time_ranges: List[Dict[str, float]], start_mode: str, task_id: Optional[str] = None) -> Dict[str, str]:
    """创建视频切片任务并启动后台线程。"""

    active = _task_store.list_active_ids()
    if active:
        raise HTTPException(status_code=409, detail="Another speaker voice job is already running")
    resolved_task_id = task_id or _build_readable_task_id()
    out_root = _resolve_result_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    payload = _build_task_payload(task_id=resolved_task_id, input_path=input_path, out_root=out_root, start_mode=start_mode)
    payload["slice_mode"] = "video"
    _task_store.create(resolved_task_id, payload)
    thread = threading.Thread(
        target=_run_speaker_video_task,
        args=(resolved_task_id,),
        kwargs={"input_path": input_path, "out_root": out_root, "time_ranges": time_ranges},
        daemon=True,
    )
    thread.start()
    return {"task_id": resolved_task_id, "short_id": payload["short_id"], "status": "queued"}


def _resolve_artifact(task: Dict[str, Any], artifact: str) -> Path:
    """按 artifact key 查找对应导出 wav。"""

    out_root = Path(str(task.get("out_root") or "")).expanduser().resolve()
    manifest_path = out_root / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Artifacts are not ready yet")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if artifact == "manifest":
        return manifest_path
    if artifact == "separation_report":
        path = Path(str(manifest.get("paths", {}).get("separation_report") or "")).expanduser().resolve()
        if path.exists():
            return path
    if artifact.startswith("range_"):
        for item in list(manifest.get("artifacts") or []):
            if str(item.get("key") or "") != artifact:
                continue
            index_text = artifact.split("_")[-1]
            matches = sorted((out_root / "exports").glob(f"speaker_voice_{index_text}_*.wav"))
            if matches:
                return matches[0].resolve()
    if artifact.startswith("video_range_"):
        for item in list(manifest.get("artifacts") or []):
            if str(item.get("key") or "") != artifact:
                continue
            index_text = artifact.split("_")[-1]
            matches = sorted((out_root / "exports").glob(f"video_slice_{index_text}_*.mp4"))
            if matches:
                return matches[0].resolve()
    raise HTTPException(status_code=404, detail="Artifact not found")


@router.post("/start")
async def start_speaker_voice(
    media: UploadFile = File(...),
    time_ranges: str = Form(""),
):
    """Standalone Upload 模式：上传媒体并按 ranges 导出人声 wav。"""

    ranges = _parse_time_ranges_form(time_ranges)
    if not ranges:
        raise HTTPException(status_code=400, detail="Get Speaker Voice requires at least one range")
    task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = _store_uploaded_media(upload_dir=upload_dir, file=media)
    return _queue_task(input_path=input_path, time_ranges=ranges, start_mode="standalone", task_id=task_id)


@router.post("/start-from-project")
async def start_speaker_voice_from_project(
    filename: str = Form(...),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    time_ranges: str = Form(""),
):
    """Current Project 模式：复用主 workflow 当前项目媒体。"""

    ranges = _parse_time_ranges_form(time_ranges)
    if not ranges:
        raise HTTPException(status_code=400, detail="Get Speaker Voice requires at least one range")
    readable_task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / readable_task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_media_path = _resolve_project_media_path(filename, task_id)
    display_name = _sanitize_filename(original_filename or source_media_path.name)
    input_path = upload_dir / display_name
    shutil.copy2(source_media_path, input_path)
    response = _queue_task(input_path=input_path.resolve(), time_ranges=ranges, start_mode="project", task_id=readable_task_id)
    response["project_filename"] = source_media_path.name
    return response


@router.post("/start-video-from-project")
async def start_speaker_video_from_project(
    filename: str = Form(...),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    time_ranges: str = Form(""),
):
    """Current Project 模式：复用主 workflow 当前项目媒体，按 ranges 提取视频片段。"""

    ranges = _parse_time_ranges_form(time_ranges)
    if not ranges:
        raise HTTPException(status_code=400, detail="Video slice requires at least one range")
    readable_task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / readable_task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    source_media_path = _resolve_project_media_path(filename, task_id)
    display_name = _sanitize_filename(original_filename or source_media_path.name)
    input_path = upload_dir / display_name
    shutil.copy2(source_media_path, input_path)
    response = _queue_video_task(
        input_path=input_path.resolve(),
        time_ranges=ranges,
        start_mode="project",
        task_id=readable_task_id,
    )
    response["project_filename"] = source_media_path.name
    return response


@router.get("/status/{task_id}")
async def get_speaker_voice_status(task_id: str):
    """轮询 speaker voice 任务状态。"""

    task = _task_store.get_public(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Speaker voice task not found")
    return task


@router.get("/artifact/{task_id}/{artifact}")
async def download_speaker_voice_artifact(task_id: str, artifact: str):
    """下载 speaker voice 导出结果。"""

    task = _task_store.get_copy(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Speaker voice task not found")
    path = _resolve_artifact(task, artifact)
    media_type = None
    if path.suffix.lower() == ".wav":
        media_type = "audio/wav"
    elif path.suffix.lower() == ".mp4":
        media_type = "video/mp4"
    return FileResponse(path=path, filename=path.name, media_type=media_type)
