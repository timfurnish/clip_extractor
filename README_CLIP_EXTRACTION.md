# Clip Extractor - AI-Powered Video Clip Extraction

An intelligent tool that extracts perfect clips from videos using **AI speech recognition** or simple time buffers.

## Two Modes:

### 🤖 **Smart Mode** (NEW!)
Uses OpenAI Whisper AI to find exact word boundaries:
- Provide start/end words (e.g., `"since...exploded"`)
- AI finds precise timestamps in speech
- No manual timing needed!
- Uses full transcription as filename

### ⏱️ **Buffer Mode** (Classic)
Traditional time-based extraction:
- Use your exact timeframes
- Add configurable buffers
- Fast and simple

[📖 **Detailed Smart Mode Guide**](SMART_MODE_GUIDE.md)

## What It Does

Instead of downloading entire videos, this tool:
1. **Parses RTF tables** with columns for URLs, timeframes, and dialogue  
2. **Downloads videos** from YouTube, Facebook, and other platforms (non-fragmented for speed)
3. **SMART MODE:** Transcribes with AI, finds exact word boundaries, captures complete phrases
4. **BUFFER MODE:** Applies time buffers to your timeframes
5. **Extracts precise clips** using ffmpeg
6. **Organizes clips** in folders named after the video title
7. **Names clips** intelligently (full transcription or your description)

## Perfect For

- Creating video montages from multiple sources
- Extracting key moments from long videos
- Building presentation materials with specific video segments
- Curating content libraries with precise clips

## RTF File Format

Your RTF file should be a table with these columns:

| Link | Media Type | VIDEO NAME | **Timeframe** | Duration | Description | Added text | **Dialogue** |
|------|------------|------------|---------------|----------|-------------|------------|--------------|
| https://youtube.com/... | | | **0:09-0:18** | | NATO must pay | | **"NATO...obligations"** |
| https://youtube.com/... | | | **4:14-4:17 & 4:29-4:31** | | Kick out NATO | | **"We had...Spain" & "maybe...NATO"** |

### Required Columns:
- **Link**: URL to the video (YouTube, Facebook, etc.)
- **Timeframe**: Time ranges in format `MM:SS-MM:SS` or `H:MM:SS-H:MM:SS`
  - Single range: `0:09-0:18`
  - Multiple ranges: `4:14-4:17 & 4:29-4:31` (separated by `&`)
  - Smart Mode: Provides approximate location (helps if words repeat)
- **Dialogue**: Description OR word pattern for the clip:
  - **Buffer Mode**: Any description (e.g., "NATO must pay")
  - **Smart Mode**: Use pattern `"start_word...end_word"` (e.g., `"NATO...obligations"`)
    - Multiple: `"since...exploded" & "why...services"`

## Installation

### Basic Installation (Buffer Mode):
```bash
pip install yt-dlp requests
brew install ffmpeg  # macOS
```

### Full Installation (Smart Mode):
```bash
pip install -r requirements.txt
brew install ffmpeg  # macOS
```

This installs:
- `yt-dlp` - Video downloader
- `requests` - HTTP library  
- `openai-whisper` - AI transcription (for Smart Mode)
- `torch` - ML framework (for Smart Mode)
- `ffmpeg` - Video processing

**Note:** First run of Smart Mode downloads Whisper model (~400MB, one-time)

## Usage

### Interactive Mode (Recommended)

Simply run the script without any arguments:

```bash
python clip_extractor.py
```

The script will guide you through:
1. **Select RTF file** via file dialog
2. **Choose target directory**:
   - Use source file's directory (default)
   - Choose different directory via dialog
   - Create new folder in source location
3. **Select extraction mode**:
   - **A. Smart Mode**: AI finds word boundaries (dialogue must use `"word...word"` format)
   - **B. Buffer Mode**: Time-based with buffers (faster, simpler)
4. **Configure settings** (buffers if using Buffer Mode)
5. **Confirm and start** extraction

### Why Use Buffers?

Time buffers prevent cutting off the beginning or end of dialogue/action:
- **Original timeframe**: `0:09-0:18` (9 seconds)
- **With 2s buffers**: `0:07-0:20` (13 seconds)
- **Result**: ✅ No cut-off sentences!

### Command Line Mode (Advanced)

For automation or when you know your settings:

```bash
# With interactive buffer prompts
python clip_extractor.py <rtf_file> <output_directory>

# With specified buffers (2s before, 3s after)
python clip_extractor.py <rtf_file> <output_directory> 2 3

# No buffers (exact timeframes)
python clip_extractor.py <rtf_file> <output_directory> 0 0
```

### Examples

```bash
# Interactive mode - easiest!
python clip_extractor.py

# Command line with prompts
python clip_extractor.py "NATO Clips.rtf" "./NATO_Video_Clips"

# Command line with all settings
python clip_extractor.py "clips.rtf" "./output" 2 3
```

### Example with absolute paths

```bash
python3 clip_extractor.py "/path/to/project/clips.rtf" "/path/to/output/folder"
```

## Output Structure

```
Output Directory/
├── Donald-Trump-tells-Nato-allies-to-pay-up-BBC-News/
│   ├── NATO...obligations.mp4
│   └── another-clip.mp4
├── Trump-Says-Spain-Should-Be-Expelled-from-NATO/
│   ├── We-had...Spain-part1.mp4
│   └── maybe...NATO-part2.mp4
├── _temp_downloads/
│   └── (full videos cached here)
├── clip_extraction_log.txt
└── clip_extraction_stats.json
```

### Folder Organization:
- Each **video gets its own folder** named after the video title
- **Clips are named** using the dialogue/description you provided
- **Multiple ranges** create separate files with `-part1`, `-part2`, etc.
- **Full videos** are cached in `_temp_downloads` (reused if extracting multiple clips)

## Time Buffers (IMPORTANT!)

### Why Use Buffers?

When you specify exact timeframes, you risk cutting off:
- The beginning of a sentence
- The end of an action
- Important context

**Solution:** Add a buffer before and after each clip!

### How It Works

**Example with 2-second buffers:**
```
Original RTF timeframe: 0:09-0:18
With 2s buffers:        0:07-0:20  (2s before, 2s after)

Original RTF timeframe: 1:23:45-1:24:30
With 3s buffers:        1:23:42-1:24:33  (3s before, 3s after)
```

### Buffer Settings

When you run the script, you'll be prompted:
```
Seconds to add BEFORE each clip [default: 2]: 3
Seconds to add AFTER each clip [default: 2]: 3
```

**Recommended buffers:**
- **Dialogue clips:** 2-3 seconds each side
- **Action shots:** 1-2 seconds each side
- **Precise cuts:** 0 seconds (exact timeframes)

### Safety Features

- Buffers **won't go negative** (start time can't be before 0:00)
- Buffers apply to **all clips** consistently
- Original timeframes are **logged** for reference

## Timeframe Format Examples

### Single Clip
```
0:09-0:18          → Extracts from 0:09 to 0:18 (+ buffers)
1:23:45-1:24:30    → Extracts from 1h 23m 45s to 1h 24m 30s (+ buffers)
```

### Multiple Clips from Same Video
```
4:14-4:17 & 4:29-4:31          → Creates 2 separate clip files (each with buffers)
0:05-0:10 & 1:20-1:30 & 2:45-3:00  → Creates 3 separate clip files (each with buffers)
```

## Features

### Smart Video Management
- ✅ Downloads each video **only once** even if multiple clips needed
- ✅ Caches videos in `_temp_downloads` for reuse
- ✅ Processes clips **sequentially** to avoid overwhelming your system

### Robust Parsing
- ✅ Handles complex RTF table formats
- ✅ Extracts URLs from hyperlink fields
- ✅ Finds timeframes automatically (looks for patterns with `:` and `-`)
- ✅ Identifies dialogue/descriptions intelligently

### Clip Extraction
- ✅ Uses **ffmpeg** for fast, lossless clip extraction
- ✅ Preserves **original video quality**
- ✅ **Smart codec handling**:
  - H.264/H.265 videos: Fast copy (no re-encoding)
  - AV1/VP9 videos: Auto re-encodes to H.264 for Adobe Premiere compatibility
- ✅ Handles **multiple time ranges** per video
- ✅ **Configurable time buffers** to prevent cut-off clips
- ✅ Smart buffer handling (won't go before 0:00)

### Cross-Platform Safety
- ✅ Sanitizes filenames for Windows, Mac, and Linux
- ✅ Removes special characters (colons, slashes, quotes, etc.)
- ✅ Creates safe folder names from video titles

## Workflow Benefits

### Before (Manual Process):
1. Manually download each full video
2. Open each in video editor
3. Find exact timecodes
4. Export each clip individually
5. Rename and organize files
6. **Time: Hours for dozens of clips**

### After (Automated):
1. Copy your planning spreadsheet to RTF
2. Run one command
3. **Time: Minutes (mostly download/processing time)**

## Troubleshooting

### "No clip data found"
- Ensure your RTF has proper table structure
- Check that URLs are in hyperlink format (not plain text)
- Verify timeframe column has format like `0:09-0:18`

### "FFmpeg error"
- Ensure ffmpeg is installed: `ffmpeg -version`
- Check that timeframes are valid (start < end)
- Verify video downloaded successfully (check `_temp_downloads`)

### Clips are too short/long
- Double-check your timeframe format
- Ensure `MM:SS` format (not frames or other units)
- For hours, use `H:MM:SS` format

### Missing clips
- Check `clip_extraction_log.txt` for detailed errors
- Verify the dialogue column has content (used for filename)
- Ensure timeframes are within video duration

## Advanced Usage

### Converting Existing AV1 Clips

If you have existing clips in AV1 format that won't work in Adobe Premiere:

```bash
python convert_av1_to_h264.py "/path/to/clips/directory"
```

This utility:
- Scans all videos in directory (recursively)
- Finds AV1/VP9 encoded files
- Shows you which files will be converted
- Asks for confirmation
- Converts to H.264 (high quality, CRF 18)
- **Overwrites originals** (saves disk space)
- ⚠️ WARNING: Original AV1 files will be permanently replaced!

### Cleaning Up
After extraction, you can delete `_temp_downloads` folder if you don't need the full videos:
```bash
rm -rf "output_directory/_temp_downloads"
```

### Re-running
- Videos already downloaded are **reused automatically**
- Clips are **overwritten** if you run again
- Useful for tweaking timeframes or dialogue names

### New Clips Auto-Compatible
All **new clips** extracted with the updated script will automatically be:
- ✅ H.264 if source was AV1/VP9 (Adobe Premiere compatible)
- ✅ Original codec if source was H.264/H.265 (fast copy, no re-encoding)

## Performance

### Download Speed (Optimized!)
- **Non-fragmented downloads**: Prefers single-file downloads over HLS fragments
- **2-3x faster** than fragmented downloads
- **More reliable**: No "fragment not found" errors
- Speed depends on video platform and your internet connection

### Extraction Speed
- **Very fast** (no re-encoding thanks to `-c copy`)
- **~1-2 seconds per clip** typically
- Longer for very large source files or long clips
- Multiple clips from same video are nearly instant (video already downloaded)

### Example Performance:
```
10 clips from 3 different videos:
- Download 3 videos: ~5-10 minutes
- Extract 10 clips: ~10-20 seconds
Total: ~6-11 minutes

Compare to manual: 2-3 hours minimum!
```

## Limitations

- Requires **ffmpeg** to be installed
- RTF parsing relies on hyperlink format (not plain URLs)
- Time codes must be in `MM:SS` or `H:MM:SS` format
- Cannot extract from DRM-protected videos

## Comparison with Main Downloader

| Feature | media_downloader.py | clip_extractor.py |
|---------|---------------------|-------------------|
| Purpose | Download full videos | Extract specific clips |
| Input | Simple RTF with URLs | Multi-column RTF with timeframes |
| Output | Full videos & images | Organized clip folders |
| Organization | Flat directory | Nested by video title |
| Best For | Archiving content | Creating montages |

## Tips

1. **Test with one video first** to verify your RTF format works
2. **Use descriptive dialogue names** - they become your clip filenames
3. **Keep timeframes precise** - helps with seamless editing later
4. **Group clips logically** in your RTF for easier review
5. **Check the log file** if anything seems wrong

## Example Workflow

1. Plan your video project in Google Sheets
2. Add columns for: URL, Timeframe, Dialogue
3. Copy to TextEdit and save as RTF
4. Run clip extractor
5. Review extracted clips
6. Import directly into your video editor!

---

**Happy clipping!** 🎬✂️

