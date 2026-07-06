#!/bin/bash

# Failure Analysis Tool Startup Script

echo "🔍 Starting Failure Analysis Pattern Recognition Tool..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Check if required packages are installed
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "📦 Installing required packages..."
    pip3 install -r requirements.txt
    echo ""
fi

# Ensure Streamlit config directory exists
mkdir -p ~/.streamlit

# Create config if it doesn't exist
if [ ! -f ~/.streamlit/config.toml ]; then
    echo "⚙️  Creating Streamlit configuration..."
    cat > ~/.streamlit/config.toml << 'EOF'
[browser]
gatherUsageStats = false

[server]
headless = true

[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
EOF
    echo "✅ Configuration created"
    echo ""
fi

# Start the application
echo "🚀 Launching application..."
echo "📊 The app will open in your default browser"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

python3 -m streamlit run failure_analysis_app.py
