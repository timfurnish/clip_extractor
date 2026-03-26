#!/bin/bash
#
# AV1 to H.264 Converter Droplet Script
# This script is designed to work with macOS Automator as a droplet
#

# Resolve this script's folder (portable — works from any install location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/convert_av1_to_h264.py"

if [ -n "${VIDEOGRABBER_PYTHON:-}" ] && [ -x "${VIDEOGRABBER_PYTHON}" ]; then
    PYTHON_PATH="${VIDEOGRABBER_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_PATH="python3"
else
    PYTHON_PATH="python"
fi

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "Error: Conversion script not found at: $PYTHON_SCRIPT"
    exit 1
fi

# Process each dropped item
for item in "$@"
do
    echo "Processing: $item"
    
    # Run the conversion script with absolute path
    "$PYTHON_PATH" "$PYTHON_SCRIPT" "$item"
    
    # Check exit status
    if [ $? -eq 0 ]; then
        osascript -e "display notification \"Conversion completed successfully\" with title \"AV1 Converter\" sound name \"Glass\""
    else
        osascript -e "display notification \"Conversion failed - check Terminal for details\" with title \"AV1 Converter\" sound name \"Basso\""
    fi
done

echo ""
echo "All conversions complete. Press any key to close..."
read -n 1 -s

