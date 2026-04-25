from __future__ import annotations

import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.requests import Request

from subtitle_maker.dubbing_cli_api import cancel_active_dubbing

from .. import legacy_runtime


router = APIRouter(tags=["projects"])


@router.get("/")
async def index(request: Request):
    """渲染主页面模板。"""

    context = {
        "request": request,
        "app_js_version": legacy_runtime._static_version("app.js"),
        "style_css_version": legacy_runtime._static_version("style.css"),
    }
    return legacy_runtime.templates.TemplateResponse(request, "index.html", context)


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """上传媒体文件，并返回可直接回放的 URL。"""

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    filepath = os.path.join(legacy_runtime.UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"file_id": file_id, "filename": filename, "url": f"/stream/{filename}"}


@router.get("/stream/{filename}")
async def stream_video(filename: str):
    """回放已上传的原始媒体。"""

    file_path = os.path.join(legacy_runtime.UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.post("/project/reset")
async def reset_project_storage():
    """清理 legacy 上传/输出目录，但保留 dubbing 历史目录。"""

    cancelled_auto_tasks = cancel_active_dubbing("Cancelled via project reset")
    uploads_removed = legacy_runtime.clear_directory_contents(
        legacy_runtime.UPLOAD_DIR,
        exclude_names={"dubbing"},
    )
    dubbing_pruned = legacy_runtime.prune_dubbing_uploads_keep_latest_videos(
        os.path.join(legacy_runtime.UPLOAD_DIR, "dubbing"),
        keep_count=3,
    )
    outputs_removed = legacy_runtime.clear_directory_contents(
        legacy_runtime.OUTPUT_DIR,
        exclude_names={"dub_jobs"},
    )
    return {
        "status": "reset",
        "cancelled_auto_tasks": cancelled_auto_tasks,
        "uploads_removed": uploads_removed,
        "dubbing_pruned": dubbing_pruned,
        "outputs_removed": outputs_removed,
    }
