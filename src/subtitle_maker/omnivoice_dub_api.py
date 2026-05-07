from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import traceback
import subprocess
from urllib.parse import urlparse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from subtitle_maker.app import legacy_runtime
from subtitle_maker.core.ffmpeg import run_cmd
from subtitle_maker.dubbing_cli_api import _resolve_project_media_path, _sanitize_filename
from subtitle_maker.dubbing_cli_api import _store_uploaded_reference_file
from subtitle_maker.domains.dubbing.alignment import (
    fit_audio_to_duration,
    trim_audio_to_max_duration,
    trim_leading_silence_conservative,
)
from subtitle_maker.domains.dubbing.references import extract_reference_audio_from_offset
from subtitle_maker.domains.media import (
    compose_vocals_master,
    extract_source_audio,
    ffprobe_duration,
    has_video_stream,
    load_mono_audio,
    mix_with_bgm,
    normalize_speech_audio_level,
    prepare_dubbed_audio_for_video,
    replace_video_audio_two_step,
)
from subtitle_maker.domains.subtitles import normalize_subtitles_with_speakers
from subtitle_maker.jobs import TaskStore
from subtitle_maker.transcriber import format_srt
from subtitle_maker.translator import (
    DEFAULT_TRANSLATE_BASE_URL,
    DEFAULT_TRANSLATE_MODEL,
    LEGACY_TRANSLATE_API_KEY_ENV,
    TRANSLATE_API_KEY_ENV,
    Translator,
    build_translation_system_prompt,
    resolve_translation_api_key,
)

router = APIRouter(prefix="/omnivoice/auto", tags=["omnivoice-auto"])

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "dub_jobs"
LEGACY_OUTPUT_ROOT = REPO_ROOT / "outputs" / "omnivoice_dub_jobs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
LEGACY_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

_task_store = TaskStore()
logger = logging.getLogger(__name__)

DEFAULT_OMNIVOICE_API_URL = "http://127.0.0.1:3900"
DEFAULT_SPEAKER_REF_SECONDS = 8.0
MIN_SPEAKER_REF_SECONDS = 4.0
MAX_SPEAKER_REF_SECONDS = 15.0
UPLOADED_SPEAKER_REF_TEXT = "你好，这是我的声音音色，很高兴为你进行配音服务。"
REMOTE_GENERATE_TIMEOUT_SEC = 3600
OMNIVOICE_STUDIO_DIR = (REPO_ROOT / "OmniVoice-Studio-main").resolve()
OMNIVOICE_BACKEND_MAIN = OMNIVOICE_STUDIO_DIR / "backend" / "main.py"
OMNIVOICE_BACKEND_PYTHON = OMNIVOICE_STUDIO_DIR / ".venv" / "bin" / "python"
OMNIVOICE_BACKEND_PID_FILE = REPO_ROOT / "outputs" / "omnivoice_backend.pid"
OMNIVOICE_BACKEND_LOG_PATH = REPO_ROOT / "outputs" / "omnivoice_backend.log"
OMNIVOICE_LOCAL_CHECKPOINT_DIR = Path("/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/checkpoints")
_omnivoice_backend_start_lock = threading.Lock()


def _iso_now() -> str:
    """统一使用 UTC 时间戳，方便前端和恢复页排序。"""

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _build_readable_task_id() -> str:
    """生成可读任务 ID：UTC 时间戳 + 递增后缀。"""

    base = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    existing_ids = set(_task_store.keys_snapshot())
    candidate = base
    index = 2
    while candidate in existing_ids or (OUTPUT_ROOT / f"omnivoice_{candidate}").exists():
        candidate = f"{base}_{index:02d}"
        index += 1
    return candidate


def _resolve_output_dir(task_id: str) -> Path:
    """按任务 ID 解析输出目录。"""

    return (OUTPUT_ROOT / f"omnivoice_{task_id}").resolve()


def _resolve_legacy_output_dir(task_id: str) -> Path:
    """按旧任务 ID 解析历史 OmniVoice 输出目录。"""

    return (LEGACY_OUTPUT_ROOT / f"web_{task_id}").resolve()


def _build_artifact_url(task_id: str, artifact: str) -> str:
    """生成可下载的 artifact URL。"""

    return f"/omnivoice/auto/artifact/{task_id}/{artifact}"


def _set_task(task_id: str, **updates: Any) -> None:
    """更新 OmniVoice 任务状态。"""

    payload = dict(updates)
    payload.setdefault("updated_at", _iso_now())
    _task_store.update(task_id, **payload)


def _normalize_subtitles_payload(raw: str, *, field_name: str) -> List[Dict[str, Any]]:
    """把前端传来的字幕 JSON 规范化为内部配音结构。"""

    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {exc}") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: must be a list")

    rows: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        start_sec = item.get("start", item.get("start_sec"))
        end_sec = item.get("end", item.get("end_sec"))
        text_value = str(item.get("text", "") or "").strip()
        if start_sec is None or end_sec is None or not text_value:
            continue
        try:
            start_value = float(start_sec)
            end_value = float(end_sec)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {field_name} timing: {exc}") from exc
        if end_value <= start_value:
            continue
        rows.append(
            {
                "start": round(start_value, 3),
                "end": round(end_value, 3),
                "text": text_value,
                "speaker_id": str(item.get("speaker_id") or "").strip(),
            }
        )

    rows.sort(key=lambda item: float(item.get("start", 0.0) or 0.0))
    rows, _ = normalize_subtitles_with_speakers(rows)
    return rows


def _ensure_speaker_ids(rows: List[Dict[str, Any]], fallback_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """补齐缺失 speaker_id，避免 OmniVoice 路由时出现空 speaker。"""

    normalized: List[Dict[str, Any]] = []
    fallback_rows = fallback_rows or []
    for index, row in enumerate(rows):
        speaker_id = str(row.get("speaker_id") or "").strip()
        if not speaker_id and index < len(fallback_rows):
            speaker_id = str(fallback_rows[index].get("speaker_id") or "").strip()
        if not speaker_id:
            speaker_id = "Speaker 1"
        normalized.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": str(row.get("text") or "").strip(),
                "speaker_id": speaker_id,
            }
        )
    return normalized


def _normalize_translation_result(
    source_rows: List[Dict[str, Any]],
    translated_texts: List[str],
) -> List[Dict[str, Any]]:
    """把翻译后的文本重新塞回原时间轴和 speaker_id。"""

    normalized: List[Dict[str, Any]] = []
    for index, source_row in enumerate(source_rows):
        normalized.append(
            {
                "start": float(source_row.get("start", 0.0) or 0.0),
                "end": float(source_row.get("end", 0.0) or 0.0),
                "text": str(translated_texts[index] if index < len(translated_texts) else "").strip(),
                "speaker_id": str(source_row.get("speaker_id") or "").strip(),
            }
        )
    return normalized


def _drop_empty_subtitle_rows(
    rows: List[Dict[str, Any]],
    *,
    label: str,
) -> List[Dict[str, Any]]:
    """过滤空字幕行，避免空文本继续进入 OmniVoice 生成阶段。"""

    filtered: List[Dict[str, Any]] = []
    dropped = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            dropped += 1
            continue
        filtered.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": text,
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
        )
    if dropped > 0:
        logger.warning("OmniVoice dropped %d empty %s rows before synthesis", dropped, label)
    return filtered


def _pick_reference_slices(items: List[Tuple[int, Dict[str, Any]]]) -> List[Tuple[int, Dict[str, Any]]]:
    """按 OmniVoice 推荐思路选择参考音片段：优先长句，最多累计到一个稳定窗口。"""

    if not items:
        return []

    by_duration = sorted(
        items,
        key=lambda pair: float(pair[1].get("end", 0.0) or 0.0) - float(pair[1].get("start", 0.0) or 0.0),
        reverse=True,
    )
    picked: List[Tuple[int, Dict[str, Any]]] = []
    total = 0.0
    for index, segment in by_duration:
        dur = max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
        if dur <= 0.0:
            continue
        if picked and total + dur > MAX_SPEAKER_REF_SECONDS:
            break
        picked.append((index, segment))
        total += dur
        if total >= DEFAULT_SPEAKER_REF_SECONDS:
            break

    if not picked:
        picked = [by_duration[0]]
    picked.sort(key=lambda pair: pair[0])
    return picked


def _concat_reference_slices(
    *,
    vocals_path: Path,
    picked: List[Tuple[int, Dict[str, Any]]],
    out_dir: Path,
    speaker_id: str,
) -> Tuple[Path, float]:
    """把同一 speaker 的多段参考音拼成一个稳定 ref wav。"""

    out_dir.mkdir(parents=True, exist_ok=True)
    segment_arrays: List[np.ndarray] = []
    sample_rate = 44100
    for index, segment in picked:
        start_sec = float(segment.get("start", 0.0) or 0.0)
        end_sec = float(segment.get("end", start_sec) or start_sec)
        clip_path = out_dir / f"clip_{index + 1:04d}.wav"
        try:
            from subtitle_maker.domains.media import cut_audio_segment

            cut_audio_segment(
                source_audio=vocals_path,
                output_audio=clip_path,
                start_sec=start_sec,
                end_sec=end_sec,
            )
        except Exception as exc:
            logger.warning("OmniVoice ref slice failed for %s: %s", speaker_id, exc)
            continue
        wav, sr = load_mono_audio(clip_path)
        if wav.size == 0 or sr <= 0:
            continue
        if sr != sample_rate:
            from subtitle_maker.domains.media import resample_mono_audio

            wav = resample_mono_audio(wav, sr, sample_rate)
        segment_arrays.append(np.asarray(wav, dtype=np.float32))

    if not segment_arrays:
        raise RuntimeError(f"speaker reference extraction failed for {speaker_id}")

    gap = np.zeros(int(0.02 * sample_rate), dtype=np.float32)
    combined: List[np.ndarray] = []
    for index, audio in enumerate(segment_arrays):
        if index > 0:
            combined.append(gap)
        combined.append(audio)
    reference = np.concatenate(combined) if combined else np.zeros(0, dtype=np.float32)
    ref_path = out_dir / f"voice_{_safe_speaker_name(speaker_id)}.wav"
    sf.write(str(ref_path), reference, sample_rate)
    return ref_path, float(reference.size) / float(sample_rate)


def _safe_speaker_name(speaker_id: str) -> str:
    """把 speaker id 转成文件系统安全名称。"""

    cleaned: List[str] = []
    for char in str(speaker_id or "").lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-"}:
            cleaned.append("_")
    return "".join(cleaned) or "speaker"


def _build_speaker_reference_map(
    *,
    vocals_path: Path,
    subtitles: List[Dict[str, Any]],
    transcript_subtitles: Optional[List[Dict[str, Any]]] = None,
    out_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    """从人声轨里给每个 speaker 生成一份聚合参考音。"""

    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for index, subtitle in enumerate(subtitles):
        speaker_id = str(subtitle.get("speaker_id") or "").strip() or "Speaker 1"
        grouped.setdefault(speaker_id, []).append((index, subtitle))

    references: Dict[str, Dict[str, Any]] = {}
    if not grouped:
        return references

    for speaker_id, items in grouped.items():
        speaker_dir = out_dir / _safe_speaker_name(speaker_id)
        picked = _pick_reference_slices(items)
        try:
            ref_path, duration_sec = _concat_reference_slices(
                vocals_path=vocals_path,
                picked=picked,
                out_dir=speaker_dir,
                speaker_id=speaker_id,
            )
        except Exception as exc:
            logger.warning("OmniVoice speaker ref fallback for %s: %s", speaker_id, exc)
            first_start = float(items[0][1].get("start", 0.0) or 0.0)
            ref_path = speaker_dir / f"voice_{_safe_speaker_name(speaker_id)}_fallback.wav"
            extract_reference_audio_from_offset(
                vocals_audio=vocals_path,
                out_ref=ref_path,
                seconds=DEFAULT_SPEAKER_REF_SECONDS,
                start_sec=first_start,
            )
            duration_sec = max(0.0, float(sf.info(str(ref_path)).duration))

        ref_text_parts: List[str] = []
        for index, segment in picked:
            transcript_segment = None
            if transcript_subtitles and index < len(transcript_subtitles):
                candidate = transcript_subtitles[index]
                same_speaker = (str(candidate.get("speaker_id") or "").strip() or "Speaker 1") == speaker_id
                start_delta = abs(float(candidate.get("start", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
                end_delta = abs(float(candidate.get("end", 0.0) or 0.0) - float(segment.get("end", 0.0) or 0.0))
                if same_speaker and start_delta <= 0.25 and end_delta <= 0.25:
                    transcript_segment = candidate
            text_value = str((transcript_segment or segment).get("text") or "").strip()
            if text_value:
                ref_text_parts.append(text_value)

        ref_text = " ".join(ref_text_parts).strip()
        references[speaker_id] = {
            "ref_audio": str(ref_path.resolve()),
            "ref_text": ref_text,
            "duration": round(duration_sec, 3),
            "source_count": len(picked),
        }

    return references


def _build_generation_ref_text(ref_meta: Dict[str, Any]) -> str:
    """为生成阶段构造参考文本。

    说明：
    - speaker 克隆阶段仍然保留完整的 ref_text 作为调试材料；
    - 真正调用 OmniVoice 生成时，不要把长 transcript 继续喂给模型，
      否则它会把 ref_text 也拼进条件文本，直接把语速估计和语义条件带偏。
    - 这里改成只在 ref_text 很短时才保留，长文本一律收敛为空串。
    """

    raw = str(ref_meta.get("ref_text") or "").strip()
    if not raw:
        return ""

    if len(raw) <= 80:
        return raw

    # 过长的参考文本会污染 OmniVoice 的 conditioning；这里只保留开头一小段，
    # 让它仍然和 reference audio 的前部对齐，但不会把整段 transcript 喂进去。
    sentence_chunks = [chunk.strip() for chunk in re.split(r"(?<=[。！？!?\.])\s*", raw) if chunk.strip()]
    if sentence_chunks:
        short_parts: List[str] = []
        short_len = 0
        for chunk in sentence_chunks:
            if short_parts and short_len + len(chunk) > 80:
                break
            short_parts.append(chunk)
            short_len += len(chunk)
            if short_len >= 40:
                break
        if short_parts:
            return " ".join(short_parts).strip()

    return raw[:80].strip()


def _check_omnivoice_health(api_url: str, timeout_sec: int = 5) -> None:
    """确认 OmniVoice 后端健康可用，避免任务跑到一半才失败。"""

    url = api_url.rstrip("/") + "/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if response.status >= 400:
                raise RuntimeError(f"health status {response.status}")
    except Exception as exc:
        raise RuntimeError(f"OmniVoice health check failed: {exc}") from exc


def _fetch_omnivoice_model_status(api_url: str, timeout_sec: int = 5) -> Dict[str, Any]:
    """读取 OmniVoice 后端模型状态，区分“进程活着”和“模型已就绪”。"""

    url = api_url.rstrip("/") + "/model/status"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body or "{}")
            if not isinstance(payload, dict):
                raise RuntimeError("model status response must be a JSON object")
            return payload
    except Exception as exc:
        raise RuntimeError(f"OmniVoice model status check failed: {exc}") from exc


def _is_local_omnivoice_api(api_url: str) -> bool:
    """判断 api_url 是否指向本机 OmniVoice 服务。"""

    parsed = urlparse(api_url or DEFAULT_OMNIVOICE_API_URL)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True
    return host in {"127.0.0.1", "localhost", "::1"}


def _read_pid_file(pid_file: Path) -> Optional[int]:
    """读取 pid 文件。"""

    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        return int(raw)
    except Exception:
        return None


def _pid_is_alive(pid: int) -> bool:
    """检查进程是否仍然存活。"""

    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _start_local_omnivoice_backend() -> Dict[str, Any]:
    """按需拉起本机 3900 OmniVoice 服务。"""

    if not OMNIVOICE_BACKEND_PYTHON.is_file():
        raise FileNotFoundError(f"OmniVoice backend python not found: {OMNIVOICE_BACKEND_PYTHON}")
    if not OMNIVOICE_BACKEND_MAIN.is_file():
        raise FileNotFoundError(f"OmniVoice backend entry not found: {OMNIVOICE_BACKEND_MAIN}")

    with _omnivoice_backend_start_lock:
        if OMNIVOICE_BACKEND_PID_FILE.exists():
            pid = _read_pid_file(OMNIVOICE_BACKEND_PID_FILE)
            if pid and _pid_is_alive(pid):
                return {"started": False, "pid": pid, "reason": "pid-file-alive"}

        OMNIVOICE_BACKEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.setdefault("OMNIVOICE_MODEL", str(OMNIVOICE_LOCAL_CHECKPOINT_DIR))
        env.setdefault("OMNIVOICE_LOAD_ASR", "0")
        with open(OMNIVOICE_BACKEND_LOG_PATH, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [str(OMNIVOICE_BACKEND_PYTHON), str(OMNIVOICE_BACKEND_MAIN)],
                cwd=str(OMNIVOICE_STUDIO_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        OMNIVOICE_BACKEND_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        logger.info("Started local OmniVoice backend: pid=%s log=%s", proc.pid, OMNIVOICE_BACKEND_LOG_PATH)
        return {"started": True, "pid": proc.pid, "reason": "launched"}


def _ensure_omnivoice_backend_ready(api_url: str) -> Dict[str, Any]:
    """确认独立 OmniVoice 后端已完成模型加载。"""

    if _is_local_omnivoice_api(api_url):
        try:
            _start_local_omnivoice_backend()
        except Exception as exc:
            logger.warning("Local OmniVoice backend auto-start failed: %s", exc)
    _check_omnivoice_health(api_url)
    status = _fetch_omnivoice_model_status(api_url)
    loading_flag = bool(status.get("loading", False))
    status_name = str(status.get("status") or "").strip().lower()
    sub_stage = str(status.get("sub_stage") or "").strip().lower()
    if loading_flag or status_name == "loading" or sub_stage.startswith("loading"):
        detail = str(status.get("detail") or status.get("sub_stage") or status.get("status") or "loading").strip()
        raise RuntimeError(f"OmniVoice backend is still loading: {detail}")
    return status


def _encode_multipart_form_data(fields: Dict[str, str], files: Dict[str, Tuple[str, bytes, str]]) -> Tuple[bytes, str]:
    """手工编码 multipart/form-data，避免额外依赖 requests/httpx。"""

    boundary = f"----subtitle-maker-{int(time.time() * 1000)}"
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for name, (filename, data, content_type) in files.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _call_remote_generate(
    *,
    api_url: str,
    text: str,
    language: str,
    ref_audio_path: Path,
    ref_text: str,
    instruct: str,
    duration: float,
    num_step: int = 16,
    guidance_scale: float = 2.0,
    speed: float = 1.0,
) -> bytes:
    """调用独立 OmniVoice 生成服务，直接拿回 WAV bytes。"""

    generate_url = api_url.rstrip("/") + "/generate"
    files = {
        "ref_audio": (
            ref_audio_path.name or "ref.wav",
            ref_audio_path.open("rb"),
            "audio/wav",
        )
    }
    data = {
        "text": text,
        "language": language,
        "ref_text": ref_text,
        "instruct": instruct,
        "duration": f"{max(0.05, float(duration)):.3f}",
        "num_step": str(int(num_step)),
        "guidance_scale": f"{float(guidance_scale):.3f}",
        "speed": f"{float(speed):.3f}",
        "denoise": "true",
        "postprocess_output": "true",
    }

    try:
        import requests

        response = requests.post(
            generate_url,
            data=data,
            files=files,
            timeout=REMOTE_GENERATE_TIMEOUT_SEC,
        )
        if response.status_code >= 400:
            message = response.text[:800]
            raise RuntimeError(f"OmniVoice generate failed ({response.status_code}): {message}")
        return response.content
    finally:
        file_handle = files["ref_audio"][1]
        try:
            file_handle.close()
        except Exception:
            pass


def _translate_subtitles_if_needed(
    *,
    subtitles_mode: str,
    source_rows: List[Dict[str, Any]],
    translated_rows: List[Dict[str, Any]],
    target_lang: str,
    api_key: str,
    translate_base_url: str,
    translate_model: str,
    translate_system_prompt: str,
    task_id: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """根据字幕模式挑选或翻译字幕，返回最终用于配音的字幕。"""

    normalized_mode = (subtitles_mode or "auto").strip().lower()
    selected_rows: List[Dict[str, Any]] = []
    selected_mode = "translated"
    if normalized_mode == "translated":
        if translated_rows:
            return _ensure_speaker_ids(translated_rows, fallback_rows=source_rows), "translated"
        if source_rows:
            selected_rows = source_rows
            selected_mode = "source"
        else:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")
    elif normalized_mode == "source":
        if not source_rows and translated_rows:
            return _ensure_speaker_ids(translated_rows, fallback_rows=source_rows), "translated"
        if not source_rows:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")
        selected_rows = source_rows
        selected_mode = "source"
    else:
        if translated_rows:
            return _ensure_speaker_ids(translated_rows, fallback_rows=source_rows), "translated"
        if source_rows:
            selected_rows = source_rows
            selected_mode = "source"
        else:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")

    effective_api_key = resolve_translation_api_key(api_key=api_key)
    if not effective_api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Translation API key is required for source subtitles. Provide api_key or configure "
                f"{TRANSLATE_API_KEY_ENV} / {LEGACY_TRANSLATE_API_KEY_ENV}."
            ),
        )
    translator = Translator(
        api_key=effective_api_key,
        base_url=translate_base_url or DEFAULT_TRANSLATE_BASE_URL,
        model=translate_model or DEFAULT_TRANSLATE_MODEL,
    )
    texts = [str(row.get("text") or "").strip() for row in selected_rows]
    translated_texts = translator.translate_batch(
        texts,
        target_lang=target_lang,
        system_prompt=build_translation_system_prompt(translate_system_prompt),
    )
    translated_rows = _normalize_translation_result(selected_rows, translated_texts)
    translated_rows = _ensure_speaker_ids(translated_rows, fallback_rows=source_rows)
    translated_rows = _drop_empty_subtitle_rows(translated_rows, label="translated")
    if not translated_rows:
        raise HTTPException(status_code=400, detail="OmniVoice translation produced no usable subtitle rows")
    logger.info("OmniVoice task %s translated %d subtitles from source mode", task_id, len(translated_rows))
    return translated_rows, selected_mode


def _normalize_generated_segment_audio(input_path: Path, output_path: Path, target_duration_sec: float) -> Path:
    """对单句 OmniVoice 输出做轻量收尾处理，避免前导空白和轻微时长漂移。"""

    work_dir = output_path.parent
    trim_path = work_dir / f"{output_path.stem}._trim.wav"
    norm_path = work_dir / f"{output_path.stem}._norm.wav"
    full_duration, trimmed_duration = trim_leading_silence_conservative(
        input_path=input_path,
        output_path=trim_path,
        threshold_db=-35.0,
        pad_sec=0.08,
        max_trim_sec=0.35,
    )
    if trimmed_duration <= 0.0:
        shutil.copy2(input_path, output_path)
        return output_path

    normalize_speech_audio_level(
        input_path=trim_path,
        output_path=norm_path,
        target_rms=0.12,
        activity_threshold_db=-35.0,
        max_gain_db=8.0,
        peak_ceiling=0.95,
    )
    current_duration = max(0.01, float(sf.info(str(norm_path)).duration))
    target_duration_sec = max(0.05, float(target_duration_sec))
    if current_duration > target_duration_sec + 0.15:
        ratio = current_duration / target_duration_sec
        if ratio <= 1.25:
            try:
                fit_audio_to_duration(
                    input_path=norm_path,
                    output_path=output_path,
                    target_duration_sec=target_duration_sec,
                )
                return output_path
            except Exception as exc:
                logger.warning("OmniVoice fit timing fallback for %s: %s", output_path.name, exc)
        trim_audio_to_max_duration(
            input_path=norm_path,
            output_path=output_path,
            max_duration_sec=target_duration_sec,
        )
        return output_path

    shutil.copy2(norm_path, output_path)
    return output_path


def _create_task_payload(
    *,
    task_id: str,
    project_filename: str,
    input_media_path: Path,
    subtitle_mode: str,
    source_lang: str,
    target_lang: str,
    source_count: int,
    translated_count: int,
    speaker_ids: List[str],
    out_root: Path,
) -> Dict[str, Any]:
    """创建 OmniVoice 任务初始记录。"""

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
        "batch_id": task_id,
        "batch_manifest_path": str((out_root / "manifest.json").resolve()),
        "processed_segments": 0,
        "total_segments": 0,
        "manual_review_segments": 0,
        "project_filename": project_filename,
        "input_media_path": str(input_media_path),
        "input_media_url": None,
        "subtitle_mode": subtitle_mode,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_subtitles_count": source_count,
        "translated_subtitles_count": translated_count,
        "speaker_ids": speaker_ids,
        "omnivoice_api_url": DEFAULT_OMNIVOICE_API_URL,
        "result_audio": None,
        "result_srt": None,
    }


def _build_manifest(
    *,
    task: Dict[str, Any],
    out_root: Path,
    source_audio_path: Path,
    source_vocals_path: Path,
    source_bgm_path: Path,
    speaker_ref_map_path: Path,
    final_srt_path: Path,
    final_vocals_path: Path,
    final_mix_path: Path,
    final_video_path: Optional[Path],
    separated_video_audio_path: Optional[Path],
    separation_report_path: Path,
    speaker_reference_dir: Path,
    subtitles_path: Path,
) -> Dict[str, Any]:
    """写入独立 OmniVoice manifest，供恢复与 artifact 下载使用。"""

    paths: Dict[str, Optional[str]] = {
        "source_audio": str(source_audio_path.resolve()) if source_audio_path.exists() else None,
        "source_vocals": str(source_vocals_path.resolve()) if source_vocals_path.exists() else None,
        "source_bgm": str(source_bgm_path.resolve()) if source_bgm_path.exists() else None,
        "speaker_ref_map": str(speaker_ref_map_path.resolve()) if speaker_ref_map_path.exists() else None,
        "speaker_reference_dir": str(speaker_reference_dir.resolve()) if speaker_reference_dir.exists() else None,
        "selected_subtitles": str(subtitles_path.resolve()) if subtitles_path.exists() else None,
        "dubbed_final_srt": str(final_srt_path.resolve()) if final_srt_path.exists() else None,
        "dubbed_vocals": str(final_vocals_path.resolve()) if final_vocals_path.exists() else None,
        "dubbed_mix": str(final_mix_path.resolve()) if final_mix_path.exists() else None,
        "dubbed_audio_for_video": str(separated_video_audio_path.resolve()) if separated_video_audio_path and separated_video_audio_path.exists() else None,
        "dubbed_video_full": str(final_video_path.resolve()) if final_video_path and final_video_path.exists() else None,
        "separation_report": str(separation_report_path.resolve()) if separation_report_path.exists() else None,
        "manifest": str((out_root / "manifest.json").resolve()),
    }
    artifacts: List[Dict[str, str]] = [
        {"key": "srt", "label": "Dubbed Final SRT", "url": _build_artifact_url(task["id"], "srt")},
        {"key": "vocals", "label": "Dubbed Vocals WAV", "url": _build_artifact_url(task["id"], "vocals")},
        {"key": "mix", "label": "Dubbed Mix WAV", "url": _build_artifact_url(task["id"], "mix")},
        {"key": "manifest", "label": "Manifest JSON", "url": _build_artifact_url(task["id"], "manifest")},
    ]
    if final_video_path and final_video_path.exists():
        artifacts.insert(3, {"key": "video", "label": "Dubbed Video MP4", "url": _build_artifact_url(task["id"], "video")})
    if separated_video_audio_path and separated_video_audio_path.exists():
        artifacts.append({"key": "video_audio", "label": "Dubbed Audio M4A", "url": _build_artifact_url(task["id"], "video_audio")})
    if separation_report_path.exists():
        artifacts.append({"key": "separation_report", "label": "Separation Report", "url": _build_artifact_url(task["id"], "separation_report")})

    manifest = {
        "task_id": task["id"],
        "batch_id": task["batch_id"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "status": task["status"],
        "stage": task["stage"],
        "progress": task["progress"],
        "project_filename": task["project_filename"],
        "input_media_path": task["input_media_path"],
        "subtitle_mode": task["subtitle_mode"],
        "source_lang": task["source_lang"],
        "target_lang": task["target_lang"],
        "selected_subtitle_mode": task.get("selected_subtitle_mode"),
        "source_subtitles_count": task["source_subtitles_count"],
        "translated_subtitles_count": task["translated_subtitles_count"],
        "speaker_ids": task["speaker_ids"],
        "speaker_reference_mode": task.get("speaker_reference_mode") or "auto_aggregate",
        "paths": paths,
        "artifacts": artifacts,
        "segment_count": task.get("total_segments", 0),
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _load_manifest(batch_id: str) -> Optional[Dict[str, Any]]:
    """从磁盘加载历史 OmniVoice manifest。"""

    candidate_roots = [
        _resolve_output_dir(batch_id),
        _resolve_legacy_output_dir(batch_id),
    ]
    for out_root in candidate_roots:
        manifest_path = out_root / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                manifest["_manifest_path"] = str(manifest_path.resolve())
            return manifest
        except Exception:
            continue
    return None


def _artifact_path_from_task(task: Dict[str, Any], artifact: str) -> Optional[Path]:
    """根据 artifact key 解析输出路径。"""

    manifest_path = Path(str(task.get("batch_manifest_path") or "")).expanduser()
    out_root = manifest_path.parent if manifest_path.exists() else _resolve_output_dir(str(task.get("batch_id") or task.get("id") or ""))
    paths = {
        "srt": out_root / "final" / "dubbed_final_full.srt",
        "vocals": out_root / "final" / "dubbed_vocals_full.wav",
        "mix": out_root / "final" / "dubbed_mix_full.wav",
        "video": out_root / "final" / "dubbed_video_full.mp4",
        "video_audio": out_root / "final" / "dubbed_audio_for_video.m4a",
        "manifest": out_root / "manifest.json",
        "separation_report": out_root / "separation_report.json",
    }
    return paths.get(artifact)


def _create_task_from_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """把磁盘 manifest 转成可回放的任务记录。"""

    task_id = str(manifest.get("task_id") or manifest.get("batch_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="Invalid OmniVoice manifest")
    manifest_path_text = str(manifest.get("_manifest_path") or "").strip()
    manifest_path = Path(manifest_path_text).expanduser().resolve() if manifest_path_text else None
    out_root = manifest_path.parent if manifest_path and manifest_path.exists() else _resolve_output_dir(task_id)
    task = _create_task_payload(
        task_id=task_id,
        project_filename=str(manifest.get("project_filename") or ""),
        input_media_path=Path(str(manifest.get("input_media_path") or "")),
        subtitle_mode=str(manifest.get("subtitle_mode") or "auto"),
        source_lang=str(manifest.get("source_lang") or "auto"),
        target_lang=str(manifest.get("target_lang") or "Chinese"),
        source_count=int(manifest.get("source_subtitles_count") or 0),
        translated_count=int(manifest.get("translated_subtitles_count") or 0),
        speaker_ids=list(manifest.get("speaker_ids") or []),
        out_root=out_root,
    )
    task["status"] = str(manifest.get("status") or "completed")
    task["stage"] = str(manifest.get("stage") or "completed")
    task["progress"] = float(manifest.get("progress") or 100.0)
    task["selected_subtitle_mode"] = str(manifest.get("selected_subtitle_mode") or "")
    task["speaker_reference_mode"] = str(manifest.get("speaker_reference_mode") or "auto_aggregate")
    task["artifacts"] = list(manifest.get("artifacts") or [])
    task["result_srt"] = str((manifest.get("paths") or {}).get("dubbed_final_srt") or "") or None
    task["result_audio"] = str((manifest.get("paths") or {}).get("dubbed_mix") or "") or None
    task["batch_manifest_path"] = str((out_root / "manifest.json").resolve())
    _task_store.create(task_id, task)
    return task


def _run_omnivoice_job(
    *,
    task_id: str,
    input_media_path: Path,
    project_filename: str,
    source_subtitles: List[Dict[str, Any]],
    translated_subtitles: List[Dict[str, Any]],
    subtitle_mode: str,
    source_lang: str,
    target_lang: str,
    api_key: str,
    translate_base_url: str,
    translate_model: str,
    translate_system_prompt: str,
    omnivoice_api_url: str,
    uploaded_speaker_ref_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """后台执行独立 OmniVoice dubbing 链路。"""

    out_root = _resolve_output_dir(task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    final_dir = out_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    segment_root = out_root / "segment_jobs"
    segment_root.mkdir(parents=True, exist_ok=True)
    stems_root = out_root / "stems"
    stems_root.mkdir(parents=True, exist_ok=True)
    speaker_root = stems_root / "speaker_refs"
    speaker_root.mkdir(parents=True, exist_ok=True)

    source_audio_path = stems_root / "source_audio.wav"
    source_vocals_path = stems_root / "full_source_vocals.wav"
    source_bgm_path = stems_root / "full_source_bgm.wav"
    separation_report_path = out_root / "separation_report.json"
    speaker_ref_map_path = out_root / "speaker_ref_map.json"

    # 先确认独立 OmniVoice 后端不仅活着，而且模型已经就绪，再进入后续昂贵步骤。
    _ensure_omnivoice_backend_ready(omnivoice_api_url)
    _set_task(task_id, status="running", stage="dubbing:preparing", progress=1.0)
    extract_source_audio(input_media=input_media_path, output_wav=source_audio_path)

    # 先做人声/背景分离，再让中间链路只用人声。
    _set_task(task_id, stage="dubbing:separating", progress=7.0)
    separator_device = "mps"
    try:
        import torch

        if not torch.backends.mps.is_available():
            separator_device = "auto"
    except Exception:
        separator_device = "auto"

    demucs_out = stems_root / "demucs_tmp"
    demucs_out.mkdir(parents=True, exist_ok=True)
    attempts: List[Dict[str, Any]] = []
    vocals_src = None
    bgm_src = None
    has_bgm_track = False
    for model_name in ("htdemucs", "mdx_extra_q"):
        cmd = [
            sys.executable,
            "-m",
            "demucs.separate",
            "-n",
            model_name,
            "--two-stems=vocals",
            "-o",
            str(demucs_out),
            str(source_audio_path),
        ]
        if separator_device and separator_device != "auto":
            cmd[5:5] = ["-d", separator_device]
        code, _, err = run_cmd(cmd, cwd=REPO_ROOT)
        if code != 0:
            attempts.append({"model": model_name, "ok": False, "error": err.strip() or "demucs failed"})
            continue
        model_root = demucs_out / model_name
        vocals_candidates = list(model_root.glob("**/vocals.wav"))
        bgm_candidates = list(model_root.glob("**/no_vocals.wav"))
        if not vocals_candidates:
            attempts.append({"model": model_name, "ok": False, "error": "vocals.wav not found"})
            continue
        vocals_src = vocals_candidates[0]
        bgm_src = bgm_candidates[0] if bgm_candidates else None
        attempts.append({"model": model_name, "ok": True, "error": ""})
        break

    if vocals_src is None:
        separation_report_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "attempts": attempts,
                    "separator_device": separator_device,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise RuntimeError("OmniVoice pre-separation failed")

    shutil.copy2(vocals_src, source_vocals_path)
    if bgm_src and bgm_src.exists():
        shutil.copy2(bgm_src, source_bgm_path)
        has_bgm_track = True

    separation_report_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "attempts": attempts,
                "separator_device": separator_device,
                "source_audio": str(source_audio_path.resolve()),
                "source_vocals": str(source_vocals_path.resolve()),
                "source_bgm": str(source_bgm_path.resolve()) if has_bgm_track else None,
                "has_bgm_track": has_bgm_track,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    selected_subtitles, selected_mode = _translate_subtitles_if_needed(
        subtitles_mode=subtitle_mode,
        source_rows=source_subtitles,
        translated_rows=translated_subtitles,
        target_lang=target_lang,
        api_key=api_key,
        translate_base_url=translate_base_url,
        translate_model=translate_model,
        translate_system_prompt=translate_system_prompt,
        task_id=task_id,
    )
    selected_subtitles = _ensure_speaker_ids(selected_subtitles, fallback_rows=source_subtitles)
    selected_subtitles = _drop_empty_subtitle_rows(selected_subtitles, label="selected")
    source_reference_subtitles = _ensure_speaker_ids(source_subtitles, fallback_rows=selected_subtitles)
    selected_subtitles_path = out_root / "selected_subtitles.srt"
    selected_subtitles_path.write_text(format_srt(selected_subtitles), encoding="utf-8")

    if not selected_subtitles:
        raise RuntimeError("No usable subtitles for OmniVoice dubbing")

    detected_speaker_ids = sorted(
        {
            str(row.get("speaker_id") or "").strip() or "Speaker 1"
            for row in selected_subtitles
        }
    )

    # speaker 参考音优先使用用户上传的 strict 映射；未提供时才回退自动聚合。
    _set_task(task_id, stage="dubbing:preparing_refs", progress=12.0)
    reference_mode = "auto_aggregate"
    if uploaded_speaker_ref_map:
        missing_speakers = [
            speaker_id
            for speaker_id in detected_speaker_ids
            if speaker_id not in uploaded_speaker_ref_map
        ]
        if missing_speakers:
            raise RuntimeError(
                "OmniVoice strict speaker mapping missing uploaded references for: "
                + ", ".join(missing_speakers)
            )
        speaker_ref_map = {
            speaker_id: dict(uploaded_speaker_ref_map[speaker_id])
            for speaker_id in detected_speaker_ids
        }
        reference_mode = "uploaded_strict"
    else:
        speaker_ref_map = _build_speaker_reference_map(
            vocals_path=source_vocals_path,
            subtitles=selected_subtitles,
            transcript_subtitles=source_reference_subtitles if source_reference_subtitles else selected_subtitles,
            out_dir=speaker_root,
        )
    speaker_ref_map_path.write_text(
        json.dumps(
            {
                "reference_mode": reference_mode,
                "fixed_ref_text": UPLOADED_SPEAKER_REF_TEXT if reference_mode == "uploaded_strict" else None,
                "speakers": speaker_ref_map,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not speaker_ref_map:
        raise RuntimeError("No speaker reference audio could be built")
    _set_task(task_id, speaker_reference_mode=reference_mode)

    _set_task(
        task_id,
        total_segments=len(selected_subtitles),
        processed_segments=0,
        stage="dubbing:generating",
        progress=15.0,
    )

    segment_results: List[Dict[str, Any]] = []
    total_segments = len(selected_subtitles)
    for index, row in enumerate(selected_subtitles, start=1):
        speaker_id = str(row.get("speaker_id") or "").strip() or "Speaker 1"
        ref_meta = speaker_ref_map.get(speaker_id) or next(iter(speaker_ref_map.values()))
        ref_audio_path = Path(str(ref_meta.get("ref_audio") or "")).expanduser()
        if not ref_audio_path.exists():
            raise RuntimeError(f"reference audio missing for speaker {speaker_id}: {ref_audio_path}")
        segment_dir = segment_root / f"segment_{index:04d}"
        segment_dir.mkdir(parents=True, exist_ok=True)
        output_segment_path = segment_dir / f"seg_{index:04d}.wav"
        duration_sec = max(0.05, float(row.get("end", 0.0) or 0.0) - float(row.get("start", 0.0) or 0.0))
        ref_text_for_generation = _build_generation_ref_text(ref_meta)
        generation_text = str(row.get("text") or "").strip()
        if not generation_text:
            raise RuntimeError(
                f"OmniVoice subtitle #{index:04d} has empty text after filtering; "
                "cannot synthesize blank content"
            )
        generated_bytes = _call_remote_generate(
            api_url=omnivoice_api_url,
            text=generation_text,
            language=target_lang,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text_for_generation,
            instruct="",
            duration=duration_sec,
        )
        output_segment_path.write_bytes(generated_bytes)
        normalized_segment_path = segment_dir / f"seg_{index:04d}_normalized.wav"
        _normalize_generated_segment_audio(
            input_path=output_segment_path,
            output_path=normalized_segment_path,
            target_duration_sec=duration_sec,
        )
        final_segment_path = segment_dir / f"seg_{index:04d}.wav"
        shutil.copy2(normalized_segment_path, final_segment_path)
        segment_manifest = {
            "id": f"seg_{index:04d}",
            "speaker_id": speaker_id,
            "start_sec": float(row.get("start", 0.0) or 0.0),
            "end_sec": float(row.get("end", 0.0) or 0.0),
            "text": generation_text,
            "ref_audio_path": str(ref_audio_path.resolve()),
            "tts_audio_path": str(final_segment_path.resolve()),
            "duration_sec": round(duration_sec, 3),
            "normalized_duration_sec": round(float(sf.info(str(final_segment_path)).duration), 3),
        }
        (segment_dir / "manifest.json").write_text(json.dumps(segment_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        segment_results.append(segment_manifest)
        _set_task(
            task_id,
            processed_segments=index,
            progress=15.0 + (65.0 * (index / max(1, total_segments))),
            stage="dubbing:generating",
        )

    # 回填全时轴 vocals。
    _set_task(task_id, stage="dubbing:composing", progress=82.0)
    compose_inputs = [
        {
            "id": item["id"],
            "start_sec": item["start_sec"],
            "end_sec": item["end_sec"],
            "tts_audio_path": item["tts_audio_path"],
        }
        for item in segment_results
    ]
    final_vocals_path = final_dir / "dubbed_vocals_full.wav"
    compose_vocals_master(
        segments=compose_inputs,
        output_path=final_vocals_path,
        source_audio_fallback=source_vocals_path,
    )

    final_mix_path = final_dir / "dubbed_mix_full.wav"
    if has_bgm_track:
        mix_with_bgm(
            vocals_path=final_vocals_path,
            bgm_path=source_bgm_path,
            output_path=final_mix_path,
            target_sr=44100,
        )
    else:
        shutil.copy2(final_vocals_path, final_mix_path)

    final_srt_path = final_dir / "dubbed_final_full.srt"
    final_srt_path.write_text(format_srt(selected_subtitles), encoding="utf-8")

    final_video_path: Optional[Path] = None
    prepared_audio_path: Optional[Path] = None
    if has_video_stream(input_media_path):
        _set_task(task_id, stage="dubbing:muxing", progress=91.0)
        final_video_path = final_dir / "dubbed_video_full.mp4"
        prepared_audio_path = final_dir / "dubbed_audio_for_video.m4a"
        prepare_dubbed_audio_for_video(
            preferred_audio_path=final_mix_path,
            output_audio_path=prepared_audio_path,
            target_duration_sec=max(0.05, float(ffprobe_duration(input_media_path))),
        )
        replace_video_audio_two_step(
            input_media_path=input_media_path,
            prepared_audio_path=prepared_audio_path,
            output_video_path=final_video_path,
            target_duration_sec=max(0.05, float(ffprobe_duration(input_media_path))),
        )

    task = _task_store.get(task_id)
    if task is None:
        raise RuntimeError("OmniVoice task disappeared from store unexpectedly")
    task.update(
        {
            "status": "completed",
            "stage": "completed",
            "progress": 100.0,
            "processed_segments": total_segments,
            "artifacts": [],
            "result_audio": str(final_mix_path.resolve()),
            "result_srt": str(final_srt_path.resolve()),
            "selected_subtitle_mode": selected_mode,
            "speaker_reference_mode": reference_mode,
        }
    )
    manifest = _build_manifest(
        task=task,
        out_root=out_root,
        source_audio_path=source_audio_path,
        source_vocals_path=source_vocals_path,
        source_bgm_path=source_bgm_path,
        speaker_ref_map_path=speaker_ref_map_path,
        final_srt_path=final_srt_path,
        final_vocals_path=final_vocals_path,
        final_mix_path=final_mix_path,
        final_video_path=final_video_path,
        separated_video_audio_path=prepared_audio_path,
        separation_report_path=separation_report_path,
        speaker_reference_dir=speaker_root,
        subtitles_path=selected_subtitles_path,
    )
    task["artifacts"] = list(manifest.get("artifacts") or [])
    task["batch_manifest_path"] = str((out_root / "manifest.json").resolve())
    task["out_root"] = str(out_root.resolve())
    task["result_audio"] = str(final_mix_path.resolve())
    task["result_srt"] = str(final_srt_path.resolve())
    _set_task(task_id, status="completed", stage="completed", progress=100.0)


def _background_runner(task_id: str, **kwargs: Any) -> None:
    """后台线程入口，统一捕获异常并落到任务状态。"""

    try:
        _run_omnivoice_job(task_id=task_id, **kwargs)
    except Exception as exc:
        logger.error("OmniVoice task %s failed: %s\n%s", task_id, exc, traceback.format_exc())
        _set_task(
            task_id,
            status="failed",
            stage="failed",
            progress=100.0,
            error=str(exc),
        )


def _task_to_public(task: Dict[str, Any]) -> Dict[str, Any]:
    """构造前端可直接消费的公开任务视图。"""

    public = dict(task)
    public.setdefault("artifacts", [])
    return public


@router.post("/start-from-project")
async def start_omnivoice_from_project(
    filename: str = Form(""),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    source_subtitles_json: str = Form(""),
    translated_subtitles_json: str = Form(""),
    speaker_ref_files: List[UploadFile] = File([]),
    speaker_ref_speaker_ids_json: str = Form(""),
    subtitle_mode: str = Form("auto"),
    source_lang: str = Form("auto"),
    target_lang: str = Form("Chinese"),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
    omnivoice_api_url: str = Form(DEFAULT_OMNIVOICE_API_URL),
) -> Dict[str, Any]:
    """基于当前项目上下文启动独立 OmniVoice dubbing 任务。"""

    active = _task_store.list_active_ids()
    if active:
        raise HTTPException(status_code=409, detail="Another OmniVoice job is already running")

    try:
        backend_status = _ensure_omnivoice_backend_ready(omnivoice_api_url or DEFAULT_OMNIVOICE_API_URL)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    source_media_path = _resolve_project_media_path(filename, task_id)
    display_name = _sanitize_filename(original_filename or source_media_path.name)
    source_rows = _normalize_subtitles_payload(source_subtitles_json, field_name="source_subtitles_json")
    translated_rows = _normalize_subtitles_payload(translated_subtitles_json, field_name="translated_subtitles_json")
    if not source_rows and not translated_rows:
        raise HTTPException(status_code=400, detail="OmniVoice requires project subtitles")

    resolved_task_id = _build_readable_task_id()
    out_root = _resolve_output_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)

    selected_rows_for_preview = _ensure_speaker_ids(
        translated_rows if translated_rows else source_rows,
        fallback_rows=source_rows,
    )
    speaker_ids = sorted(
        {
            str(row.get("speaker_id") or "").strip() or "Speaker 1"
            for row in selected_rows_for_preview
        }
    )
    uploaded_speaker_ref_map: Dict[str, Dict[str, Any]] = {}
    if speaker_ref_speaker_ids_json.strip():
        try:
            speaker_ids_payload = json.loads(speaker_ref_speaker_ids_json)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid speaker_ref_speaker_ids_json: {exc}") from exc
        if not isinstance(speaker_ids_payload, list):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json must be a list")
        if len(speaker_ids_payload) != len(speaker_ref_files):
            raise HTTPException(status_code=400, detail="speaker_ref_speaker_ids_json count must match speaker_ref_files")
        missing_uploads = [speaker_id for speaker_id in speaker_ids if speaker_id not in {str(item or '').strip() for item in speaker_ids_payload}]
        if missing_uploads:
            raise HTTPException(
                status_code=400,
                detail="OmniVoice strict speaker mapping missing uploaded references for: " + ", ".join(missing_uploads),
            )
        uploaded_ref_dir = out_root / "uploaded_speaker_refs"
        uploaded_ref_dir.mkdir(parents=True, exist_ok=True)
        for speaker_id, ref_file in zip(speaker_ids_payload, speaker_ref_files):
            normalized_speaker_id = str(speaker_id or "").strip()
            if not normalized_speaker_id:
                continue
            if normalized_speaker_id not in speaker_ids:
                raise HTTPException(status_code=400, detail=f"unknown speaker_id in uploaded OmniVoice references: {normalized_speaker_id}")
            stored_path = _store_uploaded_reference_file(
                upload_dir=uploaded_ref_dir,
                file=ref_file,
                fallback_name=f"{_sanitize_filename(normalized_speaker_id) or 'speaker'}_ref.wav",
            )
            if not stored_path:
                continue
            uploaded_speaker_ref_map[normalized_speaker_id] = {
                "ref_audio": stored_path,
                "ref_text": UPLOADED_SPEAKER_REF_TEXT,
                "duration": round(float(sf.info(stored_path).duration), 3),
                "source_count": 1,
                "reference_mode": "uploaded_strict",
            }
        unresolved = [speaker_id for speaker_id in speaker_ids if speaker_id not in uploaded_speaker_ref_map]
        if unresolved:
            raise HTTPException(
                status_code=400,
                detail="OmniVoice strict speaker mapping missing valid audio files for: " + ", ".join(unresolved),
            )

    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=display_name,
        input_media_path=source_media_path,
        subtitle_mode=subtitle_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        source_count=len(source_rows),
        translated_count=len(translated_rows),
        speaker_ids=speaker_ids,
        out_root=out_root,
    )
    task["omnivoice_api_url"] = omnivoice_api_url or DEFAULT_OMNIVOICE_API_URL
    task["omnivoice_backend_status"] = backend_status
    task["speaker_reference_mode"] = "uploaded_strict" if uploaded_speaker_ref_map else "auto_aggregate"
    _task_store.create(resolved_task_id, task)

    thread = threading.Thread(
        target=_background_runner,
        kwargs=dict(
            task_id=resolved_task_id,
            input_media_path=source_media_path,
            project_filename=display_name,
            source_subtitles=source_rows,
            translated_subtitles=translated_rows,
            subtitle_mode=subtitle_mode,
            source_lang=source_lang,
            target_lang=target_lang,
            api_key=api_key,
            translate_base_url=translate_base_url,
            translate_model=translate_model,
            translate_system_prompt=translate_system_prompt,
            omnivoice_api_url=task["omnivoice_api_url"],
            uploaded_speaker_ref_map=uploaded_speaker_ref_map,
        ),
        daemon=True,
    )
    task["process"] = thread
    thread.start()
    return {
        "task_id": resolved_task_id,
        "short_id": resolved_task_id.split("_")[0],
        "status": "queued",
        "stage": "queued",
        "project_filename": display_name,
        "message": "OmniVoice task started",
    }


@router.get("/backend-status")
async def get_omnivoice_backend_status(
    omnivoice_api_url: str = DEFAULT_OMNIVOICE_API_URL,
) -> Dict[str, Any]:
    """给前端显示独立 OmniVoice 后端是否真正 ready。"""

    try:
        status = _ensure_omnivoice_backend_ready(omnivoice_api_url or DEFAULT_OMNIVOICE_API_URL)
        return {
            "ok": True,
            "ready": True,
            "status": status.get("status") or "ready",
            "detail": status.get("detail") or "",
            "sub_stage": status.get("sub_stage") or "",
            "loaded": True,
            "loading": False,
        }
    except Exception as exc:
        message = str(exc)
        health_ok = False
        try:
            _check_omnivoice_health(omnivoice_api_url or DEFAULT_OMNIVOICE_API_URL)
            health_ok = True
        except Exception:
            health_ok = False
        return {
            "ok": False,
            "ready": False,
            "status": "loading",
            "detail": message,
            "loaded": False,
            "loading": True,
            "health": "ok" if health_ok else "error",
        }


@router.get("/status/{task_id}")
async def get_omnivoice_status(task_id: str) -> Dict[str, Any]:
    """轮询 OmniVoice 任务状态。"""

    task = _task_store.get_public(task_id)
    if task is None:
        manifest = _load_manifest(task_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="Task not found")
        task = _task_to_public(_create_task_from_manifest(manifest))
    task.setdefault("artifacts", [])
    return task


@router.get("/batches")
async def list_omnivoice_batches() -> Dict[str, Any]:
    """列出可恢复的 OmniVoice 结果目录。"""

    manifest_paths: List[Path] = []
    manifest_paths.extend(sorted(OUTPUT_ROOT.glob("omnivoice_*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    manifest_paths.extend(sorted(LEGACY_OUTPUT_ROOT.glob("web_*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    seen_paths = set()
    collected: List[Tuple[float, Dict[str, Any]]] = []
    for manifest_path in manifest_paths:
        if manifest_path in seen_paths:
            continue
        seen_paths.add(manifest_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        collected.append(
            (
                manifest_path.stat().st_mtime,
                {
                    "batch_id": str(
                        manifest.get("batch_id")
                        or manifest.get("task_id")
                        or manifest_path.parent.name.removeprefix("omnivoice_").removeprefix("web_")
                    ),
                    "task_id": str(manifest.get("task_id") or ""),
                    "project_filename": str(manifest.get("project_filename") or ""),
                    "status": str(manifest.get("status") or ""),
                    "created_at": str(manifest.get("created_at") or ""),
                    "target_lang": str(manifest.get("target_lang") or ""),
                    "subtitle_mode": str(manifest.get("subtitle_mode") or ""),
                },
            )
        )
    items = [item for _, item in sorted(collected, key=lambda pair: pair[0], reverse=True)]
    return {"items": items}


@router.post("/load-batch")
async def load_omnivoice_batch(batch_id: str = Form(...)) -> Dict[str, Any]:
    """从磁盘恢复一个 OmniVoice 任务视图。"""

    manifest = _load_manifest(batch_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Batch folder not found")
    task = _create_task_from_manifest(manifest)
    return _task_to_public(task)


@router.get("/artifact/{task_id}/{artifact}")
async def download_omnivoice_artifact(task_id: str, artifact: str):
    """下载 OmniVoice 输出产物。"""

    task = _task_store.get(task_id)
    if task is None:
        manifest = _load_manifest(task_id)
        if manifest is not None:
            task = _create_task_from_manifest(manifest)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    path = _artifact_path_from_task(task, artifact)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = "application/octet-stream"
    if artifact in {"srt"}:
        media_type = "application/x-subrip"
    elif artifact in {"vocals", "mix", "video_audio"}:
        media_type = "audio/wav" if artifact != "video_audio" else "audio/mp4"
    elif artifact == "video":
        media_type = "video/mp4"
    elif artifact == "manifest":
        media_type = "application/json"
    elif artifact == "separation_report":
        media_type = "application/json"
    return FileResponse(path=path, filename=path.name, media_type=media_type)
