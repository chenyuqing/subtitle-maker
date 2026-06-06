#!/bin/bash
# Subtitle Maker Start Script

set -euo pipefail

# Ensure we are in the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
WEB_PORT="${SUBTITLE_MAKER_PORT:-17493}"
WEB_URL="http://localhost:${WEB_PORT}"

echo "Starting Subtitle Maker..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: 'uv' is not installed. Please install it first."
    echo "Install command: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if port is already in use
if lsof -Pi :"$WEB_PORT" -sTCP:LISTEN -t >/dev/null ; then
    echo "Warning: Port $WEB_PORT is already in use."
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

# 当前统一走懒汉式 TTS 运行时：
# - `./start.sh` 只启动 Subtitle Maker Web
# - 配音后端由对应链路在实际请求到来时按需拉起
echo "TTS runtime mode: lazy on-demand (backend is not prewarmed by start.sh)"
PYANNOTE_LOCAL_MODEL_DIR="${PYANNOTE_LOCAL_MODEL_DIR:-$PROJECT_DIR/models/pyannote-speaker-diarization-community-1}"
PYANNOTE_EXTERNAL_PYTHON_DEFAULT="$PROJECT_DIR/.venv-pyannote/bin/python"
PYANNOTE_EXTERNAL_PYTHON_FALLBACK="/Users/tim/Documents/vibe-coding/MVP/OmniVoice/.venv/bin/python"

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
        echo "Warning: using fallback pyannote python from external env"
        echo "PYANNOTE_PYTHON_BIN set to: $PYANNOTE_PYTHON_BIN"
    else
        echo "Warning: External pyannote python not found: $PYANNOTE_EXTERNAL_PYTHON_DEFAULT"
    fi
else
    echo "PYANNOTE_PYTHON_BIN preset: $PYANNOTE_PYTHON_BIN"
fi

# Start the server in background to allow polling
echo "Launching server..."
uv run subtitle-maker-web &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to initialize..."
MAX_RETRIES=30
COUNT=0

while ! curl -s "$WEB_URL" > /dev/null; do
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
open "$WEB_URL"
echo "Tip: dubbing backend will auto-start only when the corresponding panel actually uses it."
echo "Tip: Auto Dubbing logs now include detailed runtime snapshot: TTS base, dubbing mode, grouping policy, timing mode, merge policy, range policy, and segment sizing."

# Handle script exit to kill server
trap "kill $SERVER_PID" EXIT

# Keep script running
wait $SERVER_PID
