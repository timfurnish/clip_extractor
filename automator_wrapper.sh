#!/bin/bash
#
# Automator Wrapper for AV1 Converter
# This ensures we're in the right directory and provides detailed error logging
#

# Set up logging
LOG_FILE="$HOME/Desktop/av1_converter_log.txt"
echo "=== AV1 Converter Run: $(date) ===" >> "$LOG_FILE"

# Change to this script's directory (portable — no hardcoded user paths)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || {
    echo "ERROR: Cannot change to directory: $SCRIPT_DIR" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Script directory not found!" with title "AV1 Converter Error" sound name "Basso"'
    exit 1
}

# Prefer python3 on PATH; set PYTHON to a specific interpreter if needed
if [ -n "${VIDEOGRABBER_PYTHON:-}" ] && [ -x "${VIDEOGRABBER_PYTHON}" ]; then
    PYTHON="${VIDEOGRABBER_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

# Check if conversion script exists
SCRIPT="./convert_av1_to_h264_auto.py"
if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: Conversion script not found at: $SCRIPT_DIR/$SCRIPT" | tee -a "$LOG_FILE"
    osascript -e 'display notification "Conversion script not found!" with title "AV1 Converter Error" sound name "Basso"'
    exit 1
fi

# Check if we received any input
if [ $# -eq 0 ]; then
    echo "ERROR: No files or folders were dropped on the droplet" | tee -a "$LOG_FILE"
    osascript -e 'display notification "No files or folders provided!" with title "AV1 Converter Error" sound name "Basso"'
    exit 1
fi

echo "Received $# item(s) to process" | tee -a "$LOG_FILE"

# Process each dropped folder/file
for item in "$@"
do
    echo "=========================================" | tee -a "$LOG_FILE"
    echo "Processing: $item" | tee -a "$LOG_FILE"
    echo "=========================================" | tee -a "$LOG_FILE"
    
    # Run the AUTO conversion script (no prompts - for droplet use)
    "$PYTHON" "$SCRIPT" "$item" 2>&1 | tee -a "$LOG_FILE"
    
    exitcode=${PIPESTATUS[0]}
    
    echo "Exit code: $exitcode" >> "$LOG_FILE"
    
    # Show notification with enhanced sound
    if [ $exitcode -eq 0 ]; then
        # Success notification with multiple sound cues
        osascript -e 'display notification "Conversion completed successfully!" with title "AV1 to H.264 Converter" sound name "Glass"'
        # Additional system beep for extra attention
        afplay /System/Library/Sounds/Glass.aiff 2>/dev/null || echo -e "\a"
    else
        # Error notification
        osascript -e 'display notification "Conversion failed - check Desktop log file" with title "AV1 Converter Error" sound name "Basso"'
        # Error beep
        afplay /System/Library/Sounds/Basso.aiff 2>/dev/null || echo -e "\a"
    fi
done

echo "" | tee -a "$LOG_FILE"
echo "All done! Check $LOG_FILE for details" | tee -a "$LOG_FILE"
echo "=== End of run ===" >> "$LOG_FILE"
echo ""

