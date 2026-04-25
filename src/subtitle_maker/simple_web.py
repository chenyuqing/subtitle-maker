from subtitle_maker.app.legacy_simple_app import app


def start():
    """启动旧版 simple 字幕翻译 wrapper。"""

    import uvicorn

    uvicorn.run("subtitle_maker.simple_web:app", host="0.0.0.0", port=8100, reload=True)


__all__ = ["app", "start"]
