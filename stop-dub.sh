#!/bin/bash

PORT=8000

echo "Stopping Dubbing Service..."

# 1. Try PID file
if [ -f dubbing.pid ]; then
    PID=$(cat dubbing.pid)
    echo "Found PID file: $PID"
    if ps -p $PID > /dev/null; then
        echo "Killing PID $PID..."
        kill $PID 2>/dev/null
    else
        echo "PID $PID not running. Removing stale PID file."
    fi
    rm dubbing.pid
fi

# 2. Check Port and Force Kill if needed
PORT_PID=$(lsof -ti :$PORT)
if [ -n "$PORT_PID" ]; then
    echo "Found process $PORT_PID listening on port $PORT. Killing..."
    kill -9 $PORT_PID 2>/dev/null
fi

# 3. Final cleanup by name
pkill -f "uvicorn subtitle_maker.web:app" 2>/dev/null

# 4. Wait for port to be free
echo "Waiting for port $PORT to be released..."
for i in {1..10}; do
    if ! lsof -i :$PORT > /dev/null; then
        echo "Port $PORT is free."
        exit 0
    fi
    echo "Waiting... ($i/10)"
    sleep 1
done

echo "WARNING: Port $PORT might still be in use."
exit 1
