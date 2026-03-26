#!/usr/bin/env bash
# Portable launcher: run from any folder; uses python3 on PATH unless VIDEOGRABBER_PYTHON is set.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# -u: unbuffered stdout/stderr so the terminal shows banners immediately
if [ -n "${VIDEOGRABBER_PYTHON:-}" ] && [ -x "${VIDEOGRABBER_PYTHON}" ]; then
    exec "${VIDEOGRABBER_PYTHON}" -u "${SCRIPT_DIR}/clip_extractor.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -u "${SCRIPT_DIR}/clip_extractor.py" "$@"
else
    exec python -u "${SCRIPT_DIR}/clip_extractor.py" "$@"
fi
