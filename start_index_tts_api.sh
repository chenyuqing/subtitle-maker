#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEX_TTS_ROOT="${INDEX_TTS_ROOT:-/Users/tim/Documents/vibe-coding/MVP/index-tts-1108}"
INDEX_TTS_PYTHON="${INDEX_TTS_PYTHON:-$INDEX_TTS_ROOT/.venv/bin/python}"
INDEX_TTS_CFG_PATH="${INDEX_TTS_CFG_PATH:-$INDEX_TTS_ROOT/checkpoints/config.yaml}"
INDEX_TTS_MODEL_DIR="${INDEX_TTS_MODEL_DIR:-$INDEX_TTS_ROOT/checkpoints}"
INDEX_TTS_DEVICE="${INDEX_TTS_DEVICE:-auto}"
INDEX_TTS_HOST="${INDEX_TTS_HOST:-127.0.0.1}"
INDEX_TTS_PORT="${INDEX_TTS_PORT:-8010}"
INDEX_TTS_LOG_PATH="${INDEX_TTS_LOG_PATH:-$PROJECT_DIR/outputs/index_tts_api.log}"
INDEX_TTS_AUTO_RESTART_REQUESTS="${INDEX_TTS_AUTO_RESTART_REQUESTS:-50}"
INDEX_TTS_AUTO_RESTART_EXIT_CODE="${INDEX_TTS_AUTO_RESTART_EXIT_CODE:-75}"
# 强制使用 index-tts 仓库本地缓存目录，确保离线场景命中已下载模型。
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
HF_HOME="${HF_HOME:-$INDEX_TTS_ROOT/checkpoints/hf_home}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$INDEX_TTS_ROOT/checkpoints/hf_cache}"
HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HUB_CACHE}"
TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$INDEX_TTS_ROOT/checkpoints/hf_transformers_cache}"
# 默认离线优先，防止运行时回退到 huggingface.co。
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
INDEX_TTS_FORCE_OFFLINE="${INDEX_TTS_FORCE_OFFLINE:-1}"
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
mkdir -p "$XDG_CACHE_HOME" "$HF_HOME" "$HF_HUB_CACHE" "$HUGGINGFACE_HUB_CACHE" "$TRANSFORMERS_CACHE" "$MPLCONFIGDIR" "$NUMBA_CACHE_DIR"

nohup env \
    XDG_CACHE_HOME="$XDG_CACHE_HOME" \
    HF_HOME="$HF_HOME" \
    HF_HUB_CACHE="$HF_HUB_CACHE" \
    HUGGINGFACE_HUB_CACHE="$HUGGINGFACE_HUB_CACHE" \
    TRANSFORMERS_CACHE="$TRANSFORMERS_CACHE" \
    HF_HUB_OFFLINE="$HF_HUB_OFFLINE" \
    TRANSFORMERS_OFFLINE="$TRANSFORMERS_OFFLINE" \
    INDEX_TTS_FORCE_OFFLINE="$INDEX_TTS_FORCE_OFFLINE" \
    INDEX_TTS_ROOT="$INDEX_TTS_ROOT" \
    INDEX_TTS_PYTHON="$INDEX_TTS_PYTHON" \
    INDEX_TTS_CFG_PATH="$INDEX_TTS_CFG_PATH" \
    INDEX_TTS_MODEL_DIR="$INDEX_TTS_MODEL_DIR" \
    INDEX_TTS_DEVICE="$INDEX_TTS_DEVICE" \
    INDEX_TTS_HOST="$INDEX_TTS_HOST" \
    INDEX_TTS_PORT="$INDEX_TTS_PORT" \
    INDEX_TTS_AUTO_RESTART_REQUESTS="$INDEX_TTS_AUTO_RESTART_REQUESTS" \
    INDEX_TTS_AUTO_RESTART_EXIT_CODE="$INDEX_TTS_AUTO_RESTART_EXIT_CODE" \
    MPLCONFIGDIR="$MPLCONFIGDIR" \
    NUMBA_CACHE_DIR="$NUMBA_CACHE_DIR" \
    PROJECT_DIR="$PROJECT_DIR" \
    /bin/bash -lc '
set -uo pipefail
child_pid=""
terminate_supervisor() {
    if [ -n "${child_pid:-}" ] && kill -0 "$child_pid" >/dev/null 2>&1; then
        kill "$child_pid" >/dev/null 2>&1 || true
        wait "$child_pid" >/dev/null 2>&1 || true
    fi
    exit 0
}
trap terminate_supervisor TERM INT
while true; do
    "$INDEX_TTS_PYTHON" "$PROJECT_DIR/tools/index_tts_fastapi_server.py" \
        --host "$INDEX_TTS_HOST" \
        --port "$INDEX_TTS_PORT" \
        --indextts-root "$INDEX_TTS_ROOT" \
        --cfg-path "$INDEX_TTS_CFG_PATH" \
        --model-dir "$INDEX_TTS_MODEL_DIR" \
        --device "$INDEX_TTS_DEVICE" \
        --auto-restart-requests "$INDEX_TTS_AUTO_RESTART_REQUESTS" &
    child_pid=$!
    wait "$child_pid"
    exit_code=$?
    child_pid=""
    if [ "$exit_code" -eq "$INDEX_TTS_AUTO_RESTART_EXIT_CODE" ]; then
        echo "index-tts auto restart triggered (exit=$exit_code, threshold=$INDEX_TTS_AUTO_RESTART_REQUESTS)"
        sleep 1
        continue
    fi
    exit "$exit_code"
done
' > "$INDEX_TTS_LOG_PATH" 2>&1 &

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
