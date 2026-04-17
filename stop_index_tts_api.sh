#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/index_tts_api.pid"
INDEX_TTS_PORT="${INDEX_TTS_PORT:-8010}"

echo "Stopping local index-tts API..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" >/dev/null 2>&1; then
        kill "$PID" >/dev/null 2>&1 || true
        echo "Stopped PID $PID"
    fi
    rm -f "$PID_FILE"
fi

if lsof -Pi :"$INDEX_TTS_PORT" -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up port $INDEX_TTS_PORT..."
    lsof -ti:"$INDEX_TTS_PORT" | xargs kill -9 || true
fi

echo "Done."
