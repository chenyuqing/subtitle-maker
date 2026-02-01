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

# Terminate FastAPI/Qwen3-ASR processes
kill_pattern "subtitle-maker-web" "subtitle-maker CLI wrapper"
kill_pattern "uv run subtitle-maker-web" "uv launcher"
kill_pattern "uvicorn .*subtitle_maker.web" "uvicorn workers"
kill_pattern "python[0-9.]* .*subtitle_maker/web.py" "direct python workers"

# Clean up port 8000 listeners
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up process on port 8000..."
    lsof -ti:8000 | xargs kill -9
    echo "Port 8000 cleared."
fi

# Stop local Sakura translation model
kill_pattern "llama-server" "Local Sakura model"

if lsof -Pi :8081 -sTCP:LISTEN -t >/dev/null ; then
    echo "Cleaning up port 8081..."
    lsof -ti:8081 | xargs kill -9
fi

echo "Done."
