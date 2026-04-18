"""FastAPI bridge for the CLI dubbing pipeline.

This module intentionally keeps dubbing task state separate from the existing
transcription task store in web.py so the new UI path cannot affect subtitle
generation, translation, or export flows.
"""

from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse


router = APIRouter(prefix="/dubbing/auto", tags=["dubbing"])

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = REPO_ROOT / "uploads" / "dubbing"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "dub_jobs"
TOOL_PATH = REPO_ROOT / "tools" / "dub_long_video.py"
INDEX_TTS_START_SCRIPT = REPO_ROOT / "start_index_tts_api.sh"

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
DEFAULT_TRANSLATE_BASE_URL = "https://api.deepseek.com"
DEFAULT_TRANSLATE_MODEL = "deepseek-chat"
DEFAULT_INDEX_TTS_API_URL = "http://127.0.0.1:8010"


def _index_tts_target_lang_supported(target_lang: str) -> bool:
    """判断当前 index-tts 服务是否支持目标语种（本地部署版本仅稳定支持中/英）。"""
    lowered = (target_lang or "").strip().lower()
    if not lowered:
        return False
    # 兼容中英文常见写法；其余语种（如 Japanese）直接拦截，避免生成无效音。
    supported_markers = [
        "chinese",
        "中文",
        "mandarin",
        "cantonese",
        "english",
        "英文",
        "en",
        "zh",
    ]
    return any(marker in lowered for marker in supported_markers)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sanitize_filename(name: str) -> str:
    stem = Path(name or "media").stem
    suffix = Path(name or "").suffix
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-") or "media"
    safe_suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix or "") else ""
    return f"{safe_stem}{safe_suffix}"


def _read_bool_form(value: str, *, field_name: str) -> bool:
    # 解析表单布尔值，统一支持 true/false/1/0。
    lowered = (value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def _parse_time_ranges_form(raw: str) -> List[Dict[str, float]]:
    # 解析 time_ranges，支持 JSON 与简写文本（如 00:10-00:45, 01:20-02:00）。
    if not raw or not raw.strip():
        return []
    text = raw.strip()

    def parse_time_token(token: str) -> float:
        value = (token or "").strip()
        if not value:
            raise ValueError("empty time token")
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return float(value)
        parts = value.split(":")
        if len(parts) == 2:
            minutes = int(parts[0] or "0")
            seconds = float(parts[1] or "0")
            return minutes * 60.0 + seconds
        if len(parts) == 3:
            hours = int(parts[0] or "0")
            minutes = int(parts[1] or "0")
            seconds = float(parts[2] or "0")
            return hours * 3600.0 + minutes * 60.0 + seconds
        raise ValueError(f"invalid time token: {token}")

    parsed: List[Dict[str, float]] = []
    if text.startswith("["):
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid time_ranges JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise HTTPException(status_code=400, detail="Invalid time_ranges JSON: must be a list")
        for item in payload:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Invalid time_ranges JSON item")
            start_sec = float(item.get("start_sec", item.get("start", 0.0)) or 0.0)
            end_sec = float(item.get("end_sec", item.get("end", start_sec)) or start_sec)
            if end_sec <= start_sec:
                continue
            parsed.append({"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)})
    else:
        entries = [part.strip() for part in re.split(r"[,\n;，；]+", text) if part.strip()]
        for entry in entries:
            if "-" not in entry:
                raise HTTPException(status_code=400, detail=f"Invalid time_ranges entry: {entry}")
            start_text, end_text = entry.split("-", 1)
            try:
                start_sec = parse_time_token(start_text)
                end_sec = parse_time_token(end_text)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid time_ranges entry: {entry} ({exc})") from exc
            if end_sec <= start_sec:
                continue
            parsed.append({"start_sec": round(start_sec, 3), "end_sec": round(end_sec, 3)})

    parsed.sort(key=lambda item: item["start_sec"])
    return parsed


def _build_readable_task_id() -> str:
    # 生成可读任务 ID：UTC 时间戳 + 冲突递增序号，不使用随机串。
    base = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    with _lock:
        existing_ids = set(_tasks.keys())
    candidate = base
    index = 2
    while (
        candidate in existing_ids
        or (UPLOAD_ROOT / candidate).exists()
        or (OUTPUT_ROOT / f"web_{candidate}").exists()
    ):
        candidate = f"{base}_{index:02d}"
        index += 1
    return candidate


def _set_task(task_id: str, **updates: Any) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updated_at"] = _iso_now()


def _append_stdout(task_id: str, line: str) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        tail = task.setdefault("stdout_tail", [])
        tail.append(line)
        if len(tail) > 120:
            del tail[:-120]


def _public_task(task: Dict[str, Any]) -> Dict[str, Any]:
    public = {
        key: value
        for key, value in task.items()
        if key not in {"process", "input_path", "out_root", "upload_dir"}
    }
    public.setdefault("artifacts", [])
    return public


def _progress_for_segment(processed: int, total: Optional[int]) -> float:
    if not total or total <= 0:
        return 45.0
    return min(92.0, 25.0 + 67.0 * (processed / total))


def _bump_stage(task_id: str, stage: str, minimum_progress: float) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        task["stage"] = stage
        task["progress"] = max(float(task.get("progress", 0.0) or 0.0), minimum_progress)
        task["updated_at"] = _iso_now()


def _update_from_stdout(task_id: str, line: str) -> None:
    planned_match = re.search(r"Planned segments:\s*(\d+)", line)
    existing_match = re.search(r"Existing segments:\s*(\d+)", line)
    if planned_match or existing_match:
        total = int((planned_match or existing_match).group(1))
        _set_task(task_id, total_segments=total, line_progress_total=total)
        return

    if "Step 1/5" in line:
        _set_task(task_id, stage="dubbing:preparing", progress=8.0)
        return
    if "Step 2/5" in line:
        _set_task(task_id, stage="dubbing:planning", progress=16.0)
        return
    if "Step 3/5" in line:
        _set_task(task_id, stage="dubbing:segmenting", progress=23.0)
        return
    if "Step 4/5" in line:
        _set_task(task_id, stage="dubbing", progress=28.0)
        return
    if "Step 5/5" in line:
        _set_task(task_id, stage="dubbing:merging", progress=94.0)
        return

    if "[INFO] extract_audio:" in line or "[INFO] asr_align:" in line:
        _bump_stage(task_id, "transcribing", 34.0)
        return
    if "[INFO] translate:" in line:
        _bump_stage(task_id, "translating", 52.0)
        return
    if (
        "[INFO] separate_vocals:" in line
        or "[INFO] ref_extract:" in line
        or "[INFO] tts:" in line
        or "[INFO] mix:" in line
    ):
        _bump_stage(task_id, "dubbing", 68.0)
        return

    done_match = re.search(r"===== Segment\s+(\d+)\s+done", line)
    if done_match:
        with _lock:
            task = _tasks.get(task_id)
            if not task:
                return
            processed = max(int(task.get("processed_segments", 0)), int(done_match.group(1)))
            total = task.get("total_segments")
        _set_task(
            task_id,
            processed_segments=processed,
            line_progress_processed=processed,
            progress=_progress_for_segment(processed, total),
            stage="dubbing",
        )
        return

    if "Batch completed." in line:
        _set_task(task_id, stage="dubbing:completed", progress=98.0)


def _normalize_cli_failure_line(line: str, max_length: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", (line or "").strip())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _extract_cli_failure_detail(stdout_tail: List[str]) -> Optional[str]:
    for raw_line in reversed(stdout_tail):
        line = (raw_line or "").strip()
        if not line:
            continue
        if line.startswith("Pipeline failed:"):
            return _normalize_cli_failure_line(line)
        if line.startswith("[ERROR]"):
            parts = line.split(" - ", 1)
            if len(parts) == 2:
                message = parts[1].strip()
                if message and message.lower() not in {"pipeline failed", "job failed"}:
                    return _normalize_cli_failure_line(message)
            continue
        if line.startswith("[INFO]") or line.startswith("HTTP Request:"):
            continue
        if line.startswith("Traceback ") or line == "Traceback (most recent call last):":
            continue
        if line.startswith("During handling of the above exception"):
            continue
        if re.match(r'^File ".+", line \d+, in .+', line):
            continue
        if line.startswith("RuntimeError: command failed"):
            continue
        return _normalize_cli_failure_line(line)
    return None


def _build_cli_exit_error(code: int, stdout_tail: List[str]) -> str:
    message = f"dub_long_video.py exited with code {code}"
    detail = _extract_cli_failure_detail(stdout_tail)
    if not detail:
        return message
    return f"{message}: {detail}"


def _find_batch_manifest(out_root: Path) -> Optional[Path]:
    manifests = sorted(
        out_root.glob("longdub_*/batch_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return manifests[0] if manifests else None


def _artifact_url(task_id: str, key: str) -> str:
    return f"/dubbing/auto/artifact/{task_id}/{key}"


def _check_index_tts_service(api_url: str, timeout_sec: float = 2.0) -> None:
    url = api_url.rstrip("/") + "/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"index-tts service unavailable: {exc}. Run ./start_index_tts_api.sh first.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"index-tts health check failed: {exc}. Run ./start_index_tts_api.sh first.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise HTTPException(
            status_code=503,
            detail=f"index-tts service unhealthy: {payload}. Run ./start_index_tts_api.sh first.",
        )


def _auto_start_local_index_tts(api_url: str) -> None:
    normalized = api_url.rstrip("/")
    if normalized != DEFAULT_INDEX_TTS_API_URL:
        return
    if not INDEX_TTS_START_SCRIPT.exists():
        return

    proc = subprocess.run(
        [str(INDEX_TTS_START_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "unknown error"
        raise HTTPException(
            status_code=503,
            detail=f"index-tts auto-start failed: {details}. Run ./start_index_tts_api.sh manually.",
        )


def _ensure_index_tts_service(api_url: str) -> None:
    try:
        _check_index_tts_service(api_url)
    except HTTPException as exc:
        _auto_start_local_index_tts(api_url)
        try:
            _check_index_tts_service(api_url)
        except HTTPException:
            raise exc


def _build_artifacts(task_id: str, manifest_path: Path) -> List[Dict[str, str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths", {})
    candidates = [
        ("preferred_audio", "Preferred Audio", paths.get("preferred_audio")),
        ("mix", "Mixed Audio WAV", paths.get("dubbed_mix_full")),
        ("vocals", "Vocals WAV", paths.get("dubbed_vocals_full")),
        ("bilingual_srt", "Bilingual SRT", paths.get("dubbed_final_full_srt")),
        ("translated_srt", "Translated SRT", paths.get("translated_full_srt")),
        ("source_srt", "Source SRT", paths.get("source_full_srt")),
        ("manifest", "Batch Manifest", str(manifest_path)),
    ]
    artifacts: List[Dict[str, str]] = []
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
        artifacts.append({"key": key, "label": label, "url": _artifact_url(task_id, key)})
    return artifacts


def _complete_task_from_manifest(task_id: str, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = _build_artifacts(task_id, manifest_path)
    paths = manifest.get("paths", {})
    # 统计批处理级别的人工复核/成功片段数量，用于判定任务是否“真成功”
    total_done = 0
    total_segments = 0
    total_manual_review = 0
    for segment in manifest.get("segments", []):
        summary = segment.get("summary") or {}
        total_done += int(summary.get("done", 0) or 0)
        total_segments += int(summary.get("total", 0) or 0)
        total_manual_review += int(summary.get("manual_review", 0) or 0)

    # 当所有片段都进入 manual_review 且没有任何成功 TTS 时，输出通常是静音兜底文件：
    # 这种情况应标记为失败，避免前端显示“完成”误导用户。
    if total_done <= 0 and total_segments > 0 and total_manual_review >= total_segments:
        _set_task(
            task_id,
            status="failed",
            stage="failed",
            progress=100.0,
            batch_id=manifest.get("batch_id"),
            batch_manifest_path=str(manifest_path),
            processed_segments=manifest.get("segments_total"),
            total_segments=manifest.get("segments_total"),
            manual_review_segments=total_manual_review,
            artifacts=artifacts,
            error=(
                "TTS synthesis failed for all subtitle segments "
                "(all segments fell back to manual_review/silent placeholders)."
            ),
        )
        return

    manual_review_segments = sum(
        int((segment.get("summary") or {}).get("manual_review", 0) or 0)
        for segment in manifest.get("segments", [])
    )
    result_audio = None
    if paths.get("preferred_audio") and Path(paths["preferred_audio"]).exists():
        result_audio = _artifact_url(task_id, "preferred_audio")
    elif paths.get("dubbed_mix_full") and Path(paths["dubbed_mix_full"]).exists():
        result_audio = _artifact_url(task_id, "mix")
    elif paths.get("dubbed_vocals_full") and Path(paths["dubbed_vocals_full"]).exists():
        result_audio = _artifact_url(task_id, "vocals")

    _set_task(
        task_id,
        status="completed",
        stage="finished",
        progress=100.0,
        batch_id=manifest.get("batch_id"),
        batch_manifest_path=str(manifest_path),
        processed_segments=manifest.get("segments_total"),
        total_segments=manifest.get("segments_total"),
        manual_review_segments=manual_review_segments,
        artifacts=artifacts,
        result_audio=result_audio,
        result_srt=_artifact_url(task_id, "bilingual_srt") if paths.get("dubbed_final_full_srt") else None,
    )


def _run_cli_task(task_id: str, cmd: List[str], env: Dict[str, str], out_root: Path) -> None:
    stdout_log = out_root / "web_cli_stdout.log"
    _set_task(task_id, status="running", stage="queued", progress=2.0, stdout_log=str(stdout_log))
    try:
        with stdout_log.open("a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            _set_task(task_id, process=proc, pid=proc.pid)
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                log_handle.write(line + "\n")
                log_handle.flush()
                _append_stdout(task_id, line)
                _update_from_stdout(task_id, line)

            code = proc.wait()

        with _lock:
            task = _tasks.get(task_id)
            if task and task.get("status") == "cancelled":
                return

        if code != 0:
            with _lock:
                task = _tasks.get(task_id) or {}
                stdout_tail = list(task.get("stdout_tail", []))
            _set_task(
                task_id,
                status="failed",
                stage="failed",
                progress=100.0,
                error=_build_cli_exit_error(code, stdout_tail),
                exit_code=code,
            )
            return

        manifest_path = _find_batch_manifest(out_root)
        if not manifest_path:
            _set_task(
                task_id,
                status="failed",
                stage="failed",
                progress=100.0,
                error="CLI completed but batch_manifest.json was not found",
                exit_code=code,
            )
            return

        _complete_task_from_manifest(task_id, manifest_path)
        _set_task(task_id, exit_code=code)
    except BaseException as exc:
        _set_task(task_id, status="failed", stage="failed", progress=100.0, error=str(exc))
    finally:
        _set_task(task_id, process=None)


@router.post("/start")
async def start_auto_dubbing(
    video: UploadFile = File(...),
    subtitle_file: UploadFile | None = File(None),
    subtitle_mode: str = Form("source"),
    source_lang: str = Form("auto"),
    target_lang: str = Form(...),
    speaker_mode: str = Form("single-speaker"),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    index_tts_api_url: str = Form(DEFAULT_INDEX_TTS_API_URL),
    segment_minutes: float = Form(8.0),
    min_segment_minutes: float = Form(4.0),
    timing_mode: str = Form("strict"),
    grouping_strategy: str = Form("sentence"),
    time_ranges: str = Form(""),
    auto_pick_ranges: str = Form("false"),
    auto_pick_min_silence_sec: float = Form(0.8),
    auto_pick_min_speech_sec: float = Form(1.0),
):
    if not TOOL_PATH.exists():
        raise HTTPException(status_code=500, detail=f"CLI not found: {TOOL_PATH}")
    if segment_minutes <= 0 or min_segment_minutes <= 0 or min_segment_minutes > segment_minutes:
        raise HTTPException(status_code=400, detail="Invalid segment duration settings")
    if not target_lang.strip():
        raise HTTPException(status_code=400, detail="target_lang is required")
    if not _index_tts_target_lang_supported(target_lang):
        raise HTTPException(
            status_code=400,
            detail=(
                "Current index-tts backend in this project only supports Chinese/English reliably. "
                f"Unsupported target_lang: {target_lang}"
            ),
        )
    # 允许前端显式传入说话人模式；默认保持单人模式，确保兼容历史行为
    speaker_mode = (speaker_mode or "").strip() or "single-speaker"
    if speaker_mode not in {"single-speaker", "per-speaker", "auto"}:
        raise HTTPException(status_code=400, detail="Invalid speaker_mode")
    timing_mode = (timing_mode or "").strip() or "strict"
    if timing_mode not in {"strict", "balanced"}:
        raise HTTPException(status_code=400, detail="Invalid timing_mode")
    grouping_strategy = (grouping_strategy or "").strip() or "sentence"
    if grouping_strategy not in {"legacy", "sentence"}:
        raise HTTPException(status_code=400, detail="Invalid grouping_strategy")
    if auto_pick_min_silence_sec < 0.1 or auto_pick_min_silence_sec > 10.0:
        raise HTTPException(status_code=400, detail="Invalid auto_pick_min_silence_sec")
    if auto_pick_min_speech_sec < 0.1 or auto_pick_min_speech_sec > 30.0:
        raise HTTPException(status_code=400, detail="Invalid auto_pick_min_speech_sec")
    subtitle_mode = (subtitle_mode or "").strip().lower() or "source"
    if subtitle_mode not in {"source", "translated"}:
        raise HTTPException(status_code=400, detail="Invalid subtitle_mode")
    auto_pick_ranges_enabled = _read_bool_form(auto_pick_ranges, field_name="auto_pick_ranges")
    parsed_time_ranges = _parse_time_ranges_form(time_ranges)
    translate_base_url = (translate_base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL
    translate_model = (translate_model or "").strip() or DEFAULT_TRANSLATE_MODEL
    index_tts_api_url = (index_tts_api_url or "").strip() or DEFAULT_INDEX_TTS_API_URL
    effective_api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    # 当上传的是“已翻译字幕”时，自动跳过翻译环节，不强制要求翻译 API Key。
    skip_translation_by_uploaded_subtitle = bool(subtitle_file is not None and subtitle_file.filename and subtitle_mode == "translated")
    if (not skip_translation_by_uploaded_subtitle) and (not effective_api_key) and translate_base_url == DEFAULT_TRANSLATE_BASE_URL:
        raise HTTPException(
            status_code=400,
            detail="Translation API key is required. Provide api_key or configure a custom translate_base_url.",
        )
    _ensure_index_tts_service(index_tts_api_url)
    with _lock:
        active = [
            task_id
            for task_id, task in _tasks.items()
            if task.get("status") not in {"completed", "failed", "cancelled"}
        ]
    if active:
        raise HTTPException(status_code=409, detail="Another auto dubbing job is already running")

    task_id = _build_readable_task_id()
    upload_dir = UPLOAD_ROOT / task_id
    out_root = OUTPUT_ROOT / f"web_{task_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(video.filename or "input_media")
    input_path = upload_dir / filename
    with input_path.open("wb") as handle:
        shutil.copyfileobj(video.file, handle)
    input_srt_path: Optional[Path] = None
    if subtitle_file is not None and subtitle_file.filename:
        subtitle_name = _sanitize_filename(subtitle_file.filename)
        if not subtitle_name.lower().endswith(".srt"):
            raise HTTPException(status_code=400, detail="subtitle_file must be .srt")
        input_srt_path = upload_dir / f"manual_{subtitle_name}"
        with input_srt_path.open("wb") as handle:
            shutil.copyfileobj(subtitle_file.file, handle)
    # 上传字幕时，默认走“按字幕时间轴处理”的稳定链路，避免自动语音区间切成大量碎片段。
    # 这能防止出现“用户未显式开启 auto-pick，但任务仍按 auto ranges 切 10 段”的误行为。
    if input_srt_path is not None and auto_pick_ranges_enabled:
        auto_pick_ranges_enabled = False

    cmd = [
        sys.executable,
        "-u",  # 使用无缓冲输出，确保前端能实时收到阶段日志而非长期停留在 Queued
        str(TOOL_PATH),
        "--input-media",
        str(input_path),
        "--target-lang",
        target_lang,
        "--speaker-mode",
        speaker_mode,
        # 关键逻辑：Web 默认优先 pyannote（community-1），失败会在 dub_pipeline 内自动回退 simple。
        "--diarization-provider",
        "auto",
        "--pyannote-model",
        os.environ.get("PYANNOTE_MODEL_SOURCE", "pyannote/speaker-diarization-community-1"),
        "--pyannote-python-bin",
        os.environ.get("PYANNOTE_PYTHON_BIN", ""),
        "--out-dir",
        str(out_root),
        "--segment-minutes",
        str(segment_minutes),
        "--min-segment-minutes",
        str(min_segment_minutes),
        "--merge-track",
        "auto",
        "--timing-mode",
        timing_mode,
        "--grouping-strategy",
        grouping_strategy,
        # 这里不要再拼接“--”分隔符，避免被下游 dub_pipeline 误解析为未知参数
        "--tts-backend",
        "index-tts",
        "--index-tts-via-api",
        "true",
        "--index-tts-api-url",
        index_tts_api_url,
        "--index-tts-api-release-after-job",
        "true",
        "--index-max-text-tokens",
        "40",
        "--translate-base-url",
        translate_base_url,
        "--translate-model",
        translate_model,
        "--auto-pick-ranges",
        "true" if auto_pick_ranges_enabled else "false",
        "--auto-pick-min-silence-sec",
        str(auto_pick_min_silence_sec),
        "--auto-pick-min-speech-sec",
        str(auto_pick_min_speech_sec),
    ]
    if input_srt_path is not None:
        cmd.extend(["--input-srt", str(input_srt_path)])
        cmd.extend(["--input-srt-kind", subtitle_mode])
    if parsed_time_ranges:
        cmd.extend(["--time-ranges-json", json.dumps(parsed_time_ranges, ensure_ascii=False)])
    if source_lang and source_lang != "auto":
        cmd.extend(["--asr-language", source_lang])

    env = os.environ.copy()
    # 双保险：即使底层入口再次拉起 Python，也尽量保持 stdout/stderr 实时刷新
    env["PYTHONUNBUFFERED"] = "1"
    if effective_api_key:
        env["DEEPSEEK_API_KEY"] = effective_api_key
    elif translate_base_url != DEFAULT_TRANSLATE_BASE_URL:
        env["DEEPSEEK_API_KEY"] = "sk-no-key-required"

    task = {
        "id": task_id,
        "short_id": task_id.split("-")[0],
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "filename": filename,
        "target_lang": target_lang,
        "speaker_mode": speaker_mode,
        "timing_mode": timing_mode,
        "grouping_strategy": grouping_strategy,
        "source_lang": source_lang,
        "subtitle_mode": subtitle_mode,
        "translate_base_url": translate_base_url,
        "translate_model": translate_model,
        "index_tts_api_url": index_tts_api_url,
        "time_ranges": parsed_time_ranges,
        "auto_pick_ranges": auto_pick_ranges_enabled,
        "auto_pick_min_silence_sec": auto_pick_min_silence_sec,
        "auto_pick_min_speech_sec": auto_pick_min_speech_sec,
        "processed_segments": 0,
        "total_segments": None,
        "artifacts": [],
        "stdout_tail": [],
        "input_path": str(input_path),
        "input_srt": str(input_srt_path) if input_srt_path else None,
        "upload_dir": str(upload_dir),
        "out_root": str(out_root),
        "command": [part if part != api_key else "***" for part in cmd],
    }
    with _lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_run_cli_task, args=(task_id, cmd, env, out_root), daemon=True)
    thread.start()

    return {"task_id": task_id, "short_id": task["short_id"], "status": "queued"}


@router.get("/status/{task_id}")
async def get_auto_dubbing_status(task_id: str):
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Dubbing task not found")
        return _public_task(dict(task))


@router.post("/cancel/{task_id}")
async def cancel_auto_dubbing(task_id: str):
    cancelled = _cancel_task(task_id, "Cancelled by user")
    if not cancelled:
        raise HTTPException(status_code=404, detail="Dubbing task not found or already finished")
    return {"status": "cancelled"}


def _resolve_artifact(task: Dict[str, Any], artifact: str) -> Path:
    manifest_path_text = task.get("batch_manifest_path")
    if not manifest_path_text:
        if artifact == "stdout" and task.get("stdout_log"):
            path = Path(task["stdout_log"]).resolve()
            out_root = Path(task["out_root"]).resolve()
            try:
                path.relative_to(out_root)
            except ValueError as exc:
                raise HTTPException(status_code=403, detail="Artifact path is outside task output") from exc
            if not path.exists():
                raise HTTPException(status_code=404, detail="Artifact file not found")
            return path
        raise HTTPException(status_code=404, detail="Artifacts are not ready yet")

    manifest_path = Path(manifest_path_text).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths", {})
    key_to_path = {
        "preferred_audio": paths.get("preferred_audio"),
        "mix": paths.get("dubbed_mix_full"),
        "vocals": paths.get("dubbed_vocals_full"),
        "bgm": paths.get("source_bgm_full"),
        "source_srt": paths.get("source_full_srt"),
        "translated_srt": paths.get("translated_full_srt"),
        "bilingual_srt": paths.get("dubbed_final_full_srt"),
        "manifest": str(manifest_path),
        "stdout": task.get("stdout_log"),
    }
    path_text = key_to_path.get(artifact)
    if not path_text:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(path_text).expanduser().resolve()
    out_root = Path(task["out_root"]).resolve()
    try:
        path.relative_to(out_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Artifact path is outside task output") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return path


@router.get("/artifact/{task_id}/{artifact}")
async def download_auto_dubbing_artifact(task_id: str, artifact: str):
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Dubbing task not found")
        task_copy = dict(task)
    path = _resolve_artifact(task_copy, artifact)
    return FileResponse(path, filename=path.name)


def _cancel_task(task_id: str, reason: str) -> bool:
    with _lock:
        task = _tasks.get(task_id)
        if not task or task.get("status") in {"completed", "failed", "cancelled"}:
            return False
        proc: Optional[subprocess.Popen[str]] = task.get("process")
        task["status"] = "cancelled"
        task["stage"] = "cancelled"
        task["error"] = reason
        task["updated_at"] = _iso_now()

    if proc and proc.poll() is None:
        if hasattr(os, "killpg"):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
    return True


def cancel_active_dubbing(reason: str) -> int:
    with _lock:
        active_ids = [
            task_id
            for task_id, task in _tasks.items()
            if task.get("status") not in {"completed", "failed", "cancelled"}
        ]
    return sum(1 for task_id in active_ids if _cancel_task(task_id, reason))
