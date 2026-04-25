from __future__ import annotations

import logging
import os
import re
import shutil
import time
from threading import Lock
from typing import Dict, List, Optional

from fastapi.templating import Jinja2Templates

from subtitle_maker.transcriber import SubtitleGenerator, format_srt


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# 普通转写任务仍保留原有内存态存储；Phase 9 只做 route 拆分，不统一状态层。
tasks: Dict[str, dict] = {}

generator = None
model_lock = Lock()


def _sanitize_stub(name: str) -> str:
    """将任意名称规整为安全文件名前缀。"""

    stub = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return stub or "file"


def _static_version(filename: str) -> int:
    """为静态资源生成基于 mtime 的版本号。"""

    if filename == "app.js":
        # 前端模块化后，`/static/app.js` 会动态装配 `static/js/*.js`。
        # 这里返回“入口脚本 + 子模块”的最新 mtime，避免只改子模块却命中旧缓存。
        candidate_paths = [os.path.join(STATIC_DIR, "app.js")]
        module_dir = os.path.join(STATIC_DIR, "js")
        if os.path.isdir(module_dir):
            for root, _, files in os.walk(module_dir):
                for name in files:
                    if name.endswith(".js"):
                        candidate_paths.append(os.path.join(root, name))
        latest_mtime = 0.0
        for path in candidate_paths:
            try:
                latest_mtime = max(latest_mtime, os.path.getmtime(path))
            except OSError:
                continue
        if latest_mtime > 0:
            return int(latest_mtime)
        return int(time.time())

    path = os.path.join(STATIC_DIR, filename)
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return int(time.time())


def get_generator():
    """懒加载 Qwen3 ASR 生成器。"""

    global generator
    if generator is None:
        logger.info("Initializing Qwen3-ASR Generator (Lazy)...")
        generator = SubtitleGenerator(
            model_path="./models/Qwen3-ASR-0.6B",
            aligner_path="./models/Qwen3-ForcedAligner-0.6B",
            device="mps",
            lazy_load=True,
        )
    return generator


def release_generator():
    """释放当前 ASR 模型占用的内存。"""

    global generator
    if generator is not None:
        logger.info("Releasing model memory...")
        del generator
        generator = None
        import gc
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        gc.collect()
        logger.info("Model memory released.")


def transcribe_task(
    task_id: str,
    file_path: str,
    source_lang: str,
    max_width: int,
    time_ranges: Optional[List] = None,
    existing_subtitles: Optional[List] = None,
):
    """执行普通字幕转写任务，并把结果写回 legacy `tasks`。"""

    del time_ranges  # 迁移期保持原签名；当前实现尚未单独处理 time_ranges。
    with model_lock:
        tasks[task_id]["status"] = "processing"

        try:
            gen = get_generator()
            logger.info("Task %s: Loading ASR model (On Demand)...", task_id)
            gen.load_model()

            processed_audio = None
            tasks[task_id]["status"] = "preprocessing"
            logger.info("Task %s: Preprocessing %s", task_id, file_path)
            processed_audio = gen.preprocess_audio(file_path)

            tasks[task_id]["status"] = "transcribing"
            tasks[task_id]["processed_chunks"] = 0
            tasks[task_id]["generated_lines"] = 0
            tasks[task_id]["subtitles"] = []
            lang_arg = "auto" if source_lang == "auto" else source_lang
            logger.info("Task %s: Transcribing in chunks...", task_id)

            for chunk_results in gen.transcribe_iter(
                processed_audio,
                language=lang_arg,
                chunk_size=30,
                preprocessed=True,
            ):
                if tasks[task_id].get("status") == "cancelled":
                    logger.info("Task %s: Cancelled mid-transcription", task_id)
                    return

                chunk_subtitles = gen.generate_subtitles(chunk_results, max_len=max_width)
                tasks[task_id]["subtitles"].extend(chunk_subtitles)
                tasks[task_id]["processed_chunks"] += 1
                tasks[task_id]["generated_lines"] = len(tasks[task_id]["subtitles"])

                del chunk_results
                del chunk_subtitles
                import gc

                gc.collect()

            new_subtitles = tasks[task_id]["subtitles"]
            if existing_subtitles and len(existing_subtitles) > 0:
                logger.info(
                    "Task %s: Merging %s existing + %s new subtitles",
                    task_id,
                    len(existing_subtitles),
                    len(new_subtitles),
                )
                all_subtitles = existing_subtitles + new_subtitles
                all_subtitles.sort(key=lambda item: item.get("start", 0))
                subtitles = all_subtitles
                logger.info("Task %s: Total after merge: %s subtitles", task_id, len(subtitles))
            else:
                subtitles = new_subtitles

            srt_content = format_srt(subtitles)
            base_name = os.path.basename(file_path)
            srt_filename = f"{os.path.splitext(base_name)[0]}.srt"
            srt_path = os.path.join(OUTPUT_DIR, srt_filename)

            with open(srt_path, "w", encoding="utf-8") as handle:
                handle.write(srt_content)

            tasks[task_id]["status"] = "completed"
            tasks[task_id]["subtitles"] = subtitles
            tasks[task_id]["srt_url"] = f"/download/{srt_filename}"
        except Exception as exc:
            logger.error("Task failed: %s", exc, exc_info=True)
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(exc)
        finally:
            if "processed_audio" in locals() and processed_audio and os.path.exists(processed_audio):
                os.remove(processed_audio)
            logger.info("Task %s: Unloading ASR model...", task_id)
            release_generator()


def clear_directory_contents(target_dir: str, exclude_names: Optional[set[str]] = None) -> int:
    """清空目录内容，可排除指定条目。"""

    os.makedirs(target_dir, exist_ok=True)
    excludes = set(exclude_names or set())
    removed = 0
    for entry in os.listdir(target_dir):
        if entry in excludes:
            continue
        path = os.path.join(target_dir, entry)
        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
            removed += 1
        except Exception as exc:
            logger.warning("Failed to remove %s: %s", path, exc)
    return removed


def prune_dubbing_uploads_keep_latest_videos(dubbing_dir: str, keep_count: int = 3) -> Dict[str, int]:
    """清理 uploads/dubbing，仅保留最新 N 个视频所在任务目录。"""

    os.makedirs(dubbing_dir, exist_ok=True)
    keep_n = max(0, int(keep_count))
    video_exts = {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
        ".ts",
        ".flv",
        ".wmv",
    }

    video_files: List[tuple[float, str]] = []
    for root, _, files in os.walk(dubbing_dir):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in video_exts:
                continue
            full_path = os.path.join(root, filename)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            video_files.append((mtime, full_path))

    video_files.sort(key=lambda item: item[0], reverse=True)
    keep_task_dirs: set[str] = set()
    for _, file_path in video_files[:keep_n]:
        rel = os.path.relpath(file_path, dubbing_dir)
        first_part = rel.split(os.sep)[0] if rel else ""
        if first_part:
            keep_task_dirs.add(first_part)

    removed = 0
    kept = 0
    for entry in os.listdir(dubbing_dir):
        path = os.path.join(dubbing_dir, entry)
        if entry in keep_task_dirs:
            kept += 1
            continue
        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
            removed += 1
        except Exception as exc:
            logger.warning("Failed to prune %s: %s", path, exc)

    for root, dirs, _ in os.walk(dubbing_dir, topdown=False):
        for dirname in dirs:
            folder = os.path.join(root, dirname)
            try:
                if not os.listdir(folder):
                    os.rmdir(folder)
            except Exception:
                pass

    return {
        "video_candidates": len(video_files),
        "kept_task_dirs": kept,
        "removed_entries": removed,
    }


def cancel_active_transcriptions(reason: str) -> int:
    """取消当前所有进行中的普通转写任务。"""

    cancelled = 0
    for task in tasks.values():
        if task.get("status") in ("processing", "pending"):
            task["status"] = "cancelled"
            task["error"] = reason
            cancelled += 1
    return cancelled
