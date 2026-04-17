#!/bin/bash
# Subtitle Maker Stop Script

set -euo pipefail

echo "Stopping Subtitle Maker..."

kill_pattern() {
    local pattern="$1"
    local label="$2"
    if pkill -f "$pattern" >/dev/null 2>&1; then
        echo "Stopped $label ($pattern)."
    fi
}

INDEX_TTS_PROJECT_DIR="${INDEX_TTS_PROJECT_DIR:-/Users/tim/Documents/vibe-coding/MVP/index-tts-1108}"
INDEX_TTS_STOP_SCRIPT="${INDEX_TTS_STOP_SCRIPT:-$INDEX_TTS_PROJECT_DIR/stop-api.sh}"

# Terminate FastAPI/Qwen3-ASR processes
kill_pattern "subtitle-maker-web" "subtitle-maker CLI wrapper"
kill_pattern "uv run subtitle-maker-web" "uv launcher"
kill_pattern "uvicorn .*subtitle_maker.web" "uvicorn workers"
kill_pattern "python[0-9.]* .*subtitle_maker/web.py" "direct python workers"

# Clean up port 8000 listeners
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up process on port 8000..."
    lsof -ti:8000 | xargs kill -9 || true
    if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
        echo "Warning: port 8000 still occupied."
    else
        echo "Port 8000 cleared."
    fi
fi

# Stop local Sakura translation model
kill_pattern "llama-server" "Local Sakura model"

if lsof -Pi :8081 -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up port 8081..."
    lsof -ti:8081 | xargs kill -9 || true
fi

# 优先停止 index-tts 项目内独立 API 服务脚本
if [ -x "$INDEX_TTS_STOP_SCRIPT" ]; then
    "$INDEX_TTS_STOP_SCRIPT" || true
# 兼容旧脚本：外部脚本不存在时回退到本仓库脚本
elif [ -f ./stop_index_tts_api.sh ]; then
    ./stop_index_tts_api.sh || true
else
    # Stop local index-tts API
    kill_pattern "tools/index_tts_fastapi_server.py" "Local index-tts API"
    kill_pattern "index_tts_fastapi_server.py" "Local index-tts API"

    if lsof -Pi :8010 -sTCP:LISTEN -t >/dev/null ; then
        echo "Cleaning up port 8010..."
        lsof -ti:8010 | xargs kill -9 || true
    fi

    if [ -f index_tts_api.pid ]; then
        rm -f index_tts_api.pid
    fi
fi

echo "Done."
