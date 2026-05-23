from __future__ import annotations

import json
import logging
import os
import random
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
from typing import Any, Dict, List, Optional, Set, Tuple

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
    burn_ass_subtitles_into_video,
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
from subtitle_maker.domains.subtitles import optimize_srt_import_subtitles
from subtitle_maker.domains.subtitles.srt import (
    ends_with_connector,
    infer_cjk_mode_from_lines,
    is_sentence_end,
    starts_with_connector,
    subtitle_group_text,
    subtitle_text_units,
)
from subtitle_maker.jobs import TaskStore
from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.translator import (
    DEFAULT_TRANSLATE_BASE_URL,
    DEFAULT_TRANSLATE_MODEL,
    LEGACY_TRANSLATE_API_KEY_ENV,
    TRANSLATE_API_KEY_ENV,
    Translator,
    build_translation_system_prompt,
    normalize_language_tag_for_passthrough,
    resolve_translation_api_key,
    normalize_cantonese_translation_text,
)

router = APIRouter(prefix="/omnivoice/auto", tags=["omnivoice-auto"])

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "outputs" / "dub_jobs"
LEGACY_OUTPUT_ROOT = REPO_ROOT / "outputs" / "omnivoice_dub_jobs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
# 旧目录只用于兼容读取历史任务，不再主动创建，避免污染新的输出结构。

_task_store = TaskStore()
logger = logging.getLogger(__name__)

DEFAULT_OMNIVOICE_API_URL = "http://127.0.0.1:3900"
DEFAULT_SPEAKER_REF_SECONDS = 8.0
MIN_SPEAKER_REF_SECONDS = 4.0
MAX_SPEAKER_REF_SECONDS = 15.0
UPLOADED_SPEAKER_REF_TEXT_ZH = "你好，这是我的声音音色，很高兴为你提供配音服务。"
UPLOADED_SPEAKER_REF_TEXT_YUE = "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。"
# 兼容旧调用点：默认仍指向普通话参考文案。
UPLOADED_SPEAKER_REF_TEXT = UPLOADED_SPEAKER_REF_TEXT_ZH
REMOTE_GENERATE_TIMEOUT_SEC = 3600
OMNIVOICE_STUDIO_DIR = (REPO_ROOT / "OmniVoice-Studio-main").resolve()
OMNIVOICE_BACKEND_MAIN = OMNIVOICE_STUDIO_DIR / "backend" / "main.py"
OMNIVOICE_BACKEND_PYTHON = OMNIVOICE_STUDIO_DIR / ".venv" / "bin" / "python"
OMNIVOICE_BACKEND_PID_FILE = REPO_ROOT / "outputs" / "omnivoice_backend.pid"
OMNIVOICE_BACKEND_LOG_PATH = REPO_ROOT / "outputs" / "omnivoice_backend.log"
OMNIVOICE_LOCAL_CHECKPOINT_DIR = Path("/Users/tim/Documents/vibe-coding/MVP/OmniVoice/omnivoice/checkpoints")
REF_VOICES_ROOT = REPO_ROOT / "ref-voices"
LOCAL_VOICE_GENDER_MODEL_DIR = REPO_ROOT / "norwood-maleVSfemale"
_omnivoice_backend_start_lock = threading.Lock()
_voice_gender_classifier_lock = threading.Lock()
_voice_gender_classifier = None
OMNIVOICE_FINAL_SRT_MAX_CHARS = 25
_OMNIVOICE_STRONG_BREAK_RE = re.compile(r'([。！？!?]+["\')\]]*)')
_OMNIVOICE_SOFT_BREAK_RE = re.compile(r"([，,；;：:、…]+)")
OMNIVOICE_SYNTH_MIN_CPS = 0.8
OMNIVOICE_SYNTH_MAX_CPS = 20.0
OMNIVOICE_SYNTH_PAIR_MAX_GAP_SEC = 0.8
OMNIVOICE_SYNTH_MIN_SEG_SEC = 0.25
OMNIVOICE_SELECTED_MAX_SEG_SEC = 12.0
OMNIVOICE_SELECTED_SPLIT_MAX_CHARS = 60
OMNIVOICE_SELECTED_MAX_CPS = 10.0
OMNIVOICE_SELECTED_MIN_SEG_SEC = 0.25
_OMNIVOICE_TARGET_CPS: Dict[str, float] = {
    "zh": 6.0, "yue": 6.0, "ja": 10.0, "ko": 10.0,
    "en": 15.0, "de": 14.0, "fr": 15.0, "es": 15.5, "it": 15.0, "pt": 15.0,
}
_OMNIVOICE_TTS_SPEED_MIN = 0.8
_OMNIVOICE_ULTRA_SHORT_CHARS = 4
_OMNIVOICE_ULTRA_SHORT_SEC = 0.3
_OMNIVOICE_SILENCE_SAMPLE_RATE = 24000
_OMNIVOICE_TTS_SPEED_MAX = 1.4
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_THRESHOLD_SEC = 90.0 * 60.0
# 长视频分段预分离默认切成 40 分钟一块，降低 Demucs 调度和音频拆分开销。
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC = 40.0 * 60.0
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MIN_CHUNK_SEC = 30.0 * 60.0
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MAX_CHUNK_SEC = 50.0 * 60.0
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_SEARCH_WINDOW_SEC = 3.0 * 60.0
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_SILENCE_THRESHOLD_DB = -34.0
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MIN_SILENCE_SEC = 0.35
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_FRAME_SEC = 0.20
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_HOP_SEC = 0.05
OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_BOUNDARY_SNAP_SEC = 1.0
VOICE_GENDER_MALE_MARKERS = ("male", "man", "boy", "男", "nan")
VOICE_GENDER_FEMALE_MARKERS = ("female", "woman", "girl", "女", "nv")


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


def _is_cantonese_language_variant(language: str) -> bool:
    """判断语言值是否属于粤语同义写法。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    markers = ("cantonese", "cantonese-mainland", "mainland cantonese", "yue", "粤语", "廣東話", "广东话")
    return any(marker in lowered for marker in markers)


def _is_mainland_cantonese_language_variant(language: str) -> bool:
    """判断语言值是否属于“广东式口语”这一档。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "cantonese-mainland",
        "mainland cantonese",
        "mainland-cantonese",
        "广东式粤语",
        "廣東式粵語",
        "繁体粤语",
        "繁體粵語",
        "简体粤语",
        "簡體粵語",
    )
    return any(marker in lowered for marker in markers)


def _normalize_omnivoice_language_pair(language: str, *, default: str = "") -> Tuple[str, str]:
    """把 5 号面板语言值统一成“展示值 + 运行值”。"""

    raw = str(language or "").strip()
    if not raw:
        return default, default
    lowered = raw.lower()
    if lowered == "auto":
        return "auto", "auto"
    if _is_mainland_cantonese_language_variant(raw):
        return "Cantonese-Mainland", "yue"
    if _is_cantonese_language_variant(raw):
        return "Cantonese", "yue"
    if lowered in {"chinese", "mandarin", "zh", "中文", "漢語", "汉语", "普通话", "普通話"}:
        return "Chinese", "zh"
    return raw, raw


def _speaker_ref_text_for_target_lang(target_lang: str) -> str:
    """按目标语种选择上传参考音默认文案。"""

    return UPLOADED_SPEAKER_REF_TEXT_YUE if _is_cantonese_language_variant(target_lang) else UPLOADED_SPEAKER_REF_TEXT_ZH


def _resolve_omnivoice_ref_voice_candidates(target_lang: str) -> List[str]:
    """生成参考音目录的候选名，优先保留用户输入，再补展示值和运行值。"""

    display_lang, runtime_lang = _normalize_omnivoice_language_pair(target_lang, default="Chinese")
    candidates: List[str] = []
    for candidate in (str(target_lang or "").strip(), display_lang, runtime_lang):
        normalized = str(candidate or "").strip()
        if normalized and normalized.lower() not in {item.lower() for item in candidates}:
            candidates.append(normalized)
    if display_lang == "Cantonese-Mainland" and "Cantonese" not in candidates:
        candidates.append("Cantonese")
    return candidates


def _ensure_speaker_ids(
    rows: List[Dict[str, Any]],
    fallback_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    force_align_by_time: bool = False,
) -> List[Dict[str, Any]]:
    """补齐或按时间校正 speaker_id，避免 OmniVoice 路由时 speaker 错位。"""

    def _build_fallback_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把 fallback rows 规整成可按时间匹配 speaker 的候选集。"""

        candidates: List[Dict[str, Any]] = []
        for item in items:
            speaker_id = str(item.get("speaker_id") or "").strip()
            if not speaker_id:
                continue
            start_sec = float(item.get("start", 0.0) or 0.0)
            end_sec = float(item.get("end", 0.0) or 0.0)
            if end_sec <= start_sec:
                continue
            candidates.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "speaker_id": speaker_id,
                    "center": (start_sec + end_sec) / 2.0,
                }
            )
        candidates.sort(key=lambda item: (item["start"], item["end"]))
        return candidates

    def _pick_speaker_id_by_time(
        row: Dict[str, Any],
        *,
        candidates: List[Dict[str, Any]],
        index: int,
        index_fallback: List[Dict[str, Any]],
    ) -> str:
        """优先按时间重叠挑 speaker，兜底才按索引。"""

        if not candidates:
            return ""

        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        center_sec = (start_sec + end_sec) / 2.0 if end_sec > start_sec else start_sec
        best_overlap = 0.0
        best_distance = float("inf")
        best_speaker = ""

        for candidate in candidates:
            overlap = max(0.0, min(end_sec, candidate["end"]) - max(start_sec, candidate["start"]))
            if overlap <= 0.0:
                continue
            distance = abs(center_sec - float(candidate["center"]))
            if overlap > best_overlap + 1e-9:
                best_overlap = overlap
                best_distance = distance
                best_speaker = str(candidate["speaker_id"])
                continue
            if abs(overlap - best_overlap) <= 1e-9 and distance < best_distance:
                best_distance = distance
                best_speaker = str(candidate["speaker_id"])

        if best_speaker:
            return best_speaker

        nearest: Optional[Dict[str, Any]] = None
        nearest_distance = float("inf")
        for candidate in candidates:
            distance = abs(center_sec - float(candidate["center"]))
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = candidate
        if nearest is not None:
            return str(nearest.get("speaker_id") or "")

        if index < len(index_fallback):
            return str(index_fallback[index].get("speaker_id") or "").strip()
        return ""

    normalized: List[Dict[str, Any]] = []
    fallback_rows = fallback_rows or []
    fallback_candidates = _build_fallback_candidates(fallback_rows)
    for index, row in enumerate(rows):
        speaker_id = str(row.get("speaker_id") or "").strip()
        if force_align_by_time or not speaker_id:
            speaker_id = _pick_speaker_id_by_time(
                row,
                candidates=fallback_candidates,
                index=index,
                index_fallback=fallback_rows,
            )
        if not speaker_id and normalized:
            speaker_id = str(normalized[-1].get("speaker_id") or "").strip()
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


def _resolve_ref_voices_dir(target_lang: str) -> Optional[Path]:
    """按目标语种解析预存参考音目录（ref-voices/<target_lang>/）。"""

    candidates = _resolve_omnivoice_ref_voice_candidates(target_lang)
    if not candidates:
        return None
    if not REF_VOICES_ROOT.exists():
        return None
    for lang in candidates:
        direct = (REF_VOICES_ROOT / lang).resolve()
        if direct.exists() and direct.is_dir():
            return direct
    lowered_candidates = {lang.lower() for lang in candidates}
    for child in REF_VOICES_ROOT.iterdir():
        if child.is_dir() and child.name.lower() in lowered_candidates:
            return child.resolve()
    return None


def _list_preset_ref_voice_audio_files(
    *,
    base_dir: Path,
    excluded_source_filenames: Optional[List[str]] = None,
) -> List[Path]:
    """列出目录下可用的预置参考音文件。"""

    audio_exts = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    excluded_name_set = {
        Path(str(name or "").strip()).name.lower()
        for name in (excluded_source_filenames or [])
        if str(name or "").strip()
    }
    return [
        path
        for path in sorted(base_dir.rglob("*"), key=lambda p: str(p).lower())
        if path.is_file()
        and path.suffix.lower() in audio_exts
        and path.name.lower() not in excluded_name_set
    ]


def _validate_preset_ref_voices_available(
    *,
    target_lang: str,
    missing_speaker_ids: List[str],
    excluded_source_filenames: Optional[List[str]] = None,
) -> None:
    """在任务启动前校验预置参考音池是否足够，避免后台跑到中途才失败。"""

    if not missing_speaker_ids:
        return

    ref_dir = _resolve_ref_voices_dir(target_lang)
    if ref_dir is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Missing preset reference voices dir for {target_lang}. "
                f"Expected under {REF_VOICES_ROOT}. Upload all missing speaker references or add preset voices first."
            ),
        )

    candidates = _list_preset_ref_voice_audio_files(
        base_dir=ref_dir,
        excluded_source_filenames=excluded_source_filenames,
    )
    if candidates:
        return

    raise HTTPException(
        status_code=400,
        detail=(
            f"Preset reference voices dir is empty for {target_lang}: {ref_dir}. "
            "Upload all missing speaker references or add usable preset voices first."
        ),
    )


def _pick_preset_ref_voices_for_missing_speakers(
    *,
    missing_speaker_ids: List[str],
    target_lang: str,
    out_root: Path,
    speaker_gender_hints: Optional[Dict[str, str]] = None,
    excluded_source_filenames: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """为缺失 speaker 从 ref-voices/<target_lang>/ 挑选参考音并落盘到任务目录。"""

    if not missing_speaker_ids:
        return {}

    ref_dir = _resolve_ref_voices_dir(target_lang)
    if ref_dir is None:
        raise RuntimeError(
            f"Missing preset reference voices dir: {REF_VOICES_ROOT}/{target_lang}. "
            "Please create it or upload all speaker references."
        )

    speaker_gender_hints = dict(speaker_gender_hints or {})
    gender_pools: Dict[str, List[Path]] = {"male": [], "female": []}
    for gender in ("male", "female"):
        gender_dir = ref_dir / gender
        if gender_dir.exists() and gender_dir.is_dir():
            gender_pools[gender] = _list_preset_ref_voice_audio_files(
                base_dir=gender_dir,
                excluded_source_filenames=excluded_source_filenames,
            )
            random.shuffle(gender_pools[gender])
    gender_pool_cursor = {"male": 0, "female": 0}

    generic_candidates = _list_preset_ref_voice_audio_files(
        base_dir=ref_dir,
        excluded_source_filenames=excluded_source_filenames,
    )
    if not generic_candidates:
        raise RuntimeError(
            f"No usable preset reference voices under {ref_dir}. "
            "Please add audio files or upload missing speaker references."
        )
    random.shuffle(generic_candidates)

    target_dir = out_root / "uploaded_speaker_refs"
    target_dir.mkdir(parents=True, exist_ok=True)

    preset_map: Dict[str, Dict[str, Any]] = {}
    for index, speaker_id in enumerate(missing_speaker_ids):
        preferred_gender = str(speaker_gender_hints.get(speaker_id) or "").strip().lower()
        source_path: Path
        if preferred_gender in {"male", "female"} and gender_pools[preferred_gender]:
            pool = gender_pools[preferred_gender]
            cursor = gender_pool_cursor[preferred_gender]
            source_path = pool[cursor % len(pool)]
            gender_pool_cursor[preferred_gender] = cursor + 1
        elif preferred_gender in {"male", "female"}:
            raise RuntimeError(
                f"No usable preset reference voices under {ref_dir / preferred_gender} "
                f"for speaker {speaker_id}. Please add matching preset voices or upload a reference."
            )
        else:
            source_path = generic_candidates[index % len(generic_candidates)]
        safe_name = _sanitize_filename(speaker_id) or f"speaker_{index+1}"
        copied_path = (target_dir / f"preset_{safe_name}{source_path.suffix.lower()}").resolve()
        shutil.copy2(source_path, copied_path)
        duration_sec = 0.0
        try:
            duration_sec = round(float(sf.info(copied_path).duration), 3)
        except Exception:
            duration_sec = 0.0
        preset_map[speaker_id] = {
            "ref_audio": str(copied_path),
            "ref_text": _speaker_ref_text_for_target_lang(target_lang),
            "duration": duration_sec,
            "source_count": 1,
            "reference_mode": "preset_pool",
            "source_path": str(source_path.resolve()),
            "gender_hint": preferred_gender if preferred_gender in {"male", "female"} else "",
        }
    return preset_map


def _infer_gender_from_text_hint(raw: str) -> Optional[str]:
    """从目录名/文件名里的标记词推断男声或女声。"""

    text = str(raw or "").strip().lower()
    if not text:
        return None
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", text)
    tokens = [token for token in normalized.split(" ") if token]
    # 先判 female，避免 "female" 被 "male" 子串误命中。
    for marker in VOICE_GENDER_FEMALE_MARKERS:
        marker_text = str(marker).strip().lower()
        if marker_text and marker_text in tokens:
            return "female"
    for marker in VOICE_GENDER_MALE_MARKERS:
        marker_text = str(marker).strip().lower()
        if marker_text and marker_text in tokens:
            return "male"
    return None


def _get_local_voice_gender_classifier():
    """懒加载本地男/女声分类器，避免启动阶段额外加载大模型。"""

    global _voice_gender_classifier
    if _voice_gender_classifier is not None:
        return _voice_gender_classifier
    with _voice_gender_classifier_lock:
        if _voice_gender_classifier is not None:
            return _voice_gender_classifier
        if not LOCAL_VOICE_GENDER_MODEL_DIR.exists():
            return None
        from transformers import pipeline

        _voice_gender_classifier = pipeline(
            "audio-classification",
            model=str(LOCAL_VOICE_GENDER_MODEL_DIR.resolve()),
        )
        return _voice_gender_classifier


def _classify_voice_gender_with_local_model(audio_path: Path) -> Optional[str]:
    """使用本地男/女声分类模型对单个参考音做判别。"""

    classifier = _get_local_voice_gender_classifier()
    if classifier is None:
        return None
    try:
        result = classifier(str(Path(audio_path).expanduser()))
    except Exception as exc:
        logger.warning("Local voice gender classification failed for %s: %s", audio_path, exc)
        return None
    if not isinstance(result, list) or not result:
        return None
    top = result[0]
    if isinstance(top, dict):
        raw_label = top.get("label")
    else:
        raw_label = top
    label = _infer_gender_from_text_hint(str(raw_label or ""))
    if label in {"male", "female"}:
        return label
    raw = str(raw_label or "").strip().lower()
    if raw.startswith("male"):
        return "male"
    if raw.startswith("female"):
        return "female"
    return None


def _estimate_voice_pitch_hz(audio: np.ndarray, sample_rate: int) -> Optional[float]:
    """用自相关法估算主频，作为男女声粗分依据。"""

    if sample_rate <= 0:
        return None
    wav = np.asarray(audio, dtype=np.float32).flatten()
    if wav.size < int(sample_rate * 0.3):
        return None
    max_samples = int(sample_rate * 8.0)
    wav = wav[:max_samples]
    wav = wav - float(np.mean(wav))
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak <= 1e-6:
        return None
    wav = wav / peak

    frame_len = max(256, int(0.04 * sample_rate))
    hop_len = max(128, int(0.01 * sample_rate))
    min_lag = max(1, int(sample_rate / 300.0))
    max_lag = max(min_lag + 1, int(sample_rate / 80.0))
    if frame_len <= max_lag + 2:
        return None

    starts = range(0, max(1, wav.size - frame_len + 1), hop_len)
    energies: List[float] = []
    frames: List[np.ndarray] = []
    for start in starts:
        frame = wav[start : start + frame_len]
        if frame.size < frame_len:
            continue
        frames.append(frame)
        energies.append(float(np.mean(frame * frame)))
    if not energies:
        return None

    energy_threshold = max(1e-6, float(np.percentile(np.asarray(energies, dtype=np.float32), 45)))
    f0_values: List[float] = []
    for frame, energy in zip(frames, energies):
        if energy < energy_threshold:
            continue
        centered = frame - float(np.mean(frame))
        corr = np.correlate(centered, centered, mode="full")[frame_len - 1 :]
        if corr.size <= max_lag or corr[0] <= 0:
            continue
        search = corr[min_lag : max_lag + 1]
        if search.size == 0:
            continue
        peak_idx = int(np.argmax(search))
        peak_lag = min_lag + peak_idx
        peak_score = float(search[peak_idx]) / float(corr[0])
        if peak_score < 0.18:
            continue
        f0 = float(sample_rate) / float(peak_lag)
        if 80.0 <= f0 <= 300.0:
            f0_values.append(f0)

    if len(f0_values) < 4:
        return None
    return float(np.median(np.asarray(f0_values, dtype=np.float32)))


def _infer_voice_gender_label(audio_path: Path, *, use_path_hint: bool = True) -> Optional[str]:
    """识别音频男/女声；可选是否信任目录/文件名提示。"""

    path = Path(audio_path).expanduser()
    if use_path_hint:
        hint_text = " ".join(part.lower() for part in path.parts[-4:]) + " " + path.name.lower()
        hint_label = _infer_gender_from_text_hint(hint_text)
        if hint_label in {"male", "female"}:
            return hint_label
    local_model_label = _classify_voice_gender_with_local_model(path)
    if local_model_label in {"male", "female"}:
        return local_model_label

    try:
        wav, sample_rate = load_mono_audio(path)
    except Exception:
        return None
    pitch_hz = _estimate_voice_pitch_hz(wav, int(sample_rate))
    if pitch_hz is None:
        return None
    if pitch_hz <= 155.0:
        return "male"
    if pitch_hz >= 185.0:
        return "female"
    return None


def _target_prefers_cjk_text(target_lang: str) -> bool:
    """判断目标语言是否应优先输出中文文本。"""

    lowered = str(target_lang or "").strip().lower()
    if not lowered:
        return False
    markers = ("chinese", "mandarin", "cantonese", "yue", "zh", "中文", "汉语", "漢語", "普通话", "普通話", "粤语", "廣東話", "广东话")
    return any(marker in lowered for marker in markers)


def _should_passthrough_source_rows_without_translation(
    *,
    source_rows: List[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
) -> bool:
    """判断 5 号面板 source 字幕是否应直接复用，避免明确同语种时重复计费翻译。"""

    source_tag = normalize_language_tag_for_passthrough(source_lang)
    target_tag = normalize_language_tag_for_passthrough(target_lang)
    if source_tag and target_tag and source_tag not in {"", "auto"} and source_tag == target_tag:
        return True
    if target_tag != "zh":
        return False
    if source_tag not in {"", "auto"}:
        return False
    sample_text = "".join(str(row.get("text") or "").strip() for row in list(source_rows or [])[:12])
    cjk_count = sum(1 for char in sample_text if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in sample_text if ("a" <= char <= "z") or ("A" <= char <= "Z"))
    return cjk_count > 0 and cjk_count >= max(4, latin_count * 2)


def _sanitize_translated_rows_for_target(
    rows: List[Dict[str, Any]],
    *,
    target_lang: str,
) -> List[Dict[str, Any]]:
    """清洗已存在的译文字幕。

    5 号面板这里不再调用共享 sanitize_translation_text(...)：
    用户已确认正常粤语正文会被这层误裁，所以当前只做最小 trim，
    再按目标语种执行可逆的口语化/字形规整。
    """

    sanitized_rows: List[Dict[str, Any]] = []
    for row in list(rows or []):
        sanitized_text = str(row.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not sanitized_text:
            continue
        if _is_cantonese_language_variant(target_lang):
            sanitized_text = normalize_cantonese_translation_text(sanitized_text, target_lang)
        sanitized_rows.append(
            {
                **row,
                "text": sanitized_text,
            }
        )
    return sanitized_rows


def _is_latin_dominant_text(text: str) -> bool:
    """判定文本是否英文主导（用于发现漏译行）。"""

    raw = str(text or "").strip()
    if not raw:
        return False
    latin_count = len(re.findall(r"[A-Za-z]", raw))
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", raw))
    if latin_count < 8:
        return False
    return cjk_count == 0 or latin_count > cjk_count * 2


def _normalize_omnivoice_selected_text(text: str) -> str:
    """清洗 5 号链路字幕文本，修正中英粘连与大小写连写。"""

    normalized = _normalize_final_srt_text(text)
    if not normalized:
        return ""

    if re.search(r"[A-Za-z]", normalized):
        # 先拆 PascalCase / camelCase：ClaudeCode -> Claude Code
        normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", normalized)
        normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", normalized)

    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized))
    has_latin_or_digit = bool(re.search(r"[A-Za-z0-9]", normalized))
    if has_cjk and has_latin_or_digit:
        # 中英文或数字直接贴在一起时补空格：AI时代 -> AI 时代
        normalized = re.sub(r"([A-Za-z0-9])([\u4e00-\u9fff])", r"\1 \2", normalized)
        normalized = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9])", r"\1 \2", normalized)

    normalized = re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _merge_two_subtitle_rows(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """合并两条相邻字幕。"""

    cjk_mode = infer_cjk_mode_from_lines([str(left.get("text") or ""), str(right.get("text") or "")])
    merged_text = _normalize_final_srt_text(
        subtitle_group_text(
            [
                {"text": str(left.get("text") or "").strip()},
                {"text": str(right.get("text") or "").strip()},
            ],
            cjk_mode=cjk_mode,
        )
    )
    speaker_id = str(left.get("speaker_id") or "").strip() or str(right.get("speaker_id") or "").strip()
    return {
        "start": float(left.get("start", 0.0) or 0.0),
        "end": float(right.get("end", 0.0) or 0.0),
        "text": merged_text,
        "speaker_id": speaker_id,
    }


def _smooth_selected_rows_for_cps(
    rows: List[Dict[str, Any]],
    *,
    max_cps: float = OMNIVOICE_SELECTED_MAX_CPS,
    min_seg_sec: float = OMNIVOICE_SELECTED_MIN_SEG_SEC,
) -> List[Dict[str, Any]]:
    """仅在 5 号 selected 链路压制高 CPS：先并短碎行，再按 CPS 分段。"""

    if not rows:
        return []

    merged_rows: List[Dict[str, Any]] = []
    index = 0
    while index < len(rows):
        current = dict(rows[index])
        if index + 1 >= len(rows):
            merged_rows.append(current)
            break
        nxt = dict(rows[index + 1])
        gap_sec = float(nxt["start"]) - float(current["end"])
        same_speaker = str(current.get("speaker_id") or "").strip() == str(nxt.get("speaker_id") or "").strip()
        current_duration = max(0.0, float(current["end"]) - float(current["start"]))
        current_text = str(current.get("text") or "").strip()
        cjk_mode = infer_cjk_mode_from_lines([current_text, str(nxt.get("text") or "")])
        current_units = max(1, subtitle_text_units(current_text, cjk_mode=cjk_mode))
        current_cps = current_units / max(0.05, current_duration)
        should_merge = (
            same_speaker
            and gap_sec <= 0.25
            and current_duration < 0.7
            and current_cps > max_cps
        )
        if should_merge:
            merged_rows.append(_merge_two_subtitle_rows(current, nxt))
            index += 2
            continue
        merged_rows.append(current)
        index += 1

    output: List[Dict[str, Any]] = []
    for row in merged_rows:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        duration_sec = max(0.0, end_sec - start_sec)
        text = _normalize_final_srt_text(str(row.get("text") or ""))
        speaker_id = str(row.get("speaker_id") or "").strip()
        if not text or duration_sec <= 0.0:
            continue
        cjk_mode = infer_cjk_mode_from_lines([text])
        units = max(1, subtitle_text_units(text, cjk_mode=cjk_mode))
        cps = units / max(0.05, duration_sec)
        if cps <= max_cps:
            output.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue

        desired_parts = max(2, int(np.ceil(cps / max_cps)))
        max_parts_by_duration = max(1, int(np.floor(duration_sec / max(min_seg_sec, 0.01))))
        part_count = min(desired_parts, max_parts_by_duration)
        if part_count <= 1:
            output.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue

        segments = _split_long_final_segment(
            text,
            max_chars=max(6, int(np.ceil(len(text) / part_count))),
        )
        if len(segments) <= 1:
            output.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue
        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(spans) != len(segments):
            output.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue
        for (seg_start, seg_end), seg_text in zip(spans, segments):
            cleaned = str(seg_text or "").strip()
            if not cleaned or seg_end <= seg_start:
                continue
            output.append(
                {
                    "start": float(seg_start),
                    "end": float(seg_end),
                    "text": cleaned,
                    "speaker_id": speaker_id,
                }
            )
    return _merge_selected_fragment_rows(output)


def _is_selected_fragment_row(row: Dict[str, Any]) -> bool:
    """判断一条字幕是否像残句碎片，便于最后做轻量回并。"""

    text = _normalize_omnivoice_selected_text(str(row.get("text") or ""))
    if not text:
        return True
    duration_sec = max(0.0, float(row.get("end", 0.0) or 0.0) - float(row.get("start", 0.0) or 0.0))
    compact_len = len(re.sub(r"\s+", "", text))
    if duration_sec <= 0.4:
        return True
    if compact_len <= 8 and not is_sentence_end(text):
        return True
    if not is_sentence_end(text) and (ends_with_connector(text) or starts_with_connector(text)):
        return True
    return False


def _merge_selected_fragment_rows(
    rows: List[Dict[str, Any]],
    *,
    max_gap_sec: float = 0.35,
) -> List[Dict[str, Any]]:
    """把同 speaker 的短残句回并，减少“半句断裂”字幕。"""

    if len(rows) <= 1:
        return [dict(item) for item in rows]

    merged: List[Dict[str, Any]] = []
    for raw_row in rows:
        current = {
            "start": float(raw_row.get("start", 0.0) or 0.0),
            "end": float(raw_row.get("end", 0.0) or 0.0),
            "text": _normalize_omnivoice_selected_text(str(raw_row.get("text") or "")),
            "speaker_id": str(raw_row.get("speaker_id") or "").strip(),
        }
        if not current["text"] or current["end"] <= current["start"]:
            continue

        if not merged:
            merged.append(current)
            continue

        prev = merged[-1]
        same_speaker = str(prev.get("speaker_id") or "").strip() == str(current.get("speaker_id") or "").strip()
        gap_sec = float(current["start"]) - float(prev["end"])
        if not same_speaker or gap_sec > max_gap_sec:
            merged.append(current)
            continue

        merged_duration = float(current["end"]) - float(prev["start"])
        should_merge = (
            _is_selected_fragment_row(prev)
            or _is_selected_fragment_row(current)
            or ends_with_connector(str(prev.get("text") or ""))
            or starts_with_connector(str(current.get("text") or ""))
        )
        if should_merge and merged_duration <= (OMNIVOICE_SELECTED_MAX_SEG_SEC + 0.5):
            merged[-1] = _merge_two_subtitle_rows(prev, current)
            merged[-1]["text"] = _normalize_omnivoice_selected_text(str(merged[-1].get("text") or ""))
            continue
        merged.append(current)
    return merged


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


def _should_keep_omnivoice_source_cue_boundaries(subtitle_mode: str) -> bool:
    """判断 5 号面板当前是否应优先保留原始 cue 边界。"""

    normalized_mode = str(subtitle_mode or "").strip().lower()
    return normalized_mode in {"", "auto", "source"}


def _normalize_omnivoice_passthrough_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """规整 5 号面板 source 直通字幕，只做清洗和超长单条切分，不跨 cue 合并。"""

    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        if end_sec <= start_sec:
            continue
        text = _normalize_omnivoice_selected_text(str(row.get("text") or ""))
        if not text:
            continue
        speaker_id = str(row.get("speaker_id") or "").strip()
        duration_sec = end_sec - start_sec
        if duration_sec <= OMNIVOICE_SELECTED_MAX_SEG_SEC:
            normalized_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue

        # 只在单条 cue 本身已经过长时，才在其内部做时间均分切分，避免再次跨条吞字。
        segments = _wrap_final_srt_text_segments(
            text,
            max_chars=OMNIVOICE_SELECTED_SPLIT_MAX_CHARS,
        )
        if len(segments) <= 1:
            normalized_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue

        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(spans) != len(segments):
            normalized_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue

        for (split_start, split_end), split_text in zip(spans, segments):
            cleaned = str(split_text or "").strip()
            if not cleaned or split_end <= split_start:
                continue
            normalized_rows.append(
                {
                    "start": float(split_start),
                    "end": float(split_end),
                    "text": cleaned,
                    "speaker_id": speaker_id,
                }
            )
    return normalized_rows


def _optimize_omnivoice_source_rows(
    source_rows: List[Dict[str, Any]],
    *,
    subtitle_mode: str = "auto",
) -> List[Dict[str, Any]]:
    """仅在 5 号 OmniVoice source 字幕链路做导入优化，避免影响其他入口。"""

    if not source_rows:
        return []
    if _should_keep_omnivoice_source_cue_boundaries(subtitle_mode):
        passthrough_rows = _normalize_omnivoice_passthrough_rows(source_rows)
        return _ensure_speaker_ids(passthrough_rows, fallback_rows=source_rows)
    optimized = optimize_srt_import_subtitles(
        source_rows,
        speaker_mode="auto",
        enforce_merge_duration_guard=True,
    )
    return _ensure_speaker_ids(optimized, fallback_rows=source_rows)


def _optimize_omnivoice_selected_rows(
    selected_rows: List[Dict[str, Any]],
    *,
    subtitle_mode: str = "translated",
) -> List[Dict[str, Any]]:
    """仅在 5 号 OmniVoice 最终选中字链路做防长时窗优化，不影响其他面板。

    约束：
    - 这里强制按 multi-speaker 规则执行句块优化，避免 auto 在 speaker 缺失/错填时退化成 single，
      进而吞掉 speaker 边界，导致后续配音映射错位。
    """

    if not selected_rows:
        return []
    if _should_keep_omnivoice_source_cue_boundaries(subtitle_mode):
        passthrough_rows = _normalize_omnivoice_passthrough_rows(selected_rows)
        return _ensure_speaker_ids(
            passthrough_rows,
            fallback_rows=selected_rows,
            force_align_by_time=True,
        )
    normalized_input_rows: List[Dict[str, Any]] = []
    for row in selected_rows:
        normalized_input_rows.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": _normalize_omnivoice_selected_text(str(row.get("text") or "")),
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
        )
    expanded_rows: List[Dict[str, Any]] = []
    for row in normalized_input_rows:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        duration_sec = max(0.0, end_sec - start_sec)
        if duration_sec <= OMNIVOICE_SELECTED_MAX_SEG_SEC:
            expanded_rows.append(dict(row))
            continue
        normalized_text = _normalize_final_srt_text(str(row.get("text") or ""))
        if not normalized_text:
            expanded_rows.append(dict(row))
            continue
        segments = _wrap_final_srt_text_segments(
            normalized_text,
            max_chars=OMNIVOICE_SELECTED_SPLIT_MAX_CHARS,
        )
        if len(segments) <= 1:
            expanded_rows.append(dict(row))
            continue
        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(spans) != len(segments):
            expanded_rows.append(dict(row))
            continue
        for (split_start, split_end), split_text in zip(spans, segments):
            if not split_text or split_end <= split_start:
                continue
            expanded_rows.append(
                {
                    "start": split_start,
                    "end": split_end,
                    "text": split_text,
                    "speaker_id": str(row.get("speaker_id") or "").strip(),
                }
            )
    optimized = optimize_srt_import_subtitles(
        expanded_rows,
        speaker_mode="multi",
        enforce_merge_duration_guard=True,
    )
    optimized = _ensure_speaker_ids(
        optimized,
        fallback_rows=expanded_rows,
        force_align_by_time=True,
    )

    final_rows: List[Dict[str, Any]] = []
    for row in optimized:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        duration_sec = max(0.0, end_sec - start_sec)
        text = str(row.get("text") or "").strip()
        speaker_id = str(row.get("speaker_id") or "").strip()
        if not text or duration_sec <= OMNIVOICE_SELECTED_MAX_SEG_SEC:
            if text and end_sec > start_sec:
                final_rows.append(
                    {
                        "start": start_sec,
                        "end": end_sec,
                        "text": text,
                        "speaker_id": speaker_id,
                    }
                )
            continue
        piece_count = max(2, int(np.ceil(duration_sec / OMNIVOICE_SELECTED_MAX_SEG_SEC)))
        segments = _split_long_final_segment(text, max_chars=max(6, int(np.ceil(len(text) / piece_count))))
        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(segments) != len(spans):
            final_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue
        for (seg_start, seg_end), seg_text in zip(spans, segments):
            cleaned = str(seg_text or "").strip()
            if not cleaned or seg_end <= seg_start:
                continue
            final_rows.append(
                {
                    "start": float(seg_start),
                    "end": float(seg_end),
                    "text": cleaned,
                    "speaker_id": speaker_id,
                }
            )

    repaired_rows = [dict(item) for item in final_rows]
    for index in range(len(repaired_rows) - 1):
        current = repaired_rows[index]
        nxt = repaired_rows[index + 1]
        if str(current.get("speaker_id") or "").strip() != str(nxt.get("speaker_id") or "").strip():
            continue
        gap_sec = float(nxt["start"]) - float(current["end"])
        if gap_sec > 0.3:
            continue
        current_duration = max(0.05, float(current["end"]) - float(current["start"]))
        if current_duration <= OMNIVOICE_SELECTED_MAX_SEG_SEC:
            continue
        current_text = str(current.get("text") or "").strip()
        next_text = str(nxt.get("text") or "").strip()
        if not current_text or not next_text:
            continue
        cjk_mode = infer_cjk_mode_from_lines([current_text, next_text])
        current_units = max(1, subtitle_text_units(current_text, cjk_mode=cjk_mode))
        next_units = max(1, subtitle_text_units(next_text, cjk_mode=cjk_mode))
        if current_units > 2:
            continue
        window_start = float(current["start"])
        window_end = float(nxt["end"])
        total_duration = max(0.1, window_end - window_start)
        target_current = total_duration * (current_units / float(current_units + next_units))
        target_current = max(0.25, min(2.0, target_current))
        target_current = min(target_current, total_duration - 0.25)
        current["end"] = round(window_start + target_current, 3)
        nxt["start"] = current["end"]
        nxt["end"] = round(window_end, 3)

    capped_rows: List[Dict[str, Any]] = []
    for row in repaired_rows:
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        duration_sec = max(0.0, end_sec - start_sec)
        text = str(row.get("text") or "").strip()
        speaker_id = str(row.get("speaker_id") or "").strip()
        if not text or end_sec <= start_sec:
            continue
        if duration_sec <= OMNIVOICE_SELECTED_MAX_SEG_SEC:
            capped_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue
        piece_count = max(2, int(np.ceil(duration_sec / OMNIVOICE_SELECTED_MAX_SEG_SEC)))
        segments = _split_long_final_segment(
            text,
            max_chars=max(6, int(np.ceil(len(text) / piece_count))),
        )
        if len(segments) <= 1:
            midpoint = max(1, len(text) // 2)
            segments = [text[:midpoint].strip(), text[midpoint:].strip()]
            segments = [segment for segment in segments if segment]
        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(spans) != len(segments):
            capped_rows.append(
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": text,
                    "speaker_id": speaker_id,
                }
            )
            continue
        for (seg_start, seg_end), seg_text in zip(spans, segments):
            cleaned = str(seg_text or "").strip()
            if not cleaned or seg_end <= seg_start:
                continue
            capped_rows.append(
                {
                    "start": float(seg_start),
                    "end": float(seg_end),
                    "text": cleaned,
                    "speaker_id": speaker_id,
                }
            )

    return _smooth_selected_rows_for_cps(capped_rows)


def _rebalance_omnivoice_synthesis_rows(
    rows: List[Dict[str, Any]],
    *,
    min_cps: float = OMNIVOICE_SYNTH_MIN_CPS,
    max_cps: float = OMNIVOICE_SYNTH_MAX_CPS,
    max_pair_gap_sec: float = OMNIVOICE_SYNTH_PAIR_MAX_GAP_SEC,
    min_seg_sec: float = OMNIVOICE_SYNTH_MIN_SEG_SEC,
) -> Tuple[List[Dict[str, Any]], int]:
    """在合成前修正极端“文本-时长失配”的相邻字幕对，减少无效长音/截断。"""

    if len(rows) <= 1:
        return [dict(item) for item in rows], 0

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": str(row.get("text") or "").strip(),
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
        )

    adjusted_pairs = 0
    for index in range(len(normalized) - 1):
        current = normalized[index]
        nxt = normalized[index + 1]
        if not current["text"] or not nxt["text"]:
            continue
        if current["speaker_id"] != nxt["speaker_id"]:
            continue

        gap = float(nxt["start"]) - float(current["end"])
        if gap > max_pair_gap_sec:
            continue

        current_duration = max(0.05, float(current["end"]) - float(current["start"]))
        next_duration = max(0.05, float(nxt["end"]) - float(nxt["start"]))
        cjk_mode = infer_cjk_mode_from_lines([current["text"], nxt["text"]])
        current_units = max(1, subtitle_text_units(current["text"], cjk_mode=cjk_mode))
        next_units = max(1, subtitle_text_units(nxt["text"], cjk_mode=cjk_mode))
        current_cps = current_units / current_duration
        next_cps = next_units / next_duration

        is_extreme_pair = (
            (current_cps < min_cps and next_cps > max_cps)
            or (current_cps > max_cps and next_cps < min_cps)
        )
        if not is_extreme_pair:
            continue

        window_start = float(current["start"])
        window_end = max(float(current["end"]), float(nxt["end"]))
        total_duration = window_end - window_start
        if total_duration < min_seg_sec * 2:
            continue

        total_units = current_units + next_units
        target_current = total_duration * (current_units / float(total_units))
        target_current = max(min_seg_sec, min(total_duration - min_seg_sec, target_current))
        target_next = total_duration - target_current
        if target_next < min_seg_sec:
            continue

        current["start"] = window_start
        current["end"] = round(window_start + target_current, 3)
        nxt["start"] = current["end"]
        nxt["end"] = round(window_end, 3)
        adjusted_pairs += 1

    return normalized, adjusted_pairs


def _equalize_cps_across_neighbors(
    rows: List[Dict[str, Any]],
    *,
    max_cps_ratio: float = 2.0,
    min_seg_sec: float = 0.25,
    max_iterations: int = 3,
) -> Tuple[List[Dict[str, Any]], int]:
    """对同 speaker 相邻行按文本密度重分时间，降低 CPS 方差。"""

    if len(rows) <= 1:
        return [dict(item) for item in rows], 0

    result = [dict(item) for item in rows]
    total_adjusted = 0

    for _ in range(max_iterations):
        adjusted_this_round = 0
        for index in range(len(result) - 1):
            current = result[index]
            nxt = result[index + 1]
            if not current.get("text") or not nxt.get("text"):
                continue
            if str(current.get("speaker_id") or "").strip() != str(nxt.get("speaker_id") or "").strip():
                continue
            gap = float(nxt["start"]) - float(current["end"])
            if gap > 0.8:
                continue

            c_dur = max(0.05, float(current["end"]) - float(current["start"]))
            n_dur = max(0.05, float(nxt["end"]) - float(nxt["start"]))
            cjk_mode = infer_cjk_mode_from_lines(
                [str(current.get("text") or ""), str(nxt.get("text") or "")]
            )
            c_units = max(1, subtitle_text_units(str(current["text"]).strip(), cjk_mode=cjk_mode))
            n_units = max(1, subtitle_text_units(str(nxt["text"]).strip(), cjk_mode=cjk_mode))
            c_cps = c_units / c_dur
            n_cps = n_units / n_dur
            ratio = max(c_cps, n_cps) / max(0.01, min(c_cps, n_cps))
            if ratio < max_cps_ratio:
                continue

            window_start = float(current["start"])
            window_end = max(float(current["end"]), float(nxt["end"]))
            total_dur = window_end - window_start
            if total_dur < min_seg_sec * 2:
                continue
            target_c = total_dur * (c_units / float(c_units + n_units))
            target_c = max(min_seg_sec, min(total_dur - min_seg_sec, target_c))
            current["end"] = round(window_start + target_c, 3)
            nxt["start"] = current["end"]
            nxt["end"] = round(window_end, 3)
            adjusted_this_round += 1

        total_adjusted += adjusted_this_round
        if adjusted_this_round == 0:
            break

    return result, total_adjusted


_TRAD_TO_SIMP_FOR_DEDUP = str.maketrans({
    "後": "后", "車": "车", "過": "过", "從": "从", "會": "会",
    "個": "个", "對": "对", "電": "电", "動": "动", "話": "话",
    "還": "还", "機": "机", "經": "经", "開": "开", "來": "来",
    "門": "门", "們": "们", "認": "认", "時": "时", "書": "书",
    "說": "说", "為": "为", "問": "问", "學": "学", "長": "长",
    "這": "这", "讓": "让", "與": "与", "語": "语", "場": "场",
    "號": "号", "資": "资", "際": "际", "關": "关", "練": "练",
    "單": "单", "選": "选", "題": "题", "間": "间", "頭": "头",
    "覺": "觉", "護": "护", "環": "环", "養": "养", "總": "总",
    "導": "导", "寫": "写", "識": "识", "證": "证", "較": "较",
    "項": "项", "實": "实", "團": "团", "圓": "圆", "壓": "压",
    "願": "愿", "係": "是", "慶": "庆", "廣": "广", "適": "适",
    "發": "发", "異": "异", "當": "当", "盡": "尽", "種": "种",
    "積": "积", "稱": "称", "維": "维", "繼": "继", "聲": "声",
    "興": "兴", "處": "处", "計": "计", "設": "设", "試": "试",
    "調": "调", "論": "论", "買": "买", "轉": "转", "輕": "轻",
    "進": "进", "運": "运", "達": "达", "遠": "远", "邊": "边",
    "鍵": "键", "響": "响", "點": "点",
})


def _deduplicate_translated_rows(
    rows: List[Dict[str, Any]],
    *,
    similarity_threshold: float = 0.65,
    lookback: int = 15,
    min_chars: int = 10,
) -> Tuple[List[Dict[str, Any]], int]:
    """移除 LLM 翻译产生的近似重复行（如繁简重复翻译）。绝不跨 speaker 去重。"""

    if len(rows) <= 1:
        return list(rows), 0

    output: List[Dict[str, Any]] = [rows[0]]
    removed = 0

    for i in range(1, len(rows)):
        row = rows[i]
        text = str(row.get("text") or "").strip()
        speaker = str(row.get("speaker_id") or "").strip()

        if len(text) < min_chars:
            output.append(row)
            continue

        chars_i = set(text.translate(_TRAD_TO_SIMP_FOR_DEDUP))
        is_dup = False
        start_j = max(0, len(output) - lookback)
        for j in range(start_j, len(output)):
            prev = output[j]
            prev_text = str(prev.get("text") or "").strip()
            prev_speaker = str(prev.get("speaker_id") or "").strip()
            if speaker != prev_speaker:
                continue
            if len(prev_text) < min_chars:
                continue
            chars_j = set(prev_text.translate(_TRAD_TO_SIMP_FOR_DEDUP))
            intersection = len(chars_i & chars_j)
            union = len(chars_i | chars_j)
            if union > 0 and intersection / union >= similarity_threshold:
                is_dup = True
                break

        if is_dup:
            removed += 1
        else:
            output.append(row)

    return output, removed


def _merge_ultra_short_segments(
    rows: List[Dict[str, Any]],
    *,
    min_chars: int = _OMNIVOICE_ULTRA_SHORT_CHARS,
    min_sec: float = _OMNIVOICE_ULTRA_SHORT_SEC,
    max_gap_sec: float = 0.5,
) -> Tuple[List[Dict[str, Any]], int]:
    """将超短段合并到同 speaker 相邻行，绝不跨 speaker 合并。"""

    if not rows:
        return [], 0

    items = [dict(r) for r in rows]
    merged_count = 0
    absorbed: set = set()

    for i, row in enumerate(items):
        if i in absorbed:
            continue
        text = re.sub(r"\s+", "", str(row.get("text") or ""))
        dur = max(0.0, float(row.get("end", 0) or 0) - float(row.get("start", 0) or 0))
        if len(text) > min_chars and dur > min_sec:
            continue
        spk = str(row.get("speaker_id") or "").strip()
        best_target: int | None = None
        best_gap = float("inf")
        for j in (i - 1, i + 1):
            if j < 0 or j >= len(items) or j in absorbed:
                continue
            neighbor = items[j]
            if str(neighbor.get("speaker_id") or "").strip() != spk:
                continue
            gap = abs(float(row["start"]) - float(neighbor["end"])) if j < i else abs(float(neighbor["start"]) - float(row["end"]))
            if gap > max_gap_sec:
                continue
            if gap < best_gap:
                best_gap = gap
                best_target = j
        if best_target is None:
            continue
        target = items[best_target]
        target["start"] = min(float(target["start"]), float(row["start"]))
        target["end"] = max(float(target["end"]), float(row["end"]))
        t_text = str(target.get("text") or "").strip()
        r_text = str(row.get("text") or "").strip()
        if best_target < i:
            target["text"] = t_text + r_text
        else:
            target["text"] = r_text + t_text
        absorbed.add(i)
        merged_count += 1

    result = [items[i] for i in range(len(items)) if i not in absorbed]
    return result, merged_count


def _merge_short_lines_for_tts(
    rows: List[Dict[str, Any]],
    *,
    target_chars: int = 25,
) -> Tuple[List[Dict[str, Any]], int]:
    """将 <target_chars 的短行合并到同 speaker 相邻行，直到接近上限。绝不跨 speaker。"""

    if not rows:
        return [], 0

    output: List[Dict[str, Any]] = []
    merge_count = 0
    current = dict(rows[0])

    for i in range(1, len(rows)):
        nxt = dict(rows[i])
        cur_spk = str(current.get("speaker_id") or "").strip()
        nxt_spk = str(nxt.get("speaker_id") or "").strip()
        cjk_mode = infer_cjk_mode_from_lines([str(current.get("text") or "")])
        cur_units = subtitle_text_units(str(current.get("text") or "").strip(), cjk_mode=cjk_mode)
        if cur_spk != nxt_spk or cur_units >= target_chars:
            output.append(current)
            current = nxt
            continue
        nxt_cjk = infer_cjk_mode_from_lines([str(nxt.get("text") or "")])
        nxt_units = subtitle_text_units(str(nxt.get("text") or "").strip(), cjk_mode=nxt_cjk)
        if cur_units + nxt_units <= target_chars:
            current = _merge_two_subtitle_rows(current, nxt)
            merge_count += 1
        else:
            output.append(current)
            current = nxt

    output.append(current)
    return output, merge_count


def _normalize_final_srt_text(text: str) -> str:
    """把结果字幕正文清洗成单行，避免内部换行干扰后续切分。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\s+", " ", normalized)


def _format_ass_time(seconds_value: float) -> str:
    """把秒数格式化成 ASS 时间戳 `H:MM:SS.cc`。"""

    total_centiseconds = max(0, int(round(float(seconds_value or 0.0) * 100.0)))
    hours, rem = divmod(total_centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    """转义 ASS 正文里的特殊字符，并把内部换行映射为 `\\N`。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    # ASS 把花括号当作 override block，需要显式转义成全角以避免样式串被误解析。
    normalized = normalized.replace("{", "｛").replace("}", "｝")
    lines = [line.strip() for line in normalized.split("\n")]
    return r"\N".join(line for line in lines if line)


def _build_styled_ass_from_rows(rows: List[Dict[str, Any]], *, source_name: str) -> str:
    """按固定样式模板把最终字幕行导出为 styled ASS。"""

    header_lines = [
        "[Script Info]",
        f"; Converted from {source_name}",
        "; Style: large bold white Chinese subtitles with semi-transparent black background bar",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,PingFang SC,80,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,4,0,0,2,80,80,80,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    dialogue_lines: List[str] = []
    for row in rows:
        text = _escape_ass_text(str(row.get("text") or ""))
        if not text:
            continue
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        if end_sec <= start_sec:
            continue
        dialogue_lines.append(
            f"Dialogue: 0,{_format_ass_time(start_sec)},{_format_ass_time(end_sec)},Default,,0,0,0,,{text}"
        )
    return "\n".join(header_lines + dialogue_lines) + "\n"


def _build_selected_subtitles_with_speaker_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构建带 speaker 前缀的字幕副本行，用于人工 review。"""

    output: List[Dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        speaker_id = str(row.get("speaker_id") or "").strip() or "Speaker 1"
        output.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": f"[{speaker_id}] {text}",
                "speaker_id": speaker_id,
            }
        )
    return output


def _split_by_regex_with_left_punct(text: str, pattern: re.Pattern[str]) -> List[str]:
    """按给定标点边界切分文本，并把标点保留在左侧片段。"""

    tokens = pattern.split(text)
    parts: List[str] = []
    current = ""
    for token in tokens:
        if not token:
            continue
        if pattern.fullmatch(token):
            current += token
            if current.strip():
                parts.append(current.strip())
            current = ""
        else:
            current += token
    if current.strip():
        parts.append(current.strip())
    return parts


def _is_ascii_word_char(ch: str) -> bool:
    """判断字符是否属于英文/数字单词，避免把单词从中间硬切开。"""

    return ch.isascii() and ch.isalnum()


def _split_long_final_segment(text: str, *, max_chars: int, min_piece_chars: int = 6) -> List[str]:
    """把仍然超长的片段切到上限以内，优先自然边界，再回退字符边界。"""

    remaining = text.strip()
    pieces: List[str] = []
    break_chars = set("，。！？；：、,.;:!?…")
    while len(remaining) > max_chars:
        total_chars = len(remaining)
        target_cut = min(max_chars, max(min_piece_chars, round(total_chars / 2)))
        lower_bound = max(min_piece_chars, total_chars - max_chars)
        upper_bound = min(max_chars, total_chars - min_piece_chars) if total_chars - min_piece_chars >= lower_bound else max_chars
        best_cut: Optional[int] = None
        best_score: Optional[int] = None
        for cut in range(lower_bound, upper_bound + 1):
            if cut < len(remaining) and _is_ascii_word_char(remaining[cut - 1]) and _is_ascii_word_char(remaining[cut]):
                continue
            last_char = remaining[cut - 1]
            if last_char in break_chars:
                boundary_kind = 0
            elif last_char.isspace():
                boundary_kind = 1
            else:
                boundary_kind = 2
            remainder_chars = total_chars - cut
            score = (boundary_kind * 1000) + abs(cut - target_cut) * 10 + max(0, min_piece_chars - remainder_chars) * 200
            if best_score is None or score < best_score:
                best_score = score
                best_cut = cut
        if best_cut is None:
            best_cut = target_cut
            while (
                best_cut < len(remaining)
                and _is_ascii_word_char(remaining[best_cut - 1])
                and _is_ascii_word_char(remaining[best_cut])
            ):
                best_cut += 1
            if best_cut > max_chars:
                best_cut = max_chars
                while (
                    best_cut > min_piece_chars
                    and _is_ascii_word_char(remaining[best_cut - 1])
                    and _is_ascii_word_char(remaining[best_cut])
                ):
                    best_cut -= 1
        next_piece = remaining[:best_cut].strip()
        if next_piece:
            pieces.append(next_piece)
        remaining = remaining[best_cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _wrap_final_srt_text_segments(text: str, *, max_chars: int) -> List[str]:
    """按“强句末 -> 软标点 -> 超长补切”的顺序把结果字幕拆成显示片段。"""

    segments: List[str] = []
    for sentence in _split_by_regex_with_left_punct(text, _OMNIVOICE_STRONG_BREAK_RE):
        if len(sentence) <= max_chars:
            segments.append(sentence)
            continue
        for clause in _split_by_regex_with_left_punct(sentence, _OMNIVOICE_SOFT_BREAK_RE):
            if len(clause) <= max_chars:
                segments.append(clause)
            else:
                segments.extend(_split_long_final_segment(clause, max_chars=max_chars))
    merged: List[str] = []
    for segment in segments:
        if merged and len(segment) <= 2 and len(merged[-1]) + len(segment) <= max_chars:
            merged[-1] += segment
        else:
            merged.append(segment)
    return merged


def _estimate_final_srt_time_spans(start_sec: float, end_sec: float, segments: List[str]) -> List[Tuple[float, float]]:
    """按文本负载把原 cue 时长分配给拆分后的多个片段。"""

    if not segments:
        return []
    if len(segments) == 1:
        return [(float(start_sec), float(end_sec))]

    total_duration_sec = max(0.05, float(end_sec) - float(start_sec))
    weights = [max(1, len(re.sub(r"\s+", "", segment))) for segment in segments]
    total_weight = max(1, sum(weights))
    min_piece_duration = 0.25
    if total_duration_sec < min_piece_duration * len(segments):
        step = total_duration_sec / len(segments)
        return [
            (float(start_sec) + index * step, float(start_sec) + (index + 1) * step)
            for index in range(len(segments))
        ]

    spans: List[Tuple[float, float]] = []
    cursor = float(start_sec)
    consumed_weight = 0
    for index, weight in enumerate(weights):
        consumed_weight += weight
        if index == len(weights) - 1:
            segment_end = float(end_sec)
        else:
            target_end = float(start_sec) + total_duration_sec * (consumed_weight / float(total_weight))
            remaining_slots = len(weights) - index - 1
            max_end = float(end_sec) - min_piece_duration * remaining_slots
            segment_end = max(cursor + min_piece_duration, min(max_end, target_end))
        spans.append((cursor, segment_end))
        cursor = segment_end
    return spans


def _rebalance_omnivoice_final_srt_rows(
    rows: List[Dict[str, Any]],
    *,
    max_chars: int = OMNIVOICE_FINAL_SRT_MAX_CHARS,
) -> List[Dict[str, Any]]:
    """重构 OmniVoice 结果字幕：每行限长并重估时间戳，仅用于最终结果落盘。"""

    rebalanced: List[Dict[str, Any]] = []
    for row in rows:
        text = _normalize_final_srt_text(str(row.get("text") or ""))
        if not text:
            continue
        start_sec = float(row.get("start", 0.0) or 0.0)
        end_sec = float(row.get("end", 0.0) or 0.0)
        if end_sec <= start_sec:
            continue
        segments = _wrap_final_srt_text_segments(text, max_chars=max_chars)
        spans = _estimate_final_srt_time_spans(start_sec, end_sec, segments)
        if len(spans) != len(segments):
            total_duration_sec = max(0.05, end_sec - start_sec)
            step = total_duration_sec / max(1, len(segments))
            spans = [
                (start_sec + index * step, start_sec + (index + 1) * step)
                for index in range(len(segments))
            ]
        for (segment_start, segment_end), segment_text in zip(spans, segments):
            rebalanced.append(
                {
                    "start": round(float(segment_start), 3),
                    "end": round(float(segment_end), 3),
                    "text": segment_text,
                    "speaker_id": str(row.get("speaker_id") or "").strip(),
                }
            )
    return rebalanced


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


def _infer_missing_speaker_gender_hints(
    *,
    vocals_path: Path,
    subtitles: List[Dict[str, Any]],
    missing_speaker_ids: List[str],
    out_root: Path,
) -> Dict[str, str]:
    """从原音频中抽取缺失 speaker 的片段，粗判男/女用于挑选预存参考音。"""

    if not missing_speaker_ids:
        return {}
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for index, subtitle in enumerate(subtitles):
        speaker_id = str(subtitle.get("speaker_id") or "").strip() or "Speaker 1"
        if speaker_id in missing_speaker_ids:
            grouped.setdefault(speaker_id, []).append((index, subtitle))
    if not grouped:
        return {}

    probe_root = out_root / "speaker_gender_probe"
    hints: Dict[str, str] = {}
    for speaker_id in missing_speaker_ids:
        items = grouped.get(speaker_id) or []
        if not items:
            continue
        picked = _pick_reference_slices(items)
        speaker_probe_dir = probe_root / _safe_speaker_name(speaker_id)
        try:
            probe_path, _ = _concat_reference_slices(
                vocals_path=vocals_path,
                picked=picked,
                out_dir=speaker_probe_dir,
                speaker_id=speaker_id,
            )
            label = _infer_voice_gender_label(probe_path, use_path_hint=False)
            if label in {"male", "female"}:
                hints[speaker_id] = label
        except Exception as exc:
            logger.warning("OmniVoice gender hint probe failed for %s: %s", speaker_id, exc)
            continue
    return hints


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
        with _open_omnivoice_request(request, api_url=api_url, timeout_sec=timeout_sec) as response:
            if response.status >= 400:
                raise RuntimeError(f"health status {response.status}")
    except Exception as exc:
        raise RuntimeError(f"OmniVoice health check failed: {exc}") from exc


def _fetch_omnivoice_model_status(api_url: str, timeout_sec: int = 5) -> Dict[str, Any]:
    """读取 OmniVoice 后端模型状态，区分“进程活着”和“模型已就绪”。"""

    url = api_url.rstrip("/") + "/model/status"
    request = urllib.request.Request(url, method="GET")
    try:
        with _open_omnivoice_request(request, api_url=api_url, timeout_sec=timeout_sec) as response:
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


def _open_omnivoice_request(request: urllib.request.Request, *, api_url: str, timeout_sec: int):
    """访问本机 OmniVoice 服务时显式绕过系统代理，避免误判后端未就绪。"""

    if _is_local_omnivoice_api(api_url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout_sec)
    return urllib.request.urlopen(request, timeout=timeout_sec)


def _build_omnivoice_requests_session(api_url: str):
    """为 OmniVoice HTTP 请求构造 session，本机地址显式禁用环境代理。"""

    import requests

    session = requests.Session()
    if _is_local_omnivoice_api(api_url):
        session.trust_env = False
        session.proxies.clear()
    return session


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


def _is_ultra_short_for_tts(text: str, duration_sec: float) -> bool:
    """判断文本是否太短以至于 TTS 可能产生无效音。"""
    chars = len(re.sub(r"\s+", "", text or ""))
    return chars <= _OMNIVOICE_ULTRA_SHORT_CHARS or duration_sec <= _OMNIVOICE_ULTRA_SHORT_SEC


def _generate_silence_wav(output_path: Path, duration_sec: float) -> None:
    """生成指定时长的静音 WAV 文件。"""
    samples = int(max(0.01, duration_sec) * _OMNIVOICE_SILENCE_SAMPLE_RATE)
    silence = np.zeros(samples, dtype=np.float32)
    sf.write(str(output_path), silence, _OMNIVOICE_SILENCE_SAMPLE_RATE)


def _compute_tts_speed_for_segment(
    text: str,
    duration_sec: float,
    target_lang: str,
) -> float:
    """根据文本密度与时间窗计算 TTS speed 参数，让语速匹配时间槽。"""
    lang_key = (target_lang or "zh").strip().lower().split("-")[0]
    target_cps = _OMNIVOICE_TARGET_CPS.get(lang_key, 6.0)
    cjk_mode = infer_cjk_mode_from_lines([text])
    units = max(1, subtitle_text_units(text, cjk_mode=cjk_mode))
    natural_duration = units / target_cps
    slot = max(0.1, float(duration_sec))
    speed = natural_duration / slot
    return max(_OMNIVOICE_TTS_SPEED_MIN, min(_OMNIVOICE_TTS_SPEED_MAX, speed))


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
        with _build_omnivoice_requests_session(api_url) as session:
            response = session.post(
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
    source_lang: str,
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
            return _ensure_speaker_ids(
                _sanitize_translated_rows_for_target(translated_rows, target_lang=target_lang),
                fallback_rows=source_rows,
            ), "translated"
        if source_rows:
            selected_rows = source_rows
            selected_mode = "source"
        else:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")
    elif normalized_mode == "source":
        if not source_rows and translated_rows:
            return _ensure_speaker_ids(
                _sanitize_translated_rows_for_target(translated_rows, target_lang=target_lang),
                fallback_rows=source_rows,
            ), "translated"
        if not source_rows:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")
        selected_rows = source_rows
        selected_mode = "source"
    else:
        if translated_rows:
            return _ensure_speaker_ids(
                _sanitize_translated_rows_for_target(translated_rows, target_lang=target_lang),
                fallback_rows=source_rows,
            ), "translated"
        if source_rows:
            selected_rows = source_rows
            selected_mode = "source"
        else:
            raise HTTPException(status_code=400, detail="OmniVoice requires at least one subtitle row")

    if _should_passthrough_source_rows_without_translation(
        source_rows=selected_rows,
        source_lang=source_lang,
        target_lang=target_lang,
    ):
        return _ensure_speaker_ids(
            [
                {
                    **row,
                    "text": str(row.get("text") or "").strip(),
                }
                for row in selected_rows
                if str(row.get("text") or "").strip()
            ],
            fallback_rows=source_rows,
        ), "source"

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
        sanitize_outputs=False,
    )
    selected_mode = "translated"
    if _target_prefers_cjk_text(target_lang):
        retry_indices = [
            index
            for index, text in enumerate(translated_texts)
            if _is_latin_dominant_text(str(text or ""))
        ]
        if retry_indices:
            retry_inputs = [texts[index] for index in retry_indices]
            try:
                retry_outputs = translator.translate_batch(
                    retry_inputs,
                    target_lang=target_lang,
                    system_prompt=build_translation_system_prompt(translate_system_prompt),
                    sanitize_outputs=False,
                )
                if len(retry_outputs) != len(retry_inputs):
                    logger.warning(
                        "OmniVoice translation retry count mismatch: requested=%d returned=%d",
                        len(retry_inputs),
                        len(retry_outputs),
                    )
                    retry_outputs = []
                replaced = 0
                for idx, retry_text in zip(retry_indices, retry_outputs):
                    if not _is_latin_dominant_text(str(retry_text or "")):
                        translated_texts[idx] = str(retry_text or "").strip()
                        replaced += 1
                if replaced > 0:
                    logger.warning(
                        "OmniVoice translation retry replaced %d latin-dominant rows",
                        replaced,
                    )
            except Exception as exc:
                logger.warning("OmniVoice translation retry failed: %s", exc)
    translated_rows = _normalize_translation_result(selected_rows, translated_texts)
    translated_rows = _ensure_speaker_ids(translated_rows, fallback_rows=source_rows)
    # 空行回退必须在 sanitize 之前：sanitize 会丢弃空行，导致 1:1 索引失效。
    repaired_rows: List[Dict[str, Any]] = []
    fallback_count = 0
    for index, row in enumerate(translated_rows):
        text = str(row.get("text") or "").strip()
        if not text and index < len(selected_rows):
            text = str(selected_rows[index].get("text") or "").strip()
            if text:
                fallback_count += 1
        repaired_rows.append(
            {
                "start": float(row.get("start", 0.0) or 0.0),
                "end": float(row.get("end", 0.0) or 0.0),
                "text": text,
                "speaker_id": str(row.get("speaker_id") or "").strip(),
            }
        )
    if fallback_count > 0:
        logger.warning(
            "OmniVoice translation fallback restored %d empty rows using source text",
            fallback_count,
        )
    # 空译文回退 source 后，仍可能残留英文主导文本——定向重译。
    if _target_prefers_cjk_text(target_lang):
        repaired_retry_indices = [
            index
            for index, row in enumerate(repaired_rows)
            if _is_latin_dominant_text(str(row.get("text") or ""))
        ]
        if repaired_retry_indices:
            repaired_retry_inputs = [texts[index] for index in repaired_retry_indices]
            strict_prompt = (
                f"{build_translation_system_prompt(translate_system_prompt)}\n"
                "硬性要求：输出必须是中文，不要保留整句英文；专有名词请用中文或中文括注。"
            )
            try:
                repaired_retry_outputs = translator.translate_batch(
                    repaired_retry_inputs,
                    target_lang=target_lang,
                    system_prompt=strict_prompt,
                    system_prompt_is_final=True,
                    sanitize_outputs=False,
                )
                if len(repaired_retry_outputs) != len(repaired_retry_inputs):
                    logger.warning(
                        "OmniVoice repaired-row retry count mismatch: requested=%d returned=%d",
                        len(repaired_retry_inputs),
                        len(repaired_retry_outputs),
                    )
                    repaired_retry_outputs = []
                repaired_replaced = 0
                for idx, retry_text in zip(repaired_retry_indices, repaired_retry_outputs):
                    normalized_retry_text = str(retry_text or "").strip()
                    if normalized_retry_text and not _is_latin_dominant_text(normalized_retry_text):
                        repaired_rows[idx]["text"] = normalized_retry_text
                        repaired_replaced += 1
                if repaired_replaced > 0:
                    logger.warning(
                        "OmniVoice repaired-row retry replaced %d latin-dominant rows",
                        repaired_replaced,
                    )
            except Exception as exc:
                logger.warning("OmniVoice repaired-row retry failed: %s", exc)
    # 所有回退和重译完成后，统一做 sanitize + 粤语规整。
    translated_rows = _sanitize_translated_rows_for_target(repaired_rows, target_lang=target_lang)
    if _is_cantonese_language_variant(target_lang):
        translated_rows = [
            {
                **row,
                "text": normalize_cantonese_translation_text(str(row.get("text") or ""), target_lang),
            }
            for row in translated_rows
        ]
    translated_rows = _drop_empty_subtitle_rows(translated_rows, label="translated")
    if not translated_rows:
        raise HTTPException(status_code=400, detail="OmniVoice translation produced no usable subtitle rows")
    logger.info("OmniVoice task %s translated %d subtitles from source mode", task_id, len(translated_rows))
    return translated_rows, selected_mode


def _normalize_generated_segment_audio(
    input_path: Path, output_path: Path, target_duration_sec: float,
) -> Tuple[Path, str]:
    """对单句 OmniVoice 输出做轻量收尾处理，返回 (输出路径, 操作类型)。"""

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
        return output_path, "passthrough"

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
        if ratio <= 1.5:
            try:
                fit_audio_to_duration(
                    input_path=norm_path,
                    output_path=output_path,
                    target_duration_sec=target_duration_sec,
                )
                return output_path, "time_stretch"
            except Exception as exc:
                logger.warning("OmniVoice fit timing fallback for %s: %s", output_path.name, exc)
        trim_audio_to_max_duration(
            input_path=norm_path,
            output_path=output_path,
            max_duration_sec=target_duration_sec,
        )
        return output_path, "hard_trim"

    if current_duration < target_duration_sec * 0.85 and target_duration_sec >= 0.5:
        try:
            fit_audio_to_duration(
                input_path=norm_path,
                output_path=output_path,
                target_duration_sec=target_duration_sec,
            )
            return output_path, "slow_fit"
        except Exception as exc:
            logger.warning("OmniVoice slow-fit fallback for %s: %s", output_path.name, exc)

    shutil.copy2(norm_path, output_path)
    return output_path, "passthrough"


def _generate_synthesis_diagnostic_report(
    segment_results: List[Dict[str, Any]],
    out_root: Path,
    target_lang: str,
) -> Path:
    """合成完成后生成诊断报告，量化语速/时长匹配质量。"""

    if not segment_results:
        report_path = out_root / "synthesis_report.json"
        report_path.write_text(json.dumps({"segments": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    sync_ratios: List[float] = []
    speeds: List[float] = []
    cps_values: List[float] = []
    action_counts: Dict[str, int] = {}
    problem_segments: List[Dict[str, Any]] = []

    for seg in segment_results:
        target_dur = max(0.01, float(seg.get("duration_sec", 0.0) or 0.0))
        actual_dur = max(0.01, float(seg.get("normalized_duration_sec", 0.0) or 0.0))
        sync = actual_dur / target_dur
        sync_ratios.append(sync)

        speed = float(seg.get("tts_speed", 1.0) or 1.0)
        speeds.append(speed)

        text = str(seg.get("text") or "")
        chars = len(re.sub(r"\s+", "", text))
        cps = chars / target_dur
        cps_values.append(cps)

        action = str(seg.get("fit_action") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1

        reasons: List[str] = []
        if sync > 1.3:
            reasons.append(f"sync_ratio={sync:.2f}>1.3")
        if sync < 0.7:
            reasons.append(f"sync_ratio={sync:.2f}<0.7")
        if action == "hard_trim":
            reasons.append("hard_trim")
        if cps > 12:
            reasons.append(f"cps={cps:.1f}>12")
        if reasons:
            problem_segments.append({
                "id": seg.get("id", ""),
                "text": text[:80],
                "duration_sec": round(target_dur, 3),
                "sync_ratio": round(sync, 3),
                "tts_speed": round(speed, 3),
                "cps": round(cps, 1),
                "fit_action": action,
                "reasons": reasons,
            })

    def _percentile(vals: List[float], p: float) -> float:
        s = sorted(vals)
        idx = min(len(s) - 1, max(0, int(len(s) * p)))
        return s[idx]

    report = {
        "segments": len(segment_results),
        "sync_ratio": {
            "min": round(min(sync_ratios), 3),
            "max": round(max(sync_ratios), 3),
            "median": round(_percentile(sync_ratios, 0.5), 3),
            "p10": round(_percentile(sync_ratios, 0.1), 3),
            "p90": round(_percentile(sync_ratios, 0.9), 3),
        },
        "tts_speed": {
            "min": round(min(speeds), 3),
            "max": round(max(speeds), 3),
            "median": round(_percentile(speeds, 0.5), 3),
            "extreme_slow_count": sum(1 for s in speeds if s < 0.85),
            "extreme_fast_count": sum(1 for s in speeds if s > 1.3),
        },
        "cps": {
            "median": round(_percentile(cps_values, 0.5), 1),
            "p10": round(_percentile(cps_values, 0.1), 1),
            "p90": round(_percentile(cps_values, 0.9), 1),
            "above_12_count": sum(1 for c in cps_values if c > 12),
        },
        "fit_actions": action_counts,
        "problem_segments": problem_segments,
    }

    report_path = out_root / "synthesis_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "OmniVoice synthesis report: %d segments, median sync=%.2f, %d hard_trim, %d slow_fit, %d problem",
        len(segment_results),
        _percentile(sync_ratios, 0.5),
        action_counts.get("hard_trim", 0),
        action_counts.get("slow_fit", 0),
        len(problem_segments),
    )
    return report_path


def _create_task_payload(
    *,
    task_id: str,
    project_filename: str,
    input_media_path: Path,
    subtitle_mode: str,
    source_lang: str,
    target_lang: str,
    enable_source_separation: bool = True,
    source_count: int,
    translated_count: int,
    speaker_ids: List[str],
    out_root: Path,
) -> Dict[str, Any]:
    """创建 OmniVoice 任务初始记录。"""

    display_source_lang, runtime_source_lang = _normalize_omnivoice_language_pair(source_lang, default="auto")
    display_target_lang, runtime_target_lang = _normalize_omnivoice_language_pair(target_lang, default="Chinese")
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
        "source_lang": display_source_lang,
        "source_lang_runtime": runtime_source_lang,
        "target_lang": display_target_lang,
        "target_lang_runtime": runtime_target_lang,
        "enable_source_separation": bool(enable_source_separation),
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
    subtitles_with_speaker_path: Optional[Path] = None,
    final_ass_path: Optional[Path] = None,
    burned_video_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """写入独立 OmniVoice manifest，供恢复与 artifact 下载使用。"""

    display_source_lang, runtime_source_lang = _normalize_omnivoice_language_pair(task["source_lang"], default="auto")
    display_target_lang, runtime_target_lang = _normalize_omnivoice_language_pair(task["target_lang"], default="Chinese")
    paths: Dict[str, Optional[str]] = {
        "source_audio": str(source_audio_path.resolve()) if source_audio_path.exists() else None,
        "source_vocals": str(source_vocals_path.resolve()) if source_vocals_path.exists() else None,
        "source_bgm": str(source_bgm_path.resolve()) if source_bgm_path.exists() else None,
        "speaker_ref_map": str(speaker_ref_map_path.resolve()) if speaker_ref_map_path.exists() else None,
        "speaker_reference_dir": str(speaker_reference_dir.resolve()) if speaker_reference_dir.exists() else None,
        "selected_subtitles": str(subtitles_path.resolve()) if subtitles_path.exists() else None,
        "selected_subtitles_with_speakers": (
            str(subtitles_with_speaker_path.resolve())
            if subtitles_with_speaker_path and subtitles_with_speaker_path.exists()
            else None
        ),
        "dubbed_final_srt": str(final_srt_path.resolve()) if final_srt_path.exists() else None,
        "dubbed_final_ass": str(final_ass_path.resolve()) if final_ass_path and final_ass_path.exists() else None,
        "dubbed_vocals": str(final_vocals_path.resolve()) if final_vocals_path.exists() else None,
        "dubbed_mix": str(final_mix_path.resolve()) if final_mix_path.exists() else None,
        "dubbed_audio_for_video": str(separated_video_audio_path.resolve()) if separated_video_audio_path and separated_video_audio_path.exists() else None,
        "dubbed_video_full": str(final_video_path.resolve()) if final_video_path and final_video_path.exists() else None,
        "dubbed_video_burned": str(burned_video_path.resolve()) if burned_video_path and burned_video_path.exists() else None,
        "separation_report": str(separation_report_path.resolve()) if separation_report_path.exists() else None,
        "manifest": str((out_root / "manifest.json").resolve()),
    }
    artifacts: List[Dict[str, str]] = [
        {"key": "srt", "label": "Dubbed Final SRT", "url": _build_artifact_url(task["id"], "srt")},
        {"key": "ass", "label": "Dubbed Final ASS", "url": _build_artifact_url(task["id"], "ass")},
        {"key": "vocals", "label": "Dubbed Vocals WAV", "url": _build_artifact_url(task["id"], "vocals")},
        {"key": "mix", "label": "Dubbed Mix WAV", "url": _build_artifact_url(task["id"], "mix")},
        {"key": "manifest", "label": "Manifest JSON", "url": _build_artifact_url(task["id"], "manifest")},
    ]
    if burned_video_path and burned_video_path.exists():
        artifacts.insert(2, {"key": "video_burned", "label": "Dubbed Video MP4 (Burned ASS)", "url": _build_artifact_url(task["id"], "video_burned")})
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
        "source_lang": display_source_lang,
        "source_lang_runtime": runtime_source_lang,
        "target_lang": display_target_lang,
        "target_lang_runtime": runtime_target_lang,
        "enable_source_separation": bool(task.get("enable_source_separation", True)),
        "selected_subtitle_mode": task.get("selected_subtitle_mode"),
        "source_subtitles_count": task["source_subtitles_count"],
        "translated_subtitles_count": task["translated_subtitles_count"],
        "speaker_ids": task["speaker_ids"],
        "speaker_reference_mode": task.get("speaker_reference_mode") or "auto_aggregate",
        "paths": paths,
        "artifacts": artifacts,
        "segment_count": task.get("total_segments", 0),
        "processed_segments": task.get("processed_segments", 0),
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


def _resolve_existing_optional_path(raw: Any) -> Optional[Path]:
    """安全解析可选路径；空字符串不能退化为当前目录。"""

    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.exists():
        return None
    return path


def _parse_selected_subtitles_with_speaker(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把带 `[Speaker X]` 前缀的 SRT 行还原为内部字幕结构。"""

    rows: List[Dict[str, Any]] = []
    for item in items:
        raw_text = str(item.get("text") or "").strip()
        if not raw_text:
            continue
        speaker_id = ""
        text = raw_text
        match = re.match(r"^\[(.+?)\]\s*(.*)$", raw_text)
        if match:
            speaker_id = str(match.group(1) or "").strip()
            text = str(match.group(2) or "").strip()
        rows.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
                "speaker_id": speaker_id,
            }
        )
    return rows


def _load_selected_subtitles_from_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """优先从带 speaker 副本恢复 selected_subtitles，避免重启后丢 speaker_id。"""

    paths = dict(manifest.get("paths") or {})
    speaker_copy_path = _resolve_existing_optional_path(paths.get("selected_subtitles_with_speakers"))
    if speaker_copy_path is not None:
        items = parse_srt(speaker_copy_path.read_text(encoding="utf-8"))
        rows = _parse_selected_subtitles_with_speaker(items)
        if rows:
            return _ensure_speaker_ids(rows, fallback_rows=rows, force_align_by_time=False)

    selected_path = _resolve_existing_optional_path(paths.get("selected_subtitles"))
    if selected_path is not None:
        items = parse_srt(selected_path.read_text(encoding="utf-8"))
        return _ensure_speaker_ids(items, fallback_rows=items, force_align_by_time=False)
    return []


def _load_speaker_ref_map_for_resume(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """从任务目录恢复 speaker 参考音映射，供 resume 直接复用。"""

    paths = dict(manifest.get("paths") or {})
    ref_map_path = _resolve_existing_optional_path(paths.get("speaker_ref_map"))
    if ref_map_path is None:
        return {}
    try:
        payload = json.loads(ref_map_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    speakers = payload.get("speakers")
    if not isinstance(speakers, dict):
        return {}
    restored: Dict[str, Dict[str, Any]] = {}
    for speaker_id, meta in speakers.items():
        if not isinstance(meta, dict):
            continue
        ref_audio_path = Path(str(meta.get("ref_audio") or "")).expanduser()
        if not ref_audio_path.exists():
            continue
        restored[str(speaker_id)] = dict(meta)
    return restored


def _segment_row_matches_manifest(row: Dict[str, Any], segment_manifest: Dict[str, Any]) -> bool:
    """判断磁盘 segment manifest 是否仍和当前 selected_subtitles 行一致。"""

    expected_speaker = str(row.get("speaker_id") or "").strip() or "Speaker 1"
    actual_speaker = str(segment_manifest.get("speaker_id") or "").strip() or "Speaker 1"
    if expected_speaker != actual_speaker:
        return False
    if str(row.get("text") or "").strip() != str(segment_manifest.get("text") or "").strip():
        return False
    expected_start = float(row.get("start", 0.0) or 0.0)
    expected_end = float(row.get("end", 0.0) or 0.0)
    actual_start = float(segment_manifest.get("start_sec", 0.0) or 0.0)
    actual_end = float(segment_manifest.get("end_sec", 0.0) or 0.0)
    return abs(expected_start - actual_start) <= 0.02 and abs(expected_end - actual_end) <= 0.02


def _collect_resumable_segment_results(
    *,
    segment_root: Path,
    selected_subtitles: List[Dict[str, Any]],
) -> Tuple[Set[int], List[Dict[str, Any]]]:
    """扫描已有 segment 产物，只复用“音频+manifest 都完整且内容匹配”的条目。"""

    completed_indices: Set[int] = set()
    reusable_results: List[Dict[str, Any]] = []
    for index, row in enumerate(selected_subtitles, start=1):
        segment_dir = segment_root / f"segment_{index:04d}"
        manifest_path = segment_dir / "manifest.json"
        final_segment_path = segment_dir / f"seg_{index:04d}.wav"
        if not manifest_path.exists() or not final_segment_path.exists():
            continue
        try:
            segment_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _segment_row_matches_manifest(row, segment_manifest):
            continue
        reusable = dict(segment_manifest)
        reusable["tts_audio_path"] = str(final_segment_path.resolve())
        completed_indices.add(index)
        reusable_results.append(reusable)
    return completed_indices, reusable_results


def _infer_resume_state(
    manifest: Dict[str, Any],
    *,
    out_root: Path,
) -> Dict[str, Any]:
    """根据磁盘产物推断一个 OmniVoice batch 能否恢复、恢复到哪一阶段。"""

    status = str(manifest.get("status") or "").strip().lower()
    stage = str(manifest.get("stage") or "").strip()
    paths = dict(manifest.get("paths") or {})
    selected_rows = _load_selected_subtitles_from_manifest(manifest)
    total_segments = int(manifest.get("segment_count") or manifest.get("processed_segments") or len(selected_rows) or 0)
    if total_segments <= 0:
        total_segments = len(selected_rows)

    completed_segment_indices, _ = _collect_resumable_segment_results(
        segment_root=out_root / "segment_jobs",
        selected_subtitles=selected_rows,
    )
    completed_segments = len(completed_segment_indices)

    final_srt_path = _resolve_existing_optional_path(paths.get("dubbed_final_srt"))
    if final_srt_path is not None:
        return {
            "resumable": False,
            "resume_stage": "completed",
            "completed_segments": total_segments if total_segments > 0 else completed_segments,
            "total_segments": total_segments,
        }

    if completed_segments > 0 and total_segments > completed_segments:
        return {
            "resumable": True,
            "resume_stage": "dubbing_partial",
            "completed_segments": completed_segments,
            "total_segments": total_segments,
        }

    selected_subtitles_path = _resolve_existing_optional_path(paths.get("selected_subtitles"))
    if selected_subtitles_path is not None and selected_rows:
        return {
            "resumable": True,
            "resume_stage": "prepared",
            "completed_segments": completed_segments,
            "total_segments": total_segments if total_segments > 0 else len(selected_rows),
        }

    return {
        "resumable": status in {"failed", "cancelled"} and bool(stage),
        "resume_stage": "unavailable",
        "completed_segments": completed_segments,
        "total_segments": total_segments,
    }


def _annotate_task_with_resume_state(
    task: Dict[str, Any],
    *,
    manifest: Dict[str, Any],
    out_root: Path,
    from_disk: bool = False,
) -> Dict[str, Any]:
    """把恢复信息附着到任务记录；从磁盘加载 stale running 任务时改标为 interrupted。"""

    resume_state = _infer_resume_state(manifest, out_root=out_root)
    task["resumable"] = bool(resume_state.get("resumable"))
    task["resume_stage"] = str(resume_state.get("resume_stage") or "")
    task["processed_segments"] = int(resume_state.get("completed_segments") or task.get("processed_segments") or 0)
    task["total_segments"] = int(resume_state.get("total_segments") or task.get("total_segments") or 0)

    status = str(task.get("status") or "").strip().lower()
    if from_disk and status in {"queued", "running"} and task.get("resume_stage") != "completed":
        task["status"] = "failed"
        task["stage"] = "failed"
        task["error"] = "Interrupted OmniVoice job loaded from disk. Use resume to continue."
    return task


def _build_resume_context(
    *,
    manifest: Dict[str, Any],
    out_root: Path,
) -> Dict[str, Any]:
    """从 batch 目录构造 resume 所需的最小上下文。"""

    selected_subtitles = _load_selected_subtitles_from_manifest(manifest)
    if not selected_subtitles:
        raise HTTPException(status_code=409, detail="Resume selected_subtitles.srt missing or empty")

    speaker_ref_map = _load_speaker_ref_map_for_resume(manifest)
    completed_segment_indices, reusable_segment_results = _collect_resumable_segment_results(
        segment_root=out_root / "segment_jobs",
        selected_subtitles=selected_subtitles,
    )

    paths = dict(manifest.get("paths") or {})
    source_audio_path = _resolve_existing_optional_path(paths.get("source_audio"))
    source_vocals_path = _resolve_existing_optional_path(paths.get("source_vocals"))
    source_bgm_path = _resolve_existing_optional_path(paths.get("source_bgm"))
    separation_report_path = _resolve_existing_optional_path(paths.get("separation_report"))

    return {
        "selected_subtitles": selected_subtitles,
        "speaker_ref_map": speaker_ref_map,
        "speaker_reference_mode": str(manifest.get("speaker_reference_mode") or ""),
        "completed_segment_indices": completed_segment_indices,
        "reusable_segment_results": reusable_segment_results,
        "reuse_selected_subtitles": True,
        "reuse_stems": source_audio_path is not None and source_vocals_path is not None,
        "reuse_speaker_refs": bool(speaker_ref_map),
        "source_audio_path": str(source_audio_path.resolve()) if source_audio_path is not None else "",
        "source_vocals_path": str(source_vocals_path.resolve()) if source_vocals_path is not None else "",
        "source_bgm_path": str(source_bgm_path.resolve()) if source_bgm_path is not None else "",
        "separation_report_path": str(separation_report_path.resolve()) if separation_report_path is not None else "",
        "has_bgm_track": source_bgm_path is not None,
    }


def _persist_omnivoice_task_manifest(
    *,
    task_id: str,
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
    subtitles_with_speaker_path: Optional[Path] = None,
    final_ass_path: Optional[Path] = None,
    burned_video_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """把当前任务快照写回 manifest，支持中途断电后的磁盘恢复。"""

    task = _task_store.get(task_id)
    if task is None:
        return None
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
        separated_video_audio_path=separated_video_audio_path,
        separation_report_path=separation_report_path,
        speaker_reference_dir=speaker_reference_dir,
        subtitles_path=subtitles_path,
        subtitles_with_speaker_path=subtitles_with_speaker_path,
        final_ass_path=final_ass_path,
        burned_video_path=burned_video_path,
    )
    _annotate_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=False)
    return manifest


def _artifact_path_from_task(task: Dict[str, Any], artifact: str) -> Optional[Path]:
    """根据 artifact key 解析输出路径。"""

    manifest_path = Path(str(task.get("batch_manifest_path") or "")).expanduser()
    out_root = manifest_path.parent if manifest_path.exists() else _resolve_output_dir(str(task.get("batch_id") or task.get("id") or ""))
    paths = {
        "srt": out_root / "final" / "dubbed_final_full.srt",
        "ass": out_root / "final" / "dubbed_final_full-styled.ass",
        "selected_srt": out_root / "selected_subtitles.srt",
        "selected_srt_with_speaker": out_root / "selected_subtitles_with_speakers.srt",
        "vocals": out_root / "final" / "dubbed_vocals_full.wav",
        "mix": out_root / "final" / "dubbed_mix_full.wav",
        "video": out_root / "final" / "dubbed_video_full.mp4",
        "video_burned": out_root / "final" / "dubbed_video_full_burned.mp4",
        "video_audio": out_root / "final" / "dubbed_audio_for_video.m4a",
        "manifest": out_root / "manifest.json",
        "separation_report": out_root / "separation_report.json",
    }
    return paths.get(artifact)


def _resolve_omnivoice_separator_device() -> str:
    """解析 Demucs 分离阶段应使用的设备。"""

    separator_device = "mps"
    try:
        import torch

        if not torch.backends.mps.is_available():
            separator_device = "auto"
    except Exception:
        separator_device = "auto"
    return separator_device


def _extract_omnivoice_audio_segment(
    *,
    input_media_path: Path,
    output_wav: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    """按绝对时间范围抽取音频片段，供长视频分块分离使用。"""

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    duration_sec = max(0.05, float(end_sec) - float(start_sec))
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{float(start_sec):.3f}",
        "-i",
        str(input_media_path),
        "-t",
        f"{duration_sec:.3f}",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        str(output_wav),
    ]
    code, _, err = run_cmd(cmd, cwd=REPO_ROOT)
    if code != 0:
        raise RuntimeError(f"OmniVoice chunk audio extract failed: {err.strip()}")
    return output_wav


def _attempt_omnivoice_demucs_separation(
    *,
    input_audio_path: Path,
    demucs_out: Path,
    separator_device: str,
) -> Dict[str, Any]:
    """尝试对单条音频做人声分离，返回可用 stem 与尝试记录。"""

    demucs_out.mkdir(parents=True, exist_ok=True)

    attempts: List[Dict[str, Any]] = []
    vocals_src = None
    bgm_src = None
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
            str(input_audio_path),
        ]
        if separator_device and separator_device != "auto":
            cmd[5:5] = ["-d", separator_device]
        code, _, err = run_cmd(cmd, cwd=REPO_ROOT)
        model_root = demucs_out / model_name
        vocals_candidates = list(model_root.glob("**/vocals.wav"))
        bgm_candidates = list(model_root.glob("**/no_vocals.wav"))
        if not vocals_candidates:
            attempts.append({"model": model_name, "ok": False, "error": err.strip() or "demucs failed"})
            continue
        vocals_src = vocals_candidates[0]
        bgm_src = bgm_candidates[0] if bgm_candidates else None
        attempt_error = ""
        if code != 0 and err.strip():
            # 某些 Demucs 版本会在收尾阶段非零退出，但 stem 已经可用，此时保留 stderr 便于排障。
            attempt_error = err.strip()
        attempts.append({"model": model_name, "ok": True, "error": attempt_error})
        break

    return {
        "separator_device": separator_device,
        "attempts": attempts,
        "vocals_src": vocals_src,
        "bgm_src": bgm_src,
    }


def _prepare_omnivoice_source_stems_single_pass(
    *,
    source_audio_path: Path,
    source_vocals_path: Path,
    source_bgm_path: Path,
    separation_report_path: Path,
    demucs_out: Path,
    separator_device: str,
) -> Dict[str, Any]:
    """沿用现有整段 Demucs 分离路径；失败时退化为 vocals-only。"""

    separation_result = _attempt_omnivoice_demucs_separation(
        input_audio_path=source_audio_path,
        demucs_out=demucs_out,
        separator_device=separator_device,
    )
    attempts = list(separation_result.get("attempts") or [])
    vocals_src = separation_result.get("vocals_src")
    bgm_src = separation_result.get("bgm_src")
    has_bgm_track = False

    if vocals_src is None:
        shutil.copy2(source_audio_path, source_vocals_path)
        if source_bgm_path.exists():
            source_bgm_path.unlink()
        separation_report_path.write_text(
            json.dumps(
                {
                    "status": "failed_fallback_vocals_only",
                    "mode": "single_pass",
                    "attempts": attempts,
                    "separator_device": separator_device,
                    "source_audio": str(source_audio_path.resolve()),
                    "source_vocals": str(source_vocals_path.resolve()),
                    "source_bgm": None,
                    "has_bgm_track": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "separator_device": separator_device,
            "attempts": attempts,
            "has_bgm_track": False,
            "degraded_to_vocals_only": True,
        }

    shutil.copy2(vocals_src, source_vocals_path)
    if bgm_src and bgm_src.exists():
        shutil.copy2(bgm_src, source_bgm_path)
        has_bgm_track = True
    elif source_bgm_path.exists():
        source_bgm_path.unlink()

    separation_report_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "mode": "single_pass",
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
    return {
        "separator_device": separator_device,
        "attempts": attempts,
        "has_bgm_track": has_bgm_track,
        "degraded_to_vocals_only": False,
    }


def _prepare_omnivoice_source_stems_passthrough(
    *,
    source_audio_path: Path,
    source_vocals_path: Path,
    source_bgm_path: Path,
    separation_report_path: Path,
) -> Dict[str, Any]:
    """手动关闭分离时直接复用源音频做人声轨，并显式关闭 BGM。"""

    shutil.copy2(source_audio_path, source_vocals_path)
    if source_bgm_path.exists():
        source_bgm_path.unlink()
    separation_report_path.write_text(
        json.dumps(
            {
                "status": "skipped_passthrough_vocals_only",
                "mode": "passthrough",
                "attempts": [],
                "separator_device": None,
                "source_audio": str(source_audio_path.resolve()),
                "source_vocals": str(source_vocals_path.resolve()),
                "source_bgm": None,
                "has_bgm_track": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "separator_device": None,
        "attempts": [],
        "has_bgm_track": False,
        "degraded_to_vocals_only": False,
        "mode": "passthrough",
    }


def _build_omnivoice_cut_hint_points(
    subtitles: Optional[List[Dict[str, Any]]],
) -> Dict[str, List[float]]:
    """从字幕里提取可辅助切点搜索的边界时间。"""

    boundaries: List[float] = []
    speaker_changes: List[float] = []
    if not subtitles:
        return {"boundaries": boundaries, "speaker_changes": speaker_changes}

    normalized: List[Dict[str, Any]] = []
    for row in subtitles:
        if not isinstance(row, dict):
            continue
        try:
            start_sec = float(row.get("start", 0.0) or 0.0)
            end_sec = float(row.get("end", 0.0) or 0.0)
        except Exception:
            continue
        if end_sec <= start_sec:
            continue
        normalized.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "speaker_id": str(row.get("speaker_id") or "").strip() or "Speaker 1",
            }
        )
    if len(normalized) < 2:
        return {"boundaries": boundaries, "speaker_changes": speaker_changes}

    normalized.sort(key=lambda item: (item["start_sec"], item["end_sec"]))
    for current, nxt in zip(normalized, normalized[1:]):
        boundary_sec = float(current["end_sec"])
        if float(nxt["start_sec"]) > float(current["end_sec"]):
            boundary_sec = (float(current["end_sec"]) + float(nxt["start_sec"])) / 2.0
        boundary_sec = round(max(float(current["end_sec"]), boundary_sec), 3)
        boundaries.append(boundary_sec)
        if str(current["speaker_id"]) != str(nxt["speaker_id"]):
            speaker_changes.append(boundary_sec)
    return {
        "boundaries": sorted(set(boundaries)),
        "speaker_changes": sorted(set(speaker_changes)),
    }


def _load_omnivoice_audio_window(
    *,
    source_audio_path: Path,
    start_sec: float,
    end_sec: float,
) -> Tuple[np.ndarray, int]:
    """按时间窗读取单声道音频，避免长视频整段载入内存。"""

    safe_start_sec = max(0.0, float(start_sec))
    safe_end_sec = max(safe_start_sec, float(end_sec))
    if safe_end_sec <= safe_start_sec:
        return np.zeros(0, dtype=np.float32), 0

    with sf.SoundFile(str(source_audio_path)) as handle:
        sample_rate = int(handle.samplerate)
        start_frame = max(0, int(round(safe_start_sec * sample_rate)))
        end_frame = max(start_frame, int(round(safe_end_sec * sample_rate)))
        handle.seek(start_frame)
        wav = handle.read(end_frame - start_frame, dtype="float32", always_2d=True)
    if wav.size == 0:
        return np.zeros(0, dtype=np.float32), sample_rate
    mono = np.mean(wav, axis=1, dtype=np.float32)
    return np.asarray(mono, dtype=np.float32), sample_rate


def _analyze_omnivoice_split_window(
    *,
    source_audio_path: Path,
    start_sec: float,
    end_sec: float,
    frame_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_FRAME_SEC,
    hop_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_HOP_SEC,
    silence_threshold_db: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_SILENCE_THRESHOLD_DB,
    min_silence_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MIN_SILENCE_SEC,
) -> Dict[str, Any]:
    """分析切点搜索窗口内的能量和静音区，给智能切分提供依据。"""

    mono_audio, sample_rate = _load_omnivoice_audio_window(
        source_audio_path=source_audio_path,
        start_sec=start_sec,
        end_sec=end_sec,
    )
    if mono_audio.size == 0 or sample_rate <= 0:
        return {
            "times_sec": np.zeros(0, dtype=np.float32),
            "rms_values": np.zeros(0, dtype=np.float32),
            "silent_spans": [],
        }

    frame_samples = max(1, int(sample_rate * max(0.02, float(frame_sec))))
    hop_samples = max(1, int(sample_rate * max(0.01, float(hop_sec))))
    safe_threshold_rms = float(10 ** (float(silence_threshold_db) / 20.0))

    squares = np.square(np.asarray(mono_audio, dtype=np.float64))
    prefix = np.concatenate(([0.0], np.cumsum(squares, dtype=np.float64)))
    last_start = max(0, mono_audio.shape[0] - frame_samples)
    frame_starts = list(range(0, last_start + 1, hop_samples))
    if not frame_starts or frame_starts[-1] != last_start:
        frame_starts.append(last_start)

    times_sec: List[float] = []
    rms_values: List[float] = []
    half_frame_sec = float(frame_samples) / float(sample_rate) / 2.0
    for frame_start in frame_starts:
        frame_end = min(len(mono_audio), frame_start + frame_samples)
        if frame_end <= frame_start:
            continue
        energy = float(prefix[frame_end] - prefix[frame_start]) / float(frame_end - frame_start)
        rms_value = float(np.sqrt(max(0.0, energy)))
        center_sec = float(start_sec) + (float(frame_start + frame_end) / 2.0 / float(sample_rate))
        times_sec.append(center_sec)
        rms_values.append(rms_value)

    if not times_sec:
        return {
            "times_sec": np.zeros(0, dtype=np.float32),
            "rms_values": np.zeros(0, dtype=np.float32),
            "silent_spans": [],
        }

    silent_spans: List[Tuple[float, float]] = []
    silent_start_index: Optional[int] = None
    for index, rms_value in enumerate(rms_values):
        if rms_value <= safe_threshold_rms:
            if silent_start_index is None:
                silent_start_index = index
            continue
        if silent_start_index is not None:
            span_start_sec = max(float(start_sec), times_sec[silent_start_index] - half_frame_sec)
            span_end_sec = min(float(end_sec), times_sec[index - 1] + half_frame_sec)
            if span_end_sec - span_start_sec >= float(min_silence_sec):
                silent_spans.append((round(span_start_sec, 3), round(span_end_sec, 3)))
            silent_start_index = None
    if silent_start_index is not None:
        span_start_sec = max(float(start_sec), times_sec[silent_start_index] - half_frame_sec)
        span_end_sec = min(float(end_sec), times_sec[-1] + half_frame_sec)
        if span_end_sec - span_start_sec >= float(min_silence_sec):
            silent_spans.append((round(span_start_sec, 3), round(span_end_sec, 3)))

    return {
        "times_sec": np.asarray(times_sec, dtype=np.float32),
        "rms_values": np.asarray(rms_values, dtype=np.float32),
        "silent_spans": silent_spans,
    }


def _snap_omnivoice_split_to_subtitle_boundary(
    *,
    candidate_sec: float,
    boundary_points: List[float],
    speaker_change_points: List[float],
    search_start_sec: float,
    search_end_sec: float,
    allowed_snap_start_sec: Optional[float] = None,
    allowed_snap_end_sec: Optional[float] = None,
    snap_tolerance_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_BOUNDARY_SNAP_SEC,
) -> Dict[str, Any]:
    """在候选切点附近优先吸附到字幕边界，并把 speaker 切换点作为并列决胜。"""

    safe_candidate_sec = float(candidate_sec)
    allowed_boundaries = [
        float(point)
        for point in boundary_points
        if float(search_start_sec) <= float(point) <= float(search_end_sec)
        and (allowed_snap_start_sec is None or float(point) >= float(allowed_snap_start_sec))
        and (allowed_snap_end_sec is None or float(point) <= float(allowed_snap_end_sec))
        and abs(float(point) - safe_candidate_sec) <= float(snap_tolerance_sec)
    ]
    if not allowed_boundaries:
        return {
            "split_sec": round(safe_candidate_sec, 3),
            "snapped_to_boundary": False,
            "snapped_to_speaker_change": False,
        }

    speaker_change_set = {round(float(point), 3) for point in speaker_change_points}
    best_boundary = min(
        allowed_boundaries,
        key=lambda point: (
            abs(float(point) - safe_candidate_sec),
            0 if round(float(point), 3) in speaker_change_set else 1,
            float(point),
        ),
    )
    return {
        "split_sec": round(float(best_boundary), 3),
        "snapped_to_boundary": True,
        "snapped_to_speaker_change": round(float(best_boundary), 3) in speaker_change_set,
    }


def _pick_omnivoice_adaptive_split_point(
    *,
    source_audio_path: Optional[Path],
    target_sec: float,
    search_start_sec: float,
    search_end_sec: float,
    boundary_points: List[float],
    speaker_change_points: List[float],
) -> Dict[str, Any]:
    """在目标切点附近寻找更适合 separation 的实际切点。"""

    safe_target_sec = min(max(float(target_sec), float(search_start_sec)), float(search_end_sec))
    if source_audio_path is None or not Path(source_audio_path).exists():
        return {
            "split_sec": round(safe_target_sec, 3),
            "split_reason": "fallback_fixed",
            "snapped_to_boundary": False,
            "snapped_to_speaker_change": False,
        }

    analysis = _analyze_omnivoice_split_window(
        source_audio_path=Path(source_audio_path),
        start_sec=search_start_sec,
        end_sec=search_end_sec,
    )
    times_sec_raw = analysis.get("times_sec")
    rms_values_raw = analysis.get("rms_values")
    times_sec = np.asarray(times_sec_raw if times_sec_raw is not None else np.zeros(0, dtype=np.float32), dtype=np.float32)
    rms_values = np.asarray(rms_values_raw if rms_values_raw is not None else np.zeros(0, dtype=np.float32), dtype=np.float32)
    silent_spans = list(analysis.get("silent_spans") or [])

    candidate_sec = safe_target_sec
    split_reason = "fallback_fixed"
    silence_span_for_snap: Optional[Tuple[float, float]] = None
    if silent_spans:
        best_start_sec, best_end_sec = min(
            silent_spans,
            key=lambda span: abs(((float(span[0]) + float(span[1])) / 2.0) - safe_target_sec),
        )
        candidate_sec = (float(best_start_sec) + float(best_end_sec)) / 2.0
        split_reason = "silence"
        silence_span_for_snap = (float(best_start_sec), float(best_end_sec))
    elif times_sec.size > 0 and rms_values.size == times_sec.size:
        rms_min = float(np.min(rms_values))
        rms_span = max(1e-8, float(np.max(rms_values)) - rms_min)
        distance_norm = np.abs(times_sec.astype(np.float64) - safe_target_sec) / max(
            1.0,
            float(search_end_sec) - float(search_start_sec),
        )
        rms_norm = (rms_values.astype(np.float64) - rms_min) / rms_span
        scores = rms_norm + (0.15 * distance_norm)
        best_index = int(np.argmin(scores))
        candidate_sec = float(times_sec[best_index])
        split_reason = "low_energy"

    snapped = _snap_omnivoice_split_to_subtitle_boundary(
        candidate_sec=candidate_sec,
        boundary_points=boundary_points,
        speaker_change_points=speaker_change_points,
        search_start_sec=search_start_sec,
        search_end_sec=search_end_sec,
        allowed_snap_start_sec=silence_span_for_snap[0] if silence_span_for_snap else None,
        allowed_snap_end_sec=silence_span_for_snap[1] if silence_span_for_snap else None,
    )
    return {
        "split_sec": round(float(snapped["split_sec"]), 3),
        "split_reason": split_reason,
        "snapped_to_boundary": bool(snapped["snapped_to_boundary"]),
        "snapped_to_speaker_change": bool(snapped["snapped_to_speaker_change"]),
    }


def _build_omnivoice_chunk_plan(
    *,
    total_duration_sec: float,
    source_audio_path: Optional[Path] = None,
    subtitle_hints: Optional[List[Dict[str, Any]]] = None,
    chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC,
    min_chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MIN_CHUNK_SEC,
    max_chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MAX_CHUNK_SEC,
    search_window_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_SEARCH_WINDOW_SEC,
) -> List[Dict[str, Any]]:
    """构建长视频 separation 的智能切块计划。"""

    safe_total = max(0.0, float(total_duration_sec))
    if safe_total <= 1e-6:
        return []
    safe_chunk = max(1.0, float(chunk_duration_sec))
    safe_min_chunk = max(1.0, min(float(min_chunk_duration_sec), safe_chunk))
    safe_max_chunk = max(safe_chunk, float(max_chunk_duration_sec))
    safe_search_window = max(1.0, float(search_window_sec))
    hint_points = _build_omnivoice_cut_hint_points(subtitle_hints)
    boundary_points = list(hint_points.get("boundaries") or [])
    speaker_change_points = list(hint_points.get("speaker_changes") or [])

    # 先选一个整体可行、且平均块长尽量接近目标块长的 chunk 数，避免后面把尾块挤到不合理长度。
    min_chunk_count = max(1, int(np.ceil(safe_total / safe_max_chunk)))
    max_chunk_count = max(min_chunk_count, int(np.floor(safe_total / safe_min_chunk)))
    feasible_chunk_counts = [
        count
        for count in range(min_chunk_count, max_chunk_count + 1)
        if (count * safe_min_chunk) <= safe_total <= (count * safe_max_chunk)
    ]
    if not feasible_chunk_counts:
        feasible_chunk_counts = [min_chunk_count]
    target_chunk_count = min(
        feasible_chunk_counts,
        key=lambda count: (
            abs((safe_total / float(count)) - safe_chunk),
            abs(float(count) - (safe_total / safe_chunk)),
            count,
        ),
    )

    plan: List[Dict[str, Any]] = []
    start_sec = 0.0
    for chunk_index in range(target_chunk_count):
        remaining_chunks = target_chunk_count - chunk_index
        if remaining_chunks <= 1:
            plan.append(
                {
                    "start_sec": round(start_sec, 3),
                    "end_sec": round(safe_total, 3),
                    "target_end_sec": round(safe_total, 3),
                    "split_reason": "tail",
                    "snapped_to_boundary": False,
                    "snapped_to_speaker_change": False,
                }
            )
            break

        remaining_sec = safe_total - start_sec
        average_chunk_sec = remaining_sec / float(remaining_chunks)
        target_end_sec = start_sec + min(safe_max_chunk, max(safe_min_chunk, average_chunk_sec))
        earliest_end_sec = max(
            start_sec + safe_min_chunk,
            safe_total - ((remaining_chunks - 1) * safe_max_chunk),
        )
        latest_end_sec = min(
            start_sec + safe_max_chunk,
            safe_total - ((remaining_chunks - 1) * safe_min_chunk),
        )
        search_start_sec = max(earliest_end_sec, target_end_sec - safe_search_window)
        search_end_sec = min(latest_end_sec, target_end_sec + safe_search_window)

        split_meta = _pick_omnivoice_adaptive_split_point(
            source_audio_path=source_audio_path,
            target_sec=target_end_sec,
            search_start_sec=search_start_sec,
            search_end_sec=search_end_sec,
            boundary_points=boundary_points,
            speaker_change_points=speaker_change_points,
        )
        actual_end_sec = min(latest_end_sec, max(earliest_end_sec, float(split_meta["split_sec"])))
        actual_end_sec = round(actual_end_sec, 3)
        if actual_end_sec <= start_sec:
            actual_end_sec = round(min(safe_total, max(earliest_end_sec, start_sec + 1.0)), 3)
            split_meta["split_reason"] = "fallback_fixed"
            split_meta["snapped_to_boundary"] = False
            split_meta["snapped_to_speaker_change"] = False

        plan.append(
            {
                "start_sec": round(start_sec, 3),
                "end_sec": actual_end_sec,
                "target_end_sec": round(target_end_sec, 3),
                "split_reason": str(split_meta.get("split_reason") or "fallback_fixed"),
                "snapped_to_boundary": bool(split_meta.get("snapped_to_boundary")),
                "snapped_to_speaker_change": bool(split_meta.get("snapped_to_speaker_change")),
            }
        )
        start_sec = actual_end_sec
    return plan


def _build_omnivoice_chunk_ranges(
    *,
    total_duration_sec: float,
    source_audio_path: Optional[Path] = None,
    subtitle_hints: Optional[List[Dict[str, Any]]] = None,
    chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC,
    min_chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MIN_CHUNK_SEC,
    max_chunk_duration_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_MAX_CHUNK_SEC,
    search_window_sec: float = OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_SEARCH_WINDOW_SEC,
) -> List[Tuple[float, float]]:
    """兼容旧调用，返回智能切块计划里的 start/end 范围。"""

    plan = _build_omnivoice_chunk_plan(
        total_duration_sec=total_duration_sec,
        source_audio_path=source_audio_path,
        subtitle_hints=subtitle_hints,
        chunk_duration_sec=chunk_duration_sec,
        min_chunk_duration_sec=min_chunk_duration_sec,
        max_chunk_duration_sec=max_chunk_duration_sec,
        search_window_sec=search_window_sec,
    )
    return [
        (float(item["start_sec"]), float(item["end_sec"]))
        for item in plan
    ]


def _prepare_omnivoice_source_stems_chunked(
    *,
    input_media_path: Path,
    source_audio_path: Path,
    source_vocals_path: Path,
    source_bgm_path: Path,
    separation_report_path: Path,
    demucs_out: Path,
    separator_device: str,
    total_duration_sec: float,
    subtitle_hints: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """对超过阈值的长视频按时间块做人声分离，并回并成整片 stem。"""

    stems_root = source_audio_path.parent
    chunk_plan = _build_omnivoice_chunk_plan(
        total_duration_sec=total_duration_sec,
        source_audio_path=source_audio_path,
        subtitle_hints=subtitle_hints,
    )
    vocals_segments: List[Dict[str, Any]] = []
    bgm_segments: List[Dict[str, Any]] = []
    range_reports: List[Dict[str, Any]] = []
    has_any_degraded_chunk = False
    all_ranges_have_bgm = True

    for index, chunk_meta in enumerate(chunk_plan, start=1):
        start_sec = float(chunk_meta["start_sec"])
        end_sec = float(chunk_meta["end_sec"])
        range_dir = stems_root / f"range_{index:04d}"
        range_dir.mkdir(parents=True, exist_ok=True)
        range_audio_path = range_dir / "range_audio.wav"
        range_vocals_path = range_dir / "range_vocals.wav"
        range_bgm_path = range_dir / "range_bgm.wav"
        _extract_omnivoice_audio_segment(
            input_media_path=input_media_path,
            output_wav=range_audio_path,
            start_sec=start_sec,
            end_sec=end_sec,
        )
        separation_result = _attempt_omnivoice_demucs_separation(
            input_audio_path=range_audio_path,
            demucs_out=demucs_out / f"range_{index:04d}",
            separator_device=separator_device,
        )
        vocals_src = separation_result.get("vocals_src")
        bgm_src = separation_result.get("bgm_src")
        attempts = list(separation_result.get("attempts") or [])
        chunk_has_bgm = False
        chunk_status = "ok"

        if vocals_src is None:
            has_any_degraded_chunk = True
            chunk_status = "failed_fallback_vocals_only"
            shutil.copy2(range_audio_path, range_vocals_path)
            if range_bgm_path.exists():
                range_bgm_path.unlink()
            all_ranges_have_bgm = False
        else:
            shutil.copy2(vocals_src, range_vocals_path)
            if bgm_src and Path(bgm_src).exists():
                shutil.copy2(Path(bgm_src), range_bgm_path)
                chunk_has_bgm = True
            else:
                all_ranges_have_bgm = False
                if range_bgm_path.exists():
                    range_bgm_path.unlink()

        vocals_segments.append(
            {
                "id": f"range_{index:04d}",
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "tts_audio_path": str(range_vocals_path.resolve()),
            }
        )
        if chunk_has_bgm:
            bgm_segments.append(
                {
                    "id": f"range_{index:04d}",
                    "start_sec": float(start_sec),
                    "end_sec": float(end_sec),
                    "tts_audio_path": str(range_bgm_path.resolve()),
                }
            )
        range_reports.append(
            {
                "range_index": index,
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "status": chunk_status,
                "target_end_sec": float(chunk_meta.get("target_end_sec", end_sec) or end_sec),
                "actual_end_sec": float(end_sec),
                "split_reason": str(chunk_meta.get("split_reason") or "tail"),
                "snapped_to_boundary": bool(chunk_meta.get("snapped_to_boundary")),
                "snapped_to_speaker_change": bool(chunk_meta.get("snapped_to_speaker_change")),
                "attempts": attempts,
                "range_audio": str(range_audio_path.resolve()),
                "range_vocals": str(range_vocals_path.resolve()),
                "range_bgm": str(range_bgm_path.resolve()) if chunk_has_bgm else None,
                "has_bgm_track": chunk_has_bgm,
            }
        )

    compose_vocals_master(
        segments=vocals_segments,
        output_path=source_vocals_path,
        source_audio_fallback=source_audio_path,
    )

    has_bgm_track = all_ranges_have_bgm and len(bgm_segments) == len(vocals_segments)
    # 只要任一块没有可靠 BGM，就整片关闭 BGM 回并，避免出现局部原人声残留。
    if has_bgm_track:
        compose_vocals_master(
            segments=bgm_segments,
            output_path=source_bgm_path,
            source_audio_fallback=None,
        )
    elif source_bgm_path.exists():
        source_bgm_path.unlink()

    top_level_status = "ok"
    if has_any_degraded_chunk:
        top_level_status = "partial_fallback_vocals_only"
        if all(item.get("status") == "failed_fallback_vocals_only" for item in range_reports):
            top_level_status = "failed_fallback_vocals_only"

    separation_report_path.write_text(
        json.dumps(
            {
                "status": top_level_status,
                "mode": "chunked",
                "separator_device": separator_device,
                "threshold_sec": OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_THRESHOLD_SEC,
                "chunk_duration_sec": OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_CHUNK_SEC,
                "total_duration_sec": round(float(total_duration_sec), 3),
                "source_audio": str(source_audio_path.resolve()),
                "source_vocals": str(source_vocals_path.resolve()),
                "source_bgm": str(source_bgm_path.resolve()) if has_bgm_track else None,
                "has_bgm_track": has_bgm_track,
                "ranges": range_reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "separator_device": separator_device,
        "has_bgm_track": has_bgm_track,
        "degraded_to_vocals_only": top_level_status != "ok",
        "mode": "chunked",
        "range_count": len(range_reports),
    }


def _prepare_omnivoice_source_stems(
    *,
    input_media_path: Path,
    source_audio_path: Path,
    source_vocals_path: Path,
    source_bgm_path: Path,
    separation_report_path: Path,
    demucs_out: Path,
    enable_source_separation: bool = True,
    subtitle_hints: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """提取源音频并根据时长选择整段或分段人声分离策略。"""

    extract_source_audio(input_media=input_media_path, output_wav=source_audio_path)
    if not bool(enable_source_separation):
        return _prepare_omnivoice_source_stems_passthrough(
            source_audio_path=source_audio_path,
            source_vocals_path=source_vocals_path,
            source_bgm_path=source_bgm_path,
            separation_report_path=separation_report_path,
        )
    separator_device = _resolve_omnivoice_separator_device()
    total_duration_sec = max(0.0, float(ffprobe_duration(input_media_path)))
    if total_duration_sec > OMNIVOICE_LONG_VIDEO_CHUNKED_SEPARATION_THRESHOLD_SEC:
        return _prepare_omnivoice_source_stems_chunked(
            input_media_path=input_media_path,
            source_audio_path=source_audio_path,
            source_vocals_path=source_vocals_path,
            source_bgm_path=source_bgm_path,
            separation_report_path=separation_report_path,
            demucs_out=demucs_out,
            separator_device=separator_device,
            total_duration_sec=total_duration_sec,
            subtitle_hints=subtitle_hints,
        )
    return _prepare_omnivoice_source_stems_single_pass(
        source_audio_path=source_audio_path,
        source_vocals_path=source_vocals_path,
        source_bgm_path=source_bgm_path,
        separation_report_path=separation_report_path,
        demucs_out=demucs_out,
        separator_device=separator_device,
    )


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
        enable_source_separation=bool(manifest.get("enable_source_separation", True)),
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
    task["source_lang"] = str(manifest.get("source_lang") or task["source_lang"])
    task["source_lang_runtime"] = str(manifest.get("source_lang_runtime") or task["source_lang_runtime"])
    task["target_lang"] = str(manifest.get("target_lang") or task["target_lang"])
    task["target_lang_runtime"] = str(manifest.get("target_lang_runtime") or task["target_lang_runtime"])
    task["artifacts"] = list(manifest.get("artifacts") or [])
    task["result_srt"] = str((manifest.get("paths") or {}).get("dubbed_final_srt") or "") or None
    task["result_audio"] = str((manifest.get("paths") or {}).get("dubbed_mix") or "") or None
    task["batch_manifest_path"] = str((out_root / "manifest.json").resolve())
    _annotate_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=True)
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
    enable_source_separation: bool = True,
    uploaded_speaker_ref_map: Optional[Dict[str, Dict[str, Any]]] = None,
    resume_context: Optional[Dict[str, Any]] = None,
) -> None:
    """后台执行独立 OmniVoice dubbing 链路。"""

    display_source_lang, runtime_source_lang = _normalize_omnivoice_language_pair(source_lang, default="auto")
    display_target_lang, runtime_target_lang = _normalize_omnivoice_language_pair(target_lang, default="Chinese")
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
    resume_context = dict(resume_context or {})

    # 先确认独立 OmniVoice 后端不仅活着，而且模型已经就绪，再进入后续昂贵步骤。
    _ensure_omnivoice_backend_ready(omnivoice_api_url)
    _set_task(task_id, status="running", stage="dubbing:preparing", progress=1.0)

    # 分段人声分离只需要时间边界提示，不依赖后续翻译结果；这里优先用 source 字幕，缺失时退回已给出的 translated 字幕。
    chunk_hint_rows = source_subtitles if source_subtitles else translated_subtitles
    chunk_hint_rows = _ensure_speaker_ids(
        chunk_hint_rows,
        fallback_rows=source_subtitles or translated_subtitles,
    )

    if bool(resume_context.get("reuse_stems")):
        resumed_source_audio = _resolve_existing_optional_path(resume_context.get("source_audio_path"))
        resumed_source_vocals = _resolve_existing_optional_path(resume_context.get("source_vocals_path"))
        resumed_source_bgm = _resolve_existing_optional_path(resume_context.get("source_bgm_path"))
        resumed_separation_report = _resolve_existing_optional_path(resume_context.get("separation_report_path"))
        if resumed_source_audio is not None and resumed_source_audio.resolve() != source_audio_path.resolve():
            shutil.copy2(resumed_source_audio, source_audio_path)
        if resumed_source_vocals is not None and resumed_source_vocals.resolve() != source_vocals_path.resolve():
            shutil.copy2(resumed_source_vocals, source_vocals_path)
        if resumed_source_bgm is not None and resumed_source_bgm.resolve() != source_bgm_path.resolve():
            shutil.copy2(resumed_source_bgm, source_bgm_path)
        if resumed_separation_report is not None and resumed_separation_report.resolve() != separation_report_path.resolve():
            shutil.copy2(resumed_separation_report, separation_report_path)
        has_bgm_track = bool(resume_context.get("has_bgm_track"))
    else:
        # 先做人声/背景分离，再让中间链路只用人声。
        _set_task(task_id, stage="dubbing:separating", progress=7.0)
        demucs_out = stems_root / "demucs_tmp"
        separation_meta = _prepare_omnivoice_source_stems(
            input_media_path=input_media_path,
            source_audio_path=source_audio_path,
            source_vocals_path=source_vocals_path,
            source_bgm_path=source_bgm_path,
            separation_report_path=separation_report_path,
            demucs_out=demucs_out,
            enable_source_separation=enable_source_separation,
            subtitle_hints=chunk_hint_rows,
        )
        has_bgm_track = bool(separation_meta.get("has_bgm_track"))

    if bool(resume_context.get("reuse_selected_subtitles")):
        selected_subtitles = list(resume_context.get("selected_subtitles") or [])
        selected_mode = "translated"
        selected_subtitles = _ensure_speaker_ids(
            selected_subtitles,
            fallback_rows=source_subtitles,
            force_align_by_time=False,
        )
        selected_subtitles = _drop_empty_subtitle_rows(selected_subtitles, label="selected")
    else:
        selected_subtitles, selected_mode = _translate_subtitles_if_needed(
            subtitles_mode=subtitle_mode,
            source_rows=_optimize_omnivoice_source_rows(
                source_subtitles,
                subtitle_mode=subtitle_mode,
            ),
            translated_rows=translated_subtitles,
            source_lang=display_source_lang,
            target_lang=display_target_lang,
            api_key=api_key,
            translate_base_url=translate_base_url,
            translate_model=translate_model,
            translate_system_prompt=translate_system_prompt,
            task_id=task_id,
        )
        selected_subtitles = _optimize_omnivoice_selected_rows(
            selected_subtitles,
            subtitle_mode=selected_mode,
        )
        selected_subtitles = _ensure_speaker_ids(
            selected_subtitles,
            fallback_rows=source_subtitles,
            force_align_by_time=True,
        )
        selected_subtitles = _drop_empty_subtitle_rows(selected_subtitles, label="selected")
    selected_subtitles, dedup_count = _deduplicate_translated_rows(selected_subtitles)
    if dedup_count > 0:
        logger.warning(
            "OmniVoice task %s removed %d near-duplicate translated rows",
            task_id,
            dedup_count,
        )
    selected_subtitles, adjusted_pairs = _rebalance_omnivoice_synthesis_rows(selected_subtitles)
    if adjusted_pairs > 0:
        logger.warning(
            "OmniVoice task %s rebalanced %d extreme subtitle timing pairs before synthesis",
            task_id,
            adjusted_pairs,
        )
    selected_subtitles, equalized_pairs = _equalize_cps_across_neighbors(selected_subtitles)
    if equalized_pairs > 0:
        logger.info(
            "OmniVoice task %s equalized CPS for %d neighbor pairs",
            task_id,
            equalized_pairs,
        )
    selected_subtitles, merged_short_lines = _merge_short_lines_for_tts(selected_subtitles)
    if merged_short_lines > 0:
        logger.info(
            "OmniVoice task %s merged %d short lines toward ~25 chars",
            task_id,
            merged_short_lines,
        )
    selected_subtitles, merged_short = _merge_ultra_short_segments(selected_subtitles)
    if merged_short > 0:
        logger.info(
            "OmniVoice task %s merged %d ultra-short segments into same-speaker neighbors",
            task_id,
            merged_short,
        )
    source_reference_subtitles = _ensure_speaker_ids(source_subtitles, fallback_rows=selected_subtitles)
    selected_subtitles_path = out_root / "selected_subtitles.srt"
    selected_subtitles_path.write_text(format_srt(selected_subtitles), encoding="utf-8")
    selected_subtitles_with_speaker_path = out_root / "selected_subtitles_with_speakers.srt"
    selected_subtitles_with_speaker_rows = _build_selected_subtitles_with_speaker_rows(selected_subtitles)
    selected_subtitles_with_speaker_path.write_text(
        format_srt(selected_subtitles_with_speaker_rows),
        encoding="utf-8",
    )

    if not selected_subtitles:
        raise RuntimeError("No usable subtitles for OmniVoice dubbing")

    _persist_omnivoice_task_manifest(
        task_id=task_id,
        out_root=out_root,
        source_audio_path=source_audio_path,
        source_vocals_path=source_vocals_path,
        source_bgm_path=source_bgm_path,
        speaker_ref_map_path=speaker_ref_map_path,
        final_srt_path=final_dir / "dubbed_final_full.srt",
        final_vocals_path=final_dir / "dubbed_vocals_full.wav",
        final_mix_path=final_dir / "dubbed_mix_full.wav",
        final_video_path=final_dir / "dubbed_video_full.mp4",
        separated_video_audio_path=final_dir / "dubbed_audio_for_video.m4a",
        separation_report_path=separation_report_path,
        speaker_reference_dir=speaker_root,
        subtitles_path=selected_subtitles_path,
        subtitles_with_speaker_path=selected_subtitles_with_speaker_path,
        final_ass_path=final_dir / "dubbed_final_full-styled.ass",
        burned_video_path=final_dir / "dubbed_video_full_burned.mp4",
    )

    detected_speaker_ids = sorted(
        {
            str(row.get("speaker_id") or "").strip() or "Speaker 1"
            for row in selected_subtitles
        }
    )

    # speaker 参考音优先使用用户上传映射；缺失 speaker 自动从预存目录补齐。
    _set_task(task_id, stage="dubbing:preparing_refs", progress=12.0)
    reference_mode = "auto_aggregate"
    if bool(resume_context.get("reuse_speaker_refs")):
        speaker_ref_map = {
            str(speaker_id): dict(meta)
            for speaker_id, meta in dict(resume_context.get("speaker_ref_map") or {}).items()
        }
        reference_mode = str(manifest_mode) if (manifest_mode := resume_context.get("speaker_reference_mode")) else "resumed"
    elif uploaded_speaker_ref_map:
        missing_speakers = [
            speaker_id
            for speaker_id in detected_speaker_ids
            if speaker_id not in uploaded_speaker_ref_map
        ]
        speaker_ref_map = {
            speaker_id: dict(uploaded_speaker_ref_map[speaker_id])
            for speaker_id in detected_speaker_ids
            if speaker_id in uploaded_speaker_ref_map
        }
        if missing_speakers:
            uploaded_source_filenames = [
                Path(str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "")).name
                for meta in uploaded_speaker_ref_map.values()
                if str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "").strip()
            ]
            speaker_gender_hints = _infer_missing_speaker_gender_hints(
                vocals_path=source_vocals_path,
                subtitles=selected_subtitles,
                missing_speaker_ids=missing_speakers,
                out_root=out_root,
            )
            preset_map = _pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=missing_speakers,
                target_lang=display_target_lang,
                out_root=out_root,
                speaker_gender_hints=speaker_gender_hints,
                excluded_source_filenames=uploaded_source_filenames,
            )
            speaker_ref_map.update(preset_map)
            reference_mode = "uploaded_mixed"
        else:
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
        "fixed_ref_text": _speaker_ref_text_for_target_lang(display_target_lang) if reference_mode == "uploaded_strict" else None,
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
    _set_task(task_id, source_lang=display_source_lang, source_lang_runtime=runtime_source_lang, target_lang=display_target_lang, target_lang_runtime=runtime_target_lang)
    _persist_omnivoice_task_manifest(
        task_id=task_id,
        out_root=out_root,
        source_audio_path=source_audio_path,
        source_vocals_path=source_vocals_path,
        source_bgm_path=source_bgm_path,
        speaker_ref_map_path=speaker_ref_map_path,
        final_srt_path=final_dir / "dubbed_final_full.srt",
        final_vocals_path=final_dir / "dubbed_vocals_full.wav",
        final_mix_path=final_dir / "dubbed_mix_full.wav",
        final_video_path=final_dir / "dubbed_video_full.mp4",
        separated_video_audio_path=final_dir / "dubbed_audio_for_video.m4a",
        separation_report_path=separation_report_path,
        speaker_reference_dir=speaker_root,
        subtitles_path=selected_subtitles_path,
        subtitles_with_speaker_path=selected_subtitles_with_speaker_path,
        final_ass_path=final_dir / "dubbed_final_full-styled.ass",
        burned_video_path=final_dir / "dubbed_video_full_burned.mp4",
    )

    completed_segment_indices = set(int(item) for item in list(resume_context.get("completed_segment_indices") or []))
    segment_results = sorted(
        [dict(item) for item in list(resume_context.get("reusable_segment_results") or [])],
        key=lambda item: float(item.get("start_sec", 0.0) or 0.0),
    )
    _set_task(
        task_id,
        total_segments=len(selected_subtitles),
        processed_segments=len(completed_segment_indices),
        stage="dubbing:generating",
        progress=15.0,
    )

    total_segments = len(selected_subtitles)
    for index, row in enumerate(selected_subtitles, start=1):
        if index in completed_segment_indices:
            _set_task(
                task_id,
                processed_segments=index,
                progress=15.0 + (65.0 * (len(completed_segment_indices) / max(1, total_segments))),
                stage="dubbing:generating",
            )
            continue
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
        if _is_ultra_short_for_tts(generation_text, duration_sec):
            logger.warning(
                "OmniVoice seg #%04d ultra-short (%d chars, %.2fs) — generating silence instead of TTS",
                index, len(generation_text.replace(" ", "")), duration_sec,
            )
            final_segment_path = segment_dir / f"seg_{index:04d}.wav"
            _generate_silence_wav(final_segment_path, duration_sec)
            actual_duration = round(duration_sec, 3)
            segment_speed = 1.0
            fit_action = "silence_skip"
        else:
            segment_speed = _compute_tts_speed_for_segment(generation_text, duration_sec, runtime_target_lang)
            generated_bytes = _call_remote_generate(
                api_url=omnivoice_api_url,
                text=generation_text,
                language=runtime_target_lang,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text_for_generation,
                instruct="",
                duration=duration_sec,
                speed=segment_speed,
            )
            output_segment_path.write_bytes(generated_bytes)
            normalized_segment_path = segment_dir / f"seg_{index:04d}_normalized.wav"
            _, fit_action = _normalize_generated_segment_audio(
                input_path=output_segment_path,
                output_path=normalized_segment_path,
                target_duration_sec=duration_sec,
            )
            final_segment_path = segment_dir / f"seg_{index:04d}.wav"
            shutil.copy2(normalized_segment_path, final_segment_path)
            actual_duration = round(float(sf.info(str(final_segment_path)).duration), 3)
        segment_manifest = {
            "id": f"seg_{index:04d}",
            "speaker_id": speaker_id,
            "start_sec": float(row.get("start", 0.0) or 0.0),
            "end_sec": float(row.get("end", 0.0) or 0.0),
            "text": generation_text,
            "ref_audio_path": str(ref_audio_path.resolve()),
            "tts_audio_path": str(final_segment_path.resolve()),
            "duration_sec": round(duration_sec, 3),
            "normalized_duration_sec": actual_duration,
            "tts_speed": round(segment_speed, 3),
            "fit_action": fit_action,
            "sync_ratio": round(actual_duration / max(0.01, duration_sec), 3),
        }
        (segment_dir / "manifest.json").write_text(json.dumps(segment_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        segment_results.append(segment_manifest)
        completed_segment_indices.add(index)
        _set_task(
            task_id,
            processed_segments=len(completed_segment_indices),
            progress=15.0 + (65.0 * (index / max(1, total_segments))),
            stage="dubbing:generating",
        )
        _persist_omnivoice_task_manifest(
            task_id=task_id,
            out_root=out_root,
            source_audio_path=source_audio_path,
            source_vocals_path=source_vocals_path,
            source_bgm_path=source_bgm_path,
            speaker_ref_map_path=speaker_ref_map_path,
            final_srt_path=final_dir / "dubbed_final_full.srt",
            final_vocals_path=final_dir / "dubbed_vocals_full.wav",
            final_mix_path=final_dir / "dubbed_mix_full.wav",
            final_video_path=final_dir / "dubbed_video_full.mp4",
            separated_video_audio_path=final_dir / "dubbed_audio_for_video.m4a",
            separation_report_path=separation_report_path,
            speaker_reference_dir=speaker_root,
            subtitles_path=selected_subtitles_path,
            subtitles_with_speaker_path=selected_subtitles_with_speaker_path,
            final_ass_path=final_dir / "dubbed_final_full-styled.ass",
            burned_video_path=final_dir / "dubbed_video_full_burned.mp4",
        )

    segment_results.sort(key=lambda item: float(item.get("start_sec", 0.0) or 0.0))

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
    final_srt_rows = _rebalance_omnivoice_final_srt_rows(selected_subtitles)
    final_srt_path.write_text(format_srt(final_srt_rows), encoding="utf-8")
    final_ass_path = final_dir / "dubbed_final_full-styled.ass"
    final_ass_path.write_text(
        _build_styled_ass_from_rows(final_srt_rows, source_name=final_srt_path.name),
        encoding="utf-8",
    )

    final_video_path: Optional[Path] = None
    burned_video_path: Optional[Path] = None
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
        _set_task(task_id, stage="dubbing:burning_subtitles", progress=96.0)
        burned_video_path = final_dir / "dubbed_video_full_burned.mp4"
        burn_ass_subtitles_into_video(
            input_video_path=final_video_path,
            ass_subtitle_path=final_ass_path,
            output_video_path=burned_video_path,
            video_codec="libx264",
            crf=16,
            preset="slow",
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
        subtitles_with_speaker_path=selected_subtitles_with_speaker_path,
        final_ass_path=final_ass_path,
        burned_video_path=burned_video_path,
    )
    task["artifacts"] = list(manifest.get("artifacts") or [])
    task["batch_manifest_path"] = str((out_root / "manifest.json").resolve())
    task["out_root"] = str(out_root.resolve())
    task["result_audio"] = str(final_mix_path.resolve())
    task["result_srt"] = str(final_srt_path.resolve())
    _generate_synthesis_diagnostic_report(
        segment_results=segment_results,
        out_root=out_root,
        target_lang=display_target_lang,
    )
    _set_task(task_id, status="completed", stage="completed", progress=100.0)
    _annotate_task_with_resume_state(task, manifest=manifest, out_root=out_root, from_disk=False)


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
        out_root = _resolve_output_dir(task_id)
        _persist_omnivoice_task_manifest(
            task_id=task_id,
            out_root=out_root,
            source_audio_path=out_root / "stems" / "source_audio.wav",
            source_vocals_path=out_root / "stems" / "full_source_vocals.wav",
            source_bgm_path=out_root / "stems" / "full_source_bgm.wav",
            speaker_ref_map_path=out_root / "speaker_ref_map.json",
            final_srt_path=out_root / "final" / "dubbed_final_full.srt",
            final_vocals_path=out_root / "final" / "dubbed_vocals_full.wav",
            final_mix_path=out_root / "final" / "dubbed_mix_full.wav",
            final_video_path=out_root / "final" / "dubbed_video_full.mp4",
            separated_video_audio_path=out_root / "final" / "dubbed_audio_for_video.m4a",
            separation_report_path=out_root / "separation_report.json",
            speaker_reference_dir=out_root / "stems" / "speaker_refs",
            subtitles_path=out_root / "selected_subtitles.srt",
            subtitles_with_speaker_path=out_root / "selected_subtitles_with_speakers.srt",
            final_ass_path=out_root / "final" / "dubbed_final_full-styled.ass",
            burned_video_path=out_root / "final" / "dubbed_video_full_burned.mp4",
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
    enable_source_separation: bool = Form(True),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
    omnivoice_api_url: str = Form(DEFAULT_OMNIVOICE_API_URL),
    prepared_batch_id: str = Form(""),
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

    prepared_batch_id = str(prepared_batch_id or "").strip()
    reuse_prepared_batch = False
    if prepared_batch_id:
        prepared_manifest = _load_manifest(prepared_batch_id)
        if prepared_manifest is None:
            raise HTTPException(status_code=400, detail=f"Prepared batch not found: {prepared_batch_id}")
        selected_path = Path(str((prepared_manifest.get("paths") or {}).get("selected_subtitles") or "")).expanduser()
        if not selected_path.exists():
            raise HTTPException(status_code=400, detail=f"Prepared selected_subtitles.srt missing: {selected_path}")
        selected_items = parse_srt(selected_path.read_text(encoding="utf-8"))
        if not selected_items:
            raise HTTPException(status_code=400, detail=f"Prepared selected_subtitles.srt is empty: {selected_path}")
        translated_rows = _ensure_speaker_ids(
            selected_items,
            fallback_rows=source_rows,
            force_align_by_time=True,
        )
        subtitle_mode = "translated"
        reuse_prepared_batch = True

    resolved_task_id = prepared_batch_id if reuse_prepared_batch else _build_readable_task_id()
    out_root = _resolve_output_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)

    selected_rows_for_preview = _ensure_speaker_ids(
        translated_rows if translated_rows else source_rows,
        fallback_rows=source_rows,
        force_align_by_time=True,
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
                "ref_text": _speaker_ref_text_for_target_lang(target_lang),
                "duration": round(float(sf.info(stored_path).duration), 3),
                "source_count": 1,
                "reference_mode": "uploaded_partial",
                "upload_filename": Path(str(ref_file.filename or "")).name,
            }

    if uploaded_speaker_ref_map:
        missing_speaker_ids = [
            speaker_id
            for speaker_id in speaker_ids
            if speaker_id not in uploaded_speaker_ref_map
        ]
        uploaded_source_filenames = [
            Path(str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "")).name
            for meta in uploaded_speaker_ref_map.values()
            if str(meta.get("upload_filename") or meta.get("source_path") or meta.get("ref_audio") or "").strip()
        ]
        _validate_preset_ref_voices_available(
            target_lang=target_lang,
            missing_speaker_ids=missing_speaker_ids,
            excluded_source_filenames=uploaded_source_filenames,
        )

    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=display_name,
        input_media_path=source_media_path,
        subtitle_mode=subtitle_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        enable_source_separation=enable_source_separation,
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
            enable_source_separation=enable_source_separation,
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


@router.post("/prepare-subtitles-from-project")
async def prepare_omnivoice_subtitles_from_project(
    filename: str = Form(""),
    original_filename: str = Form(""),
    task_id: str = Form(""),
    source_subtitles_json: str = Form(""),
    translated_subtitles_json: str = Form(""),
    subtitle_mode: str = Form("auto"),
    source_lang: str = Form("auto"),
    target_lang: str = Form("Chinese"),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
    translate_system_prompt: str = Form(""),
) -> Dict[str, Any]:
    """仅生成并落盘 selected_subtitles.srt，供人工 review 后再启动配音。"""

    source_media_path = _resolve_project_media_path(filename, task_id)
    display_name = _sanitize_filename(original_filename or source_media_path.name)
    source_rows = _normalize_subtitles_payload(source_subtitles_json, field_name="source_subtitles_json")
    translated_rows = _normalize_subtitles_payload(translated_subtitles_json, field_name="translated_subtitles_json")
    if not source_rows and not translated_rows:
        raise HTTPException(status_code=400, detail="OmniVoice requires project subtitles")

    resolved_task_id = _build_readable_task_id()
    out_root = _resolve_output_dir(resolved_task_id)
    out_root.mkdir(parents=True, exist_ok=True)

    selected_subtitles, selected_mode = _translate_subtitles_if_needed(
        subtitles_mode=subtitle_mode,
        source_rows=_optimize_omnivoice_source_rows(
            source_rows,
            subtitle_mode=subtitle_mode,
        ),
        translated_rows=translated_rows,
        source_lang=source_lang,
        target_lang=target_lang,
        api_key=api_key,
        translate_base_url=translate_base_url,
        translate_model=translate_model,
        translate_system_prompt=translate_system_prompt,
        task_id=resolved_task_id,
    )
    selected_subtitles = _optimize_omnivoice_selected_rows(
        selected_subtitles,
        subtitle_mode=selected_mode,
    )
    selected_subtitles = _ensure_speaker_ids(
        selected_subtitles,
        fallback_rows=source_rows,
        force_align_by_time=True,
    )
    selected_subtitles = _drop_empty_subtitle_rows(selected_subtitles, label="selected")
    selected_subtitles, _dd = _deduplicate_translated_rows(selected_subtitles)
    selected_subtitles, _adj = _rebalance_omnivoice_synthesis_rows(selected_subtitles)
    selected_subtitles, _eq = _equalize_cps_across_neighbors(selected_subtitles)
    selected_subtitles, _ml = _merge_short_lines_for_tts(selected_subtitles)
    selected_subtitles, _ms = _merge_ultra_short_segments(selected_subtitles)
    if not selected_subtitles:
        raise HTTPException(status_code=400, detail="OmniVoice selected subtitles are empty")

    selected_subtitles_path = out_root / "selected_subtitles.srt"
    selected_subtitles_path.write_text(format_srt(selected_subtitles), encoding="utf-8")
    selected_subtitles_with_speaker_path = out_root / "selected_subtitles_with_speakers.srt"
    selected_subtitles_with_speaker_rows = _build_selected_subtitles_with_speaker_rows(selected_subtitles)
    selected_subtitles_with_speaker_path.write_text(
        format_srt(selected_subtitles_with_speaker_rows),
        encoding="utf-8",
    )

    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=display_name,
        input_media_path=source_media_path,
        subtitle_mode=subtitle_mode,
        source_lang=source_lang,
        target_lang=target_lang,
        enable_source_separation=True,
        source_count=len(source_rows),
        translated_count=len(translated_rows),
        speaker_ids=sorted({str(row.get("speaker_id") or "").strip() or "Speaker 1" for row in selected_subtitles}),
        out_root=out_root,
    )
    task.update(
        {
            "status": "completed",
            "stage": "prepared:selected_subtitles",
            "progress": 100.0,
            "selected_subtitle_mode": selected_mode,
            "result_srt": str(selected_subtitles_path.resolve()),
            "artifacts": [
                {"key": "selected_srt", "label": "Selected Subtitles SRT", "url": _build_artifact_url(task["id"], "selected_srt")},
                {"key": "selected_srt_with_speaker", "label": "Selected Subtitles SRT (With Speaker)", "url": _build_artifact_url(task["id"], "selected_srt_with_speaker")},
                {"key": "manifest", "label": "Manifest JSON", "url": _build_artifact_url(task["id"], "manifest")},
            ],
            "batch_manifest_path": str((out_root / "manifest.json").resolve()),
            "result_audio": None,
            "speaker_reference_mode": "not_started",
        }
    )
    manifest = {
        "task_id": task["id"],
        "batch_id": task["batch_id"],
        "created_at": task["created_at"],
        "updated_at": _iso_now(),
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
        "speaker_reference_mode": task.get("speaker_reference_mode") or "not_started",
        "paths": {
            "selected_subtitles": str(selected_subtitles_path.resolve()),
            "selected_subtitles_with_speakers": str(selected_subtitles_with_speaker_path.resolve()),
            "manifest": str((out_root / "manifest.json").resolve()),
        },
        "artifacts": task["artifacts"],
        "segment_count": len(selected_subtitles),
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _task_store.create(resolved_task_id, task)
    return {
        "task_id": resolved_task_id,
        "short_id": resolved_task_id.split("_")[0],
        "status": "completed",
        "stage": "prepared:selected_subtitles",
        "project_filename": display_name,
        "selected_subtitle_mode": selected_mode,
        "result_srt": str(selected_subtitles_path.resolve()),
        "artifacts": task["artifacts"],
        "message": "OmniVoice selected subtitles prepared",
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
        resume_state = _infer_resume_state(manifest, out_root=manifest_path.parent)
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
                    "resumable": bool(resume_state.get("resumable")),
                    "resume_stage": str(resume_state.get("resume_stage") or ""),
                    "processed_segments": int(resume_state.get("completed_segments") or 0),
                    "total_segments": int(resume_state.get("total_segments") or 0),
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


@router.post("/resume/{task_id}")
async def resume_omnivoice_task(task_id: str) -> Dict[str, Any]:
    """从磁盘 batch 恢复 OmniVoice 任务，自动跳过已完成阶段与 segment。"""

    active = [active_id for active_id in _task_store.list_active_ids() if active_id != task_id]
    if active:
        raise HTTPException(status_code=409, detail="Another OmniVoice job is already running")

    manifest = _load_manifest(task_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="OmniVoice batch not found")
    status = str(manifest.get("status") or "").strip().lower()
    if status == "completed":
        raise HTTPException(status_code=409, detail="Completed OmniVoice task does not need resume")

    manifest_path_text = str(manifest.get("_manifest_path") or "").strip()
    manifest_path = Path(manifest_path_text).expanduser().resolve() if manifest_path_text else None
    out_root = manifest_path.parent if manifest_path and manifest_path.exists() else _resolve_output_dir(task_id)
    resume_context = _build_resume_context(manifest=manifest, out_root=out_root)
    resume_state = _infer_resume_state(manifest, out_root=out_root)
    if str(resume_state.get("resume_stage") or "") == "completed":
        raise HTTPException(status_code=409, detail="Completed OmniVoice task does not need resume")
    if not bool(resume_state.get("resumable")):
        raise HTTPException(status_code=409, detail="OmniVoice batch is not resumable")

    input_media_path = Path(str(manifest.get("input_media_path") or "")).expanduser()
    if not input_media_path.exists():
        raise HTTPException(status_code=404, detail=f"Resume input media missing: {input_media_path}")

    resolved_task_id = str(manifest.get("task_id") or manifest.get("batch_id") or task_id).strip() or task_id
    task = _create_task_payload(
        task_id=resolved_task_id,
        project_filename=str(manifest.get("project_filename") or input_media_path.name),
        input_media_path=input_media_path,
        subtitle_mode=str(manifest.get("subtitle_mode") or "translated"),
        source_lang=str(manifest.get("source_lang") or "auto"),
        target_lang=str(manifest.get("target_lang") or "Chinese"),
        enable_source_separation=bool(manifest.get("enable_source_separation", True)),
        source_count=int(manifest.get("source_subtitles_count") or 0),
        translated_count=int(manifest.get("translated_subtitles_count") or 0),
        speaker_ids=list(manifest.get("speaker_ids") or []),
        out_root=out_root,
    )
    task["status"] = "queued"
    task["stage"] = "queued"
    task["progress"] = 0.0
    task["selected_subtitle_mode"] = str(manifest.get("selected_subtitle_mode") or "translated")
    task["speaker_reference_mode"] = str(manifest.get("speaker_reference_mode") or "")
    task["processed_segments"] = int(resume_state.get("completed_segments") or 0)
    task["total_segments"] = int(resume_state.get("total_segments") or 0)
    task["resume_stage"] = str(resume_state.get("resume_stage") or "")
    task["resumable"] = True
    task["error"] = ""
    _task_store.create(resolved_task_id, task)

    thread = threading.Thread(
        target=_background_runner,
        kwargs=dict(
            task_id=resolved_task_id,
            input_media_path=input_media_path,
            project_filename=str(task.get("project_filename") or input_media_path.name),
            source_subtitles=[],
            translated_subtitles=[],
            subtitle_mode=str(task.get("subtitle_mode") or "translated"),
            source_lang=str(task.get("source_lang") or "auto"),
            target_lang=str(task.get("target_lang") or "Chinese"),
            api_key="",
            translate_base_url=DEFAULT_TRANSLATE_BASE_URL,
            translate_model=DEFAULT_TRANSLATE_MODEL,
            translate_system_prompt="",
            omnivoice_api_url=str(manifest.get("omnivoice_api_url") or DEFAULT_OMNIVOICE_API_URL),
            enable_source_separation=bool(task.get("enable_source_separation", True)),
            uploaded_speaker_ref_map=None,
            resume_context=resume_context,
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
        "project_filename": task["project_filename"],
        "resume_stage": task["resume_stage"],
        "message": "OmniVoice task resumed",
    }


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
    if artifact in {"srt", "selected_srt", "selected_srt_with_speaker"}:
        media_type = "application/x-subrip"
    elif artifact == "ass":
        media_type = "text/x-ass; charset=utf-8"
    elif artifact in {"vocals", "mix", "video_audio"}:
        media_type = "audio/wav" if artifact != "video_audio" else "audio/mp4"
    elif artifact in {"video", "video_burned"}:
        media_type = "video/mp4"
    elif artifact == "manifest":
        media_type = "application/json"
    elif artifact == "separation_report":
        media_type = "application/json"
    return FileResponse(path=path, filename=path.name, media_type=media_type)
