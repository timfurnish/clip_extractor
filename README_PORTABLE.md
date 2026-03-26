# VideoGrabber — portable install

This folder is intended to run from **any location** on your machine (or from a USB drive). Nothing in the scripts assumes a fixed username or home-directory path.

## Quick start

1. **Python 3.10+** recommended. Install dependencies:

   ```bash
   cd /path/to/VideoGrabber
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **ffmpeg** must be on your `PATH` (e.g. `brew install ffmpeg` on macOS).

3. **Run the app** (interactive mode):

   ```bash
   ./run_clip_extractor.sh
   ```

   Or:

   ```bash
   python3 clip_extractor.py
   ```

4. **Choose where outputs go**
   - **RTF workflow:** After you pick the RTF file, option **1** opens a **folder picker** (recommended). You can still save next to the RTF or create a subfolder.
   - **Single video download:** If you have a saved folder from last time, you can reuse it; otherwise a **folder picker** opens. You can type a path if you cancel the picker.

## macOS file / folder dialogs

On macOS, `clip_extractor` uses **AppleScript** (`osascript`) for open/save panels so it does not depend on Tk. Some Python builds ship a Tk that requires a **newer macOS point release** than yours and can abort with `macOS 15 (1507) or later required`. If you see that message from **other** tools using Tk, this project avoids Tk for pickers on macOS. If a dialog is cancelled, you can **type the path** when prompted.

## Optional: custom Python

If `python3` on your `PATH` is not the one with dependencies installed:

```bash
export VIDEOGRABBER_PYTHON="/path/to/python"
./run_clip_extractor.sh
```

The AV1 droplet scripts (`automator_wrapper.sh`, `convert_av1_droplet.sh`) also respect `VIDEOGRABBER_PYTHON`.

## YouTube cookies (optional)

To improve quality or access, place exported Netscape-format cookies next to the scripts as `youtube_cookies.txt` (see on-screen instructions). **Do not share cookie files**; they are session secrets.

## Files that stay local (not for sharing)

- `.last_destination.txt` — remembers your last single-video download folder (delete anytime).
- `youtube_cookies*.txt` — your sessions; keep out of git/public zips.

## Packaging for others

Zip this directory **without** cookie files and without `.last_destination.txt`. Recipients install dependencies, run `run_clip_extractor.sh` or `python3 clip_extractor.py`, and pick their own output folders when prompted.
