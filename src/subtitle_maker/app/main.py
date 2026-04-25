from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from subtitle_maker.agent_api import router as agent_router
from subtitle_maker.dubbing_cli_api import router as dubbing_router
from subtitle_maker.streaming_api import router as streaming_router

from . import legacy_runtime
from .routes.exports import router as exports_router
from .routes.jobs import router as jobs_router
from .routes.projects import router as projects_router
from .routes.subtitles import router as subtitles_router
from .routes.translation import router as translation_router


def create_app() -> FastAPI:
    """创建迁移期 FastAPI app，并挂载 legacy routes。"""

    app = FastAPI()
    app.mount("/static", StaticFiles(directory=legacy_runtime.STATIC_DIR), name="static")
    app.include_router(streaming_router)
    app.include_router(dubbing_router)
    app.include_router(agent_router)
    app.include_router(projects_router)
    app.include_router(subtitles_router)
    app.include_router(translation_router)
    app.include_router(exports_router)
    app.include_router(jobs_router)
    return app


app = create_app()
