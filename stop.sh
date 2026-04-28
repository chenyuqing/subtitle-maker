#!/bin/bash
# Subtitle Maker 一键停止脚本（全量清理相关进程）

set -euo pipefail

# 统一切到项目目录，避免相对路径解析错误。
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

INDEX_TTS_PROJECT_DIR="${INDEX_TTS_PROJECT_DIR:-/Users/tim/Documents/vibe-coding/MVP/index-tts-1108}"
INDEX_TTS_STOP_SCRIPT="${INDEX_TTS_STOP_SCRIPT:-$INDEX_TTS_PROJECT_DIR/stop-api.sh}"
LOCAL_INDEX_TTS_STOP_SCRIPT="$PROJECT_DIR/stop_index_tts_api.sh"
LOCAL_OMNIVOICE_STOP_SCRIPT="$PROJECT_DIR/stop_omnivoice_api.sh"

say() {
    # 统一日志前缀，便于在终端快速识别 stop 阶段输出。
    echo "[stop] $*"
}

kill_pattern() {
    # 按命令行特征批量停止进程（先 TERM，再补 KILL）。
    local pattern="$1"
    local label="$2"
    local pids=""
    pids="$(pgrep -f "$pattern" || true)"
    if [ -z "${pids// }" ]; then
        return
    fi
    say "Stopping $label via pattern: $pattern"
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 0.3
    pids="$(pgrep -f "$pattern" || true)"
    if [ -n "${pids// }" ]; then
        echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
}

kill_pid_file() {
    # 通过 PID 文件停止进程，适配 index-tts / OmniVoice / legacy dubbing 脚本。
    local pid_file="$1"
    local label="$2"
    if [ ! -f "$pid_file" ]; then
        return
    fi
    local pid=""
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "${pid// }" ] && kill -0 "$pid" >/dev/null 2>&1; then
        say "Stopping $label by pid file: $pid_file (PID=$pid)"
        kill "$pid" >/dev/null 2>&1 || true
        sleep 0.3
        if kill -0 "$pid" >/dev/null 2>&1; then
            kill -9 "$pid" >/dev/null 2>&1 || true
        fi
    fi
    rm -f "$pid_file"
}

kill_port() {
    # 清理端口监听者，防止“脚本停了但端口仍被占用”。
    local port="$1"
    local label="$2"
    local pids=""
    pids="$(lsof -ti:"$port" 2>/dev/null || true)"
    if [ -z "${pids// }" ]; then
        return
    fi
    say "Cleaning port $port ($label)"
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 0.3
    pids="$(lsof -ti:"$port" 2>/dev/null || true)"
    if [ -n "${pids// }" ]; then
        echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
}

run_stop_script() {
    # 优先复用对应子系统 stop 脚本，保持和独立调试路径一致。
    local script_path="$1"
    local label="$2"
    if [ -x "$script_path" ]; then
        say "Running $label stop script: $script_path"
        "$script_path" || true
    fi
}

say "Stopping Subtitle Maker and related services..."

# 1) 先调用子系统 stop 脚本，优先走各自定义的停机逻辑。
run_stop_script "$INDEX_TTS_STOP_SCRIPT" "index-tts(external)"
run_stop_script "$LOCAL_INDEX_TTS_STOP_SCRIPT" "index-tts(local)"
run_stop_script "$LOCAL_OMNIVOICE_STOP_SCRIPT" "omnivoice(local)"

# 2) 再按 PID 文件兜底，避免脚本异常退出后遗留孤儿进程。
kill_pid_file "$PROJECT_DIR/index_tts_api.pid" "index-tts api"
kill_pid_file "$PROJECT_DIR/omnivoice_api.pid" "omnivoice api"
kill_pid_file "$PROJECT_DIR/dubbing.pid" "legacy dubbing server"

# 3) 按进程命令特征清理所有相关后端任务与服务。
kill_pattern "uv run subtitle-maker-web" "subtitle-maker launcher"
kill_pattern "subtitle-maker-web" "subtitle-maker cli wrapper"
kill_pattern "uvicorn .*subtitle_maker\\.web" "legacy web uvicorn"
kill_pattern "uvicorn .*subtitle_maker\\.app\\.main" "new app uvicorn"
kill_pattern "python[0-9.]* .*subtitle_maker/web.py" "legacy web python process"
kill_pattern "python[0-9.]* .*subtitle_maker/app/main.py" "new app python process"
kill_pattern "tools/dub_long_video.py" "long dubbing orchestrator"
kill_pattern "tools/dub_pipeline.py" "segment dubbing pipeline"
kill_pattern "tools/repair_bad_segments.py" "repair pipeline"
kill_pattern "tools/index_tts_fastapi_server.py" "index-tts local api"
kill_pattern "tools/omnivoice_fastapi_server.py" "omnivoice local api"
kill_pattern "llama-server" "local sakura model"

# 4) 最后按端口兜底清理监听者，确保下次 start 不会被端口占用阻塞。
kill_port 8000 "subtitle-maker web"
kill_port 8010 "index-tts api"
kill_port 8020 "omnivoice api"
kill_port 8081 "sakura llama-server"

# 5) 清理可能残留的 pid 文件，避免下次误判。
rm -f "$PROJECT_DIR/index_tts_api.pid" "$PROJECT_DIR/omnivoice_api.pid" "$PROJECT_DIR/dubbing.pid"

say "Done."
