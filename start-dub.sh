#!/bin/bash
echo "Starting Dubbing Service (Subtitle Maker)..."

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYANNOTE_LOCAL_MODEL_DIR="${PYANNOTE_LOCAL_MODEL_DIR:-$PROJECT_DIR/models/pyannote-speaker-diarization-community-1}"
PYANNOTE_EXTERNAL_PYTHON_DEFAULT="$PROJECT_DIR/.venv-pyannote/bin/python"
PYANNOTE_EXTERNAL_PYTHON_FALLBACK="/Users/tim/Documents/vibe-coding/MVP/index-tts-1108/.venv/bin/python"

# 优先使用本地 pyannote 社区模型，避免运行时再走网络下载
if [ -z "${PYANNOTE_MODEL_SOURCE:-}" ]; then
    if [ -d "$PYANNOTE_LOCAL_MODEL_DIR" ]; then
        export PYANNOTE_MODEL_SOURCE="$PYANNOTE_LOCAL_MODEL_DIR"
        echo "PYANNOTE_MODEL_SOURCE set to local path: $PYANNOTE_MODEL_SOURCE"
    else
        echo "Warning: Local pyannote model not found: $PYANNOTE_LOCAL_MODEL_DIR"
    fi
else
    echo "PYANNOTE_MODEL_SOURCE preset: $PYANNOTE_MODEL_SOURCE"
fi

# 使用独立 Python 跑 pyannote community-1，规避主项目 torchaudio 版本冲突
if [ -z "${PYANNOTE_PYTHON_BIN:-}" ]; then
    if [ -x "$PYANNOTE_EXTERNAL_PYTHON_DEFAULT" ]; then
        export PYANNOTE_PYTHON_BIN="$PYANNOTE_EXTERNAL_PYTHON_DEFAULT"
        echo "PYANNOTE_PYTHON_BIN set to: $PYANNOTE_PYTHON_BIN"
    elif [ -x "$PYANNOTE_EXTERNAL_PYTHON_FALLBACK" ]; then
        export PYANNOTE_PYTHON_BIN="$PYANNOTE_EXTERNAL_PYTHON_FALLBACK"
        echo "Warning: using fallback pyannote python from index-tts env"
        echo "PYANNOTE_PYTHON_BIN set to: $PYANNOTE_PYTHON_BIN"
    else
        echo "Warning: External pyannote python not found: $PYANNOTE_EXTERNAL_PYTHON_DEFAULT"
    fi
else
    echo "PYANNOTE_PYTHON_BIN preset: $PYANNOTE_PYTHON_BIN"
fi

# Ensure dependencies are up to date
uv sync

# Run the Uvicorn server in the background
# We usage --reload for development
uv run python -m uvicorn subtitle_maker.web:app --host 0.0.0.0 --port 8000 --reload &

PID=$!
echo $PID > dubbing.pid

echo "Service started successfully!"
echo "PID: $PID"
echo "Logs: Output to terminal"
echo "Access at: http://localhost:8000"
