#!/bin/bash
APP_DIR="/Users/hectordelgado/Desktop/claude_code/bp_app"
PYTHON="/opt/anaconda3/bin/python"
PORT=8080

# Start server only if not already running on PORT
if ! lsof -i :"$PORT" -sTCP:LISTEN -t > /dev/null 2>&1; then
    cd "$APP_DIR"
    nohup "$PYTHON" app.py > /tmp/bp_app.log 2>&1 &
    # Wait up to 5 seconds for server to be ready
    for i in $(seq 1 10); do
        sleep 0.5
        if lsof -i :"$PORT" -sTCP:LISTEN -t > /dev/null 2>&1; then
            break
        fi
    done
fi

open "http://127.0.0.1:$PORT"
