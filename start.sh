#!/bin/bash

# Install ffmpeg if not present
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg
fi

# Install Python dependencies
pip install -r requirements.txt

# Start bot
python3 bot.py
