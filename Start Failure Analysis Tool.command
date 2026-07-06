#!/bin/bash

# Double-clickable launcher for the Failure Analysis Tool (macOS)
# Starts the Streamlit server and opens it in Google Chrome automatically.
# Resolves its own location so it works no matter where the folder is moved.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1

echo "🔍 Starting Failure Analysis Pattern Recognition Tool..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    echo "Press any key to close this window..."
    read -n 1
    exit 1
fi

# Install required packages if Streamlit is missing
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "📦 Installing required packages (first run only)..."
    pip3 install -r requirements.txt
    echo ""
fi

# Pick a free TCP port so the URL we open always matches the server
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()' 2>/dev/null)"
[ -z "$PORT" ] && PORT=8501
URL="http://localhost:$PORT"

# Start Streamlit in the background (headless so it doesn't open a default
# browser — we open Chrome ourselves below). Flags are passed explicitly so
# behavior doesn't depend on ~/.streamlit/config.toml.
echo "🚀 Launching application on $URL ..."
python3 -m streamlit run failure_analysis_app.py \
    --server.headless=true \
    --server.port="$PORT" \
    --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

# Make sure the server is stopped if this window is closed or Ctrl+C is pressed
cleanup() {
    echo ""
    echo "🛑 Stopping server..."
    kill "$STREAMLIT_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# Wait until the server is actually accepting connections (max ~30s)
echo "⏳ Waiting for the server to start..."
for _ in $(seq 1 60); do
    if curl -s -o /dev/null "$URL"; then
        break
    fi
    # Stop waiting if Streamlit died during startup
    if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        echo "❌ The server failed to start. See the messages above."
        echo "Press any key to close this window..."
        read -n 1
        exit 1
    fi
    sleep 0.5
done

# Open Google Chrome at the app URL; fall back to the default browser
if open -a "Google Chrome" "$URL" 2>/dev/null; then
    echo "🌐 Opened in Google Chrome: $URL"
else
    echo "ℹ️  Google Chrome not found — opening your default browser instead."
    open "$URL"
fi

echo ""
echo "📊 The tool is now running in your browser."
echo "🛑 Press Ctrl+C here (or close this window) to stop the server."
echo ""

# Keep this script (and the server) running in the foreground until stopped
wait "$STREAMLIT_PID"
