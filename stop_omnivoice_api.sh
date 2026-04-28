#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/omnivoice_api.pid"
OMNIVOICE_PORT="${OMNIVOICE_PORT:-8020}"

echo "Stopping local OmniVoice API..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" >/dev/null 2>&1; then
        kill "$PID" >/dev/null 2>&1 || true
        echo "Stopped PID $PID"
    fi
    rm -f "$PID_FILE"
fi

if lsof -Pi :"$OMNIVOICE_PORT" -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up port $OMNIVOICE_PORT..."
    lsof -ti:"$OMNIVOICE_PORT" | xargs kill -9 || true
fi

echo "Done."
