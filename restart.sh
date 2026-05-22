#!/bin/bash
# Subtitle Maker 一键重启脚本

set -euo pipefail

# 统一切到项目目录，避免相对路径受当前 shell 路径影响。
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

say() {
    # 统一日志前缀，便于区分 restart 阶段输出。
    echo "[restart] $*"
}

# 先检查依赖脚本是否存在，避免半途中断。
if [ ! -x "$PROJECT_DIR/stop.sh" ]; then
    echo "[restart] Error: stop.sh 不存在或不可执行"
    exit 1
fi

if [ ! -x "$PROJECT_DIR/start.sh" ]; then
    echo "[restart] Error: start.sh 不存在或不可执行"
    exit 1
fi

# 先完整停止现有相关服务，确保端口和后台状态回到干净状态。
say "Stopping existing services..."
"$PROJECT_DIR/stop.sh"

# 给操作系统一点时间释放端口，减少刚停止就重启时的误判。
sleep 1

# 重新启动 Web 服务；后端仍保持现有懒加载策略。
say "Starting services..."
exec "$PROJECT_DIR/start.sh"
