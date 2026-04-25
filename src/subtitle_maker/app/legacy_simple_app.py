from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.translator import Translator


logger = logging.getLogger(__name__)

# 旧 simple app 仍复用 subtitle_maker 根目录下的模板与静态资源，
# 不能按当前文件路径去猜 `app/templates` 或 `app/static`。
SUBTITLE_MAKER_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = SUBTITLE_MAKER_ROOT / "templates"
STATIC_DIR = SUBTITLE_MAKER_ROOT / "static"
OUTPUT_DIR = "outputs"

os.makedirs(OUTPUT_DIR, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def translate_srt_content(content: str, target_lang: str, system_prompt: Optional[str]):
    """翻译 SRT 文本，并返回页面展示数据与生成文件名。"""

    subtitles = parse_srt(content)
    if not subtitles:
        raise ValueError("无法解析 SRT 文件或文件为空。")

    translator = Translator(
        api_key="sk-no-key-required",
        base_url=os.environ.get("SAKURA_BASE_URL", "http://localhost:8081/v1"),
        model=os.environ.get("SAKURA_MODEL", "sakura-14b-qwen3-v1.5-iq4xs.gguf"),
    )

    texts = [sub["text"] for sub in subtitles]
    translated = translator.translate_batch(
        texts,
        target_lang=target_lang,
        system_prompt=system_prompt,
    )

    rows = []
    translated_subtitles = []
    for source_subtitle, translated_text in zip(subtitles, translated):
        rows.append(
            {
                "start": source_subtitle["start"],
                "end": source_subtitle["end"],
                "original": source_subtitle["text"],
                "translated": translated_text,
            }
        )
        subtitle_copy = source_subtitle.copy()
        subtitle_copy["text"] = translated_text
        translated_subtitles.append(subtitle_copy)

    srt_content = format_srt(translated_subtitles)
    filename = f"simple_{uuid.uuid4().hex}_{target_lang}.srt"
    file_path = Path(OUTPUT_DIR) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(srt_content, encoding="utf-8")
    return rows, srt_content, filename


def create_app() -> FastAPI:
    """创建旧 simple 字幕翻译 app。"""

    simple_app = FastAPI(title="Simple Subtitle Translator")
    simple_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @simple_app.get("/")
    async def index(request: Request):
        """返回旧版 simple 上传页。"""

        return templates.TemplateResponse(
            request,
            "simple_index.html",
            {
                "result": None,
                "error": None,
            },
        )

    @simple_app.post("/translate")
    async def translate(
        request: Request,
        file: UploadFile = File(...),
        target_lang: str = Form("Chinese"),
        system_prompt: str = Form(""),
    ):
        """接收上传的 SRT 文件，并渲染旧版 simple 结果页。"""

        if not file.filename.lower().endswith(".srt"):
            return templates.TemplateResponse(
                request,
                "simple_index.html",
                {
                    "result": None,
                    "error": "请上传 .srt 文件",
                },
                status_code=400,
            )

        content_bytes = await file.read()
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content_str = content_bytes.decode("latin-1")

        try:
            rows, srt_content, filename = translate_srt_content(
                content_str,
                target_lang,
                system_prompt or None,
            )
            return templates.TemplateResponse(
                request,
                "simple_index.html",
                {
                    "result": {
                        "rows": rows,
                        "srt_content": srt_content,
                        "download_url": f"/download/{filename}",
                        "target_lang": target_lang,
                        "filename": filename,
                    },
                    "error": None,
                },
            )
        except Exception as exc:
            logger.error("Translation failed", exc_info=True)
            message = f"翻译失败：{exc}。请确认本地 Sakura 模型已通过 ./start_local_model.sh 启动。"
            return templates.TemplateResponse(
                request,
                "simple_index.html",
                {
                    "result": None,
                    "error": message,
                },
                status_code=500,
            )

    @simple_app.get("/download/{filename}")
    async def download(filename: str):
        """下载 simple app 生成的 SRT 文件。"""

        path = Path(OUTPUT_DIR) / filename
        if not path.exists():
            return RedirectResponse("/", status_code=302)
        return FileResponse(path, filename=filename)

    return simple_app


app = create_app()
