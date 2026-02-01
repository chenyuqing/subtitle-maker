from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, FileResponse
from starlette.requests import Request
import shutil
import os
import uuid
import logging
from .transcriber import SubtitleGenerator, format_srt, merge_subtitles, parse_srt
from .translator import Translator
import asyncio
from typing import Dict, Optional
import subprocess
import time
import socket

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

# Global model instance (lazy loading)
generator = None

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

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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

def transcribe_task(task_id: str, file_path: str, source_lang: str, max_width: int):
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
        
        subtitles = tasks[task_id]["subtitles"]
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
async def upload_srt(file: UploadFile = File(...)):
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
        "filename": filename,
        "subtitles": subtitles,
        "translated_subtitles": None # Ready for translation
    }
    
    return {
        "task_id": task_id,
        "filename": filename, 
        "subtitles": subtitles
    }

@app.post("/transcribe")
async def transcribe(
    background_tasks: BackgroundTasks,
    filename: str = Form(...),
    language: str = Form("auto"),
    max_width: int = Form(40)
):
    task_id = str(uuid.uuid4())
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    tasks[task_id] = {"status": "pending"}
    
    # Cleanup old tasks (simple check: if > 100 tasks, remove oldest 20)
    if len(tasks) > 100:
        keys_to_remove = list(tasks.keys())[:20]
        for k in keys_to_remove:
            del tasks[k]
    
    background_tasks.add_task(transcribe_task, task_id, filepath, language, max_width)
    
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
        translated_texts = translator.translate_batch(original_texts, target_lang=target_lang, system_prompt=system_prompt)
        
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
        logger.error(f"Translation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    # Finally block removed as we don't load model here anymore

@app.post("/export")
async def export_subtitles(
    task_id: str = Form(...),
    format: str = Form(...) # original, translated, bilingual_orig_trans, bilingual_trans_orig
):
    task = tasks.get(task_id)
    if not task or task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not ready or not found")
        
    subtitles = task.get("subtitles", [])
    translated_subtitles = task.get("translated_subtitles", [])
    
    subtitles = task.get("subtitles", [])
    translated_subtitles = task.get("translated_subtitles", [])
    
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
    uvicorn.run("subtitle_maker.web:app", host="0.0.0.0", port=8000, reload=True)

# ASR model management
@app.post("/model/asr/release")
async def release_asr_model():
    release_generator()
    return {"status": "released"}
