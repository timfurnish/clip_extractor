# VideoGrabber - AI-Powered Video Automation Toolkit

A comprehensive Python toolkit for downloading videos/images and extracting perfect clips using **AI speech recognition** or simple time-based methods.

## 🎯 Two Powerful Tools:

### 1. **media_downloader.py** - Full Video/Image Downloader
Download complete videos and images with smart duplicate prevention and proper naming.

### 2. **clip_extractor.py** - Intelligent Clip Extractor  
Extract specific clips using:
- **🤖 Smart Mode (AI)**: Whisper finds exact word boundaries - no buffers needed!
- **⏱️ Buffer Mode**: Traditional time-based extraction with configurable buffers

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Get started quickly
- **[README_PORTABLE.md](README_PORTABLE.md)** - Install anywhere; folder pickers for output
- **[FEATURES_OVERVIEW.md](FEATURES_OVERVIEW.md)** - Complete feature comparison
- **[README_CLIP_EXTRACTION.md](README_CLIP_EXTRACTION.md)** - Clip extractor guide
- **[SMART_MODE_GUIDE.md](SMART_MODE_GUIDE.md)** - Deep dive into AI mode

## ⚡ Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Full video downloader (interactive)
python media_downloader.py

# Clip extractor (interactive with mode selection)
python3 clip_extractor.py
# or: ./run_clip_extractor.sh
```

## Features

- **Interactive User Interface**: Easy-to-use file selection dialogs and prompts
- **RTF Parsing**: Extracts URLs from RTF hyperlink fields
- **Multi-platform Video Downloads**: Uses yt-dlp to download from YouTube, Facebook, and 1000+ other sites
- **Image Downloads**: Downloads images directly via HTTP requests
- **Destination selection**: Folder picker for RTF workflows (recommended); optional same-folder or new subfolder; single-video mode uses a picker or manual path
- **Advanced Duplicate Prevention**: 
  - URL-based duplicate tracking across sessions
  - Filename-based duplicate detection
  - Removes duplicate URLs within the same RTF file
- **Accurate Filenames**: Uses actual video page titles (YouTube `<h1>` content) with quality indicators
- **Cross-Platform Filename Safety**: Sanitizes filenames to work on Windows, Mac, and Linux
- **Sequential Processing**: Downloads one item at a time to respect server limits
- **Progress Tracking**: Detailed logging and statistics with session records
- **Error Handling**: Comprehensive error handling with detailed logs
- **Highest Quality**: Downloads the best available quality (up to 1080p for videos)
- **Dual Mode Support**: Both interactive GUI and command-line interfaces

## Installation

1. **Clone or download this repository**

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install ffmpeg (required for yt-dlp video processing):**
   - **macOS:** `brew install ffmpeg`
   - **Ubuntu/Debian:** `sudo apt install ffmpeg`
   - **Windows:** Download from https://ffmpeg.org/download.html

## Usage

### Interactive Mode (Recommended)

Simply run the script without any arguments for an interactive experience:

```bash
python media_downloader.py
```

The script will:
1. Open a file dialog to select your RTF file
2. Offer three target directory options:
   - Use the same directory as the source file (default)
   - Choose a different directory via dialog
   - Create a new folder in the source directory
3. Ask for confirmation before starting downloads

### Command Line Mode (Advanced)

For automation or scripts, you can still use command line arguments:

```bash
python media_downloader.py <rtf_file> <output_directory>
```

#### Examples

```bash
# Interactive mode
python media_downloader.py

# Command line mode
python media_downloader.py "/path/to/links.rtf" "/path/to/downloads"
```

## RTF File Format

The script expects RTF files with hyperlinks in the standard RTF hyperlink format:
```
{\field{\*\fldinst{HYPERLINK "https://example.com"}}{\fldrslt Link Text}}
```

This is the format created when you:
1. Copy links from Google Sheets
2. Paste into TextEdit or Word as RTF
3. Save as RTF format

## Output

### Downloaded Files
- **Videos**: `ActualVideoTitle-QualityP.ext` (e.g., "Donald Trump tells Nato allies to pay up - BBC News-1080p.mp4")
  - Uses the actual video page title (YouTube `<h1>` tag content)
  - Appends the detected video quality (1080p, 720p, etc.)
- **Images**: `Title.ext` (e.g., "Image Title.jpg")

### Generated Files
- **download_log.txt**: Detailed log of all operations
- **download_stats.json**: Summary statistics in JSON format
- **downloaded_urls.txt**: Record of all processed URLs to prevent duplicates across sessions

### Console Output
The script provides real-time progress updates and a final summary:
```
==================================================
DOWNLOAD SUMMARY
==================================================
Total URLs found: 15
Videos downloaded: 12
Images downloaded: 2
Skipped (already exist/duplicate): 1
Errors: 0
Output directory: /path/to/downloads

Note: All filenames have been sanitized for cross-platform compatibility
Check 'downloaded_urls.txt' for a record of processed URLs
==================================================
```

## Supported Platforms

### Videos (via yt-dlp)
- YouTube
- Facebook
- Vimeo
- Twitter/X
- TikTok
- Instagram
- LinkedIn
- And 1000+ other platforms

### Images
- Direct image URLs (any HTTP/HTTPS image link)
- Supported formats: JPG, PNG, GIF, WebP, SVG, BMP, TIFF

## Error Handling & Duplicate Prevention

### Duplicate Prevention
- **URL Tracking**: Maintains a persistent record of downloaded URLs across sessions
- **Filename Checking**: Checks for existing files with various naming patterns
- **RTF Deduplication**: Removes duplicate URLs within the same RTF file
- **Similar File Detection**: Identifies files with similar names (different qualities/formats)

### Error Handling
- **Network Issues**: Automatic retries with timeouts
- **Missing Files**: Clear error messages
- **Invalid URLs**: Logged but doesn't stop processing
- **Rate Limiting**: Sequential downloads with delays to respect platform limits
- **Filename Conflicts**: Automatic numbering for duplicate filenames

### Cross-Platform Safety
- **Filename Sanitization**: Removes special characters (colons, slashes, etc.)
- **Windows Reserved Names**: Handles reserved names like CON, PRN, etc.
- **Length Limits**: Ensures filenames don't exceed system limits
- **Character Encoding**: Handles Unicode and control characters properly

## Troubleshooting

### Common Issues

1. **"yt-dlp not found"**
   - Install with: `pip install yt-dlp`

2. **"ffmpeg not found"**
   - Install ffmpeg (see installation section)

3. **Downloads failing**
   - Check internet connection
   - Some platforms may block downloads
   - Private/restricted videos cannot be downloaded

4. **No URLs found in RTF**
   - Ensure RTF file has proper hyperlink formatting
   - Try copying from original source again

### Getting Help

- Check `download_log.txt` for detailed error information
- Ensure all dependencies are installed
- Verify RTF file format is correct

## Advanced Configuration

### Modifying Video Quality
Edit line 124 in `media_downloader.py`:
```python
'format': 'best[height<=1080]/best',  # Change 1080 to desired max resolution
```

### Custom Output Naming
Edit line 123 in `media_downloader.py`:
```python
'outtmpl': str(self.output_dir / '%(title)s-%(height)sp.%(ext)s'),
```

## 🎬 New: Clip Extraction Feature

Want to extract specific clips from videos instead of downloading full files? Use the **Clip Extractor**!

### Quick Start (Interactive Mode):
```bash
python clip_extractor.py
```
Then follow the prompts to select files and configure settings!

### What It Does:
- **Parses RTF tables** with URLs, timeframes, and dialogue
- **Downloads videos** and caches them for reuse (optimized, non-fragmented)
- **Applies time buffers** to avoid cutting off dialogue (configurable)
- **Extracts precise clips** using ffmpeg (e.g., "0:09-0:18", "4:14-4:17 & 4:29-4:31")
- **Organizes clips** in folders by video title
- **Names clips** using your dialogue descriptions

### Perfect For:
- Creating presentation materials from multiple videos
- Building content montages with specific segments
- Extracting key moments without manual video editing
- Automating hours of manual video editing work!

**[📖 Full Clip Extraction Documentation](README_CLIP_EXTRACTION.md)**

---

## License

This project is for personal/educational use. Respect the terms of service of the platforms you're downloading from.
