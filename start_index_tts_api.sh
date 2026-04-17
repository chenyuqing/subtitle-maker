#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEX_TTS_ROOT="${INDEX_TTS_ROOT:-/Users/tim/Documents/vibe-coding/MVP/index-tts-1108}"
INDEX_TTS_PYTHON="${INDEX_TTS_PYTHON:-$INDEX_TTS_ROOT/.venv/bin/python}"
INDEX_TTS_CFG_PATH="${INDEX_TTS_CFG_PATH:-$INDEX_TTS_ROOT/checkpoints/config.yaml}"
INDEX_TTS_MODEL_DIR="${INDEX_TTS_MODEL_DIR:-$INDEX_TTS_ROOT/checkpoints}"
INDEX_TTS_HOST="${INDEX_TTS_HOST:-127.0.0.1}"
INDEX_TTS_PORT="${INDEX_TTS_PORT:-8010}"
INDEX_TTS_LOG_PATH="${INDEX_TTS_LOG_PATH:-$PROJECT_DIR/outputs/index_tts_api.log}"
# 优先复用系统级缓存目录（绝对路径），避免项目内临时缓存导致模型重复下载或离线找不到权重
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
MPLCONFIGDIR="${MPLCONFIGDIR:-$PROJECT_DIR/outputs/matplotlib}"
NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-$PROJECT_DIR/outputs/numba-cache}"
PID_FILE="$PROJECT_DIR/index_tts_api.pid"

echo "Starting local index-tts API..."

if [ ! -x "$INDEX_TTS_PYTHON" ]; then
    echo "Error: Python interpreter not found: $INDEX_TTS_PYTHON"
    echo "Set INDEX_TTS_PYTHON or recreate the external index-tts venv first."
    exit 1
fi

if [ ! -f "$INDEX_TTS_CFG_PATH" ]; then
    echo "Error: config not found: $INDEX_TTS_CFG_PATH"
    exit 1
fi

if [ ! -d "$INDEX_TTS_MODEL_DIR" ]; then
    echo "Error: model dir not found: $INDEX_TTS_MODEL_DIR"
    exit 1
fi

if lsof -Pi :"$INDEX_TTS_PORT" -sTCP:LISTEN -t >/dev/null ; then
    echo "Port $INDEX_TTS_PORT is already in use."
    if curl -sS "http://$INDEX_TTS_HOST:$INDEX_TTS_PORT/health" >/dev/null 2>&1; then
        echo "index-tts API is already healthy at http://$INDEX_TTS_HOST:$INDEX_TTS_PORT"
        exit 0
    fi
    echo "Existing listener is not healthy. Stop it first or change INDEX_TTS_PORT."
    exit 1
fi

mkdir -p "$(dirname "$INDEX_TTS_LOG_PATH")"
mkdir -p "$XDG_CACHE_HOME" "$HF_HOME" "$HUGGINGFACE_HUB_CACHE" "$TRANSFORMERS_CACHE" "$MPLCONFIGDIR" "$NUMBA_CACHE_DIR"

nohup env \
    XDG_CACHE_HOME="$XDG_CACHE_HOME" \
    HF_HOME="$HF_HOME" \
    HUGGINGFACE_HUB_CACHE="$HUGGINGFACE_HUB_CACHE" \
    TRANSFORMERS_CACHE="$TRANSFORMERS_CACHE" \
    MPLCONFIGDIR="$MPLCONFIGDIR" \
    NUMBA_CACHE_DIR="$NUMBA_CACHE_DIR" \
    "$INDEX_TTS_PYTHON" "$PROJECT_DIR/tools/index_tts_fastapi_server.py" \
    --host "$INDEX_TTS_HOST" \
    --port "$INDEX_TTS_PORT" \
    --indextts-root "$INDEX_TTS_ROOT" \
    --cfg-path "$INDEX_TTS_CFG_PATH" \
    --model-dir "$INDEX_TTS_MODEL_DIR" \
    > "$INDEX_TTS_LOG_PATH" 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"
echo "Spawned PID: $PID"
echo "Log file: $INDEX_TTS_LOG_PATH"

for _ in {1..30}; do
    if curl -sS "http://$INDEX_TTS_HOST:$INDEX_TTS_PORT/health" >/dev/null 2>&1; then
        echo "index-tts API is ready at http://$INDEX_TTS_HOST:$INDEX_TTS_PORT"
        exit 0
    fi
    sleep 1
done

echo "index-tts API did not become healthy in time."
echo "Last log lines:"
tail -n 40 "$INDEX_TTS_LOG_PATH" || true
exit 1
