#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMNIVOICE_ROOT="${OMNIVOICE_ROOT:-/Users/tim/Documents/vibe-coding/MVP/OmniVoice}"
OMNIVOICE_PYTHON_BIN="${OMNIVOICE_PYTHON_BIN:-$OMNIVOICE_ROOT/.venv/bin/python}"
# 默认优先使用本地 checkpoints，避免首跑依赖 HuggingFace 在线下载。
OMNIVOICE_MODEL="${OMNIVOICE_MODEL:-$OMNIVOICE_ROOT/omnivoice/checkpoints}"
OMNIVOICE_HOST="${OMNIVOICE_HOST:-127.0.0.1}"
OMNIVOICE_PORT="${OMNIVOICE_PORT:-8020}"
OMNIVOICE_DEVICE="${OMNIVOICE_DEVICE:-auto}"
OMNIVOICE_LOG_PATH="${OMNIVOICE_LOG_PATH:-$PROJECT_DIR/outputs/omnivoice_api.log}"
OMNIVOICE_START_WAIT_SEC="${OMNIVOICE_START_WAIT_SEC:-180}"
OMNIVOICE_CURL_TIMEOUT_SEC="${OMNIVOICE_CURL_TIMEOUT_SEC:-2}"
PID_FILE="$PROJECT_DIR/omnivoice_api.pid"

echo "Starting local OmniVoice API..."

if [ ! -x "$OMNIVOICE_PYTHON_BIN" ]; then
    echo "Error: Python interpreter not found: $OMNIVOICE_PYTHON_BIN"
    echo "Set OMNIVOICE_PYTHON_BIN or recreate the OmniVoice venv first."
    exit 1
fi

if [ ! -d "$OMNIVOICE_ROOT" ]; then
    echo "Error: OmniVoice root not found: $OMNIVOICE_ROOT"
    exit 1
fi

# 兜底：防止环境变量误传导致算术循环报错。
if ! [[ "$OMNIVOICE_START_WAIT_SEC" =~ ^[0-9]+$ ]]; then
    OMNIVOICE_START_WAIT_SEC=180
fi
if ! [[ "$OMNIVOICE_CURL_TIMEOUT_SEC" =~ ^[0-9]+$ ]]; then
    OMNIVOICE_CURL_TIMEOUT_SEC=2
fi

if lsof -Pi :"$OMNIVOICE_PORT" -sTCP:LISTEN -t >/dev/null ; then
    echo "Port $OMNIVOICE_PORT is already in use."
    if curl -sS --max-time "$OMNIVOICE_CURL_TIMEOUT_SEC" "http://$OMNIVOICE_HOST:$OMNIVOICE_PORT/health" >/dev/null 2>&1; then
        echo "OmniVoice API is already healthy at http://$OMNIVOICE_HOST:$OMNIVOICE_PORT"
        exit 0
    fi
    echo "Existing listener is not healthy. Stop it first or change OMNIVOICE_PORT."
    exit 1
fi

mkdir -p "$(dirname "$OMNIVOICE_LOG_PATH")"

nohup \
    "$OMNIVOICE_PYTHON_BIN" "$PROJECT_DIR/tools/omnivoice_fastapi_server.py" \
    --host "$OMNIVOICE_HOST" \
    --port "$OMNIVOICE_PORT" \
    --omnivoice-root "$OMNIVOICE_ROOT" \
    --model "$OMNIVOICE_MODEL" \
    --device "$OMNIVOICE_DEVICE" \
    > "$OMNIVOICE_LOG_PATH" 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"
echo "Spawned PID: $PID"
echo "Log file: $OMNIVOICE_LOG_PATH"

for ((i=1; i<=OMNIVOICE_START_WAIT_SEC; i++)); do
    if curl -sS --max-time "$OMNIVOICE_CURL_TIMEOUT_SEC" "http://$OMNIVOICE_HOST:$OMNIVOICE_PORT/health" >/dev/null 2>&1; then
        echo "OmniVoice API is ready at http://$OMNIVOICE_HOST:$OMNIVOICE_PORT"
        exit 0
    fi
    sleep 1
done

echo "OmniVoice API did not become healthy in time."
echo "Last log lines:"
tail -n 40 "$OMNIVOICE_LOG_PATH" || true
exit 1
