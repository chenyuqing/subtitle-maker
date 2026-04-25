from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Form, HTTPException
from starlette.concurrency import run_in_threadpool

from subtitle_maker.transcriber import format_srt
from subtitle_maker.translator import Translator

from .. import legacy_runtime


router = APIRouter(tags=["translation"])


@router.post("/translate")
async def translate(
    target_lang: str = Form(...),
    api_key: str = Form(...),
    task_id: Optional[str] = Form(None),
    subtitles_json: Optional[str] = Form(None),
    system_prompt: Optional[str] = Form(None),
):
    """Legacy 翻译入口，保留“任务内存优先，JSON 回退”的语义。"""

    subtitles = []
    task = None
    if task_id:
        task = legacy_runtime.tasks.get(task_id)

    if subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid subtitles JSON")
    elif task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])
    elif task_id:
        raise HTTPException(status_code=400, detail="Task not ready or not found")

    if not subtitles:
        return {"translated_subtitles": []}

    try:
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

        if task:
            task["translated_subtitles"] = translated_subtitles

        srt_content = format_srt(translated_subtitles)
        return {"translated_subtitles": translated_subtitles, "srt_content": srt_content}
    except Exception as exc:
        legacy_runtime.logger.error("Translation failed: %s", exc, exc_info=True)
        error_msg = str(exc)
        if "Authentication" in error_msg or "api_key" in error_msg.lower():
            raise HTTPException(status_code=401, detail=f"API Key 验证失败: {error_msg}")
        if "rate_limit" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(status_code=429, detail=f"请求过于频繁，请稍后再试: {error_msg}")
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(status_code=504, detail=f"请求超时，请检查网络: {error_msg}")
        if "connection" in error_msg.lower():
            raise HTTPException(status_code=502, detail=f"连接失败，请检查网络: {error_msg}")
        raise HTTPException(status_code=500, detail=f"翻译失败: {error_msg}")
