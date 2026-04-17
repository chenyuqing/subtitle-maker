from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from starlette.requests import Request
import shutil
import os
import uuid
import logging
import math
import re
from .transcriber import SubtitleGenerator, format_srt, merge_subtitles, parse_srt
from .translator import Translator
from .streaming_api import router as streaming_router
from .dubbing_cli_api import router as dubbing_router, cancel_active_dubbing
from .index_tts_service import (
    get_index_tts_status,
    start_index_tts_service,
    stop_index_tts_service,
    release_index_tts_model,
)


import asyncio
from typing import Any, Dict, List, Optional
import subprocess
import time
import socket
from threading import Lock
from starlette.concurrency import run_in_threadpool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Include streaming ASR router
app.include_router(streaming_router)
app.include_router(dubbing_router)

# Global model instance (lazy loading)
generator = None
model_lock = Lock()


def _sanitize_stub(name: str) -> str:
    stub = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return stub or "file"

def get_generator():
    global generator
    if generator is None:
        # Initialize but don't load weights yet
        logger.info("Initializing Qwen3-ASR Generator (Lazy)...")
        generator = SubtitleGenerator(
            model_path="./models/Qwen3-ASR-0.6B",
            aligner_path="./models/Qwen3-ForcedAligner-0.6B",
            device="mps",
            lazy_load=True
        )
    return generator


def release_generator():
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

# Task storage (simple in-memory)
tasks: Dict[str, dict] = {}

def _static_version(filename: str) -> int:
    path = os.path.join(STATIC_DIR, filename)
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return int(time.time())

@app.get("/")
async def index(request: Request):
    context = {
        "request": request,
        "app_js_version": _static_version("app.js"),
        "style_css_version": _static_version("style.css"),
    }
    return templates.TemplateResponse("index.html", context)

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"file_id": file_id, "filename": filename, "url": f"/stream/{filename}"}

@app.get("/stream/{filename}")
async def stream_video(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

def transcribe_task(task_id: str, file_path: str, source_lang: str, max_width: int, time_ranges: Optional[List] = None, existing_subtitles: Optional[List] = None):
    # Acquire lock to prevent other tasks from messing with the model
    # Note: This means concurrent transcriptions are serial, but that's required for single GPU/memory.
    with model_lock:
        tasks[task_id]["status"] = "processing"

        try:
            gen = get_generator()
            logger.info(f"Task {task_id}: Loading ASR model (On Demand)...")
            gen.load_model()

            processed_audio = None
            # Preprocess once to avoid repeated decoding for long files
            tasks[task_id]["status"] = "preprocessing"
            logger.info(f"Task {task_id}: Preprocessing {file_path}")
            processed_audio = gen.preprocess_audio(file_path)

            # Chunked transcription keeps memory usage flat regardless of duration
            tasks[task_id]["status"] = "transcribing"
            tasks[task_id]["processed_chunks"] = 0
            tasks[task_id]["generated_lines"] = 0
            tasks[task_id]["subtitles"] = []
            lang_arg = "auto" if source_lang == "auto" else source_lang
            logger.info(f"Task {task_id}: Transcribing in chunks...")

            for chunk_results in gen.transcribe_iter(
                processed_audio,
                language=lang_arg,
                chunk_size=30,
                preprocessed=True
            ):
                if tasks[task_id].get("status") == "cancelled":
                    logger.info(f"Task {task_id}: Cancelled mid-transcription")
                    return

                chunk_subtitles = gen.generate_subtitles(chunk_results, max_len=max_width)
                tasks[task_id]["subtitles"].extend(chunk_subtitles)
                tasks[task_id]["processed_chunks"] += 1
                tasks[task_id]["generated_lines"] = len(tasks[task_id]["subtitles"])

                del chunk_results
                del chunk_subtitles
                import gc
                gc.collect()

            # Merge with existing subtitles if any (for append mode)
            new_subtitles = tasks[task_id]["subtitles"]
            if existing_subtitles and len(existing_subtitles) > 0:
                logger.info(f"Task {task_id}: Merging {len(existing_subtitles)} existing + {len(new_subtitles)} new subtitles")
                # Combine and sort by start time
                all_subtitles = existing_subtitles + new_subtitles
                all_subtitles.sort(key=lambda x: x.get('start', 0))
                subtitles = all_subtitles
                logger.info(f"Task {task_id}: Total after merge: {len(subtitles)} subtitles")
            else:
                subtitles = new_subtitles

            srt_content = format_srt(subtitles)
            
            # Save SRT
            base_name = os.path.basename(file_path)
            srt_filename = f"{os.path.splitext(base_name)[0]}.srt"
            srt_path = os.path.join(OUTPUT_DIR, srt_filename)
            
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
                
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["subtitles"] = subtitles # Store structured for UI
            tasks[task_id]["srt_url"] = f"/download/{srt_filename}"
            
            # Cleanup audio
        except Exception as e:
            logger.error(f"Task failed: {e}", exc_info=True)
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)
        finally:
            if 'processed_audio' in locals() and processed_audio and os.path.exists(processed_audio):
                os.remove(processed_audio)
            # Release memory after task (success or fail)
            logger.info(f"Task {task_id}: Unloading ASR model...")
            release_generator()

@app.post("/upload_srt")
async def upload_srt(
    file: UploadFile = File(...),
    video_filename: Optional[str] = Form(None)
):
    if not file.filename.endswith('.srt'):
        raise HTTPException(status_code=400, detail="Only .srt files are supported")
    
    content_bytes = await file.read()
    try:
        content_str = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        content_str = content_bytes.decode('latin-1') # Fallback
        
    subtitles = parse_srt(content_str)
    
    if not subtitles:
        raise HTTPException(status_code=400, detail="Could not parse subtitles or file is empty")
        
    task_id = str(uuid.uuid4())
    filename = file.filename
    
    # Store complete task
    tasks[task_id] = {
        "status": "completed", # Skip transcription
        "filename": filename, # This is the SRT filename
        "video_filename": video_filename,
        "subtitles": subtitles,
        "translated_subtitles": None # Ready for translation
    }
    
    return {
        "task_id": task_id,
        "filename": filename, 
        "subtitles": subtitles
    }

@app.post("/transcribe/sync")
async def transcribe_sync(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    max_width: int = Form(40),
    target_lang: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    system_prompt: Optional[str] = Form(None)
):
    """Synchronous transcription endpoint: upload video → return SRT directly.

    Optional translation: set target_lang (e.g., "Chinese", "English") and provide api_key.
    Returns bilingual SRT with original + translation if translation is enabled.
    """
    # 1. Save uploaded file
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 2. Create a temporary task for tracking
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "pending",
        "filename": filename,
    }

    do_translate = target_lang and api_key

    try:
        # 3. Run transcription synchronously (blocking, so use to_thread)
        await asyncio.to_thread(transcribe_task, task_id, filepath, language, max_width, None, None)

        # 4. Get result
        task = tasks.get(task_id)
        if not task or task.get("status") != "completed":
            error = task.get("error", "Transcription failed") if task else "Task not found"
            raise HTTPException(status_code=500, detail=f"Transcription failed: {error}")

        subtitles = task.get("subtitles", [])

        # 5. Optional translation
        if do_translate and subtitles:
            translator = Translator(api_key=api_key)
            original_texts = [sub['text'] for sub in subtitles]

            translated_texts = await run_in_threadpool(
                translator.translate_batch,
                original_texts,
                target_lang=target_lang,
                system_prompt=system_prompt
            )

            # Build translated subtitles
            translated_subtitles = []
            for sub, trans_text in zip(subtitles, translated_texts):
                new_sub = sub.copy()
                new_sub['text'] = trans_text
                translated_subtitles.append(new_sub)

            # Return bilingual SRT (original + translated)
            bilingual_subtitles = merge_subtitles(subtitles, translated_subtitles, order="orig_trans")
            srt_content = format_srt(bilingual_subtitles)
        else:
            # Return original SRT
            srt_content = format_srt(subtitles)

        # Cleanup task
        tasks.pop(task_id, None)

        # Return as plain text (SRT format)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(srt_content, media_type="text/plain")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    finally:
        # Cleanup uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)
        tasks.pop(task_id, None)


@app.post("/transcribe")
async def transcribe(
    background_tasks: BackgroundTasks,
    filename: str = Form(...),
    language: str = Form("auto"),
    max_width: int = Form(40),
    original_filename: Optional[str] = Form(None),
    time_ranges: Optional[str] = Form(None),
    existing_subtitles: Optional[str] = Form(None)
):
    import json

    # Parse time_ranges if provided
    time_ranges_list = None
    if time_ranges:
        try:
            time_ranges_list = json.loads(time_ranges)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid time_ranges JSON")

    # Parse existing subtitles for appending
    existing_subs = None
    if existing_subtitles:
        try:
            existing_subs = json.loads(existing_subtitles)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid existing_subtitles JSON")

    task_id = str(uuid.uuid4())
    filepath = os.path.join(UPLOAD_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    tasks[task_id] = {
        "status": "pending",
        "video_filename": filename,
        "original_filename": original_filename,
    }

    # Cleanup old tasks (simple check: if > 100 tasks, remove oldest 20)
    if len(tasks) > 100:
        keys_to_remove = list(tasks.keys())[:20]
        for k in keys_to_remove:
            del tasks[k]

    background_tasks.add_task(transcribe_task, task_id, filepath, language, max_width, time_ranges_list, existing_subs)

    return {"task_id": task_id}

@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task["status"] in ["processing", "pending"]:
        task["status"] = "cancelled"
        return {"status": "cancelled"}
    return {"status": task["status"]}

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.post("/translate")
async def translate(
    target_lang: str = Form(...),
    api_key: str = Form(...),
    task_id: Optional[str] = Form(None),
    subtitles_json: Optional[str] = Form(None),
    system_prompt: Optional[str] = Form(None)
):
    import json
    subtitles = []
    task = None
    
    # Try to resolve task first (for updating persistence later)
    if task_id:
        task = tasks.get(task_id)

    # Determine source of subtitles: Direct JSON > Task Memory
    if subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid subtitles JSON")
    elif task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])
    elif task_id: # Task ID provided but not found or not ready
         raise HTTPException(status_code=400, detail="Task not ready or not found")
    
    if not subtitles:
        return {"translated_subtitles": []}
        
    try:
        # Default DeepSeek
        translator = Translator(api_key=api_key)
        
        original_texts = [sub['text'] for sub in subtitles]
        
        # Run blocking translation in threadpool to enforce async non-blocking
        translated_texts = await run_in_threadpool(
            translator.translate_batch, 
            original_texts, 
            target_lang=target_lang, 
            system_prompt=system_prompt
        )
        
        translated_subtitles = []
        for sub, trans_text in zip(subtitles, translated_texts):
            new_sub = sub.copy()
            new_sub['text'] = trans_text
            translated_subtitles.append(new_sub)
            
        # Store in task for export IF task exists
        if task:
            task["translated_subtitles"] = translated_subtitles
            
        # Generate SRT string for download
        # Use standalone function, no model loading needed!
        srt_content = format_srt(translated_subtitles)
        
        return {
            "translated_subtitles": translated_subtitles,
            "srt_content": srt_content
        }
        
    except Exception as e:
        logger.error(f"Translation failed: {e}", exc_info=True)
        error_msg = str(e)
        # Catch DeepSeek API errors specifically
        if "Authentication" in error_msg or "api_key" in error_msg.lower():
             raise HTTPException(status_code=401, detail=f"API Key 验证失败: {error_msg}")
        elif "rate_limit" in error_msg.lower() or "429" in error_msg:
             raise HTTPException(status_code=429, detail=f"请求过于频繁，请稍后再试: {error_msg}")
        elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
             raise HTTPException(status_code=504, detail=f"请求超时，请检查网络: {error_msg}")
        elif "connection" in error_msg.lower():
             raise HTTPException(status_code=502, detail=f"连接失败，请检查网络: {error_msg}")
        else:
             raise HTTPException(status_code=500, detail=f"翻译失败: {error_msg}")
    # Finally block removed as we don't load model here anymore

@app.post("/export")
async def export_subtitles(
    task_id: str = Form(...),
    format: str = Form(...), # original, translated, bilingual_orig_trans, bilingual_trans_orig
    subtitles_json: Optional[str] = Form(None),
    translated_subtitles_json: Optional[str] = Form(None)
):
    import json
    task = tasks.get(task_id)
    
    subtitles = []
    translated_subtitles = []
    
    # Priority 1: Task Memory
    if task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])
        translated_subtitles = task.get("translated_subtitles", [])
    
    # Priority 2: Client provided JSON (Resilience for restarts)
    if not subtitles and subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except:
            pass
            
    if not translated_subtitles and translated_subtitles_json:
        try:
            translated_subtitles = json.loads(translated_subtitles_json)
        except:
             pass

    if not subtitles:
        raise HTTPException(status_code=400, detail="Task not found or expired, and no subtitle data provided.")
    
    # gen = get_generator() # optimization: not needed anymore for export
    
    final_subtitles = []
    filename_suffix = ""
    
    if format == "original":
        final_subtitles = subtitles
        filename_suffix = ".srt"
    elif format == "translated":
        if not translated_subtitles:
             raise HTTPException(status_code=400, detail="Translation not available")
        final_subtitles = translated_subtitles
        filename_suffix = ".translated.srt"
    elif format == "bilingual_orig_trans":
        if not translated_subtitles:
             raise HTTPException(status_code=400, detail="Translation not available")
        # Use standalone function
        final_subtitles = merge_subtitles(subtitles, translated_subtitles, order="orig_trans")
        filename_suffix = ".bilingual.srt"
    elif format == "bilingual_trans_orig":
        if not translated_subtitles:
             raise HTTPException(status_code=400, detail="Translation not available")
        # Use standalone function
        final_subtitles = merge_subtitles(subtitles, translated_subtitles, order="trans_orig")
        filename_suffix = ".bilingual.srt"
    else:
        raise HTTPException(status_code=400, detail="Invalid format")
        
    srt_content = format_srt(final_subtitles)
    
    # Save to temp file to serve
    filename = f"export_{task_id}{filename_suffix}"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(srt_content)
        
    return FileResponse(filepath, filename=filename)

@app.get("/download/{filename}")
async def download_file(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)

def start():
    import uvicorn
    # 默认关闭 reload，避免出现多进程监听导致内存任务状态（如 auto dubbing 队列）不一致
    reload_enabled = os.environ.get("SUBTITLE_MAKER_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    # 明确单 worker，保证基于内存的任务状态读写在同一进程内
    uvicorn.run("subtitle_maker.web:app", host="0.0.0.0", port=8000, reload=reload_enabled, workers=1)

def clear_directory_contents(target_dir: str) -> int:
    """Remove all files and folders inside the given directory."""
    os.makedirs(target_dir, exist_ok=True)
    removed = 0
    for entry in os.listdir(target_dir):
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


def cancel_active_transcriptions(reason: str) -> int:
    """Mark in-flight transcription tasks as cancelled so workers can unwind."""
    cancelled = 0
    for task in tasks.values():
        if task.get("status") in ("processing", "pending"):
            task["status"] = "cancelled"
            task["error"] = reason
            cancelled += 1
    return cancelled


# ASR/model management
@app.post("/model/asr/release")
async def release_asr_model():
    release_generator()
    return {"status": "released"}


@app.post("/model/all/release")
async def release_all_models():
    reason = "Cancelled via model release"
    cancelled_transcriptions = cancel_active_transcriptions(reason)
    cancelled_auto_tasks = cancel_active_dubbing(reason)
    release_generator()
    index_tts_release = release_index_tts_model()

    return {
        "status": "all models released",
        "cancelled_transcriptions": cancelled_transcriptions,
        "cancelled_auto_tasks": cancelled_auto_tasks,
        "index_tts_release": index_tts_release,
    }


@app.get("/model/index-tts/status")
async def get_index_tts_model_status():
    return get_index_tts_status()


@app.post("/model/index-tts/start")
async def start_index_tts_model_service():
    return start_index_tts_service()


@app.post("/model/index-tts/release")
async def release_index_tts_model_service():
    return release_index_tts_model()


@app.post("/model/index-tts/stop")
async def stop_index_tts_model_service():
    return stop_index_tts_service()


@app.post("/project/reset")
async def reset_project_storage():
    """Clear uploads/outputs directories so the next project starts fresh."""
    cancelled_auto_tasks = cancel_active_dubbing("Cancelled via project reset")
    uploads_removed = clear_directory_contents(UPLOAD_DIR)
    outputs_removed = clear_directory_contents(OUTPUT_DIR)
    return {
        "status": "reset",
        "cancelled_auto_tasks": cancelled_auto_tasks,
        "uploads_removed": uploads_removed,
        "outputs_removed": outputs_removed,
    }

@app.post("/segment")
async def segment_audio(
    background_tasks: BackgroundTasks, # Not strictly needed if synchronous, but good practice if we want to defer cleanup
    task_id: str = Form(...),
    max_duration: float = Form(30.0), # Default 30s
    subtitles_json: Optional[str] = Form(None)
):
    import json
    import csv
    import zipfile
    
    task = tasks.get(task_id)
    subtitles = []
    
    # Priority 1: Task Memory
    if task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])
        
    # Priority 2: Client provided JSON
    if not subtitles and subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except:
            pass
            
    if not subtitles:
        raise HTTPException(status_code=400, detail="No subtitles found.")
        
    # Get Video Path
    video_filename = None
    if task:
        video_filename = task.get("video_filename") or task.get("filename")
    
    if not video_filename and task and task.get("filename"):
         video_filename = task.get("filename")

    if not video_filename:
         raise HTTPException(status_code=404, detail="Video file not found for this task.")
         
    video_path = os.path.join(UPLOAD_DIR, video_filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video file {video_filename} not found.")

    # Prepare Output
    segment_task_id = f"seg_{task_id}_{uuid.uuid4().hex[:6]}"
    segment_dir = os.path.join(OUTPUT_DIR, segment_task_id)
    os.makedirs(segment_dir, exist_ok=True)
    
    # --- Merging Logic ---
    merged_segments: List[Dict[str, Any]] = []
    if not subtitles:
        return {"status": "empty"}

    SENTENCE_ENDINGS = ('.', '?', '!', '。', '？', '！', '…')
    QUOTE_ENDINGS = ('.\"', '?\"', '!\"', '。\"', '？\"', '！\"', '…”')
    MIN_DURATION_RATIO = 0.5

    def rebuild_text(block: List[Dict[str, Any]]) -> str:
        return " ".join(sub['text'].strip() for sub in block if sub.get('text')).strip()

    def rebuild_segment(segment: Dict[str, Any]):
        subs = segment.get("subs", [])
        if not subs:
            return
        segment["start"] = subs[0]["start"]
        segment["end"] = subs[-1]["end"]
        segment["text"] = rebuild_text(subs)
        segment["sub_count"] = len(subs)

    def is_sentence_boundary(text: str) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return False
        return cleaned.endswith(SENTENCE_ENDINGS) or cleaned.endswith(QUOTE_ENDINGS)

    def split_text_chunks(text: str, parts: int) -> List[str]:
        stripped = text.strip()
        if not stripped:
            return [""] * parts

        sentence_parts = [s.strip() for s in re.split(r'(?<=[。！？!?…])', stripped) if s.strip()]
        if len(sentence_parts) >= parts:
            size = math.ceil(len(sentence_parts) / parts)
            chunks: List[str] = []
            for idx in range(parts):
                start = idx * size
                end = min(len(sentence_parts), (idx + 1) * size)
                chunks.append(" ".join(sentence_parts[start:end]).strip())
            return chunks

        words = stripped.split()
        if len(words) >= parts and len(words) > 1:
            size = math.ceil(len(words) / parts)
            chunks = []
            for idx in range(parts):
                start = idx * size
                end = min(len(words), (idx + 1) * size)
                chunks.append(" ".join(words[start:end]).strip())
            return chunks

        char_size = max(1, math.ceil(len(stripped) / parts))
        chunks = []
        for idx in range(parts):
            start = idx * char_size
            end = min(len(stripped), (idx + 1) * char_size)
            chunks.append(stripped[start:end].strip())
        return chunks

    def split_long_subtitle(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
        duration = sub['end'] - sub['start']
        if duration <= max_duration or duration <= 0:
            return [sub]
        parts = math.ceil(duration / max_duration)
        chunk_duration = duration / parts
        text_chunks = split_text_chunks(sub.get("text", ""), parts)
        chunks = []
        for idx in range(parts):
            start = sub['start'] + idx * chunk_duration
            end = min(sub['start'] + (idx + 1) * chunk_duration, sub['end'])
            chunk_text = text_chunks[idx] if idx < len(text_chunks) else sub.get("text", "")
            new_sub = sub.copy()
            new_sub.update({
                "start": start,
                "end": end,
                "text": chunk_text or sub.get("text", "")
            })
            chunks.append(new_sub)
        return chunks

    processed_subtitles: List[Dict[str, Any]] = []
    for sub in subtitles:
        processed_subtitles.extend(split_long_subtitle(sub))
    subtitles = processed_subtitles
    if not subtitles:
        return {"status": "empty"}

    def append_segment(block: List[Dict[str, Any]]):
        if not block:
            return
        block_subs = list(block)
        merged_segments.append({
            "start": block_subs[0]["start"],
            "end": block_subs[-1]["end"],
            "text": rebuild_text(block_subs),
            "sub_count": len(block_subs),
            "subs": block_subs
        })

    current_block: List[Dict[str, Any]] = []
    sentence_boundaries: List[int] = []  # indices inside current_block

    for sub in subtitles:
        current_block.append(sub)
        if is_sentence_boundary(sub['text']):
            sentence_boundaries.append(len(current_block) - 1)

        # Evaluate duration and split decisions in a loop in case we need to emit multiple segments
        while current_block:
            duration = current_block[-1]['end'] - current_block[0]['start']
            if duration <= max_duration:
                break

            split_idx: Optional[int] = None
            for idx in reversed(sentence_boundaries):
                boundary_duration = current_block[idx]['end'] - current_block[0]['start']
                if boundary_duration <= max_duration:
                    split_idx = idx
                    break

            if split_idx is None:
                fallback_idx = len(current_block) - 2
                while fallback_idx >= 0:
                    fallback_duration = current_block[fallback_idx]['end'] - current_block[0]['start']
                    if fallback_duration <= max_duration:
                        split_idx = fallback_idx
                        break
                    fallback_idx -= 1

            if split_idx is None:
                append_segment(current_block[:1])
                current_block = current_block[1:]
                sentence_boundaries = [i - 1 for i in sentence_boundaries if i > 0]
                continue

            emit_block = current_block[: split_idx + 1]
            append_segment(emit_block)
            current_block = current_block[split_idx + 1 :]
            sentence_boundaries = [i - (split_idx + 1) for i in sentence_boundaries if i > split_idx]

    append_segment(current_block)

    # Re-balance short segments (except the final one) by borrowing from the next chunk when possible
    i = 0
    while i < len(merged_segments) - 1:
        curr = merged_segments[i]
        next_seg = merged_segments[i + 1]
        curr_duration = curr["end"] - curr["start"]

        if curr_duration >= max_duration * MIN_DURATION_RATIO:
            i += 1
            continue

        combined_duration = next_seg["end"] - curr["start"]
        if combined_duration <= max_duration:
            curr["subs"].extend(next_seg["subs"])
            rebuild_segment(curr)
            merged_segments.pop(i + 1)
            continue

        moved = False
        while next_seg.get("subs"):
            candidate = next_seg["subs"][0]
            new_duration = candidate["end"] - curr["start"]
            if new_duration > max_duration:
                break
            curr["subs"].append(candidate)
            next_seg["subs"] = next_seg["subs"][1:]
            rebuild_segment(curr)
            if next_seg["subs"]:
                rebuild_segment(next_seg)
            else:
                merged_segments.pop(i + 1)
                moved = True
                break
            moved = True
            curr_duration = curr["end"] - curr["start"]
            if curr_duration >= max_duration * MIN_DURATION_RATIO:
                break

        if not moved:
            i += 1

    for seg in merged_segments:
        seg.pop("subs", None)
    
    # --- Processing ---
    # We need to slice audio.
    # We can use ffmpeg.
    
    metadata_rows = []
    
    try:
        # Pre-convert to 16kHz mono wav for the whole file ONCE to speed up slicing?
        # Or slice from original? Slicing from original is fine if we use -ss -t before -i (fast seek) 
        # but for accurate audio cutting, it's often safer to use decode.
        # Let's decode to a temp full wav first if input is compressed video (faster random access).
        
        full_wav_path = os.path.join(segment_dir, "full_temp.wav")
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", full_wav_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        for idx, seg in enumerate(merged_segments):
            seg_filename = f"segment_{idx:04d}.wav"
            seg_path = os.path.join(segment_dir, seg_filename)
            
            start = seg['start']
            duration = seg['end'] - seg['start']
            
            # Slice ensuring we don't go out of bounds? ffmpeg handles it.
            # Using -ss and -t on the wav
            subprocess.run([
                 "ffmpeg", "-y", "-ss", str(start), "-t", str(duration), 
                 "-i", full_wav_path, "-c", "copy", seg_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            metadata_rows.append([seg_filename, seg['text']])
            
        # Create CSV
        csv_path = os.path.join(segment_dir, "metadata.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["file_name", "transcription"])
            writer.writerows(metadata_rows)
            
        # Cleanup full wav
        if os.path.exists(full_wav_path):
            os.remove(full_wav_path)
            
        # ZIP it
        zip_filename = f"segments_{task_id}.zip"
        zip_path = os.path.join(OUTPUT_DIR, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(segment_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, segment_dir)
                    zipf.write(file_path, arcname)
                    
        # Cleanup temp dir
        shutil.rmtree(segment_dir)
        
        return {"zip_url": f"/download/{zip_filename}", "count": len(merged_segments)}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Segmentation failed: {str(e)}")
