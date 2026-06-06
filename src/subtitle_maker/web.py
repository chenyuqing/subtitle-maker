from __future__ import annotations

import logging
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

DEFAULT_WEB_PORT = int(os.environ.get("SUBTITLE_MAKER_PORT", "17493"))


class _SuppressPollingAccessLogFilter(logging.Filter):
    """过滤高频轮询接口的 access log，避免控制台被重复 200 刷屏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/dubbing/auto/status/" not in message


def _configure_access_log_filters() -> None:
    """为 uvicorn access logger 注入轮询降噪过滤器。"""

    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, _SuppressPollingAccessLogFilter) for existing in access_logger.filters):
        return
    access_logger.addFilter(_SuppressPollingAccessLogFilter())


def start():
    """迁移期启动入口：继续从 `subtitle_maker.web:app` 启动。"""

    import uvicorn

    # 在启动前先压掉高频轮询 access log，保留其余请求日志。
    _configure_access_log_filters()
    reload_enabled = os.environ.get("SUBTITLE_MAKER_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("subtitle_maker.web:app", host="0.0.0.0", port=DEFAULT_WEB_PORT, reload=reload_enabled, workers=1)
