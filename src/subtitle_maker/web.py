from __future__ import annotations

import os

from fastapi import HTTPException

from subtitle_maker.app.legacy_runtime import (
    OUTPUT_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
    UPLOAD_DIR,
    cancel_active_transcriptions,
    clear_directory_contents,
    generator,
    get_generator,
    logger,
    model_lock,
    prune_dubbing_uploads_keep_latest_videos,
    release_generator,
    tasks,
    templates,
    transcribe_task,
)
from subtitle_maker.app.main import app
from subtitle_maker.dubbing_cli_api import cancel_active_dubbing
from subtitle_maker.index_tts_service import (
    get_index_tts_status,
    release_index_tts_model,
    start_index_tts_service,
    stop_index_tts_service,
)


def start():
    """迁移期启动入口：继续从 `subtitle_maker.web:app` 启动。"""

    import uvicorn

    reload_enabled = os.environ.get("SUBTITLE_MAKER_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("subtitle_maker.web:app", host="0.0.0.0", port=8000, reload=reload_enabled, workers=1)
