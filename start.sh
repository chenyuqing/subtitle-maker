#!/bin/bash
# Subtitle Maker Start Script

# Ensure we are in the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "Starting Subtitle Maker..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: 'uv' is not installed. Please install it first."
    echo "Install command: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "Warning: Port 8000 is already in use."
    read -p "Do you want to stop the existing process? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ./stop.sh
        sleep 1
    else
        echo "Aborting start."
        exit 1
    fi
fi

# Start Local Model if script exists
# MOVED TO ON-DEMAND: Local model now starts only when requested via UI
# if [ -f "./start_local_model.sh" ]; then
#     echo "Starting Local Model Service..."
#     ./start_local_model.sh
# fi

# Start the server in background to allow polling
echo "Launching server..."
uv run subtitle-maker-web &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to initialize..."
MAX_RETRIES=30
COUNT=0

while ! curl -s http://localhost:8000 > /dev/null; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "Error: Server took too long to start."
        kill $SERVER_PID
        exit 1
    fi
done

echo "Server is ready! Opening browser..."
open "http://localhost:8000"

# Handle script exit to kill server
trap "kill $SERVER_PID" EXIT

# Keep script running
wait $SERVER_PID
