from __future__ import annotations

from importlib import import_module

from fastapi import APIRouter, HTTPException

from .. import legacy_runtime


router = APIRouter(tags=["jobs"])


def _web_module():
    """延迟读取 `subtitle_maker.web`，便于测试 patch 旧导出名。"""

    return import_module("subtitle_maker.web")


@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """取消普通转写任务。"""

    task = legacy_runtime.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] in ["processing", "pending"]:
        task["status"] = "cancelled"
        return {"status": "cancelled"}
    return {"status": task["status"]}


@router.get("/status/{task_id}")
async def get_status(task_id: str):
    """读取普通转写任务状态。"""

    task = legacy_runtime.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/model/asr/release")
async def release_asr_model():
    """释放当前 ASR 模型。"""

    _web_module().release_generator()
    return {"status": "released"}


@router.post("/model/all/release")
async def release_all_models():
    """释放所有模型，并取消进行中的任务。"""

    web_module = _web_module()
    reason = "Cancelled via model release"
    cancelled_transcriptions = web_module.cancel_active_transcriptions(reason)
    cancelled_auto_tasks = web_module.cancel_active_dubbing(reason)
    web_module.release_generator()
    index_tts_release = web_module.release_index_tts_model()
    return {
        "status": "all models released",
        "cancelled_transcriptions": cancelled_transcriptions,
        "cancelled_auto_tasks": cancelled_auto_tasks,
        "index_tts_release": index_tts_release,
    }


@router.get("/model/index-tts/status")
async def get_index_tts_model_status():
    """返回 Index-TTS 当前服务状态。"""

    return _web_module().get_index_tts_status()


@router.post("/model/index-tts/start")
async def start_index_tts_model_service():
    """启动 Index-TTS 服务。"""

    return _web_module().start_index_tts_service()


@router.post("/model/index-tts/release")
async def release_index_tts_model_service():
    """释放 Index-TTS 模型。"""

    return _web_module().release_index_tts_model()


@router.post("/model/index-tts/stop")
async def stop_index_tts_model_service():
    """停止 Index-TTS 服务。"""

    return _web_module().stop_index_tts_service()

