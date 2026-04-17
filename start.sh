#!/bin/bash
# Subtitle Maker Start Script

set -euo pipefail

# Ensure we are in the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "Starting Subtitle Maker..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: 'uv' is not installed. Please install it first."
    echo "Install command: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "Warning: Port 8000 is already in use."
    read -p "Do you want to stop the existing process? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ./stop.sh
        sleep 1
    else
        echo "Aborting start."
        exit 1
    fi
fi

INDEX_TTS_AUTO_START="${INDEX_TTS_AUTO_START:-1}"
INDEX_TTS_URL="${INDEX_TTS_URL:-http://127.0.0.1:8010/health}"
INDEX_TTS_PROJECT_DIR="${INDEX_TTS_PROJECT_DIR:-/Users/tim/Documents/vibe-coding/MVP/index-tts-1108}"
INDEX_TTS_START_SCRIPT="${INDEX_TTS_START_SCRIPT:-$INDEX_TTS_PROJECT_DIR/start-api.sh}"
PYANNOTE_LOCAL_MODEL_DIR="${PYANNOTE_LOCAL_MODEL_DIR:-$PROJECT_DIR/models/pyannote-speaker-diarization-community-1}"
PYANNOTE_EXTERNAL_PYTHON_DEFAULT="$PROJECT_DIR/.venv-pyannote/bin/python"
PYANNOTE_EXTERNAL_PYTHON_FALLBACK="/Users/tim/Documents/vibe-coding/MVP/index-tts-1108/.venv/bin/python"

# 优先使用本地 pyannote 社区模型，避免运行时再走网络下载
if [[ -z "${PYANNOTE_MODEL_SOURCE:-}" ]]; then
    if [[ -d "$PYANNOTE_LOCAL_MODEL_DIR" ]]; then
        export PYANNOTE_MODEL_SOURCE="$PYANNOTE_LOCAL_MODEL_DIR"
        echo "PYANNOTE_MODEL_SOURCE set to local path: $PYANNOTE_MODEL_SOURCE"
    else
        echo "Warning: Local pyannote model not found: $PYANNOTE_LOCAL_MODEL_DIR"
    fi
else
    echo "PYANNOTE_MODEL_SOURCE preset: $PYANNOTE_MODEL_SOURCE"
fi

# 使用独立 Python 跑 pyannote community-1，规避主项目 torchaudio 版本冲突
if [[ -z "${PYANNOTE_PYTHON_BIN:-}" ]]; then
    if [[ -x "$PYANNOTE_EXTERNAL_PYTHON_DEFAULT" ]]; then
        export PYANNOTE_PYTHON_BIN="$PYANNOTE_EXTERNAL_PYTHON_DEFAULT"
        echo "PYANNOTE_PYTHON_BIN set to: $PYANNOTE_PYTHON_BIN"
    elif [[ -x "$PYANNOTE_EXTERNAL_PYTHON_FALLBACK" ]]; then
        export PYANNOTE_PYTHON_BIN="$PYANNOTE_EXTERNAL_PYTHON_FALLBACK"
        echo "Warning: using fallback pyannote python from index-tts env"
        echo "PYANNOTE_PYTHON_BIN set to: $PYANNOTE_PYTHON_BIN"
    else
        echo "Warning: External pyannote python not found: $PYANNOTE_EXTERNAL_PYTHON_DEFAULT"
    fi
else
    echo "PYANNOTE_PYTHON_BIN preset: $PYANNOTE_PYTHON_BIN"
fi

if [[ "$INDEX_TTS_AUTO_START" == "1" ]]; then
    echo "Checking local index-tts API..."
    if curl -sS "$INDEX_TTS_URL" > /dev/null 2>&1; then
        echo "index-tts API is already healthy."
    else
        echo "index-tts API is offline. Attempting to start it..."
        # 优先使用 index-tts 项目内独立脚本，保证与手动调试路径一致
        if [[ -x "$INDEX_TTS_START_SCRIPT" ]]; then
            if "$INDEX_TTS_START_SCRIPT"; then
                echo "index-tts API started by external script: $INDEX_TTS_START_SCRIPT"
            else
                echo "Warning: Failed to start index-tts API via $INDEX_TTS_START_SCRIPT."
            fi
        # 兼容旧脚本：当外部脚本不存在时，回退到当前仓库脚本
        elif [[ -x "./start_index_tts_api.sh" ]]; then
            if ./start_index_tts_api.sh; then
                echo "index-tts API started by local fallback script."
            else
                echo "Warning: Failed to start index-tts API via local fallback script."
            fi
        else
            echo "Warning: No index-tts start script found."
        fi
    fi
fi
if [[ "$INDEX_TTS_AUTO_START" != "1" ]]; then
    echo "index-tts auto-start is disabled (INDEX_TTS_AUTO_START=$INDEX_TTS_AUTO_START)."
fi

# Start the server in background to allow polling
echo "Launching server..."
uv run subtitle-maker-web &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to initialize..."
MAX_RETRIES=30
COUNT=0

while ! curl -s http://localhost:8000 > /dev/null; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "Error: Server took too long to start."
        echo "Tip: run ./stop.sh, then retry ./start.sh"
        kill $SERVER_PID
        exit 1
    fi
done

echo "Server is ready! Opening browser..."
open "http://localhost:8000"

# Handle script exit to kill server
trap "kill $SERVER_PID" EXIT

# Keep script running
wait $SERVER_PID
