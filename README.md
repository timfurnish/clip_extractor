# VideoGrabber / clip_extractor

**Repository:** [github.com/timfurnish/clip_extractor](https://github.com/timfurnish/clip_extractor)

Python tools for downloading media and **extracting clips** from videos using **RTF tables** (URLs, timecodes, dialogue), **yt-dlp**, and **ffmpeg**. Optional **Whisper** powers Smart mode (word-boundary clipping).

## What’s included

| Script | Purpose |
|--------|---------|
| **`clip_extractor.py`** | Main workflow: RTF → download or **local folder** → clip extraction; single-URL download; optional **YouTube diagnostics** (formats, cookies, proxy). |
| **`run_clip_extractor.sh`** | Launches `clip_extractor.py` with unbuffered output; respects `VIDEOGRABBER_PYTHON`. |
| **`media_downloader.py`** | Bulk download from RTF links (full files, duplicate tracking). |

## Requirements

- **Python 3.10+** recommended  
- **ffmpeg** on `PATH` (required for video processing)  
- **yt-dlp** (listed in `requirements.txt`)  
- Optional: **Whisper / PyTorch** only if you use Smart mode  

## Install

```bash
cd /path/to/VideoGrabber
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On macOS: `brew install ffmpeg`

## Quick start — clip extractor

```bash
python3 clip_extractor.py
# or
./run_clip_extractor.sh
```

Interactive flow:

1. **Download mode** — single URL, RTF-based download + clips, **process a folder of already-downloaded videos** using RTF timecodes (no re-download), or **YouTube diagnostics** for one URL.  
2. Pick the **RTF** (if applicable) and **output folder** (folder picker on macOS via AppleScript; avoids fragile Tk dialogs on some macOS/Python builds).  
3. Set **buffer** or **Smart** mode and run.

Clips are written under the output folder, grouped by sanitized video title. Logs: `clip_extraction_log.txt` in the output directory.

## Features (clip extractor)

- **RTF tables** with hyperlinks: URLs, **Timeframe** cells (`0:08-0:12`, `1:49-1:58 & 2:09-2:16`, spaced variants like `4:13 - 4:23`), dialogue/labels for filenames.  
- **YouTube:** prefers best quality; if 720p+ exists, enforces minimum 720p unless none are available; optional **`youtube_cookies.txt`** (Netscape) next to the script for restricted videos.  
- **Proxy:** yt-dlp is configured to ignore system proxy env by default (avoids broken corporate proxy errors); adjust in code if you need a proxy.  
- **Local folder mode:** point at a directory whose **subfolders** match RTF titles; picks the main video file per folder (name similarity + size).  
- **ffmpeg:** fast stream-copy when possible; automatic **H.264/AAC** re-encode if copy fails (e.g. ProRes → MP4).  
- **Portable use:** see **[README_PORTABLE.md](README_PORTABLE.md)** (`VIDEOGRABBER_PYTHON`, packaging, files not to share).

## Media downloader (full files from RTF)

```bash
python3 media_downloader.py
# or
python3 media_downloader.py "/path/to/links.rtf" "/path/to/output"
```

Tracks URLs in `downloaded_urls.txt` and writes logs/stats in the output directory.

## RTF format

Hyperlinks should use standard RTF fields, e.g.:

```text
{\field{\*\fldinst{HYPERLINK "https://example.com/watch?v=..."}}{\fldrslt Display Title}}
```

Typical source: paste links from a spreadsheet into TextEdit/Word, save as **RTF**. Table columns expected by the clip extractor include link, timeframe, and dialogue/summary (see **[README_CLIP_EXTRACTION.md](README_CLIP_EXTRACTION.md)**).

## Documentation

| Doc | Contents |
|-----|----------|
| **[README_CLIP_EXTRACTION.md](README_CLIP_EXTRACTION.md)** | RTF columns, timecodes, modes, buffers |
| **[README_PORTABLE.md](README_PORTABLE.md)** | Venv, ffmpeg, macOS dialogs, cookies, zipping for others |
| **[QUICKSTART.md](QUICKSTART.md)** | Short getting-started steps |
| **[SMART_MODE_GUIDE.md](SMART_MODE_GUIDE.md)** | Whisper Smart mode |
| **[FEATURES_OVERVIEW.md](FEATURES_OVERVIEW.md)** | Feature comparison |
| **[CREATE_DROPLET_INSTRUCTIONS.md](CREATE_DROPLET_INSTRUCTIONS.md)** | macOS Automator / AV1 helper droplets |

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| `yt-dlp not found` | `pip install yt-dlp` in the same environment you use to run the script |
| `ffmpeg not found` | Install ffmpeg and ensure it is on `PATH` |
| Low quality on YouTube | Export cookies to `youtube_cookies.txt`; run **diagnostics** mode on the URL |
| No timeframe / wrong clips | Ensure Timeframe cells match `m:ss-m:ss` (or multi-range with `&`); use latest parser (fixes hyphen cleanup that could break ranges like `12:49-13:02`) |
| macOS dialog / Tk crash | This project uses **AppleScript** pickers on macOS; use `run_clip_extractor.sh` and see README_PORTABLE |

## License

For personal and educational use. Respect each platform’s terms of service and copyright.
