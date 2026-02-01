import os
import uuid
import logging
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from .transcriber import parse_srt, format_srt
from .translator import Translator

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Simple Subtitle Translator")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def translate_srt_content(content: str, target_lang: str, system_prompt: Optional[str]):
    subtitles = parse_srt(content)
    if not subtitles:
        raise ValueError("无法解析 SRT 文件或文件为空。")

    translator = Translator(
        api_key="sk-no-key-required",
        base_url=os.environ.get("SAKURA_BASE_URL", "http://localhost:8081/v1"),
        model=os.environ.get("SAKURA_MODEL", "sakura-14b-qwen3-v1.5-iq4xs.gguf")
    )

    texts = [sub[text] for sub in subtitles]
    translated = translator.translate_batch(texts, target_lang=target_lang, system_prompt=system_prompt)

    rows = []
    for orig, trans in zip(subtitles, translated):
        rows.append({
            "start": orig[start],
            "end": orig[end],
            "original": orig[text],
            "translated": trans
        })

    translated_subs = []
    for sub, trans in zip(subtitles, translated):
        new_sub = sub.copy()
        new_sub[text] = trans
        translated_subs.append(new_sub)

    srt_content = format_srt(translated_subs)
    filename = f"simple_{uuid.uuid4().hex}_{target_lang}.srt"
    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    return rows, srt_content, filename

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        "simple_index.html",
        {
            "request": request,
            "result": None,
            "error": None
        }
    )

@app.post("/translate")
async def translate(
    request: Request,
    file: UploadFile = File(...),
    target_lang: str = Form("Chinese"),
    system_prompt: str = Form("")
):
    if not file.filename.lower().endswith(.srt):
        return templates.TemplateResponse(
            "simple_index.html",
            {
                "request": request,
                "result": None,
                "error": "请上传 .srt 文件"
            },
            status_code=400
        )

    content_bytes = await file.read()
    try:
        content_str = content_bytes.decode(utf-8)
    except UnicodeDecodeError:
        content_str = content_bytes.decode(latin-1)

    try:
        rows, srt_content, filename = translate_srt_content(content_str, target_lang, system_prompt or None)
        return templates.TemplateResponse(
            "simple_index.html",
            {
                "request": request,
                "result": {
                    "rows": rows,
                    "srt_content": srt_content,
                    "download_url": f"/download/{filename}",
                    "target_lang": target_lang,
                    "filename": filename
                },
                "error": None
            }
        )
    except Exception as exc:
        logger.error("Translation failed", exc_info=True)
        message = f"翻译失败：{exc}。请确认本地 Sakura 模型已通过 ./start_local_model.sh 启动。"
        return templates.TemplateResponse(
            "simple_index.html",
            {
                "request": request,
                "result": None,
                "error": message
            },
            status_code=500
        )

@app.get("/download/{filename}")
async def download(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return RedirectResponse("/", status_code=302)
    return FileResponse(path, filename=filename)


def start():
    import uvicorn
    uvicorn.run("subtitle_maker.simple_web:app", host="0.0.0.0", port=8100, reload=True)
