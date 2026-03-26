# VideoGrabber Quick Start Guide

## Choose Your Tool

### 🎥 Want full videos/images?
Use `media_downloader.py`

### ✂️ Want specific clips from videos?
Use `clip_extractor.py`

---

## Tool 1: Full Video/Image Downloader

### Use When:
- Archiving full videos for later
- Downloading images
- Building a media library
- Simple URL list without timeframes

### Quick Run:
```bash
python media_downloader.py
```
Then select your RTF file and target folder via dialogs.

### RTF Format:
An RTF file containing **hyperlinks** (RTF `HYPERLINK` fields). The downloader extracts
URLs from any cell that contains a real RTF hyperlink.
```
https://youtube.com/watch?v=abc123
https://youtube.com/watch?v=def456  
https://facebook.com/video/12345
```

### Output:
```
Output/
├── Video-Title-Here-1080p.mp4
├── Another-Video-720p.mp4
├── Image-Title.jpg
├── download_log.txt
└── downloaded_urls.txt
```

---

## Tool 2: Clip Extractor

### Use When:
- Building presentations with specific video segments
- Creating montages from multiple sources
- Extracting key moments (10-30 second clips)
- Have precise timeframes for each clip

### Quick Run (Interactive):
```bash
python clip_extractor.py
```
Then follow prompts to:
- Select RTF file
- Choose target directory
- Set time buffers (default: 2s before/after)
- Confirm and extract!

### Command Line Run:
```bash
python clip_extractor.py "your_file.rtf" "./output"
```

### RTF Format:
Multi-column table with URL, **Timeframe**, and **Dialogue**:

| Link | Timeframe | Dialogue |
|------|-----------|----------|
| https://youtube.com/... | 0:09-0:18 | "Opening quote" |
| https://youtube.com/... | 4:14-4:17 & 4:29-4:31 | "Two key moments" |

### Output:
```
Output/
├── Video-Title-1/
│   ├── Opening-quote.mp4
│   └── Another-clip.mp4
├── Video-Title-2/
│   ├── Two-key-moments-part1.mp4
│   └── Two-key-moments-part2.mp4
├── _temp_downloads/
│   └── (cached full videos)
└── clip_extraction_log.txt
```

---

## Installation

Both tools need `ffmpeg` and `yt-dlp`/`requests`.

Buffer mode (downloader + buffer extraction) quick install:

```bash
pip install yt-dlp requests

# Install ffmpeg (required for clip extraction; downloader also benefits)
brew install ffmpeg  # macOS
sudo apt install ffmpeg  # Ubuntu/Linux
```

Smart mode (Whisper AI word matching) additionally needs:

```bash
pip install -r requirements.txt
```

---

## Common Workflows

### Workflow 1: Download Full Videos for Archive
1. Create RTF with video URLs
2. Run: `python media_downloader.py`
3. Select RTF file and destination
4. Done! Videos saved with actual titles

### Workflow 2: Create Video Montage (Fastest!)
1. Plan project in Google Sheets with columns:
   - URL
   - Timeframe (e.g., "0:15-0:30")
   - Description/Dialogue
2. Copy to TextEdit, save as RTF
3. Run: `python clip_extractor.py` (interactive mode)
4. Select your RTF file
5. Choose target folder
6. Set time buffers (e.g., 2s before, 2s after)
7. Confirm and let it run!
8. Import extracted clips into video editor
9. Edit and export final montage!

### Workflow 3: Mixed Content Collection
1. Use `media_downloader.py` for full videos you want to keep
2. Use `clip_extractor.py` for specific moments you'll use in presentations
3. Best of both worlds!

---

## Tips & Tricks

### For Both Tools:
- ✅ Run from project directory for easier file paths
- ✅ Check log files if something goes wrong
- ✅ Filenames are auto-sanitized for cross-platform compatibility

### For Full Downloader:
- ✅ It skips duplicates automatically
- ✅ Uses actual video titles, not RTF link text
- ✅ Can run in CLI mode or interactive mode

### For Clip Extractor:
- ✅ Videos are cached - extracting multiple clips is fast
- ✅ Use `&` to extract multiple ranges from same video
- ✅ Clips are lossless (no re-encoding)
- ✅ Folder per video keeps everything organized

---

## Troubleshooting

### "yt-dlp not found"
```bash
pip install yt-dlp
```

### "ffmpeg not found" (clip extractor)
```bash
brew install ffmpeg  # macOS
sudo apt install ffmpeg  # Linux
```

### "No URLs found"
- Check RTF has proper hyperlink format (not plain text)
- Try copying from source again

### Clips too short/wrong (clip extractor)
- Verify timeframe format: `MM:SS-MM:SS` or `H:MM:SS-H:MM:SS`
- Check timecode refers to actual video moments
- Review `clip_extraction_log.txt`

---

## Examples

### Download Full Videos
```bash
# Interactive mode
python media_downloader.py

# Command line mode
python media_downloader.py "videos.rtf" "./downloads"
```

### Extract Clips
```bash
python clip_extractor.py "presentation_clips.rtf" "./presentation"
```

### Real Project Example
```bash
# Download background videos
python media_downloader.py "background_videos.rtf" "./assets/background"

# Extract presentation clips
python clip_extractor.py "presentation_clips.rtf" "./assets/clips"
```

---

## Next Steps

- Read full documentation: [README.md](README.md)
- Learn clip extraction: [README_CLIP_EXTRACTION.md](README_CLIP_EXTRACTION.md)
- Start with a small test file (2-3 videos) to verify your RTF format

**Happy downloading and clipping! 🎬**

