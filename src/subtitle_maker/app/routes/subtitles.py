from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from subtitle_maker.transcriber import format_srt, merge_subtitles, parse_srt
from subtitle_maker.translator import Translator

from .. import legacy_runtime


router = APIRouter(tags=["subtitles"])


@router.post("/upload_srt")
async def upload_srt(
    file: UploadFile = File(...),
    video_filename: Optional[str] = Form(None),
):
    """上传现成 SRT，并直接生成可供前端消费的任务记录。"""

    if not file.filename.endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files are supported")

    content_bytes = await file.read()
    try:
        content_str = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = content_bytes.decode("latin-1")

    subtitles = parse_srt(content_str)
    if not subtitles:
        raise HTTPException(status_code=400, detail="Could not parse subtitles or file is empty")

    task_id = str(uuid.uuid4())
    legacy_runtime.tasks[task_id] = {
        "status": "completed",
        "filename": file.filename,
        "video_filename": video_filename,
        "subtitles": subtitles,
        "translated_subtitles": None,
    }
    return {"task_id": task_id, "filename": file.filename, "subtitles": subtitles}


@router.post("/transcribe/sync")
async def transcribe_sync(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    max_width: int = Form(40),
    target_lang: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    system_prompt: Optional[str] = Form(None),
):
    """同步转写入口：上传媒体后直接返回 SRT 文本。"""

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    filepath = os.path.join(legacy_runtime.UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task_id = str(uuid.uuid4())
    legacy_runtime.tasks[task_id] = {"status": "pending", "filename": filename}
    do_translate = target_lang and api_key

    try:
        await asyncio.to_thread(
            legacy_runtime.transcribe_task,
            task_id,
            filepath,
            language,
            max_width,
            None,
            None,
        )

        task = legacy_runtime.tasks.get(task_id)
        if not task or task.get("status") != "completed":
            error = task.get("error", "Transcription failed") if task else "Task not found"
            raise HTTPException(status_code=500, detail=f"Transcription failed: {error}")

        subtitles = task.get("subtitles", [])
        if do_translate and subtitles:
            translator = Translator(api_key=api_key)
            original_texts = [sub["text"] for sub in subtitles]
            translated_texts = await run_in_threadpool(
                translator.translate_batch,
                original_texts,
                target_lang=target_lang,
                system_prompt=system_prompt,
            )
            translated_subtitles = []
            for sub, trans_text in zip(subtitles, translated_texts):
                new_sub = sub.copy()
                new_sub["text"] = trans_text
                translated_subtitles.append(new_sub)
            bilingual_subtitles = merge_subtitles(subtitles, translated_subtitles, order="orig_trans")
            srt_content = format_srt(bilingual_subtitles)
        else:
            srt_content = format_srt(subtitles)

        legacy_runtime.tasks.pop(task_id, None)
        return PlainTextResponse(srt_content, media_type="text/plain")
    except HTTPException:
        raise
    except Exception as exc:
        legacy_runtime.logger.error("Sync transcription failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(exc)}")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        legacy_runtime.tasks.pop(task_id, None)


@router.post("/transcribe")
async def transcribe(
    background_tasks: BackgroundTasks,
    filename: str = Form(...),
    language: str = Form("auto"),
    max_width: int = Form(40),
    original_filename: Optional[str] = Form(None),
    time_ranges: Optional[str] = Form(None),
    existing_subtitles: Optional[str] = Form(None),
):
    """异步转写入口，保留 legacy 轮询语义。"""

    time_ranges_list = None
    if time_ranges:
        try:
            time_ranges_list = json.loads(time_ranges)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid time_ranges JSON")

    existing_subs = None
    if existing_subtitles:
        try:
            existing_subs = json.loads(existing_subtitles)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid existing_subtitles JSON")

    task_id = str(uuid.uuid4())
    filepath = os.path.join(legacy_runtime.UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    legacy_runtime.tasks[task_id] = {
        "status": "pending",
        "video_filename": filename,
        "original_filename": original_filename,
    }

    if len(legacy_runtime.tasks) > 100:
        keys_to_remove = list(legacy_runtime.tasks.keys())[:20]
        for key in keys_to_remove:
            del legacy_runtime.tasks[key]

    background_tasks.add_task(
        legacy_runtime.transcribe_task,
        task_id,
        filepath,
        language,
        max_width,
        time_ranges_list,
        existing_subs,
    )
    return {"task_id": task_id}

