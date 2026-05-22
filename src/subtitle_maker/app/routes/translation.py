from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Form, HTTPException
from starlette.concurrency import run_in_threadpool

from subtitle_maker.domains.subtitles import normalize_subtitles_with_speakers
from subtitle_maker.transcriber import format_srt
from subtitle_maker.translator import (
    DEFAULT_TRANSLATE_BASE_URL,
    DEFAULT_TRANSLATE_MODEL,
    Translator,
    get_translate_provider_host,
    get_translate_provider_label,
)

from .. import legacy_runtime


router = APIRouter(tags=["translation"])


def _raise_translation_http_error(action_label: str, exc: Exception) -> None:
    """把翻译相关异常统一映射成 HTTP 错误，避免前端自己猜错误类型。"""

    error_msg = str(exc)
    lowered = error_msg.lower()
    if "authentication" in lowered or "api_key" in lowered or "api key" in lowered:
        raise HTTPException(status_code=401, detail=f"{action_label} API Key 验证失败: {error_msg}")
    if "rate_limit" in lowered or "429" in error_msg:
        raise HTTPException(status_code=429, detail=f"{action_label}请求过于频繁，请稍后再试: {error_msg}")
    if "timeout" in lowered or "timed out" in lowered:
        raise HTTPException(status_code=504, detail=f"{action_label}请求超时，请检查网络: {error_msg}")
    if "connection" in lowered:
        raise HTTPException(status_code=502, detail=f"{action_label}连接失败，请检查网络: {error_msg}")
    raise HTTPException(status_code=500, detail=f"{action_label}失败: {error_msg}")


@router.post("/translate")
async def translate(
    target_lang: str = Form(...),
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
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
        subtitles, _ = normalize_subtitles_with_speakers(subtitles)
        translator = Translator(
            api_key=api_key,
            base_url=str(translate_base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL,
            model=str(translate_model or "").strip() or DEFAULT_TRANSLATE_MODEL,
        )
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
        _raise_translation_http_error("翻译", exc)


@router.post("/translation/test")
async def test_translation_connection(
    api_key: str = Form(""),
    translate_base_url: str = Form(DEFAULT_TRANSLATE_BASE_URL),
    translate_model: str = Form(DEFAULT_TRANSLATE_MODEL),
):
    """测试当前 OpenAI-compatible 翻译配置是否可连通。"""

    try:
        normalized_base_url = str(translate_base_url or "").strip() or DEFAULT_TRANSLATE_BASE_URL
        normalized_model = str(translate_model or "").strip() or DEFAULT_TRANSLATE_MODEL
        translator = Translator(
            api_key=api_key,
            base_url=normalized_base_url,
            model=normalized_model,
        )
        result = await run_in_threadpool(translator.test_connection)
        provider_label = get_translate_provider_label(normalized_base_url)
        provider_host = get_translate_provider_host(normalized_base_url)
        return {
            "ok": True,
            "provider": provider_label,
            "provider_host": provider_host,
            "model": normalized_model,
            "reply": result.get("reply", ""),
        }
    except Exception as exc:
        legacy_runtime.logger.error("Translation connection test failed: %s", exc, exc_info=True)
        _raise_translation_http_error("连通性测试", exc)
