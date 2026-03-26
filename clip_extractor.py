
#!/usr/bin/env python3
"""
Clip Extractor - Downloads videos and extracts specific clips based on timecodes from RTF files

This script parses multi-column RTF files containing:
- Video URLs
- Timeframes (e.g., "0:09-0:18", "4:14-4:17 & 4:29-4:31", or "1:51:24-1:51:46:30" with frames)  
- Dialogue/clip names

It downloads videos, extracts clips using ffmpeg, and organizes them in folders by video title.

Features:
- Single video download mode with smart fallback
- If direct download fails, automatically searches page for YouTube links and tries those
- AV1/VP9 to H.264 conversion for compatibility
- Smart and buffer mode clip extraction from RTF files

Dependencies:
- yt-dlp (required)
- openai-whisper (optional, for smart mode)
- requests, beautifulsoup4 (optional, for YouTube link fallback)
"""

import os
import re
import sys
import platform
import importlib.util
import subprocess
import logging
import shutil
import time
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import json
from datetime import datetime
from urllib.parse import urlparse, urljoin

try:
    import yt_dlp
except ImportError:
    print("yt-dlp not found. Please install it with: pip install yt-dlp")
    sys.exit(1)

# Whisper is optional — import lazily. Eager `import whisper` loads torch and can sit
# silently for minutes on startup with no terminal output.
_whisper_module = None
_whisper_import_attempted = False


def get_whisper_module():
    """Load openai-whisper only when needed (avoids long silent startup)."""
    global _whisper_module, _whisper_import_attempted
    if _whisper_import_attempted:
        return _whisper_module
    _whisper_import_attempted = True
    try:
        import whisper as _w
        _whisper_module = _w
    except ImportError:
        _whisper_module = None
    return _whisper_module


def is_whisper_available() -> bool:
    return get_whisper_module() is not None


def whisper_package_installed() -> bool:
    """Cheap check for the whisper package without importing torch (fast)."""
    return importlib.util.find_spec("whisper") is not None


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


def _applescript_str(s: str) -> str:
    """Escape a string for use inside AppleScript double-quoted text."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _macos_choose_file(prompt: str, default_dir: Optional[str] = None) -> Optional[str]:
    """Native file picker via osascript (avoids Tk/macOS SDK mismatch crashes)."""
    if not shutil.which("osascript"):
        return None
    p = _applescript_str(prompt)
    lines = []
    if default_dir and os.path.isdir(default_dir):
        d = _applescript_str(os.path.abspath(default_dir))
        lines.append(f'set def to POSIX file "{d}"')
        lines.append(f'POSIX path of (choose file with prompt "{p}" default location def)')
    else:
        lines.append(f'POSIX path of (choose file with prompt "{p}")')
    try:
        r = subprocess.run(
            ["osascript"] + [x for line in lines for x in ("-e", line)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
        return out if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _macos_choose_folder(prompt: str, initial_dir: Optional[str] = None) -> Optional[str]:
    if not shutil.which("osascript"):
        return None
    p = _applescript_str(prompt)
    lines = []
    if initial_dir and os.path.isdir(initial_dir):
        d = _applescript_str(os.path.abspath(initial_dir))
        lines.append(f'set def to POSIX file "{d}"')
        lines.append(f'POSIX path of (choose folder with prompt "{p}" default location def)')
    else:
        lines.append(f'POSIX path of (choose folder with prompt "{p}")')
    try:
        r = subprocess.run(
            ["osascript"] + [x for line in lines for x in ("-e", line)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or "").strip()
        return out if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _tk_choose_file(title: str, initialdir: str) -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    file_types = [
        ("Rich Text Format", "*.rtf"),
        ("Text files", "*.txt"),
        ("All files", "*.*"),
    ]
    path = filedialog.askopenfilename(
        title=title,
        filetypes=file_types,
        initialdir=initialdir,
    )
    root.destroy()
    return path if path else None


def _tk_choose_folder(title: str, initialdir: str) -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title, initialdir=initialdir)
    root.destroy()
    return path if path else None

# Web scraping imports for finding YouTube links
try:
    import requests
    from bs4 import BeautifulSoup
    WEB_SCRAPING_AVAILABLE = True
except ImportError:
    requests = None
    BeautifulSoup = None
    WEB_SCRAPING_AVAILABLE = False


def test_web_scraping_imports():
    """Test if web scraping imports work in current context"""
    try:
        import requests
        from bs4 import BeautifulSoup
        return True
    except ImportError:
        return False


class ClipExtractor:
    def __init__(self, output_dir: str, mode: str = 'buffer', buffer_before: int = 0, buffer_after: int = 0):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Setup logging first
        log_file = self.output_dir / "clip_extraction_log.txt"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Mode: 'smart' or 'buffer'
        self.mode = mode
        
        # Buffer times (in seconds) - only used in buffer mode
        self.buffer_before = buffer_before
        self.buffer_after = buffer_after
        
        # Whisper model (only load in smart mode)
        self.whisper_model = None
        if mode == 'smart':
            if not is_whisper_available():
                raise RuntimeError(
                    "Whisper not installed. Install with: pip install openai-whisper\n"
                    "Or use buffer mode instead."
                )
            wmod = get_whisper_module()
            self.logger.info("Loading Whisper model (this may take a moment)...")
            print("Loading Whisper AI model... (first time may download ~400MB)")
            self.whisper_model = wmod.load_model("base")
            self.logger.info("Whisper model loaded successfully")
            print("✓ Whisper model ready")
        
        if mode == 'smart':
            if buffer_before > 0 or buffer_after > 0:
                self.logger.info(f"Using SMART mode - Whisper transcription with {buffer_before}s before, {buffer_after}s after buffer")
            else:
                self.logger.info("Using SMART mode - Whisper transcription with word-level matching")
        elif mode == 'download':
            self.logger.info("Using DOWNLOAD mode - Full video downloads only (no clip extraction)")
        else:
            self.logger.info(f"Using BUFFER mode - {buffer_before}s before, {buffer_after}s after each clip")
        
        # Track downloaded videos and their transcriptions
        self.downloaded_videos = {}  # url -> video_path mapping
        self.video_transcriptions = {}  # video_path -> transcription data mapping

        # One-time UX warnings
        self._warned_missing_youtube_cookies = False
        
        # Stats tracking
        self.stats = {
            'videos_downloaded': 0,
            'clips_extracted': 0,
            'errors': 0,
            'total_clips': 0,
            'source_urls': []  # Store URLs for summary
        }
        
    def sanitize_folder_name(self, folder_name: str) -> str:
        """Sanitize folder name - replace : and / with -, keep spaces"""
        if not folder_name:
            return "Untitled"
        
        # Remove RTF artifacts that might have leaked through
        folder_name = re.sub(r'x\s*\d+\s*', '', folder_name)  # Remove x8640, x1234, etc.
        folder_name = re.sub(r'\*?\s*HYPERLINK\s*', '', folder_name, flags=re.IGNORECASE)
        folder_name = re.sub(r'https?\s*', '', folder_name, flags=re.IGNORECASE)
        folder_name = re.sub(r'www\.\w+\.\w+\s*watchv=\w+', '', folder_name, flags=re.IGNORECASE)
        
        # Fix smart quotes and apostrophes - convert to regular quotes and apostrophes
        folder_name = folder_name.replace(''', "'")  # Left single quotation mark
        folder_name = folder_name.replace(''', "'")  # Right single quotation mark  
        folder_name = folder_name.replace('"', '"')  # Left double quotation mark
        folder_name = folder_name.replace('"', '"')  # Right double quotation mark
        folder_name = folder_name.replace('–', '-')  # En dash
        folder_name = folder_name.replace('—', '-')  # Em dash
        folder_name = folder_name.replace('…', '...')  # Horizontal ellipsis
        
        # Fix HTML entity-like artifacts from RTF processing
        folder_name = re.sub(r'-\d+', '', folder_name)  # Remove patterns like -91, -92, -93, -94
        folder_name = re.sub(r'-\d+', '', folder_name)  # Remove patterns like -91, -92, -93, -94
        
        # Replace colons and slashes with dashes
        folder_name = folder_name.replace(':', '-').replace('/', '-').replace('\\', '-')
        
        # Remove other truly unsafe characters for filesystems
        unsafe_chars = r'[<>"|?*]'
        folder_name = re.sub(unsafe_chars, '', folder_name)
        
        # Remove control characters
        folder_name = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', folder_name)
        
        # Clean up multiple spaces and trim
        folder_name = re.sub(r'\s+', ' ', folder_name).strip()
        
        # Handle periods at the end (not allowed on Windows)
        folder_name = folder_name.rstrip('.')
        
        # Limit length
        if len(folder_name) > 100:
            folder_name = folder_name[:100].rstrip()
        
        if not folder_name:
            folder_name = "Untitled"
            
        return folder_name
    
    def sanitize_clip_name(self, clip_name: str) -> str:
        """Sanitize clip name - keep text mostly as is, just remove unsafe chars and RTF artifacts"""
        if not clip_name:
            return "clip"
        
        # Remove quotes that are often in the dialogue column
        clip_name = clip_name.strip('"\'')
        
        # Remove RTF artifacts that might have leaked through
        clip_name = re.sub(r'x\s*\d+\s*', '', clip_name)  # Remove x8640, x1234, etc.
        clip_name = re.sub(r'\*?\s*HYPERLINK\s*', '', clip_name, flags=re.IGNORECASE)
        clip_name = re.sub(r'https?\s*', '', clip_name, flags=re.IGNORECASE)
        clip_name = re.sub(r'www\.\w+\.\w+\s*watchv=\w+', '', clip_name, flags=re.IGNORECASE)
        
        # Fix smart quotes and apostrophes - convert to regular quotes and apostrophes
        clip_name = clip_name.replace(''', "'")  # Left single quotation mark
        clip_name = clip_name.replace(''', "'")  # Right single quotation mark  
        clip_name = clip_name.replace('"', '"')  # Left double quotation mark
        clip_name = clip_name.replace('"', '"')  # Right double quotation mark
        clip_name = clip_name.replace('–', '-')  # En dash
        clip_name = clip_name.replace('—', '-')  # Em dash
        clip_name = clip_name.replace('…', '...')  # Horizontal ellipsis
        
        # Fix HTML entity-like artifacts from RTF processing
        clip_name = re.sub(r'-\d+', '', clip_name)  # Remove patterns like -91, -92
        clip_name = re.sub(r'-\d+', '', clip_name)  # Remove patterns like -91, -92
        
        # Replace filesystem-unsafe characters with hyphens
        clip_name = clip_name.replace(':', '-').replace('/', '-').replace('\\', '-')
        unsafe_chars = r'[<>"|?*]'
        clip_name = re.sub(unsafe_chars, '', clip_name)
        
        # Remove control characters
        clip_name = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', clip_name)
        
        # Clean up multiple spaces
        clip_name = re.sub(r'\s+', ' ', clip_name).strip()
        
        # Handle periods at the end
        clip_name = clip_name.rstrip('.')
        
        # Limit length
        if len(clip_name) > 100:
            clip_name = clip_name[:100].rstrip()
        
        if not clip_name:
            clip_name = "clip"
            
        return clip_name
    
    def generate_contextual_filename(self, video_path: str, start_time: str, end_time: str, dialogue: str) -> str:
        """
        Generate filename using first 4 words from transcription and last word from dialogue.
        Format: "First four words...lastword.mp4"
        """
        try:
            # Parse dialogue to get first and last words
            dialogue_clean = dialogue.strip('"\'').strip()
            dialogue_words = dialogue_clean.split('...')
            
            if len(dialogue_words) >= 2:
                first_word = dialogue_words[0].strip().split()[0] if dialogue_words[0].strip() else ""
                last_word = dialogue_words[-1].strip().split()[-1] if dialogue_words[-1].strip() else ""
            else:
                # Fallback if no "..." in dialogue
                words = dialogue_clean.split()
                first_word = words[0] if words else ""
                last_word = words[-1] if len(words) > 1 else ""
            
            # Extract just this audio segment to a temporary file for transcription
            self.logger.info(f"  Transcribing clip audio to generate contextual filename...")
            
            # Load model if not already loaded
            if not hasattr(self, 'whisper_model') or not self.whisper_model:
                wmod = get_whisper_module()
                if not wmod:
                    raise RuntimeError("Whisper not installed.")
                self.whisper_model = wmod.load_model("base")
            
            # Create temp audio file for just this segment
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                temp_audio_path = temp_audio.name
            
            try:
                # Find ffmpeg
                ffmpeg_paths = [
                    'ffmpeg',  # System PATH
                    '/usr/local/bin/ffmpeg',  # Homebrew
                    '/opt/homebrew/bin/ffmpeg',  # Apple Silicon Homebrew
                    '/usr/bin/ffmpeg'  # System location
                ]
                
                ffmpeg_cmd = 'ffmpeg'  # Default
                for path in ffmpeg_paths:
                    try:
                        result = subprocess.run([path, '-version'], capture_output=True, timeout=5)
                        if result.returncode == 0:
                            ffmpeg_cmd = path
                            break
                    except:
                        continue
                
                # Extract audio segment using ffmpeg
                cmd = [
                    ffmpeg_cmd, '-i', video_path,
                    '-ss', start_time,
                    '-to', end_time,
                    '-vn',  # No video
                    '-acodec', 'libmp3lame',
                    '-y',
                    temp_audio_path
                ]
                
                subprocess.run(cmd, capture_output=True, check=True, timeout=30)
                
                # Transcribe the audio segment
                result = self.whisper_model.transcribe(
                    temp_audio_path,
                    language='en',
                    word_timestamps=False,
                    initial_prompt=first_word  # Help guide transcription
                )
                
                full_text = result['text'].strip()
                words = full_text.split()
                
                # Get first 4 words
                first_four = ' '.join(words[:4]) if len(words) >= 4 else ' '.join(words)
                
            finally:
                # Clean up temp file
                import os
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
            
            # Create filename
            if last_word:
                filename = f"{first_four}...{last_word}.mp4"
            else:
                filename = f"{first_four}.mp4"
            
            return self.sanitize_clip_name(filename.replace('.mp4', '')) + '.mp4'
            
        except Exception as e:
            self.logger.warning(f"Could not generate contextual filename: {e}")
            # Fallback to dialogue-based naming
            return self.sanitize_clip_name(dialogue) + '.mp4'
    
    def time_to_seconds(self, time_str: str) -> float:
        """Convert time string to seconds with frame precision
        
        Supports formats:
        - MM:SS (e.g., "1:30")
        - H:MM:SS (e.g., "1:51:24") 
        - H:MM:SS:FF (e.g., "1:51:24:15") - frames at 30fps
        """
        parts = time_str.split(':')
        
        if len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:  # H:MM:SS (most common)
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 4:  # H:MM:SS:FF (with frames)
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            frames = int(parts[3])
            # Convert frames to seconds (assuming 30fps standard)
            frame_seconds = frames / 30.0
            return hours * 3600 + minutes * 60 + seconds + frame_seconds
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    
    def seconds_to_time(self, seconds: float) -> str:
        """Convert seconds to time string (MM:SS or H:MM:SS)"""
        if seconds < 0:
            seconds = 0
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    def apply_buffer(self, start_time: str, end_time: str) -> Tuple[str, str]:
        """Apply buffer before and after the time range"""
        start_seconds = self.time_to_seconds(start_time)
        end_seconds = self.time_to_seconds(end_time)
        
        # Apply buffers
        buffered_start = max(0, start_seconds - self.buffer_before)
        buffered_end = end_seconds + self.buffer_after
        
        return self.seconds_to_time(buffered_start), self.seconds_to_time(buffered_end)
    
    def transcribe_video(self, video_path: str) -> Optional[Dict]:
        """Transcribe video using Whisper and return word-level timestamps"""
        if video_path in self.video_transcriptions:
            return self.video_transcriptions[video_path]
        
        if not self.whisper_model:
            return None
        
        try:
            self.logger.info(f"Transcribing video with Whisper...")
            print(f"  Transcribing (this may take 1-2 minutes)...")
            
            result = self.whisper_model.transcribe(
                video_path,
                word_timestamps=True,
                verbose=False
            )
            
            self.video_transcriptions[video_path] = result
            self.logger.info(f"Transcription complete: {len(result.get('segments', []))} segments")
            print(f"  ✓ Transcription complete")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error transcribing video: {e}")
            return None
    
    def find_word_timestamps(self, transcription: Dict, start_word: str, end_word: str, 
                            approx_start: Optional[float] = None, approx_end: Optional[float] = None) -> Optional[Tuple[float, float, str]]:
        """
        Find timestamps for start and end words in transcription
        
        Args:
            transcription: Whisper transcription result
            start_word: First word to find
            end_word: Last word to find
            approx_start: Approximate start time (from timeframe) - helps narrow search
            approx_end: Approximate end time (from timeframe) - helps narrow search
            
        Returns: (start_time, end_time, full_text) or None if not found
        """
        if not transcription or 'segments' not in transcription:
            return None
        
        # Clean up the search words (remove quotes, ellipsis)
        start_word = start_word.strip('"\'...').lower()
        end_word = end_word.strip('"\'...').lower()
        
        # Collect all words with timestamps
        all_words = []
        for segment in transcription['segments']:
            if 'words' in segment:
                all_words.extend(segment['words'])
        
        if not all_words:
            self.logger.warning("No word-level timestamps in transcription")
            return None
        
        # Define search window based on timeframe - STRICT constraint
        # Only small margin (±3 seconds) for minor timing errors
        search_window_margin = 3
        
        if approx_start is not None and approx_end is not None:
            search_start = max(0, approx_start - search_window_margin)
            search_end = approx_end + search_window_margin
            self.logger.info(f"Searching within timeframe: {search_start:.1f}s to {search_end:.1f}s (±3s margin)")
        else:
            search_start = 0
            search_end = float('inf')
        
        # Find start word within search window
        start_idx = None
        start_time = None
        for i, word_data in enumerate(all_words):
            word_time = word_data.get('start', 0)
            
            # Skip words outside search window
            if word_time < search_start or word_time > search_end:
                continue
            
            word = word_data.get('word', '').strip().lower()
            # Remove punctuation for matching
            word_clean = re.sub(r'[^\w\s]', '', word)
            if start_word in word_clean or word_clean.startswith(start_word):
                start_idx = i
                start_time = word_data.get('start', 0)
                self.logger.info(f"Found start word '{start_word}' at {start_time}s")
                break
        
        if start_idx is None:
            self.logger.warning(f"Could not find start word '{start_word}' in search window")
            return None
        
        # Find end word (search after start word, within search window)
        # Allow very minimal extension beyond timeframe
        extended_search_end = search_end + 2  # Only 2s extension for end word
        
        end_idx = None
        end_time = None
        for i in range(start_idx, len(all_words)):
            word_data = all_words[i]
            word_time = word_data.get('start', 0)
            
            # Don't search too far beyond the expected timeframe
            if word_time > extended_search_end:
                self.logger.warning(f"Reached search window limit without finding '{end_word}'")
                break
            
            word = word_data.get('word', '').strip().lower()
            word_clean = re.sub(r'[^\w\s]', '', word)
            if end_word in word_clean or word_clean.endswith(end_word):
                end_idx = i
                # Get end time of the word (includes the word duration)
                end_time = word_data.get('end', word_data.get('start', 0))
                self.logger.info(f"Found end word '{end_word}' at {end_time}s")
                break
        
        if end_idx is None:
            self.logger.warning(f"Could not find end word '{end_word}' after start word within search window")
            return None
        
        # Check if clip duration makes sense relative to timeframe
        clip_duration = end_time - start_time
        
        # If we have a timeframe, warn if clip is much longer than expected
        if approx_start is not None and approx_end is not None:
            expected_duration = approx_end - approx_start
            # Allow up to 2x expected duration (accounts for buffer and decay)
            if clip_duration > expected_duration * 2:
                self.logger.warning(f"Clip duration ({clip_duration:.1f}s) is much longer than timeframe ({expected_duration:.1f}s)")
                self.logger.warning(f"This may indicate wrong words were matched - check your dialogue column")
        elif clip_duration > 45:
            # No timeframe provided - use absolute threshold
            self.logger.warning(f"Clip duration ({clip_duration:.1f}s) seems too long - possible word mismatch")
        
        # Add small decay buffer (0.3-0.5s) for natural ending
        decay_buffer = 0.5
        end_time += decay_buffer
        
        # Extract full text between start and end words
        full_text_words = [all_words[i].get('word', '').strip() for i in range(start_idx, end_idx + 1)]
        full_text = ' '.join(full_text_words).strip()
        
        self.logger.info(f"Extracted text ({clip_duration:.1f}s): {full_text[:100]}...")
        
        return (start_time, end_time, full_text)
    
    def parse_timeframe(self, timeframe_str: str) -> List[Tuple[str, str]]:
        """
        Parse timeframe string into list of (start, end) tuples
        Examples:
            "0:09-0:18" -> [("0:09", "0:18")]
            "4:14-4:17 & 4:29-4:31" -> [("4:14", "4:17"), ("4:29", "4:31")]
            "1:51:24-1:51:46" -> [("1:51:24", "1:51:46")]  # H:MM:SS format
            "1:51:24:15-1:51:46:30" -> [("1:51:24:15", "1:51:46:30")]  # H:MM:SS:FF format
        """
        if not timeframe_str or timeframe_str.strip() == '':
            return []
        
        timeframe_str = timeframe_str.strip()

        # Support "start & end" (no hyphen) which appears in some tables.
        # Example: "1:49:58 & 2:09:16" or "7:01:05 & 7:08:13"
        amp_pair = re.match(r'^\s*(\d+:\d+(?::\d+){0,2})\s*&\s*(\d+:\d+(?::\d+){0,2})\s*$', timeframe_str)
        if amp_pair:
            start, end = amp_pair.groups()
            if self.mode == 'buffer' and (self.buffer_before > 0 or self.buffer_after > 0):
                start, end = self.apply_buffer(start.strip(), end.strip())
            return [(start.strip(), end.strip())]
        
        # Split by & for multiple ranges
        ranges = re.split(r'\s*&\s*', timeframe_str)
        
        parsed_ranges = []
        for range_str in ranges:
            # Match pattern like "0:09-0:18", "1:23:45-1:24:00", or "1:51:24-1:51:46" (H:MM:SS:FF)
            match = re.match(r'(\d+:\d+(?::\d+){0,2})\s*-\s*(\d+:\d+(?::\d+){0,2})', range_str.strip())
            if match:
                start, end = match.groups()
                # Apply buffer if configured and in buffer mode
                if self.mode == 'buffer' and (self.buffer_before > 0 or self.buffer_after > 0):
                    start, end = self.apply_buffer(start.strip(), end.strip())
                parsed_ranges.append((start.strip(), end.strip()))
            else:
                self.logger.warning(f"Could not parse timeframe: {range_str}")
        
        return parsed_ranges
    
    def parse_dialogue_words(self, dialogue: str) -> List[Tuple[str, str]]:
        """
        Parse dialogue string to extract start/end word pairs
        Example: "since...exploded" & "why...services" -> [("since", "exploded"), ("why", "services")]
        """
        if not dialogue:
            return []
        
        # Split by & for multiple phrase ranges
        ranges = re.split(r'\s*&\s*', dialogue)
        
        word_pairs = []
        for range_str in ranges:
            # Match pattern like "since...exploded" or "\"since...exploded\""
            match = re.search(r'["\']?([^\s.]+)\.\.\.([^\s."\']+)["\']?', range_str)
            if match:
                start_word, end_word = match.groups()
                word_pairs.append((start_word.strip(), end_word.strip()))
            else:
                self.logger.warning(f"Could not parse dialogue words: {range_str}")
        
        return word_pairs
    
    def extract_rtf_data(self, rtf_file: str) -> List[Dict]:
        """Extract structured data from multi-column RTF table"""
        self.logger.info(f"Parsing RTF file: {rtf_file}")
        
        try:
            with open(rtf_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"Error reading RTF file: {e}")
            return []
        
        # Pattern to match hyperlinks with their display text
        # Format: {\field{\*\fldinst{HYPERLINK "URL"}}{\fldrslt DISPLAY_TEXT}}
        url_pattern = r'\{\\field\{\\\\?\*\\fldinst\{HYPERLINK "([^"]+)"\}\}\{\\fldrslt([^}]+)\}\}'
        
        # Split content by rows
        rows = content.split('\\row')
        
        extracted_data = []
        
        for row in rows:
            # Extract all cell contents first
            cells = re.split(r'\\cell', row)
            
            # Clean cell content function
            def clean_cell(cell_text):
                if not cell_text:
                    return ""
                
                # Remove RTF control words and sequences
                # Match patterns like \fs24, \b, \par, \cell, etc.
                cleaned = re.sub(r'\\[a-z]+\d*\s*', ' ', cell_text)
                
                # Remove RTF special characters and groups
                cleaned = re.sub(r'[{}]', '', cleaned)
                
                # Remove specific RTF artifacts that are leaking through
                cleaned = re.sub(r'x\s*\d+\s*', '', cleaned)  # Remove x8640, x1234, etc.
                cleaned = re.sub(r'\*?\s*HYPERLINK\s*', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'https?\s*', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'www\.\w+\.\w+\s*watchv=\w+', '', cleaned, flags=re.IGNORECASE)
                
                # Fix smart quotes and apostrophes - convert to regular quotes and apostrophes
                cleaned = cleaned.replace(''', "'")  # Left single quotation mark
                cleaned = cleaned.replace(''', "'")  # Right single quotation mark  
                cleaned = cleaned.replace('"', '"')  # Left double quotation mark
                cleaned = cleaned.replace('"', '"')  # Right double quotation mark
                cleaned = cleaned.replace('–', '-')  # En dash
                cleaned = cleaned.replace('—', '-')  # Em dash
                cleaned = cleaned.replace('…', '...')  # Horizontal ellipsis
                
                # Do NOT strip generic "-<digits>" here: that corrupts valid ranges like
                # "12:49-13:02" (removes "-13"). RTF quote-code noise is handled elsewhere.
                
                # Clean up remaining artifacts
                cleaned = re.sub(r'\s+', ' ', cleaned)
                cleaned = cleaned.strip('"\'\\')
                
                return cleaned
            
            cleaned_cells = [clean_cell(cell) for cell in cells]
            
            # Find ALL URLs in the row (any column)
            url_matches = list(re.finditer(url_pattern, row))
            
            if not url_matches:
                continue
            
            # Extract timeframe and dialogue once for the row
            timeframe = None
            dialogue = None
            
            # Look for timeframe pattern (contains ":" and "-" or "&") 
            # Use more specific regex to avoid false positives
            timeframe_pattern = r'\d+:\d+(?::\d+)?(?::\d+)?\s*[-&]\s*\d+:\d+(?::\d+)?(?::\d+)?'
            
            for cell in cleaned_cells:
                if cell and ':' in cell:
                    # Check if this looks like a valid timeframe
                    timeframe_match = re.search(timeframe_pattern, cell)
                    if timeframe_match:
                        # If the cell contains multiple ranges (e.g. "1:49-1:58 & 2:09-2:16"),
                        # keep the whole cell so we can extract multiple clips.
                        if '&' in cell:
                            timeframe = cell.strip()
                        else:
                            timeframe = timeframe_match.group(0).strip()
                        break
                    # Fallback: if it has : and - or &, but validate it's not corrupted
                    elif ('-' in cell or '&' in cell) and not any(x in cell.lower() for x in ['hyperlink', 'www.', 'http', 'x8640']):
                        # Additional validation: should contain only time-like patterns
                        if re.search(r'\d+:\d+', cell) and not re.search(r'[a-zA-Z]{3,}', cell):
                            timeframe = cell
                            break
            
            # Dialogue is typically in the last non-empty cell
            for cell in reversed(cleaned_cells):
                if cell and timeframe != cell:
                    # Skip cells with RTF artifacts or URLs
                    if any(x in cell.lower() for x in ['hyperlink', 'www.', 'http', 'x8640', 'watchv=']):
                        continue
                    
                    # Look for dialogue-like content
                    if any(char in cell for char in ['"', '...', 'begin', 'end']) or len(cell.strip()) > 3:
                        # Additional validation: should not be mostly numbers or weird artifacts
                        if not re.match(r'^[\d\s:-]+$', cell) and len(cell.strip()) > 2:
                            dialogue = cell
                            break
            
            # If no dialogue found, try to use column F (index 5) as fallback for 'Description/Summary'
            if not dialogue or dialogue.strip() == "":
                if len(cleaned_cells) > 5:  # Ensure column F (index 5) exists
                    column_f_content = cleaned_cells[5].strip()
                    # Check if column F has meaningful content (not empty, not just artifacts)
                    if (column_f_content and 
                        len(column_f_content) > 2 and 
                        not re.match(r'^[\d\s:-]+$', column_f_content) and
                        not any(x in column_f_content.lower() for x in ['hyperlink', 'www.', 'http', 'x8640', 'watchv='])):
                        dialogue = column_f_content
                        self.logger.info(f"Using column F (Description/Summary) as dialogue fallback: {dialogue[:50]}...")
            
            # Get the link text for the FIRST URL in the row (this determines folder name)
            first_url_match = url_matches[0]
            
            # Extract and clean the link text (display text) for the first URL - this will be folder name
            first_link_text_raw = first_url_match.group(2)
            first_link_text = re.sub(r'\\[a-z]+\d*\s*', ' ', first_link_text_raw)
            first_link_text = re.sub(r'[{}]', '', first_link_text)
            first_link_text = re.sub(r'\s+', ' ', first_link_text).strip()
            
            # Process each URL found in the row - all go to same folder
            row_urls = []
            for url_match in url_matches:
                url = url_match.group(1)
                
                # Extract and clean the link text (display text) for this URL
                link_text_raw = url_match.group(2)
                # Remove RTF formatting from link text
                link_text = re.sub(r'\\[a-z]+\d*\s*', ' ', link_text_raw)
                link_text = re.sub(r'[{}]', '', link_text)
                link_text = re.sub(r'\s+', ' ', link_text).strip()
                
                # Check if this is a supported URL (video/image)
                if self.is_supported_url(url):
                    row_urls.append({
                        'url': url,
                        'link_text': link_text,
                        # Same row = same clip metadata for every supported URL (avoid None on 2nd+ link)
                        'timeframe': timeframe,
                        'dialogue': dialogue or "clip",
                        'all_cells': cleaned_cells,
                        'folder_name': first_link_text  # All URLs in row use same folder name
                    })
                    # Add URL to stats for summary
                    self.stats['source_urls'].append(url)
                else:
                    self.logger.info(f"Skipping unsupported URL: {url}")
            
            # Add all URLs from this row to extracted data
            for url_data in row_urls:
                extracted_data.append(url_data)
                
            # Log summary for this row
            if row_urls:
                primary_url = row_urls[0]
                extra_urls = len(row_urls) - 1
                self.logger.info(f"Extracted row: Primary URL={primary_url['url'][:50]}..., Folder='{first_link_text[:40]}...', Timeframe={timeframe}, Extra URLs={extra_urls}")
        
        self.logger.info(f"Extracted {len(extracted_data)} clip entries from RTF")
        return extracted_data
    
    def is_supported_url(self, url: str) -> bool:
        """Check if URL points to a supported video/image source"""
        if not url:
            return False
        
        # Common video/image platforms and file extensions
        supported_patterns = [
            r'youtube\.com/watch',
            r'youtu\.be/',
            r'vimeo\.com/',
            r'dailymotion\.com/',
            r'twitter\.com/.*status',
            r'instagram\.com/',
            r'facebook\.com/.*videos',
            r'tiktok\.com/',
            r'\.(mp4|avi|mov|mkv|webm|flv|wmv|m4v|3gp|3g2|mp3|wav|aac|flac|m4a|jpg|jpeg|png|gif|bmp|tiff|webp)(\?|$)'
        ]
        
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in supported_patterns)
    
    def find_youtube_links_on_page(self, url: str) -> List[str]:
        """Scrape a web page to find YouTube links"""
        # Try to import required modules with detailed error reporting
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            import re
            self.logger.info("Successfully imported web scraping modules")
        except ImportError as e:
            self.logger.error(f"CRITICAL: Cannot import web scraping modules: {e}")
            self.logger.error("This suggests a serious environment issue")
            # Add more debugging info
            import sys
            self.logger.error(f"Python version: {sys.version}")
            self.logger.error(f"Python executable: {sys.executable}")
            return []
        
        try:
            self.logger.info(f"Searching for YouTube links on page: {url}")
            
            # Set up headers to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Fetch the webpage
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links that point to YouTube
            youtube_links = []
            
            # Look for direct YouTube URLs in href attributes
            for link in soup.find_all('a', href=True):
                href = link['href']
                if any(pattern in href.lower() for pattern in ['youtube.com', 'youtu.be']):
                    # Convert relative URLs to absolute
                    if href.startswith('/'):
                        href = urljoin(url, href)
                    youtube_links.append(href)
            
            # Also search in script tags and other content for embedded YouTube URLs
            page_text = str(soup)
            youtube_patterns = [
                r'https://www\.youtube\.com/watch\?v=[a-zA-Z0-9_-]+',
                r'https://youtu\.be/[a-zA-Z0-9_-]+',
                r'youtube\.com/embed/[a-zA-Z0-9_-]+',
                r'youtube\.com/v/[a-zA-Z0-9_-]+'
            ]
            
            for pattern in youtube_patterns:
                matches = re.findall(pattern, page_text, re.IGNORECASE)
                for match in matches:
                    # Convert relative URLs to absolute
                    if match.startswith('youtube.com') or match.startswith('youtu.be'):
                        match = f"https://www.{match}"
                    youtube_links.append(match)
            
            # Remove duplicates and filter to valid YouTube URLs
            unique_links = list(set(youtube_links))
            valid_youtube_links = []
            
            for link in unique_links:
                # Normalize the URL format
                if 'youtu.be/' in link:
                    # Convert youtu.be format to youtube.com format
                    video_id = link.split('youtu.be/')[-1].split('?')[0].split('&')[0]
                    link = f"https://www.youtube.com/watch?v={video_id}"
                elif 'embed/' in link:
                    # Convert embed format to watch format
                    video_id = link.split('embed/')[-1].split('?')[0].split('&')[0]
                    link = f"https://www.youtube.com/watch?v={video_id}"
                elif 'v/' in link:
                    # Convert v/ format to watch format
                    video_id = link.split('v/')[-1].split('?')[0].split('&')[0]
                    link = f"https://www.youtube.com/watch?v={video_id}"
                
                if 'youtube.com/watch' in link and 'v=' in link:
                    valid_youtube_links.append(link)
            
            self.logger.info(f" Found {len(valid_youtube_links)} YouTube links on the page")
            return valid_youtube_links
            
        except Exception as e:
            self.logger.warning(f" Could not scrape page for YouTube links: {e}")
            return []
    
    def check_available_formats(self, url: str) -> Tuple[bool, str]:
        """
        Check if higher quality formats (720p+) are available for the URL.
        Returns (has_720p_or_higher, message)
        """
        try:
            if not ('youtube.com' in url.lower() or 'youtu.be' in url.lower()):
                return True, "Non-YouTube URL - skipping format check"
            
            # Quick format check with minimal options.
            # Important: include cookies if present, otherwise YouTube may hide 720p+ formats.
            check_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'simulate': True,  # Don't actually download
                'format': 'best',  # Get all available formats
                # Some environments export HTTP(S)_PROXY which can break yt-dlp with 403 tunnels.
                # Empty string disables proxy usage in yt-dlp.
                'proxy': '',
            }

            # For YouTube, 720p+ visibility can depend on which cookie profile/account
            # is used. Probe all cookie profiles we have, and only report "no 720p+"
            # if none of them show >=720 formats.
            cookie_candidates = [None]
            if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
                cookies_files = [
                    Path(__file__).parent / 'youtube_cookies.txt',
                    Path(__file__).parent / 'youtube_cookies_profile2.txt',
                    Path(__file__).parent / 'youtube_cookies_profile3.txt',
                    Path(__file__).parent / 'youtube_cookies_private.txt',
                ]
                cookie_candidates = [cf for cf in cookies_files if cf.exists()] or [None]

            for cookie_file in cookie_candidates:
                probe_opts = dict(check_opts)
                if cookie_file is not None:
                    probe_opts['cookiefile'] = str(cookie_file)
                try:
                    with yt_dlp.YoutubeDL(probe_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception:
                    continue

                if not info or 'formats' not in info:
                    # If we can't read formats, don't hard-fail quality enforcement.
                    return True, "Could not extract format info"

                # Check for formats with height >= 720
                high_quality_formats = []
                for fmt in info.get('formats', []):
                    height = fmt.get('height', 0)
                    if height >= 720:
                        high_quality_formats.append(f"{height}p")

                if high_quality_formats:
                    cookie_note = f" using cookies: {getattr(cookie_file, 'name', '')}" if cookie_file else ""
                    return True, f"720p+ formats available{cookie_note}: {', '.join(set(high_quality_formats))}"

            return False, "No 720p+ formats available (given current access/cookies)"
                    
        except Exception as e:
            return True, f"Format check failed: {e}"

    def download_video(self, url: str) -> Optional[Tuple[str, str]]:
        """Download video and return (video_path, video_title)"""
        if url in self.downloaded_videos:
            self.logger.info(f"Video already downloaded: {url}")
            return self.downloaded_videos[url]
        
        try:
            # Create temp directory for downloads
            temp_dir = self.output_dir / "_temp_downloads"
            temp_dir.mkdir(exist_ok=True)
            
            # Get video info with better error handling
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_title = info.get('title', 'video')
                    
                    # Additional fallbacks for title extraction
                    if not video_title or video_title == 'video':
                        video_title = info.get('display_id', info.get('id', 'video'))
                    
                    # Further fallback - extract from URL or use timestamp
                    if not video_title or video_title == 'video' or len(video_title.strip()) < 2:
                        parsed_url = urlparse(url)
                        if parsed_url.netloc:
                            video_title = f"{parsed_url.netloc.replace('www.', '')}_video"
                        else:
                            from datetime import datetime
                            video_title = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                            
            except Exception as e:
                self.logger.warning(f"Could not extract video info: {e}")
                # Fallback title generation - this is not fatal, we can still try to download
                parsed_url = urlparse(url)
                if parsed_url.netloc:
                    video_title = f"{parsed_url.netloc.replace('www.', '')}_video"
                else:
                    video_title = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                self.logger.info(f"Will attempt download with fallback title: {video_title}")
                
            # Sanitize title for folder name
            sanitized_title = self.sanitize_folder_name(video_title)
            
            # Decide whether we must enforce >=720p.
            is_youtube = any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be'])
            require_720p = False
            if is_youtube:
                has_720p, format_message = self.check_available_formats(url)
                require_720p = has_720p
                if require_720p:
                    self.logger.info(f"✓ 720p+ available; enforcing 720p minimum ({format_message})")
                else:
                    self.logger.warning(f"⚠️ No 720p+ formats available; allowing best available quality ({format_message})")
            
            # Check if file already exists in _temp_downloads
            # First check for H.264 versions (preferred)
            existing_files = list(temp_dir.glob(f'{sanitized_title}_H264.mp4'))
            
            # If no H.264 version, check for original files
            if not existing_files:
                existing_files = list(temp_dir.glob(f'{sanitized_title}.*'))
                
                # If still not found, try to find by checking all video files
                # (in case files were created with old naming convention)
                if not existing_files:
                    all_videos = list(temp_dir.glob('*.mp4')) + list(temp_dir.glob('*.webm')) + list(temp_dir.glob('*.mkv'))
                    # Create a normalized version of the title for comparison (lowercase, alphanumeric only)
                    normalized_search = ''.join(c.lower() for c in video_title if c.isalnum())
                    
                    for video_file in all_videos:
                        # Normalize the filename for comparison
                        normalized_filename = ''.join(c.lower() for c in video_file.stem if c.isalnum())
                        # Check if there's significant overlap
                        if normalized_search in normalized_filename or normalized_filename in normalized_search:
                            existing_files = [video_file]
                            self.logger.info(f"Found existing video with different naming: {video_file.name}")
                            break
            
            if existing_files:
                video_path = str(existing_files[0])
                self.logger.info(f"Video already exists, reusing: {video_path}")
                
                # If we're using an H.264 version, no conversion needed
                if '_H264.mp4' in video_path:
                    self.logger.info("Using existing H.264 version (no conversion needed)")
                    final_video_path = video_path
                else:
                    # Check if this video needs conversion (AV1/VP9 to H.264)
                    converted_path = self.convert_av1_to_h264_if_needed(video_path)
                    final_video_path = converted_path if converted_path else video_path
                
                # Add resolution to filename if not already present (for consistency)
                resolution = self.get_video_resolution(final_video_path)
                if resolution:
                    path_obj = Path(final_video_path)
                    # Only rename if resolution is not already in the filename
                    if resolution not in path_obj.stem:
                        new_name = f"{path_obj.stem} {resolution}{path_obj.suffix}"
                        new_path = path_obj.parent / new_name
                        try:
                            path_obj.rename(new_path)
                            final_video_path = str(new_path)
                            self.logger.info(f"Added resolution to existing file: {new_name}")
                        except Exception as e:
                            self.logger.warning(f"Could not rename file: {e}")
                
                self.downloaded_videos[url] = (final_video_path, video_title)
                return (final_video_path, video_title)
            
            self.logger.info(f"Downloading video: {url}")
            
            # Download video
            output_template = str(temp_dir / f'{sanitized_title}.%(ext)s')
            
            # yt-dlp options
            # - Prefer bestvideo+bestaudio (DASH) to actually reach 720p+ when available.
            # - If 720p+ exists for YouTube, enforce it.
            # - If no 720p+ exists, allow best available.
            ydl_opts = {
                'outtmpl': output_template,
                'format': (
                    (
                        # Prefer separate video+audio (often required for 720p+)
                        'bestvideo[height>=720][protocol^=https][vcodec!=av01]+bestaudio[protocol^=https]/'
                        'bestvideo[height>=720]+bestaudio/'
                        'best[height>=720][ext=mp4][protocol^=https]/'
                        'best[height>=720]'
                    ) if (is_youtube and require_720p) else (
                        'bestvideo+bestaudio/best[ext=mp4][protocol^=https]/best'
                    )
                ),
                'merge_output_format': 'mp4',
                'quiet': False,
                # Avoid inheriting broken proxy env vars by default.
                'proxy': '',
                'prefer_free_formats': False,
                'ignoreerrors': False,
                'extract_flat': False,
                'no_check_certificates': False,
                'retries': 2,
                'fragment_retries': 3,
                'skip_unavailable_fragments': True,
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 5242880,  # 5MB chunks for faster streaming
                'concurrent_fragment_downloads': 6,
                'socket_timeout': 30,
                'prefer_insecure': False,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                # Advanced circumvention headers
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Cache-Control': 'max-age=0',
                },
                'referer': 'https://www.youtube.com/',
                'extractor_args': {
                    'youtube': {
                        # If we're using cookies, yt-dlp will typically use the web client;
                        # android/ios often cannot use cookies and may trigger warnings.
                        'player_client': ['web', 'android', 'ios'],
                        'player_skip': ['webpage', 'configs'],
                        # Do NOT skip dash/hls; higher qualities often require them.
                        'lang': ['en', 'en-US'],
                        'geo_bypass': True,
                    }
                }
            }
            
            # Check for YouTube cookies files (multiple profiles for better access)
            cookies_files = [
                Path(__file__).parent / 'youtube_cookies.txt',  # Primary profile
                Path(__file__).parent / 'youtube_cookies_profile2.txt',  # Secondary profile
                Path(__file__).parent / 'youtube_cookies_profile3.txt',  # Tertiary profile
                Path(__file__).parent / 'youtube_cookies_private.txt',  # Private browser profile
            ]
            
            cookies_file = None
            for cookie_file in cookies_files:
                if cookie_file.exists():
                    cookies_file = cookie_file
                    self.logger.info(f"Using YouTube cookies: {cookie_file.name}")
                    break
            
            if cookies_file:
                ydl_opts['cookiefile'] = str(cookies_file)
                self.logger.info("YouTube cookies loaded for enhanced access")
            else:
                self.logger.info("No YouTube cookies found - using anonymous access")
                if is_youtube and not self._warned_missing_youtube_cookies:
                    self._warned_missing_youtube_cookies = True
                    print_cookie_quickstart(Path(__file__).parent)
            
            # Try download with retry logic for fragment failures and incomplete downloads
            max_retries = 1  # Reduced retries for faster failure
            for attempt in range(max_retries + 1):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    
                    # Find the downloaded file
                    downloaded_files = list(temp_dir.glob(f'{sanitized_title}.*'))
                    if downloaded_files and downloaded_files[0].stat().st_size > 0:
                        # Validate completeness before considering it successful
                        video_path = str(downloaded_files[0])
                        is_complete, validation_msg = self.validate_video_completeness(video_path)
                        
                        if is_complete:
                            self.logger.info(f"✅ Download attempt {attempt + 1} successful: {validation_msg}")
                            break  # Success - file exists, has content, and is complete
                        else:
                            self.logger.warning(f"❌ Download attempt {attempt + 1} incomplete: {validation_msg}")
                            # Remove incomplete file
                            try:
                                os.remove(video_path)
                                self.logger.info("Removed incomplete video file")
                            except Exception as e:
                                self.logger.warning(f"Could not remove incomplete file: {e}")
                            
                            if attempt < max_retries:
                                self.logger.warning(f"Retrying download attempt {attempt + 2} with different settings...")
                                # Try progressively different approaches for YouTube blocking
                                if attempt == 0:
                                    # Try different client but keep >=720p-only.
                                    ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
                                elif attempt == 1:
                                    # Try different client but keep >=720p-only.
                                    ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                                    ydl_opts['ignoreerrors'] = True
                                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android']}}
                                    ydl_opts.pop('merge_output_format', None)
                                elif attempt == 2:
                                    # Final attempt: still >=720p-only (no <= fallbacks).
                                    ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                                    ydl_opts['ignoreerrors'] = True
                                    ydl_opts['no_check_certificates'] = True
                                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['tv_embedded', 'web']}}
                                    # Try without cookies to avoid authentication issues
                                    ydl_opts.pop('cookiefile', None)
                                continue
                            else:
                                self.logger.error(f"All download attempts resulted in incomplete videos for: {url}")
                                break
                    elif attempt < max_retries:
                        self.logger.warning(f"Download attempt {attempt + 1} failed - retrying with different approach...")
                        # Try progressively different approaches for YouTube blocking
                        if attempt == 0:
                            # Try different client but keep high quality
                            ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                            ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
                        elif attempt == 1:
                            # Try different client and ignore errors but still prefer high quality
                            ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                            ydl_opts['ignoreerrors'] = True
                            ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android']}}
                            ydl_opts.pop('merge_output_format', None)
                        elif attempt == 2:
                            # Final attempt with most permissive settings but still try high quality first
                            ydl_opts['format'] = 'best[height>=720][ext=mp4][protocol^=https]/best[height>=720][ext=mp4]/best[height>=720]'
                            ydl_opts['ignoreerrors'] = True
                            ydl_opts['no_check_certificates'] = True
                            ydl_opts['extractor_args'] = {'youtube': {'player_client': ['tv_embedded', 'web']}}
                            # Try without cookies to avoid authentication issues
                            ydl_opts.pop('cookiefile', None)
                        continue
                    else:
                        self.logger.error(f"All download attempts failed for: {url}")
                        
                        # Try to find YouTube links on the page as fallback when all attempts failed without exceptions
                        if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                            self.logger.info("All download attempts failed, searching for YouTube links on the page...")
                            youtube_links = self.find_youtube_links_on_page(url)
                            
                            if youtube_links:
                                self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                                for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                                    try:
                                        self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                        # Recursively try to download the YouTube URL
                                        result = self.download_video(youtube_url)
                                        if result:
                                            self.logger.info("Successfully downloaded from YouTube link!")
                                            return result
                                    except Exception as yt_error:
                                        self.logger.warning(f"YouTube download also failed: {yt_error}")
                                        continue
                                
                                self.logger.error("All YouTube links on the page also failed")
                            else:
                                self.logger.info("No YouTube links found on the page")
                        
                        # Try multiple cookie profiles first, then stealth methods
                        if any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                            self.logger.info("Standard methods failed, trying multiple YouTube cookie profiles...")
                            cookie_result = self.try_multiple_cookie_profiles(url, output_template)
                            if cookie_result:
                                # Process the cookie profile download result
                                downloaded_files = [Path(cookie_result)]
                                break
                            else:
                                self.logger.info("Cookie profiles failed, trying STEALTH YouTube download methods...")
                                stealth_result = self.try_stealth_youtube_download(url, output_template)
                                if stealth_result:
                                    # Process the stealth download result
                                    downloaded_files = [Path(stealth_result)]
                                    break
                                else:
                                    self.logger.info("Stealth methods failed, trying alternative methods...")
                                    alternative_result = self.try_alternative_youtube_download(url, output_template)
                                    if alternative_result:
                                        # Process the alternative download result
                                        downloaded_files = [Path(alternative_result)]
                                        break
                                    else:
                                        self.logger.error("❌ FAILED: All YouTube download methods failed")
                                        return None
                        else:
                            self.logger.error("❌ FAILED: All download attempts failed for non-YouTube URL")
                            return None
                        
                except Exception as download_error:
                    if attempt < max_retries:
                        self.logger.warning(f"Download attempt {attempt + 1} failed: {download_error} - retrying with simpler options...")
                        
                        # Try different approaches for YouTube blocking and other issues
                        if attempt == 0:
                            # Try different client but keep high quality for YouTube
                            if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
                                ydl_opts['format'] = 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best'
                                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
                            else:
                                ydl_opts['format'] = 'best'
                            ydl_opts.pop('merge_output_format', None)
                        elif attempt == 1:
                            # Try with ignore errors enabled but still prefer high quality
                            ydl_opts['ignoreerrors'] = True
                            ydl_opts['format'] = 'best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best'
                            ydl_opts['no_check_certificates'] = True
                            ydl_opts['extract_flat'] = False
                            if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
                                ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android']}}
                                # Try without cookies to avoid authentication issues
                                ydl_opts.pop('cookiefile', None)
                            # Try to bypass some extractor issues
                            if 'pbs.org' in url.lower():
                                self.logger.info("Detected PBS URL - trying with more permissive extractor options")
                                ydl_opts['sleep_interval'] = 1
                                ydl_opts['max_sleep_interval'] = 5
                        
                        time.sleep(2)  # Brief pause before retry
                        continue
                    else:
                        # On final failure, provide more helpful error message
                        error_msg = str(download_error)
                        if "KeyError('title')" in error_msg:
                            self.logger.error(f"Video extraction failed - this URL might not be supported or requires special handling.")
                            
                            # Try to find YouTube links on the page as fallback for KeyError cases too
                            if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                                self.logger.info("Video extraction failed, searching for YouTube links on the page...")
                                youtube_links = self.find_youtube_links_on_page(url)
                                
                                if youtube_links:
                                    self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                                    for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                                        try:
                                            self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                            # Recursively try to download the YouTube URL
                                            result = self.download_video(youtube_url)
                                            if result:
                                                self.logger.info("Successfully downloaded from YouTube link!")
                                                return result
                                        except Exception as yt_error:
                                            self.logger.warning(f"YouTube download also failed: {yt_error}")
                                            continue
                                    
                                    self.logger.error("All YouTube links on the page also failed")
                                else:
                                    self.logger.info("No YouTube links found on the page")
                            
                            # Provide specific guidance for PBS URLs
                            if 'pbs.org' in url.lower():
                                self.logger.error(f"PBS NewsHour URLs may have restrictions or be live streams.")
                                self.logger.error(f"Try: 1) Check if it's a live stream (can't download live content)")
                                self.logger.error(f"     2) Use a different URL if available")
                                self.logger.error(f"     3) Update yt-dlp: pip install --upgrade yt-dlp")
                            else:
                                self.logger.error(f"Try updating yt-dlp: pip install --upgrade yt-dlp")
                            
                            self.logger.error(f"Original error: {error_msg}")
                        else:
                            self.logger.error(f"Download failed after all attempts: {error_msg}")
                            
                            # Try to find YouTube links on the page as fallback
                            if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                                self.logger.info("Original URL failed, searching for YouTube links on the page...")
                                youtube_links = self.find_youtube_links_on_page(url)
                                
                                if youtube_links:
                                    self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                                    for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                                        try:
                                            self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                            # Recursively try to download the YouTube URL
                                            result = self.download_video(youtube_url)
                                            if result:
                                                self.logger.info("Successfully downloaded from YouTube link!")
                                                return result
                                        except Exception as yt_error:
                                            self.logger.warning(f"YouTube download also failed: {yt_error}")
                                            continue
                                    
                                    self.logger.error("All YouTube links on the page also failed")
                                else:
                                    self.logger.info("No YouTube links found on the page")
                            
                        # Try multiple cookie profiles first, then stealth methods
                        if any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                            self.logger.info("Exception occurred, trying multiple YouTube cookie profiles...")
                            cookie_result = self.try_multiple_cookie_profiles(url, output_template)
                            if cookie_result:
                                # Process the cookie profile download result
                                downloaded_files = [Path(cookie_result)]
                                break
                            else:
                                self.logger.info("Cookie profiles failed, trying STEALTH YouTube download methods...")
                                stealth_result = self.try_stealth_youtube_download(url, output_template)
                                if stealth_result:
                                    # Process the stealth download result
                                    downloaded_files = [Path(stealth_result)]
                                    break
                                else:
                                    self.logger.info("Stealth methods failed, trying alternative methods...")
                                    alternative_result = self.try_alternative_youtube_download(url, output_template)
                                    if alternative_result:
                                        # Process the alternative download result
                                        downloaded_files = [Path(alternative_result)]
                                        break
                                    else:
                                        self.logger.error("❌ FAILED: All YouTube download methods failed after exception")
                                        return None
                        else:
                            self.logger.error(f"❌ FAILED: Download failed with exception: {error_msg}")
                            return None
            
            if not downloaded_files or downloaded_files[0].stat().st_size == 0:
                self.logger.error(f"❌ FAILED: Downloaded file is empty for: {url}")
                
                # Try YouTube links as fallback here too
                if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                    self.logger.info("Downloaded file is empty, searching for YouTube links on the page...")
                    youtube_links = self.find_youtube_links_on_page(url)
                    
                    if youtube_links:
                        self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                        for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                            try:
                                self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                result = self.download_video(youtube_url)
                                if result:
                                    self.logger.info("Successfully downloaded from YouTube link!")
                                    return result
                            except Exception as yt_error:
                                self.logger.warning(f"YouTube download failed: {yt_error}")
                                continue
                        
                        self.logger.error("❌ FAILED: All YouTube links on the page also failed")
                    else:
                        self.logger.error("❌ FAILED: No YouTube links found on the page")
                else:
                    self.logger.error("❌ FAILED: YouTube URL resulted in empty file")
                
                return None
            
            video_path = str(downloaded_files[0])
            
            # Validate video completeness before proceeding
            self.logger.info("Validating video completeness...")
            is_complete, validation_msg = self.validate_video_completeness(video_path)
            
            if not is_complete:
                self.logger.error(f"❌ INCOMPLETE DOWNLOAD DETECTED: {validation_msg}")
                self.logger.error(f"Video file: {video_path}")
                
                # Delete the incomplete file
                try:
                    os.remove(video_path)
                    self.logger.info("Removed incomplete video file")
                except Exception as e:
                    self.logger.warning(f"Could not remove incomplete file: {e}")
                
                # Try YouTube links as fallback for incomplete downloads
                if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                    self.logger.info("Incomplete download detected, searching for YouTube links on the page...")
                    youtube_links = self.find_youtube_links_on_page(url)
                    
                    if youtube_links:
                        self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                        for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                            try:
                                self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                result = self.download_video(youtube_url)
                                if result:
                                    self.logger.info("Successfully downloaded complete video from YouTube link!")
                                    return result
                            except Exception as yt_error:
                                self.logger.warning(f"YouTube download failed: {yt_error}")
                                continue
                
                # If no YouTube fallback or it failed, mark as failed download
                self.logger.error("❌ FAILED: Could not obtain complete video")
                return None
            
            self.logger.info(f"✅ Video completeness validation passed: {validation_msg}")
            
            # Validate quality for YouTube only when 720p+ exists for that URL.
            if is_youtube and require_720p:
                meets_quality, quality_msg = self.validate_video_quality(video_path, min_height=720)
                if not meets_quality:
                    self.logger.error(f"❌ QUALITY TOO LOW: {quality_msg}")
                    self.logger.error(f"Video file: {video_path}")
                    self.logger.error("This download will be considered a FAILURE and other methods will be tried.")
                    
                    # Delete the low-quality file
                    try:
                        os.remove(video_path)
                        self.logger.info("Removed low-quality video file")
                    except Exception as e:
                        self.logger.warning(f"Could not remove low-quality file: {e}")

                    # Quality validation failed even though we believed >=720p exists.
                    # Try the same escalation path we use for exceptions: multiple cookie
                    # profiles first, then stealth/alternative YouTube download methods.
                    retry_path = None
                    self.logger.info("Attempting re-download using multiple cookie profiles / stealth after quality failure...")
                    cookie_result = self.try_multiple_cookie_profiles(url, output_template)
                    if cookie_result:
                        retry_path = str(cookie_result)
                    else:
                        stealth_result = self.try_stealth_youtube_download(url, output_template)
                        if stealth_result:
                            retry_path = str(stealth_result)
                        else:
                            alternative_result = self.try_alternative_youtube_download(url, output_template)
                            if alternative_result:
                                retry_path = str(alternative_result)

                    if not retry_path:
                        return None
                    video_path = retry_path
                    self.logger.info("✅ Quality recovered via fallback download; continuing post-processing...")
                else:
                    self.logger.info(f"✅ Video quality validation passed: {quality_msg}")
            
            # Check if downloaded video needs conversion (AV1/VP9 to H.264)
            converted_path = self.convert_av1_to_h264_if_needed(video_path)
            final_video_path = converted_path if converted_path else video_path
            
            # Get resolution and rename file to include it
            resolution = self.get_video_resolution(final_video_path)
            if resolution:
                # Rename file to include resolution
                path_obj = Path(final_video_path)
                new_name = f"{path_obj.stem} {resolution}{path_obj.suffix}"
                new_path = path_obj.parent / new_name
                
                # Only rename if the name doesn't already include resolution
                if resolution not in path_obj.stem:
                    try:
                        path_obj.rename(new_path)
                        final_video_path = str(new_path)
                        self.logger.info(f"Renamed to include resolution: {new_name}")
                    except Exception as e:
                        self.logger.warning(f"Could not rename file: {e}")
            
            self.downloaded_videos[url] = (final_video_path, video_title)
            self.stats['videos_downloaded'] += 1
            
            self.logger.info(f"✅ Video downloaded successfully: {final_video_path}")
            return (final_video_path, video_title)
            
        except Exception as e:
            self.logger.error(f"❌ FAILED: Error downloading video {url}: {e}")
            
            # Try YouTube links as final fallback for any error
            if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
                self.logger.info("Download failed with exception, searching for YouTube links on the page...")
                try:
                    youtube_links = self.find_youtube_links_on_page(url)
                    
                    if youtube_links:
                        self.logger.info(f"Found {len(youtube_links)} YouTube links, trying first one...")
                        for youtube_url in youtube_links[:1]:  # Try first YouTube link found
                            try:
                                self.logger.info(f"Attempting download from YouTube: {youtube_url}")
                                result = self.download_video(youtube_url)
                                if result:
                                    self.logger.info("Successfully downloaded from YouTube link!")
                                    return result
                            except Exception as yt_error:
                                self.logger.warning(f"YouTube download failed: {yt_error}")
                                continue
                        
                        self.logger.error("❌ FAILED: All YouTube links on the page also failed")
                    else:
                        self.logger.error("❌ FAILED: No YouTube links found on the page")
                except Exception as scrape_error:
                    self.logger.error(f"❌ FAILED: Could not scrape page for YouTube links: {scrape_error}")
            else:
                self.logger.error("❌ FAILED: YouTube URL download failed with exception")
            
            self.stats['errors'] += 1
            return None
    
    def normalize_end_time(self, end_time: str) -> str:
        """
        Normalize end time to include all frames in that second.
        
        When user specifies "1:21", they mean "include all of second 1:21",
        which requires ffmpeg to use "1:21.999" or effectively "1:22" as the endpoint.
        """
        # Convert to seconds, add 0.999, convert back
        try:
            seconds = self.time_to_seconds(end_time)
            # Add almost a full second to include all frames
            # Using 0.999 ensures we get everything up to next second
            normalized_seconds = seconds + 0.999
            
            # Convert back to time format with milliseconds
            hours = int(normalized_seconds // 3600)
            minutes = int((normalized_seconds % 3600) // 60)
            secs = normalized_seconds % 60
            
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:06.3f}"
            else:
                return f"{minutes}:{secs:06.3f}"
        except:
            # If conversion fails, return original
            return end_time
    
    def get_video_codec(self, video_path: str) -> Optional[str]:
        """Detect the video codec of the source file"""
        try:
            # Try common ffprobe locations
            ffprobe_paths = [
                'ffprobe',  # System PATH
                '/usr/local/bin/ffprobe',  # Homebrew
                '/opt/homebrew/bin/ffprobe',  # Apple Silicon Homebrew
                '/usr/bin/ffprobe'  # System location
            ]
            
            for ffprobe_cmd in ffprobe_paths:
                try:
                    cmd = [
                        ffprobe_cmd,
                        '-v', 'error',
                        '-select_streams', 'v:0',
                        '-show_entries', 'stream=codec_name',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        video_path
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        codec = result.stdout.strip()
                        self.logger.info(f"Detected codec: {codec}")
                        return codec
                except Exception as e:
                    continue
            
            self.logger.warning("Could not find working ffprobe")
            return None
        except Exception as e:
            self.logger.warning(f"Could not detect codec: {e}")
            return None
    
    def get_video_resolution(self, video_path: str) -> Optional[str]:
        """Get video resolution in 'p' format (e.g., '1080p', '720p', '4K')"""
        try:
            # Try common ffprobe locations
            ffprobe_paths = [
                'ffprobe',  # System PATH
                '/usr/local/bin/ffprobe',  # Homebrew
                '/opt/homebrew/bin/ffprobe',  # Apple Silicon Homebrew
                '/usr/bin/ffprobe'  # System location
            ]
            
            for ffprobe_cmd in ffprobe_paths:
                try:
                    cmd = [
                        ffprobe_cmd,
                        '-v', 'error',
                        '-select_streams', 'v:0',
                        '-show_entries', 'stream=width,height',
                        '-of', 'csv=p=0:s=x',
                        video_path
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        resolution = result.stdout.strip()
                        # Convert to 'p' format (e.g., 1920x1080 -> 1080p)
                        try:
                            width, height = resolution.split('x')
                            width, height = int(width), int(height)
                            
                            # Convert to common naming
                            if height >= 2160:
                                res_str = '4K'
                            elif height >= 1440:
                                res_str = '1440p'
                            elif height >= 1080:
                                res_str = '1080p'
                            elif height >= 720:
                                res_str = '720p'
                            elif height >= 480:
                                res_str = '480p'
                            else:
                                res_str = f'{height}p'
                            
                            self.logger.info(f"Detected resolution: {resolution} -> {res_str}")
                            return res_str
                        except:
                            self.logger.warning(f"Could not parse resolution: {resolution}")
                            return None
                except Exception as e:
                    continue
            
            self.logger.warning("Could not find working ffprobe for resolution detection")
            return None
        except Exception as e:
            self.logger.warning(f"Could not detect resolution: {e}")
            return None
    
    def validate_video_completeness(self, video_path: str, expected_duration: float = None) -> Tuple[bool, str]:
        """
        Validate that a video file is complete by checking:
        1. File exists and has content
        2. Video duration matches expected duration (if provided)
        3. Video starts from beginning (no missing start)
        
        Returns: (is_complete, error_message)
        """
        try:
            # Check if file exists and has content
            if not os.path.exists(video_path):
                return False, "File does not exist"
            
            file_size = os.path.getsize(video_path)
            if file_size == 0:
                return False, "File is empty"
            
            # Get video duration using ffprobe
            ffprobe_paths = [
                'ffprobe',  # System PATH
                '/usr/local/bin/ffprobe',  # Homebrew
                '/opt/homebrew/bin/ffprobe',  # Apple Silicon Homebrew
                '/usr/bin/ffprobe'  # System location
            ]
            
            for ffprobe_cmd in ffprobe_paths:
                try:
                    result = subprocess.run([
                        ffprobe_cmd, '-v', 'quiet', '-print_format', 'json', '-show_format', video_path
                    ], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                        format_info = data.get('format', {})
                        actual_duration = float(format_info.get('duration', 0))
                        
                        if actual_duration <= 0:
                            return False, "Video has no duration or is corrupted"
                        
                        # Check if video starts from beginning by examining first few seconds
                        # This is a heuristic check - we'll look for video streams that start at 0
                        streams_result = subprocess.run([
                            ffprobe_cmd, '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path
                        ], capture_output=True, text=True, timeout=30)
                        
                        if streams_result.returncode == 0:
                            streams_data = json.loads(streams_result.stdout)
                            for stream in streams_data.get('streams', []):
                                if stream.get('codec_type') == 'video':
                                    start_time = stream.get('start_time', '0')
                                    try:
                                        start_seconds = float(start_time)
                                        if start_seconds > 5:  # If video starts more than 5 seconds in, it's likely incomplete
                                            return False, f"Video appears to start {start_seconds:.1f}s in (missing beginning)"
                                    except (ValueError, TypeError):
                                        pass
                        
                        # If we have an expected duration, compare it
                        if expected_duration and abs(actual_duration - expected_duration) > 10:
                            return False, f"Duration mismatch: expected {expected_duration:.1f}s, got {actual_duration:.1f}s"
                        
                        return True, f"Video appears complete ({actual_duration:.1f}s)"
                        
                except Exception as e:
                    continue
            
            return False, "Could not analyze video with ffprobe"
            
        except Exception as e:
            return False, f"Error validating video: {e}"
    
    def validate_video_quality(self, video_path: str, min_height: int = 720) -> Tuple[bool, str]:
        """
        Validate that a video meets minimum quality requirements.
        Returns (meets_quality, message)
        """
        try:
            if not os.path.exists(video_path):
                return False, "File does not exist"
            
            # Use ffprobe to get video information
            ffprobe_paths = [
                'ffprobe',  # System PATH
                '/usr/local/bin/ffprobe',  # Homebrew
                '/opt/homebrew/bin/ffprobe',  # Apple Silicon Homebrew
                '/usr/bin/ffprobe'  # System location
            ]
            
            ffprobe_cmd = None
            for path in ffprobe_paths:
                try:
                    subprocess.run([path, '-version'], capture_output=True, check=True, timeout=5)
                    ffprobe_cmd = path
                    break
                except:
                    continue
            
            if not ffprobe_cmd:
                return False, "ffprobe not found"
            
            # Get video information
            cmd = [
                ffprobe_cmd,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return False, f"ffprobe failed: {result.stderr}"
            
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return False, "Could not parse ffprobe output"
            
            # Check if we have video streams
            video_streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
            if not video_streams:
                return False, "No video streams found"
            
            # Get the main video stream
            main_stream = video_streams[0]
            
            # Get video dimensions
            width = int(main_stream.get('width', 0))
            height = int(main_stream.get('height', 0))
            
            if height < min_height:
                return False, f"Quality too low: {height}p (minimum required: {min_height}p)"
            
            return True, f"Quality acceptable: {height}p ({width}x{height})"
            
        except subprocess.TimeoutExpired:
            return False, "ffprobe timeout"
        except Exception as e:
            return False, f"Error validating quality: {e}"
    
    def try_multiple_cookie_profiles(self, url: str, output_template: str) -> Optional[str]:
        """
        Try downloading with different YouTube cookie profiles to bypass quality restrictions.
        This function cycles through different user profiles to find one that allows 720p+ downloads.
        """
        if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
            return None
        
        self.logger.info("🔄 Trying multiple YouTube cookie profiles to bypass quality restrictions...")
        
        # Define cookie profiles to try
        cookie_profiles = [
            {
                'name': 'Primary Profile',
                'file': Path(__file__).parent / 'youtube_cookies.txt',
                'description': 'Main YouTube account'
            },
            {
                'name': 'Secondary Profile',
                'file': Path(__file__).parent / 'youtube_cookies_profile2.txt',
                'description': 'Alternative YouTube account'
            },
            {
                'name': 'Tertiary Profile',
                'file': Path(__file__).parent / 'youtube_cookies_profile3.txt',
                'description': 'Third YouTube account'
            },
            {
                'name': 'Private Browser Profile',
                'file': Path(__file__).parent / 'youtube_cookies_private.txt',
                'description': 'Private/incognito browser session'
            },
            {
                'name': 'No Cookies',
                'file': None,
                'description': 'Anonymous access (no cookies)'
            }
        ]
        
        # Determine whether this YouTube URL actually has any >=720p formats.
        # If not, we allow best available quality rather than failing the whole job.
        require_720p = True
        try:
            has_720p, msg = self.check_available_formats(url)
            require_720p = has_720p
            if require_720p:
                self.logger.info(f"✓ 720p+ available; enforcing 720p minimum ({msg})")
            else:
                self.logger.warning(f"⚠️ No 720p+ formats available; allowing best available quality ({msg})")
        except Exception:
            # If detection fails, keep the safer behavior (require 720p).
            require_720p = True

        for i, profile in enumerate(cookie_profiles):
            try:
                self.logger.info(f"🍪 Trying profile {i+1}: {profile['name']} ({profile['description']})")
                
                # Skip if cookie file doesn't exist (except for "No Cookies" profile)
                if profile['file'] and not profile['file'].exists():
                    self.logger.info(f"Skipping {profile['name']} - cookie file not found")
                    continue
                
                # Configure yt-dlp options for this profile
                ydl_opts = {
                    'outtmpl': output_template,
                    'format': (
                        (
                            'best[height>=720][ext=mp4][protocol^=https][vcodec!=av01]/'
                            'best[height>=720][ext=mp4][protocol^=https]/'
                            'best[height>=720][ext=mp4]/'
                            'best[height>=720]'
                        ) if require_720p else (
                            'best[ext=mp4][protocol^=https]/best[ext=mp4]/best'
                        )
                    ),
                    'quiet': False,
                    'proxy': '',
                    'retries': 5,
                    'fragment_retries': 10,
                    'skip_unavailable_fragments': True,
                    'live_from_start': True,
                    'wait_for_video': (1, 60),
                    'http_chunk_size': 5242880,
                    'concurrent_fragment_downloads': 4,
                    'socket_timeout': 30,
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    },
                    'referer': 'https://www.youtube.com/',
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['android', 'ios', 'web'],
                            'player_skip': ['webpage', 'configs'],
                            'lang': ['en', 'en-US'],
                            'geo_bypass': True,
                        }
                    }
                }
                
                # Add cookies if available
                if profile['file']:
                    ydl_opts['cookiefile'] = str(profile['file'])
                    self.logger.info(f"Using cookies from: {profile['file'].name}")
                else:
                    self.logger.info("Using anonymous access (no cookies)")
                
                # Try download with this profile
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Check if download was successful
                temp_dir = Path(output_template).parent
                downloaded_files = list(temp_dir.glob('*'))
                if downloaded_files and downloaded_files[0].stat().st_size > 0:
                    video_path = str(downloaded_files[0])
                    
                    # Validate completeness
                    is_complete, completeness_msg = self.validate_video_completeness(video_path)
                    if not is_complete:
                        self.logger.warning(f"❌ Profile {profile['name']} incomplete: {completeness_msg}")
                        try:
                            os.remove(video_path)
                        except:
                            pass
                        continue
                    
                    # Validate quality only when 720p+ exists for this URL.
                    if require_720p:
                        meets_quality, quality_msg = self.validate_video_quality(video_path, min_height=720)
                        if not meets_quality:
                            self.logger.warning(f"❌ Profile {profile['name']} quality too low: {quality_msg}")
                            try:
                                os.remove(video_path)
                            except:
                                pass
                            continue
                    else:
                        quality_msg = "Quality requirement relaxed (no 720p+ formats available)"
                    
                    # Success! This profile worked
                    self.logger.info(f"🎉 PROFILE SUCCESS! {profile['name']} worked: {completeness_msg}, {quality_msg}")
                    return video_path
                
            except Exception as e:
                self.logger.warning(f"🍪 Profile {profile['name']} failed: {e}")
                continue
        
        self.logger.error("🚫 All cookie profiles failed to provide acceptable quality")
        return None
    
    def try_stealth_youtube_download(self, url: str, output_template: str) -> Optional[str]:
        """
        Advanced stealth download using multiple circumvention techniques.
        This function tries various methods to bypass YouTube's SABR system.
        """
        if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
            return None
        
        self.logger.info("🚀 Attempting STEALTH YouTube download with advanced circumvention...")
        
        # Multiple stealth configurations with different strategies
        stealth_configs = [
            {
                'name': 'Stealth Android Client + Real-time Streaming',
                'format': 'best[height<=1080][ext=mp4][protocol^=https][vcodec!=av01]/best[height<=720][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'http_headers': {
                    'User-Agent': 'com.google.android.youtube/17.36.4 (Linux; U; Android 11) gzip',
                    'X-YouTube-Client-Name': '3',
                    'X-YouTube-Client-Version': '17.36.4',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 1048576,  # 1MB chunks for real-time streaming
                'concurrent_fragment_downloads': 8,
                'retries': 10,
                'fragment_retries': 20,
            },
            {
                'name': 'Stealth iOS Client + Premium Headers',
                'format': 'best[height<=1080][ext=mp4][protocol^=https][vcodec!=av01]/best[height<=720][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['ios']}},
                'http_headers': {
                    'User-Agent': 'com.google.ios.youtube/17.36.4 (iPhone14,3; U; CPU iOS 15_6 like Mac OS X)',
                    'X-YouTube-Client-Name': '5',
                    'X-YouTube-Client-Version': '17.36.4',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 2097152,  # 2MB chunks
                'concurrent_fragment_downloads': 6,
                'retries': 2,
                'fragment_retries': 3,
            },
            {
                'name': 'Stealth TV Client + Embedded Player',
                'format': 'best[height<=1080][ext=mp4][protocol^=https][vcodec!=av01]/best[height<=720][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['tv_embedded']}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 2.4.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/2.4.0 TV Safari/538.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 4194304,  # 4MB chunks
                'concurrent_fragment_downloads': 4,
                'retries': 6,
                'fragment_retries': 12,
            },
            {
                'name': 'Stealth Web Client + Browser Simulation',
                'format': 'best[height<=1080][ext=mp4][protocol^=https][vcodec!=av01]/best[height<=720][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['web']}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Cache-Control': 'max-age=0',
                },
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 8388608,  # 8MB chunks
                'concurrent_fragment_downloads': 3,
                'retries': 5,
                'fragment_retries': 10,
            },
            {
                'name': 'Stealth Minimal Client + Direct Stream',
                'format': 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['android_music']}},
                'http_headers': {
                    'User-Agent': 'com.google.android.apps.youtube.music/5.42.52 (Linux; U; Android 11) gzip',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'live_from_start': True,
                'wait_for_video': (1, 60),
                'http_chunk_size': 524288,  # 512KB chunks for minimal footprint
                'concurrent_fragment_downloads': 2,
                'retries': 3,
                'fragment_retries': 8,
            }
        ]
        
        for i, config in enumerate(stealth_configs):
            try:
                self.logger.info(f"🎭 Trying stealth method {i+1}: {config['name']}")
                
                ydl_opts = {
                    'outtmpl': output_template,
                    'format': config['format'],
                    'quiet': False,
                    'ignoreerrors': True,
                    'no_check_certificates': True,
                    'extract_flat': False,
                    'merge_output_format': 'mp4',
                    'skip_unavailable_fragments': True,
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                    'referer': 'https://www.youtube.com/',
                }
                
                # Add config-specific options
                for key, value in config.items():
                    if key != 'name':
                        ydl_opts[key] = value
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Check if download was successful
                temp_dir = Path(output_template).parent
                downloaded_files = list(temp_dir.glob('*'))
                if downloaded_files and downloaded_files[0].stat().st_size > 0:
                    video_path = str(downloaded_files[0])
                    
                    # Validate completeness first
                    is_complete, completeness_msg = self.validate_video_completeness(video_path)
                    if not is_complete:
                        self.logger.warning(f"❌ Stealth method {i+1} incomplete: {completeness_msg}")
                        try:
                            os.remove(video_path)
                        except:
                            pass
                        continue
                    
                    # Validate quality - require 720p minimum
                    meets_quality, quality_msg = self.validate_video_quality(video_path, min_height=720)
                    if not meets_quality:
                        self.logger.warning(f"❌ Stealth method {i+1} quality too low: {quality_msg}")
                        try:
                            os.remove(video_path)
                        except:
                            pass
                        continue
                    
                    # Both completeness and quality are acceptable
                    self.logger.info(f"🎉 STEALTH SUCCESS! Method {i+1} worked: {completeness_msg}, {quality_msg}")
                    return video_path
                
            except Exception as e:
                self.logger.warning(f"🎭 Stealth method {i+1} failed: {e}")
                continue
        
        self.logger.error("🚫 All stealth methods failed - YouTube's defenses are too strong")
        return None

    def try_alternative_youtube_download(self, url: str, output_template: str) -> Optional[str]:
        """
        Try alternative methods to download YouTube videos when standard methods fail.
        This includes trying different clients, formats, and extraction methods.
        """
        if not any(pattern in url.lower() for pattern in ['youtube.com', 'youtu.be']):
            return None
        
        self.logger.info("Trying alternative YouTube download methods...")
        
        # Alternative configurations to try - prioritize higher quality first
        alternative_configs = [
            {
                'name': 'Android Client + High Quality (1080p)',
                'format': 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'ignoreerrors': True,
            },
            {
                'name': 'iOS Client + High Quality (1080p)', 
                'format': 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['ios']}},
                'ignoreerrors': True,
            },
            {
                'name': 'TV Embedded Client + High Quality (1080p)',
                'format': 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['tv_embedded']}},
                'ignoreerrors': True,
            },
            {
                'name': 'Web Client + High Quality (1080p)',
                'format': 'best[height<=1080][ext=mp4]/best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['web']}},
                'ignoreerrors': True,
                'no_check_certificates': True,
            },
            {
                'name': 'Android Client + Medium Quality (720p)',
                'format': 'best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best[height<=360][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['android']}},
                'ignoreerrors': True,
            },
            {
                'name': 'iOS Client + Medium Quality (720p)',
                'format': 'best[height<=720][ext=mp4]/best[height<=480][ext=mp4]/best[height<=360][ext=mp4]/best',
                'extractor_args': {'youtube': {'player_client': ['ios']}},
                'ignoreerrors': True,
            },
            {
                'name': 'Minimal Settings + Any Quality',
                'format': 'best',
                'ignoreerrors': True,
                'no_check_certificates': True,
                'extract_flat': False,
            },
            {
                'name': 'Emergency Fallback - Accept Any Quality',
                'format': 'worst/best',
                'ignoreerrors': True,
                'no_check_certificates': True,
                'extract_flat': False,
                'no_warnings': True,
                'quiet': True,
            }
        ]
        
        for i, config in enumerate(alternative_configs):
            try:
                self.logger.info(f"Trying alternative method {i+1}: {config['name']}")
                
                ydl_opts = {
                    'outtmpl': output_template,
                    'format': config['format'],
                    'quiet': False,
                    'retries': 3,
                    'fragment_retries': 5,
                    'skip_unavailable_fragments': True,
                    'sleep_interval': 2,
                    'max_sleep_interval': 8,
                }
                
                # Add config-specific options
                for key, value in config.items():
                    if key != 'name':
                        ydl_opts[key] = value
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Check if download was successful
                temp_dir = Path(output_template).parent
                downloaded_files = list(temp_dir.glob('*'))
                if downloaded_files and downloaded_files[0].stat().st_size > 0:
                    video_path = str(downloaded_files[0])
                    
                    # Validate completeness first
                    is_complete, completeness_msg = self.validate_video_completeness(video_path)
                    if not is_complete:
                        self.logger.warning(f"❌ Alternative method {i+1} incomplete: {completeness_msg}")
                        try:
                            os.remove(video_path)
                        except:
                            pass
                        continue
                    
                    # Validate quality - require 720p minimum (except for emergency fallback)
                    if config['name'] == 'Emergency Fallback - Accept Any Quality':
                        # Emergency fallback accepts any quality
                        quality_msg = "Emergency fallback - quality validation bypassed"
                        self.logger.warning(f"⚠️ EMERGENCY FALLBACK: Accepting any quality due to download failures")
                    else:
                        meets_quality, quality_msg = self.validate_video_quality(video_path, min_height=720)
                        if not meets_quality:
                            self.logger.warning(f"❌ Alternative method {i+1} quality too low: {quality_msg}")
                            try:
                                os.remove(video_path)
                            except:
                                pass
                            continue
                    
                    # Both completeness and quality are acceptable
                    self.logger.info(f"✅ Alternative method {i+1} successful: {completeness_msg}, {quality_msg}")
                    return video_path
                
            except Exception as e:
                self.logger.warning(f"Alternative method {i+1} failed: {e}")
                continue
        
        self.logger.error("All alternative YouTube download methods failed")
        return None
    
    def convert_av1_to_h264_if_needed(self, video_path: str) -> Optional[str]:
        """
        Convert AV1/VP9 videos to H.264 for Adobe Premiere compatibility.
        Returns the path to the H.264 file, or None if conversion not needed.
        """
        try:
            codec = self.get_video_codec(video_path)
            if not codec or codec.lower() not in ['av1', 'av01', 'vp9']:
                return None  # No conversion needed
            
            self.logger.info(f"Video uses {codec} codec (incompatible with Adobe Premiere)")
            self.logger.info("Converting to H.264 for compatibility...")
            
            # Create H.264 version with _H264 suffix
            video_file = Path(video_path)
            h264_path = video_file.parent / f"{video_file.stem}_H264.mp4"
            
            # Find ffmpeg
            ffmpeg_paths = [
                'ffmpeg',  # System PATH
                '/usr/local/bin/ffmpeg',  # Homebrew
                '/opt/homebrew/bin/ffmpeg',  # Apple Silicon Homebrew
                '/usr/bin/ffmpeg'  # System location
            ]
            
            ffmpeg_cmd = 'ffmpeg'  # Default
            for path in ffmpeg_paths:
                try:
                    result = subprocess.run([path, '-version'], capture_output=True, timeout=5)
                    if result.returncode == 0:
                        ffmpeg_cmd = path
                        break
                except:
                    continue
            
            # Convert to H.264
            cmd = [
                ffmpeg_cmd,
                '-i', video_path,
                '-map', '0:v:0',  # Explicitly map video stream
                '-map', '0:a:0?',  # Map audio stream if it exists (? makes it optional)
                '-c:v', 'libx264',  # Video codec
                '-preset', 'fast',   # Encoding speed
                '-crf', '18',        # Quality (18 = near-lossless)
                '-pix_fmt', 'yuv420p',  # Pixel format (ensures compatibility)
                '-c:a', 'aac',       # Audio codec
                '-b:a', '192k',      # Audio bitrate
                '-movflags', '+faststart',  # Web optimization
                '-y',                # Overwrite output file
                str(h264_path)
            ]
            
            self.logger.info(f"Converting: {video_file.name}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                self.logger.info(f"✓ Converted to H.264: {h264_path.name}")
                self.logger.info(f"ℹ️  Original {codec} file kept: {video_file.name}")
                self.stats['videos_converted'] = self.stats.get('videos_converted', 0) + 1
                return str(h264_path)
            else:
                self.logger.error(f"Conversion failed: {result.stderr}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error converting video: {e}")
            return None
    
    def extract_clip(self, video_path: str, start_time: str, end_time: str, output_path: str, transcription_text: str = None) -> bool:
        """Extract clip from video using ffmpeg and optionally embed transcription metadata"""
        try:
            # Normalize end time to include all frames in that second
            normalized_end = self.normalize_end_time(end_time)
            
            self.logger.info(f"Extracting clip: {start_time} to {end_time}")
            if normalized_end != end_time:
                self.logger.info(f"  (Normalized end time: {normalized_end} to include all frames)")
            
            # Ensure output directory exists
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Prefer stream copy when codecs are MP4-friendly; ProRes/odd codecs fall back below
            self.logger.info("  Trying stream copy (-c copy) for speed; will re-encode if needed")
            
            # Find ffmpeg
            ffmpeg_paths = [
                'ffmpeg',  # System PATH
                '/usr/local/bin/ffmpeg',  # Homebrew
                '/opt/homebrew/bin/ffmpeg',  # Apple Silicon Homebrew
                '/usr/bin/ffmpeg'  # System location
            ]
            
            ffmpeg_cmd = 'ffmpeg'  # Default
            for path in ffmpeg_paths:
                try:
                    result = subprocess.run([path, '-version'], capture_output=True, timeout=5)
                    if result.returncode == 0:
                        ffmpeg_cmd = path
                        break
                except:
                    continue
            
            # Build ffmpeg command with codec copy (fast, lossless)
            cmd = [
                ffmpeg_cmd,
                '-i', video_path,
                '-ss', start_time,
                '-to', normalized_end,
                '-c', 'copy',  # Copy codec (fast, no re-encoding)
                '-avoid_negative_ts', '1'
            ]
            
            # Add transcription metadata if provided
            if transcription_text:
                # Escape quotes and special characters for ffmpeg metadata
                escaped_text = transcription_text.replace('"', '\\"').replace("'", "\\'")
                cmd.extend([
                    '-metadata', f'comment="Transcription: {escaped_text}"',
                    '-metadata', f'description="AI-transcribed clip: {escaped_text}"'
                ])
            
            cmd.extend(['-y', str(output_path)])
            timeout = 60
            
            # Run ffmpeg (stream copy)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode != 0:
                err = ((result.stderr or "") + (result.stdout or "")).lower()
                needs_reencode = (
                    "could not find tag for codec" in err
                    or "codec not currently supported in container" in err
                    or ("prores" in err and "mp4" in err)
                    or ("could not write header" in err and "copy" in cmd)
                )
                if needs_reencode:
                    self.logger.warning(
                        "Stream copy failed (codec/container mismatch). Re-encoding clip to H.264/AAC…"
                    )
                    cmd_re = [
                        ffmpeg_cmd,
                        "-i", video_path,
                        "-ss", start_time,
                        "-to", normalized_end,
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "18",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-movflags", "+faststart",
                        "-avoid_negative_ts", "1",
                    ]
                    if transcription_text:
                        escaped_text = transcription_text.replace('"', '\\"').replace("'", "\\'")
                        cmd_re.extend(
                            [
                                "-metadata",
                                f'comment="Transcription: {escaped_text}"',
                                "-metadata",
                                f'description="AI-transcribed clip: {escaped_text}"',
                            ]
                        )
                    cmd_re.extend(["-y", str(output_path)])
                    result = subprocess.run(
                        cmd_re,
                        capture_output=True,
                        text=True,
                        timeout=max(timeout, 600),
                    )

            if result.returncode == 0:
                self.logger.info(f"✓ Clip extracted: {output_path.name}")
                self.stats['clips_extracted'] += 1
                return True
            else:
                self.logger.error(f"FFmpeg error: {result.stderr}")
                self.stats['errors'] += 1
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error(f"FFmpeg timeout extracting clip")
            self.stats['errors'] += 1
            return False
        except Exception as e:
            self.logger.error(f"Error extracting clip: {e}")
            self.stats['errors'] += 1
            return False
    
    def process_clips(self, rtf_file: str) -> dict:
        """Main processing function"""
        self.logger.info("="*60)
        self.logger.info("Starting Clip Extraction Process")
        self.logger.info("="*60)
        
        # Extract data from RTF
        clip_data = self.extract_rtf_data(rtf_file)
        
        if not clip_data:
            self.logger.warning("No clip data found in RTF file")
            return self.stats
        
        # Count total clips vs full downloads
        total_clips = sum(1 for clip in clip_data if clip['timeframe'])
        total_full_downloads = len(clip_data) - total_clips
        
        self.stats['total_clips'] = total_clips
        self.stats['total_full_downloads'] = total_full_downloads
        self.stats['total_entries'] = len(clip_data)
        
        # Group clips by folder name (from first URL in each row)
        clips_by_folder = {}
        for clip in clip_data:
            folder_name = clip.get('folder_name', clip.get('link_text', 'Unknown'))
            if folder_name not in clips_by_folder:
                clips_by_folder[folder_name] = []
            clips_by_folder[folder_name].append(clip)
        
        self.logger.info(f"Found {len(clip_data)} media entries from {len(clips_by_folder)} folders ({total_clips} clips + {total_full_downloads} full downloads)")
        
        # Process each folder (which may contain multiple URLs from the same row)
        for i, (folder_name, folder_clips) in enumerate(clips_by_folder.items(), 1):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Processing folder {i}/{len(clips_by_folder)}: {folder_name}")
            self.logger.info(f"{'='*60}")
            
            # Create folder for this row's media
            video_folder = self.output_dir / self.sanitize_folder_name(folder_name)
            video_folder.mkdir(exist_ok=True)
            
            # Download all URLs in this folder
            downloaded_media = {}  # url -> (video_path, video_title)
            
            for clip in folder_clips:
                url = clip['url']
                if url not in downloaded_media:
                    # Download this URL
                    download_result = self.download_video(url)
                    if download_result:
                        video_path, video_title = download_result
                        downloaded_media[url] = (video_path, video_title)
                        self.logger.info(f"Downloaded: {video_title}")
                    else:
                        self.logger.error(f"Failed to download: {url}")
                        self.stats['errors'] += 1
            
            if not downloaded_media:
                self.logger.error(f"No successful downloads for folder: {folder_name}")
                continue
            
            # Count clips vs full downloads for this folder
            clip_count = sum(1 for clip in folder_clips if clip['timeframe'])
            full_download_count = len(folder_clips) - clip_count
            self.logger.info(f"Processing {len(folder_clips)} entries in folder '{folder_name}' ({clip_count} clips + {full_download_count} full downloads)")
            
            # Move all downloaded videos to the folder and prepare for clip extraction
            primary_video_path = None  # Use this for transcription if needed
            
            for url, (video_path, video_title) in downloaded_media.items():
                # Get video resolution
                resolution = self.get_video_resolution(video_path)
                if not resolution:
                    resolution = ""  # If detection fails, don't append resolution
                
                # Move the full video into the folder (only if it's H.264, not AV1)
                video_path_obj = Path(video_path)
                if '_H264' in video_path_obj.stem or video_path_obj.suffix == '.mp4':
                    # Check if it's not an AV1 file
                    codec = self.get_video_codec(video_path)
                    if codec not in ['av1', 'av01', 'vp9']:
                        # Move the video file into the folder
                        new_video_path = video_folder / video_path_obj.name
                        try:
                            # Only move if not already in the folder
                            if video_path_obj.parent != video_folder:
                                shutil.move(str(video_path_obj), str(new_video_path))
                                video_path = str(new_video_path)
                                self.logger.info(f"Moved video to folder: {video_path_obj.name}")
                        except Exception as e:
                            self.logger.warning(f"Could not move video to folder: {e}")
                
                # Set first video as primary for transcription if needed
                if primary_video_path is None:
                    primary_video_path = video_path
            
            # In download mode, skip all clip extraction - just download and process videos
            if self.mode == 'download':
                self.logger.info(f"Download mode: All videos downloaded and processed for folder '{folder_name}'")
                self.stats['full_downloads_completed'] = self.stats.get('full_downloads_completed', 0) + len(downloaded_media)
                continue  # Skip to next folder
            
            # Transcribe primary video if in smart mode (use first video for transcription)
            transcription = None
            if self.mode == 'smart' and primary_video_path:
                transcription = self.transcribe_video(primary_video_path)
                if not transcription:
                    self.logger.warning("Transcription failed - falling back to buffer mode for this folder")
            
            # Process each clip/entry in this folder
            for clip_idx, clip in enumerate(folder_clips, 1):
                timeframe = clip['timeframe']
                dialogue = clip['dialogue']
                
                # Get the video file for this clip
                clip_url = clip['url']
                if clip_url not in downloaded_media:
                    self.logger.warning(f"Skipping clip {clip_idx} - URL not downloaded: {clip_url}")
                    continue
                
                video_path, video_title = downloaded_media[clip_url]
                
                # Get resolution for this specific video
                resolution = self.get_video_resolution(video_path)
                if not resolution:
                    resolution = ""  # If detection fails, don't append resolution
                
                # If no timeframe specified, this is a full video/image download - no clipping needed
                if not timeframe:
                    self.logger.info(f"Entry {clip_idx}/{len(folder_clips)}: No timeframe specified - full media download completed")
                    self.logger.info(f"  URL: {clip['url']}")
                    self.logger.info(f"  Title: {clip['link_text']}")
                    self.stats['full_downloads_completed'] = self.stats.get('full_downloads_completed', 0) + 1
                    continue
                
                # Try smart mode if enabled and we have transcription
                if self.mode == 'smart' and transcription:
                    # Parse dialogue to find start/end word pairs
                    word_pairs = self.parse_dialogue_words(dialogue)
                    
                    # Parse timeframe to get search window bounds
                    time_ranges = self.parse_timeframe(timeframe)
                    
                    if word_pairs and time_ranges:
                        # Use smart extraction with word matching
                        # Match word_pairs to time_ranges (should be same count)
                        for range_idx, ((start_word, end_word), (time_start, time_end)) in enumerate(zip(word_pairs, time_ranges)):
                            self.logger.info(f"Clip {clip_idx}/{len(folder_clips)} - Smart mode")
                            self.logger.info(f"  Looking for: '{start_word}' ... '{end_word}'")
                            self.logger.info(f"  Within timeframe: {time_start} to {time_end}")
                            
                            # Convert timeframe to seconds for search window
                            approx_start = self.time_to_seconds(time_start)
                            approx_end = self.time_to_seconds(time_end)
                            
                            # Find word timestamps within the specified timeframe
                            result = self.find_word_timestamps(transcription, start_word, end_word, 
                                                              approx_start, approx_end)
                            
                            if result:
                                start_time, end_time, full_text = result
                                
                                # Apply buffers in Smart Mode (after finding precise word boundaries)
                                if self.buffer_before > 0 or self.buffer_after > 0:
                                    buffered_start = max(0, start_time - self.buffer_before)
                                    buffered_end = end_time + self.buffer_after
                                    self.logger.info(f"  Applied buffer: {self.buffer_before}s before, {self.buffer_after}s after")
                                else:
                                    buffered_start = start_time
                                    buffered_end = end_time
                                
                                # Use full transcription as filename
                                if len(word_pairs) > 1:
                                    clip_name = f"{self.sanitize_clip_name(full_text)}-part{range_idx+1}"
                                else:
                                    clip_name = f"{self.sanitize_clip_name(full_text)}"
                                
                                # Add resolution if available
                                if resolution:
                                    clip_name += f" {resolution}"
                                clip_name += ".mp4"
                                
                                output_path = video_folder / clip_name
                                
                                # Convert float seconds to time format
                                start_str = self.seconds_to_time(int(buffered_start))
                                end_str = self.seconds_to_time(int(buffered_end))
                                
                                self.logger.info(f"  Smart extraction: {start_str} to {end_str}")
                                self.logger.info(f"  Full text: {full_text}")
                                self.extract_clip(video_path, start_str, end_str, output_path, full_text)
                            else:
                                self.logger.warning(f"  Could not find words - falling back to timeframe")
                                # Fall back to regular timeframe extraction
                                self._extract_with_timeframe(video_path, video_folder, clip_idx, len(folder_clips), 
                                                            timeframe, dialogue, range_idx, resolution)
                    else:
                        # No word pairs found - use regular timeframe
                        self._extract_with_timeframe(video_path, video_folder, clip_idx, len(folder_clips), 
                                                    timeframe, dialogue, 0, resolution)
                else:
                    # Buffer mode - use regular timeframe extraction
                    self._extract_with_timeframe(video_path, video_folder, clip_idx, len(folder_clips), 
                                                timeframe, dialogue, 0, resolution)
        
        # Save stats at end of all processing
        stats_file = self.output_dir / "clip_extraction_stats.json"
        with open(stats_file, 'w') as f:
            json.dump({
                **self.stats,
                'timestamp': datetime.now().isoformat(),
                'mode': self.mode,
                'output_dir': str(self.output_dir)
            }, f, indent=2)
        
        return self.stats
    
    def _extract_with_timeframe(self, video_path: str, video_folder: Path, clip_idx: int, 
                                total_clips: int, timeframe: str, dialogue: str, start_range_idx: int, resolution: str = None):
        """Helper method to extract clips using timeframes (buffer mode)"""
        # Parse timeframes
        time_ranges = self.parse_timeframe(timeframe)
        
        if not time_ranges:
            self.logger.warning(f"No valid timeframes found: {timeframe}")
            self.stats['errors'] += 1
            return
        
        # Extract each time range
        for range_idx, (start, end) in enumerate(time_ranges, start=start_range_idx):
            # Generate contextual filename using transcription
            base_filename = self.generate_contextual_filename(video_path, start, end, dialogue)
            
            # Add resolution before file extension if available
            if resolution:
                base_filename = base_filename.replace('.mp4', f' {resolution}.mp4')
            
            # Add part number if multiple ranges
            if len(time_ranges) > 1:
                clip_name = base_filename.replace('.mp4', f'-part{range_idx+1}.mp4')
            else:
                clip_name = base_filename
            
            output_path = video_folder / clip_name
            
            self.logger.info(f"Clip {clip_idx}/{total_clips}: {clip_name}")
            if self.mode == 'buffer' and (self.buffer_before > 0 or self.buffer_after > 0):
                self.logger.info(f"  (with {self.buffer_before}s before, {self.buffer_after}s after)")
            self.extract_clip(video_path, start, end, output_path, None)


def select_source_file() -> str:
    """Open a file dialog to select the RTF source file (native picker on macOS)."""
    home = os.path.expanduser("~")
    print("Opening file dialog to select source RTF file...")
    source_file = None
    if _is_darwin():
        source_file = _macos_choose_file(
            "Select RTF file containing video clips data",
            default_dir=home,
        )
    else:
        try:
            source_file = _tk_choose_file(
                "Select RTF file containing video clips data",
                initialdir=home,
            )
        except Exception as e:
            print(f"File dialog failed ({e}). Enter path manually.")
            source_file = None
    if not source_file:
        manual = input("Enter full path to RTF file (or press Enter to exit): ").strip().strip('"')
        if not manual:
            print("No file selected. Exiting.")
            sys.exit(0)
        source_file = os.path.expanduser(manual)
    if not os.path.isfile(source_file):
        print(f"Not a file: {source_file}")
        sys.exit(1)
    return source_file


def get_target_directory(source_file: str) -> str:
    """Get target directory; user should explicitly choose where outputs go (picker first)."""
    source_path = Path(source_file)
    default_target = source_path.parent
    
    print(f"\nSource file: {source_file}")
    print(f"Suggested default (same folder as RTF): {default_target}")
    
    while True:
        choice = input("\nWhere should downloads and clips be saved?\n"
                      "1. Choose folder… (opens a folder picker — recommended)\n"
                      "2. Same folder as the RTF file\n"
                      "3. Create a new subfolder next to the RTF file\n"
                      "Enter choice (1-3) [default: 1]: ").strip()
        
        if choice == "" or choice == "1":
            print("Opening folder picker…")
            target_dir = None
            if _is_darwin():
                target_dir = _macos_choose_folder(
                    "Select destination folder for downloads and clips",
                    initial_dir=str(default_target),
                )
            else:
                try:
                    target_dir = _tk_choose_folder(
                        "Select destination folder for downloads and clips",
                        initialdir=str(default_target),
                    )
                except Exception as e:
                    print(f"Folder dialog failed ({e}). Type a path instead.")
                    target_dir = None
            if not target_dir:
                typed = input(
                    "Destination folder path (or press Enter to try menu again): "
                ).strip().strip('"')
                if typed:
                    target_dir = os.path.expanduser(typed)
                    if os.path.isdir(target_dir):
                        print(f"✓ Destination: {target_dir}")
                        return target_dir
                    try:
                        os.makedirs(target_dir, exist_ok=True)
                        print(f"✓ Destination: {target_dir}")
                        return target_dir
                    except OSError as err:
                        print(f"Invalid path: {err}")
                print("No folder selected. Pick an option again or press Ctrl+C to cancel.")
                continue
            print(f"✓ Destination: {target_dir}")
            return target_dir
        
        elif choice == "2":
            print(f"✓ Using RTF folder: {default_target}")
            return str(default_target)
        
        elif choice == "3":
            folder_name = input("New folder name (created next to the RTF): ").strip()
            if folder_name:
                new_folder = default_target / folder_name
                new_folder.mkdir(exist_ok=True)
                print(f"✓ Created/using folder: {new_folder}")
                return str(new_folder)
            print("No folder name entered. Choose 1–3 again.")
            continue
        
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")


def get_extraction_mode() -> str:
    """Prompt user to select extraction mode"""
    print("\n" + "="*60)
    print("EXTRACTION MODE")
    print("="*60)
    print("Choose how to process videos:")
    print()
    print("  A. SMART MODE (Recommended for clips)")
    print("     → Uses AI transcription to find exact word boundaries")
    print("     → No buffers needed - captures complete phrases")
    print("     → Uses full transcription as clip filename")
    print("     → Requires: OpenAI Whisper (auto-installed)")
    print("     → Slower: Adds 1-2 min transcription per video")
    print()
    print("  B. BUFFER MODE (Fast & Simple for clips)")
    print("     → Uses your timeframes + configurable buffers")
    print("     → Faster: No transcription needed")
    print("     → You control exact timing")
    print()
    print("  C. DOWNLOAD MODE (Full videos only)")
    print("     → Downloads all videos from RTF and converts to H.264")
    print("     → No clip extraction - just full video downloads")
    print("     → Ignores timeframes and dialogue columns")
    print("     → Fastest: No transcription or clipping")
    print()
    
    if not whisper_package_installed():
        print("⚠️  Note: Whisper not installed - Smart mode unavailable")
        print("   Install with: pip install openai-whisper")
        print()
    
    while True:
        choice = input("Select mode (A/B/C) [default: B]: ").strip().upper()
        
        if choice == 'A' or choice == 'SMART':
            if not is_whisper_available():
                print("⚠️  Smart mode requires Whisper. Install with: pip install openai-whisper")
                continue
            print("✓ Using SMART mode - AI-powered word matching")
            return 'smart'
        elif choice == 'B' or choice == 'BUFFER' or choice == '':
            print("✓ Using BUFFER mode - Time-based extraction")
            return 'buffer'
        elif choice == 'C' or choice == 'DOWNLOAD':
            print("✓ Using DOWNLOAD mode - Full videos only (no clips)")
            return 'download'
        else:
            print("Please enter 'A', 'B', or 'C'")


def get_buffer_settings(mode: str = 'buffer') -> Tuple[int, int]:
    """Prompt user for buffer time settings"""
    # Skip buffer settings for download mode (no clips being extracted)
    if mode == 'download':
        return 0, 0
    
    print("\n" + "="*60)
    print("TIME BUFFER SETTINGS")
    print("="*60)
    if mode == 'smart':
        print("Smart Mode: Adding a buffer helps with transitions between clips.")
        print("Buffers are applied AFTER AI finds precise word boundaries.")
    else:
        print("Adding a buffer helps avoid cutting off the beginning or end of clips.")
    print("Example: A 2-second buffer adds 2s before and 2s after each clip.")
    print()
    
    while True:
        try:
            buffer = input("Seconds to add before AND after each clip [default: 2]: ").strip()
            buffer = int(buffer) if buffer else 2
            if buffer < 0:
                print("Please enter a positive number or 0")
                continue
            break
        except ValueError:
            print("Please enter a valid number")
    
    # Return same value for both before and after
    print()
    if buffer > 0:
        print(f"✓ Using buffer: {buffer}s before and after each clip")
    else:
        print("✓ No buffer - using exact timeframes")
    print()
    
    return buffer, buffer


def get_download_mode() -> str:
    """Get user's choice between RTF download or single video download"""
    print("\n" + "="*60)
    print("📋 DOWNLOAD MODE SELECTION")
    print("="*60)
    print("Choose your download mode:")
    print("A) Download from RTF file - Extract clips based on timeframes")
    print("B) Download single video - Download and convert one video")
    print("C) Download all full videos - Download all videos without clip extraction")
    print("D) Extract clips from LOCAL videos folder (RTF timeframes; no downloading)")
    print("E) Diagnostics - Analyze a single YouTube URL (formats, cookies, restrictions)")
    print()
    print("💡 Tip: Type 'go back' to return to start, 'restart' to restart the application")
    
    while True:
        choice = input("Enter choice (A/B/C/D/E): ").strip().upper()
        
        # Check for navigation commands
        if choice.lower() == 'go back':
            return 'GO_BACK'
        elif choice.lower() == 'restart':
            return 'RESTART'
        
        if choice == 'A':
            return 'rtf'
        elif choice == 'B':
            return 'single'
        elif choice == 'C':
            return 'download'
        elif choice == 'D':
            return 'local'
        elif choice == 'E':
            return 'diagnostics'
        else:
            print("Please enter 'A', 'B', 'C', 'D', or 'E'")


def get_single_video_url() -> str:
    """Get video URL from user"""
    print("\n" + "="*60)
    print("🔗 SINGLE VIDEO DOWNLOAD")
    print("="*60)
    print("Paste the URL of the video page you want to download.")
    print("Supported platforms: YouTube, Vimeo, and many others")
    print()
    print("💡 Smart fallback: If direct download fails, the script will:")
    print("   • Search the page for YouTube links")
    print("   • Automatically try downloading from YouTube if found")
    print()
    print("⚠️  Note: Some URLs may not work due to:")
    print("   • Live streams (can't download live content)")
    print("   • Geographic restrictions")
    print("   • Website-specific limitations")
    print()
    print("💡 Tip: Type 'go back' to return to download mode, 'restart' to restart the application")
    
    while True:
        url = input("Video URL: ").strip()
        
        # Check for navigation commands
        if url.lower() == 'go back':
            return 'GO_BACK'
        elif url.lower() == 'restart':
            return 'RESTART'
        
        if url and ('http://' in url or 'https://' in url):
            return url
        else:
            print("Please enter a valid URL starting with http:// or https://")


def print_cookie_instructions():
    """Print instructions for creating YouTube cookie files"""
    print("\n" + "="*60)
    print("🍪 YOUTUBE COOKIE PROFILES SETUP")
    print("="*60)
    print("To bypass YouTube's quality restrictions, you can create multiple")
    print("cookie profiles. The script will try each one until it finds one")
    print("that allows 720p+ downloads.")
    print()
    print("📁 Cookie Files to Create:")
    print("   • youtube_cookies.txt           (Primary profile)")
    print("   • youtube_cookies_profile2.txt   (Secondary profile)")
    print("   • youtube_cookies_profile3.txt   (Tertiary profile)")
    print("   • youtube_cookies_private.txt    (Private browser profile)")
    print()
    print("🔧 How to Create Cookie Files:")
    print("1. Install a browser extension like 'Get cookies.txt' or 'cookies.txt'")
    print("2. Go to YouTube.com and log in with different accounts")
    print("3. Use the extension to export cookies")
    print("4. Save as the appropriate filename in the script directory")
    print()
    print("🌐 Alternative: Use Private Browser Session")
    print("1. Open YouTube in private/incognito mode")
    print("2. Export cookies from private session")
    print("3. Save as 'youtube_cookies_private.txt'")
    print()
    print("💡 Pro Tips:")
    print("   • Different accounts may have different quality access")
    print("   • Premium accounts often get better quality")
    print("   • Private sessions sometimes bypass restrictions")
    print("   • The script will try all available profiles automatically")
    print("="*60)


def print_cookie_quickstart(script_dir: Path):
    """Short, actionable cookie instructions (used when cookies are missing)."""
    print("\n" + "="*60)
    print("🍪 YouTube cookies not found (optional, but helps quality)")
    print("="*60)
    print("Some YouTube videos will only download at low quality (e.g., 360p) without cookies.")
    print("To improve access, export cookies from a browser session and save them next to this script.")
    print()
    print(f"Put cookie files in: {script_dir}")
    print("Filenames the script looks for (Netscape cookies.txt format):")
    print("  - youtube_cookies.txt")
    print("  - youtube_cookies_profile2.txt")
    print("  - youtube_cookies_profile3.txt")
    print("  - youtube_cookies_private.txt")
    print()
    print("How to get them:")
    print("  1) In Chrome/Firefox, install an extension such as 'Get cookies.txt' / 'cookies.txt'")
    print("  2) Go to YouTube.com and log in")
    print("  3) Export cookies for youtube.com")
    print("  4) Save as one of the filenames above in that folder")
    print()
    print("Note: Cookies often help, but YouTube may still restrict 720p+ for some videos/accounts.")
    print("="*60)


def ensure_destination_memory_file():
    """Ensure the destination memory file exists and is writable"""
    script_dir = Path(__file__).parent
    last_dest_file = script_dir / '.last_destination.txt'
    
    try:
        # Try to create/access the file
        if not last_dest_file.exists():
            with open(last_dest_file, 'w', encoding='utf-8') as f:
                f.write('')
        
        # Test write access
        with open(last_dest_file, 'a') as f:
            f.write('')  # Append nothing, just test write access
        
        return True
    except Exception as e:
        print(f"❌ Could not create/access destination memory file: {e}")
        print(f"   File path: {last_dest_file}")
        print(f"   Script directory: {script_dir}")
        return False


def _pick_destination_with_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """Open a folder picker; macOS uses AppleScript (avoids Tk abort on some OS builds)."""
    start = initial_dir if initial_dir and os.path.isdir(initial_dir) else os.path.expanduser("~")
    if _is_darwin():
        path = _macos_choose_folder("Select folder for downloaded videos", initial_dir=start)
        if path:
            return path.rstrip("/")
        return None
    try:
        path = _tk_choose_folder("Select folder for downloaded videos", initialdir=start)
        return path if path else None
    except Exception:
        return None


def _save_last_destination(last_dest_file: Path, path: str) -> None:
    try:
        with open(last_dest_file, 'w', encoding='utf-8') as f:
            f.write(path)
        print(f"✅ Destination saved for next session: {path}")
    except Exception as e:
        print(f"Note: could not save destination for next time ({e})")


def get_destination_path() -> str:
    """Get destination folder: optional reuse of last path, then folder picker (or manual path)."""
    script_dir = Path(__file__).parent
    last_dest_file = script_dir / '.last_destination.txt'
    last_destination = None
    
    try:
        if last_dest_file.exists():
            with open(last_dest_file, 'r', encoding='utf-8') as f:
                last_destination = f.read().strip()
            if last_destination and os.path.isdir(last_destination):
                print(f"\nLast used destination: {last_destination}")
                use_last = input("Use same destination? (Y/n): ").strip().lower()
                if use_last in ['', 'y', 'yes']:
                    return last_destination
    except Exception as e:
        print(f"Could not read last destination: {e}")
    
    initial = last_destination if last_destination and os.path.isdir(last_destination) else os.path.expanduser("~")
    print("\nA folder picker will open — choose where to save the video.")
    
    while True:
        path = _pick_destination_with_dialog(initial_dir=initial)
        if path:
            path = os.path.expanduser(path)
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                print(f"Could not use that folder: {e}")
                continue
            _save_last_destination(last_dest_file, path)
            return path
        
        retry = input("No folder selected. Open picker again? (Y/n): ").strip().lower()
        if retry not in ['', 'y', 'yes']:
            manual = input("Or type a folder path (or 'cancel' to exit): ").strip()
            if manual.lower() == 'cancel':
                print("Cancelled.")
                sys.exit(0)
            if manual:
                path = os.path.expanduser(manual)
                try:
                    os.makedirs(path, exist_ok=True)
                    _save_last_destination(last_dest_file, path)
                    return path
                except Exception as e:
                    print(f"Error: {e}")
            else:
                print("Try the picker again or enter a path.")


def download_single_video(url: str, destination_path: str):
    """Download and process a single video"""
    print("\n" + "="*60)
    print("SINGLE VIDEO PROCESSING")
    print("="*60)
    print(f"URL: {url}")
    print(f"Destination: {destination_path}")
    print()
    
    try:
        # Create a minimal ClipExtractor instance for downloading
        # Use the destination path as the output directory
        extractor = ClipExtractor(destination_path, 'buffer', 0, 0)
        
        # Download the video
        print("Downloading video...")
        result = extractor.download_video(url)
        
        if not result:
            print("❌ Failed to download video")
            print("The script attempted to search for YouTube links on the page as a fallback.")
            
            # Provide specific guidance based on URL type
            if 'pbs.org' in url.lower():
                print("\n💡 PBS NewsHour URLs can be problematic. Possible issues:")
                print("   • The video might be a live stream (can't download live content)")
                print("   • PBS may have restrictions on downloading")
                print("   • The URL might be temporary or expired")
                print("\n🔧 Try these solutions:")
                print("   1. Check if the video is available as a regular video (not live)")
                print("   2. Try a different PBS URL if available")
                print("   3. Update yt-dlp: pip install --upgrade yt-dlp")
                print("   4. Some PBS content may need to be downloaded manually")
            else:
                print(f"\n💡 Try these solutions:")
                print("   1. Update yt-dlp: pip install --upgrade yt-dlp")
                print("   2. Check if the URL is correct and accessible")
                print("   3. Some URLs may not be downloadable due to restrictions")
            
            return False
            
        video_path, video_title = result
        print(f"✓ Downloaded: {video_title}")
        
        # The video is downloaded to _temp_downloads within the destination_path
        # We need to move it to the main destination folder
        source_path = Path(video_path)
        dest_path = Path(destination_path)
        
        # Move the final video file from _temp_downloads to the main destination
        if source_path.parent.name == "_temp_downloads":
            final_dest = dest_path / source_path.name
            try:
                shutil.move(str(source_path), str(final_dest))
                print(f"✓ Video moved to: {final_dest}")
                
                # Clean up the _temp_downloads folder if empty
                temp_dir = source_path.parent
                try:
                    if temp_dir.exists() and not any(temp_dir.iterdir()):
                        temp_dir.rmdir()
                except:
                    pass  # Ignore cleanup errors
                    
            except Exception as e:
                print(f"Warning: Could not move video to final destination: {e}")
                print(f"Video is available at: {video_path}")
        else:
            print(f"✓ Video saved to: {video_path}")
        
        print(f"\n✅ Video processed and ready for use!")
        print(f"Location: {dest_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error processing video: {e}")
        return False


def _normalize_key(s: str) -> str:
    s = (s or "").lower()
    # Normalize common punctuation/Unicode variations
    s = s.replace("’", "'").replace("“", "\"").replace("”", "\"").replace("–", "-").replace("—", "-")
    # Normalize a couple of common typos seen in titles
    s = s.replace("nividia", "nvidia")
    return ''.join(c for c in s if c.isalnum())


LOCAL_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".webm", ".mov", ".m4v"})


def _pick_best_video_in_subfolder(subdir: Path, rtf_title_key: str) -> Optional[Path]:
    """
    yt-dlp-style layouts: one folder per video title, main file named like the folder.
    Pick the single best candidate; ignore thumbnails/extras by preferring name match to
    the folder name and then largest size on ties.
    """
    import difflib

    candidates = [
        p for p in subdir.iterdir()
        if p.is_file() and p.suffix.lower() in LOCAL_VIDEO_EXTS
    ]
    if not candidates:
        return None

    folder_key = _normalize_key(subdir.name)
    scored = []
    for p in candidates:
        stem_key = _normalize_key(p.stem)
        sm = difflib.SequenceMatcher(None, folder_key, stem_key).ratio()
        if folder_key and stem_key and (folder_key in stem_key or stem_key in folder_key):
            sm = max(sm, 0.82)
        if rtf_title_key:
            sm2 = difflib.SequenceMatcher(None, rtf_title_key, stem_key).ratio()
            if rtf_title_key in stem_key or stem_key in rtf_title_key:
                sm2 = max(sm2, 0.78)
            sm = max(sm, sm2 * 0.95)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        scored.append((sm, size, p))

    scored.sort(key=lambda t: (-t[0], -t[1]))
    best_sm, _best_sz, best_p = scored[0]
    if best_sm >= 0.42:
        return best_p
    try:
        return max(candidates, key=lambda p: p.stat().st_size)
    except (ValueError, OSError):
        return best_p


def _match_rtf_title_to_subfolder(root: Path, rtf_key: str) -> Optional[Path]:
    """Find a direct child directory whose name best matches the RTF folder/title column."""
    import difflib

    if not rtf_key:
        return None
    try:
        children = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    if not children:
        return None

    best = None
    best_score = 0.0
    for child in children:
        dk = _normalize_key(child.name)
        if dk == rtf_key:
            return child
        sm = difflib.SequenceMatcher(None, rtf_key, dk).ratio()
        if rtf_key in dk or dk in rtf_key:
            sm = max(sm, 0.78)
        if sm > best_score:
            best_score = sm
            best = child

    if best and best_score >= 0.52:
        return best
    return None


def build_local_video_index(source_folder: str) -> dict:
    """
    Build an index of local video files under source_folder.
    Returns a catalog dict with:
      - by_stem: {normalized_stem: [Path, ...]}
      - items: list of {path, stem_key, path_key}
    """
    root = Path(source_folder)
    by_stem = {}
    items = []
    for p in root.rglob('*'):
        if p.is_file() and p.suffix.lower() in LOCAL_VIDEO_EXTS:
            stem_key = _normalize_key(p.stem)
            # Include parent folders in the searchable key
            rel = str(p.relative_to(root))
            path_key = _normalize_key(rel)
            by_stem.setdefault(stem_key, []).append(p)
            items.append({"path": p, "stem_key": stem_key, "path_key": path_key})
    return {"by_stem": by_stem, "items": items, "root": root}


def find_best_local_video(video_index: dict, folder_name: str, url: str = "") -> Optional[Path]:
    """
    Try to match the RTF folder/title column to a local filename.
    Prefers yt-dlp-style layouts: immediate subfolder named like the title, with one main
    video file inside named like that folder (other files in the folder are ignored).
    Falls back to matching by YouTube video id if present in URL.
    """
    import difflib

    key = _normalize_key(folder_name)
    by_stem = video_index.get("by_stem", {})
    items = video_index.get("items", [])
    root = video_index.get("root")

    # 0) Subfolder under source root: match RTF title to a child directory, then pick best file inside
    if root and key:
        sub = _match_rtf_title_to_subfolder(root, key)
        if sub:
            picked = _pick_best_video_in_subfolder(sub, key)
            if picked:
                return picked

    # 1) Exact stem match (fast path)
    if key and key in by_stem:
        return by_stem[key][0]

    # 2) YouTube id match anywhere in relative path/stem
    vid = None
    if url:
        m = re.search(r'[?&]v=([a-zA-Z0-9_-]{6,})', url)
        if m:
            vid = m.group(1).lower()
    if vid:
        for it in items:
            p = it["path"]
            if vid in p.name.lower() or vid in str(p).lower():
                return p

    # 3) Substring match against stem/path keys
    if key:
        for it in items:
            if key in it["stem_key"] or key in it["path_key"]:
                return it["path"]

    # 4) Fuzzy match: score similarity between requested title and each path key
    if not key or not items:
        return None

    best = None
    best_score = 0.0
    for it in items:
        score = difflib.SequenceMatcher(None, key, it["path_key"]).ratio()
        if score > best_score:
            best_score = score
            best = it["path"]

    # Require a reasonable similarity to avoid wild mismatches
    if best and best_score >= 0.62:
        return best

    return None


def process_local_folder_from_rtf(rtf_file: str, source_folder: str, output_dir: str, buffer_before: int, buffer_after: int):
    """
    Use RTF timeframes to extract clips from already-downloaded local videos.
    Assumes the RTF 'Folder' column corresponds to the local video filename (roughly).
    """
    print("\n" + "="*60)
    print("📁 LOCAL FOLDER CLIP EXTRACTION")
    print("="*60)
    print(f"RTF: {rtf_file}")
    print(f"Source videos folder: {source_folder}")
    print(f"Output folder: {output_dir}")
    print()

    extractor = ClipExtractor(output_dir, mode='buffer', buffer_before=buffer_before, buffer_after=buffer_after)
    entries = extractor.extract_rtf_data(rtf_file)
    if not entries:
        print("No entries found in RTF.")
        return {'errors': 1}

    video_index = build_local_video_index(source_folder)
    extractor.logger.info(f"Indexed {len(video_index.get('items', []))} local video files under: {source_folder}")

    total_entries = len(entries)
    rows_with_timeframes = 0
    total_clips = 0
    extracted = 0
    errors = 0

    def local_clip_filename(dialogue: str, start: str, end: str) -> str:
        base = extractor.sanitize_clip_name(dialogue or "clip")
        # Keep times in filename for traceability
        safe_time = f"{start.replace(':','-')}_{end.replace(':','-')}"
        return f"{base}__{safe_time}.mp4"

    # Group entries by folder name
    by_folder = {}
    for e in entries:
        by_folder.setdefault(e.get('folder_name') or e.get('link_text') or "Untitled", []).append(e)

    for i, (folder, folder_entries) in enumerate(by_folder.items(), start=1):
        extractor.logger.info("=" * 60)
        extractor.logger.info(f"Local folder {i}/{len(by_folder)}: {folder}")
        extractor.logger.info("=" * 60)

        primary_url = (folder_entries[0].get('url') or "")
        local_video = find_best_local_video(video_index, folder, primary_url)
        if not local_video:
            extractor.logger.error(f"❌ No local video match found for folder '{folder}'")
            errors += len(folder_entries)
            continue

        extractor.logger.info(f"Using local video: {local_video}")
        video_folder = Path(output_dir) / extractor.sanitize_folder_name(folder)
        video_folder.mkdir(parents=True, exist_ok=True)

        for e in folder_entries:
            timeframe = e.get('timeframe')
            dialogue = e.get('dialogue') or "clip"
            if not timeframe:
                extractor.logger.warning("No timeframe specified - skipping clip extraction for this row")
                continue
            rows_with_timeframes += 1

            # Parse time ranges and extract each
            ranges = extractor.parse_timeframe(timeframe)
            if not ranges:
                extractor.logger.warning(f"No valid timeframes: {timeframe}")
                errors += 1
                continue

            for (start, end) in ranges:
                total_clips += 1
                # Apply buffers using existing helper
                start_adj, end_adj = extractor.apply_buffer(start, end)
                clip_name = local_clip_filename(dialogue, start, end)
                out_path = video_folder / clip_name
                ok = extractor.extract_clip(str(local_video), start_adj, end_adj, out_path, None)
                if ok:
                    extracted += 1
                else:
                    errors += 1

    return {
        'total_entries': total_entries,
        'total_rows_with_timeframes': rows_with_timeframes,
        'total_clips': total_clips,
        'clips_extracted': extracted,
        'videos_downloaded': 0,
        'videos_converted': 0,
        'errors': errors,
        'mode': 'local',
        'output_dir': output_dir,
        'source_folder': source_folder,
        'rtf_file': rtf_file,
    }


def get_navigation_input(prompt: str, allow_back: bool = False, allow_restart: bool = False) -> str:
    """Get user input with navigation options"""
    while True:
        user_input = input(prompt).strip()
        
        # Check for navigation commands
        if user_input.lower() == 'go back' and allow_back:
            return 'GO_BACK'
        elif user_input.lower() == 'restart' and allow_restart:
            return 'RESTART'
        elif user_input.lower() in ['go back', 'restart']:
            print("❌ Navigation command not available at this step.")
            continue
        else:
            return user_input


def handle_navigation(navigation_result: str, current_step: str) -> str:
    """Handle navigation commands and return the step to go to"""
    if navigation_result == 'GO_BACK':
        # Define step hierarchy for going back
        step_hierarchy = {
            'download_mode': 'start',
            'rtf_file': 'download_mode',
            'output_dir': 'rtf_file',
            'extraction_mode': 'output_dir',
            'buffer_settings': 'extraction_mode',
            'confirmation': 'buffer_settings',
            'single_url': 'download_mode',
            'single_destination': 'single_url',
            'single_another': 'single_url'
        }
        
        if current_step in step_hierarchy:
            return step_hierarchy[current_step]
        else:
            print("❌ Cannot go back from this step.")
            return current_step
    
    elif navigation_result == 'RESTART':
        return 'start'
    
    return current_step


def run_youtube_diagnostics(url: str):
    print("\n" + "="*60)
    print("🧪 DIAGNOSTICS: YouTube URL analysis")
    print("="*60)
    print(f"URL: {url}")
    print()

    # Basic environment info
    print(f"Python: {sys.executable}")
    print(f"Platform: {platform.platform()}")

    # Proxy env visibility
    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    active = {k: os.environ.get(k) for k in proxy_vars if os.environ.get(k)}
    if active:
        print("\nProxy environment variables detected (may affect yt-dlp):")
        for k, v in active.items():
            print(f"  - {k}={v}")
    else:
        print("\nNo proxy environment variables detected.")

    # Cookie detection
    script_dir = Path(__file__).parent
    cookie_candidates = [
        script_dir / "youtube_cookies.txt",
        script_dir / "youtube_cookies_profile2.txt",
        script_dir / "youtube_cookies_profile3.txt",
        script_dir / "youtube_cookies_private.txt",
    ]
    cookie_found = next((p for p in cookie_candidates if p.exists()), None)
    print("\nCookie files:")
    if cookie_found:
        print(f"  ✓ Found: {cookie_found.name}")
    else:
        print("  ✗ None found next to the script (anonymous access)")

    # yt-dlp info
    try:
        import yt_dlp
        print(f"\nyt-dlp: {getattr(yt_dlp, '__version__', 'unknown')}")
    except Exception as e:
        print(f"\nCould not import yt-dlp: {e}")
        return

    # Extract formats
    opts = {
        "quiet": True,
        "no_warnings": True,
        "simulate": True,
        "extract_flat": False,
        "format": "best",
        "proxy": "",  # ignore proxy env by default
    }
    if cookie_found:
        opts["cookiefile"] = str(cookie_found)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print("\n❌ yt-dlp failed to extract info.")
        print(f"Error: {e}")
        print("\nIf you see PO Token / Data Sync ID / SABR warnings during downloads,")
        print("it often means YouTube is restricting higher qualities for this video/account.")
        return

    title = info.get("title")
    print(f"\nTitle: {title}")

    formats = info.get("formats") or []
    heights = sorted({f.get("height") for f in formats if f.get("height")}, reverse=True)
    has_720 = any(h >= 720 for h in heights)
    print(f"Max height seen: {heights[0] if heights else None}")
    print(f"Has 720p+: {has_720}")

    # Show a compact table of top formats
    print("\nTop formats (up to 20):")
    shown = 0
    for f in sorted(formats, key=lambda x: (x.get("height") or 0, x.get("tbr") or 0), reverse=True):
        if shown >= 20:
            break
        fid = f.get("format_id")
        h = f.get("height")
        ext = f.get("ext")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        proto = f.get("protocol")
        note = f.get("format_note") or ""
        if not fid:
            continue
        print(f"  - id={fid} {h}p ext={ext} v={vcodec} a={acodec} proto={proto} {note}".strip())
        shown += 1

    print("\nInterpretation:")
    if has_720:
        print("  - 720p+ formats exist. If downloads still come out 360p, YouTube is likely blocking access")
        print("    (cookies can help, but sometimes PO tokens / account state still restricts).")
    else:
        print("  - No 720p+ formats are visible to yt-dlp in this environment (even with cookies if present).")
        print("    In that case, the script will allow best-available quality.")


def main():
    print("="*60)
    print("Clip Extractor - Video Download & Processing Tool")
    print("="*60)
    print("This tool can download videos and extract clips based on RTF timeframes,")
    print("or download and convert individual videos from URLs.")
    print()
    
    ensure_destination_memory_file()
    print()
    
    # Show cookie setup instructions
    print_cookie_instructions()
    print()
    
    # Check if ffmpeg is available first
    ffmpeg_paths = [
        'ffmpeg',  # System PATH
        '/usr/local/bin/ffmpeg',  # Homebrew
        '/opt/homebrew/bin/ffmpeg',  # Apple Silicon Homebrew
        '/usr/bin/ffmpeg'  # System location
    ]
    
    ffmpeg_found = False
    for path in ffmpeg_paths:
        try:
            subprocess.run([path, '-version'], capture_output=True, check=True, timeout=5)
            ffmpeg_found = True
            break
        except:
            continue
    
    if not ffmpeg_found:
        print("Error: ffmpeg is not installed or not in PATH")
        print("Please install ffmpeg:")
        print("  macOS: brew install ffmpeg")
        print("  Ubuntu: sudo apt install ffmpeg")
        sys.exit(1)
    
    # Support both command line and interactive modes
    if len(sys.argv) in [3, 4, 5]:
        # Command line mode (backward compatibility - always uses buffer mode)
        rtf_file = sys.argv[1]
        output_dir = sys.argv[2]
        mode = 'buffer'  # Command line defaults to buffer mode
        
        if not os.path.exists(rtf_file):
            print(f"Error: RTF file '{rtf_file}' not found")
            sys.exit(1)
        
        # Get buffer settings
        if len(sys.argv) == 4:
            # Single buffer value for both before and after
            buffer = int(sys.argv[3])
            buffer_before = buffer_after = buffer
            print(f"Using buffer mode: {buffer}s before and after")
        elif len(sys.argv) == 5:
            # Separate before and after values (backwards compatibility)
            buffer_before = int(sys.argv[3])
            buffer_after = int(sys.argv[4])
            print(f"Using buffer mode: {buffer_before}s before, {buffer_after}s after")
        else:
            # Prompt for buffer settings (mode unknown in command line, default to buffer)
            buffer_before, buffer_after = get_buffer_settings('buffer')
            
    elif len(sys.argv) == 1:
        # Interactive mode with navigation support
        while True:
            try:
                download_mode = get_download_mode()
                
                # Handle navigation responses
                if download_mode == 'GO_BACK':
                    print("❌ Cannot go back from the start. Use 'restart' to restart the application.")
                    continue
                elif download_mode == 'RESTART':
                    print("🔄 Restarting application...")
                    # Restart by calling main() recursively
                    main()
                    return
                
                if download_mode == 'single':
                    # Single video download mode with loop for multiple downloads
                    destination_path = None
                    
                    while True:
                        # Get URL for this download
                        url = get_single_video_url()
                        
                        # Handle navigation responses
                        if url == 'GO_BACK':
                            print("🔄 Going back to download mode selection...")
                            break  # Break out of single video loop to return to download mode
                        elif url == 'RESTART':
                            print("🔄 Restarting application...")
                            main()
                            return
                        
                        # Get destination path (remember previous if available)
                        if destination_path is None:
                            destination_path = get_destination_path()
                        else:
                            print(f"\nPrevious destination: {destination_path}")
                            use_same = input("Use same destination? (Y/n): ").strip().lower()
                            if use_same in ['', 'y', 'yes']:
                                print(f"Using destination: {destination_path}")
                                # Save this destination for next session
                                try:
                                    script_dir = Path(__file__).parent
                                    last_dest_file = script_dir / '.last_destination.txt'
                                    print(f"Saving reused destination to: {last_dest_file}")
                                    with open(last_dest_file, 'w') as f:
                                        f.write(destination_path)
                                    print(f"✅ Destination saved for next session: {destination_path}")
                                except Exception as e:
                                    print(f"❌ Could not save destination for next session: {e}")
                                    print(f"   File path: {last_dest_file}")
                                    print(f"   Script directory: {script_dir}")
                            else:
                                destination_path = get_destination_path()
                        
                        # Process single video
                        success = download_single_video(url, destination_path)
                        if success:
                            print("\n✅ Single video download completed successfully!")
                        else:
                            print("\n❌ Single video download failed!")
                        
                        # Ask if user wants to download another video
                        print("\n" + "="*60)
                        another = input("Download another video? (Y/n): ").strip().lower()
                        if another not in ['', 'y', 'yes']:
                            break
                    
                    print("\n🎉 All downloads completed!")
                    sys.exit(0)

                elif download_mode == 'diagnostics':
                    url = get_single_video_url()
                    if url in ('GO_BACK', 'RESTART'):
                        continue
                    run_youtube_diagnostics(url)
                    again = input("\nRun another diagnostics URL? (y/N): ").strip().lower()
                    if again in ['y', 'yes']:
                        continue
                    sys.exit(0)

                elif download_mode == 'local':
                    rtf_file = select_source_file()
                    # Ask for folder containing already downloaded videos
                    print("\nSelect the folder that contains your already-downloaded videos (1080p, etc.).")
                    source_folder = None
                    if _is_darwin():
                        source_folder = _macos_choose_folder("Select folder containing local videos", initial_dir=str(Path(rtf_file).parent))
                    if not source_folder:
                        source_folder = input("Local videos folder path: ").strip().strip('\"')
                    source_folder = os.path.expanduser(source_folder)
                    if not os.path.isdir(source_folder):
                        print(f"Not a folder: {source_folder}")
                        sys.exit(1)

                    output_dir = get_target_directory(rtf_file)
                    # Only buffer mode for local processing
                    buffer_before, buffer_after = get_buffer_settings('buffer')
                    mode = 'local'
                    break
                    
                else:  # download_mode == 'rtf' or 'download'
                    # Original RTF processing mode
                    rtf_file = select_source_file()
                    output_dir = get_target_directory(rtf_file)
                    mode = get_extraction_mode()
                    
                    # Ask for buffer settings (automatically skips for download mode)
                    buffer_before, buffer_after = get_buffer_settings(mode)
                    
                    # Break out of navigation loop to proceed with processing
                    break
                    
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                sys.exit(0)
            except Exception as e:
                print(f"Error during operation: {e}")
                sys.exit(1)
    else:
        print("Usage: python clip_extractor.py [<rtf_file> <output_directory> [buffer_seconds]]")
        print("\nInteractive mode (no arguments) - Choose between:")
        print('  python clip_extractor.py')
        print("    A) Download from RTF file - Extract clips based on timeframes")
        print("    B) Download single video - Download and convert one video")
        print("\nCommand line mode (RTF processing only):")
        print('  python clip_extractor.py "clips.rtf" "./output"')
        print('  python clip_extractor.py "clips.rtf" "./output" 2  # 2s buffer before and after')
        print('  python clip_extractor.py "clips.rtf" "./output" 2 3  # 2s before, 3s after (legacy)')
        print("\nRTF file should contain:")
        print("  - Column with video URLs")
        print("  - Column with timeframes (e.g., '0:09-0:18' or '4:14-4:17 & 4:29-4:31')")
        print("  - Column with dialogue/clip names")
        sys.exit(1)
    
    print(f"\nFinal settings:")
    print(f"Source file: {rtf_file}")
    print(f"Target directory: {output_dir}")
    print(f"Extraction mode: {mode.upper()}")
    if mode == 'buffer':
        print(f"Time buffers: {buffer_before}s before, {buffer_after}s after")
    elif mode == 'smart':
        if buffer_before > 0 or buffer_after > 0:
            print(f"Smart mode: Using AI transcription with {buffer_before}s before, {buffer_after}s after buffer")
        else:
            print("Smart mode: Using AI transcription for precise word matching")
    elif mode == 'download':
        print("Download mode: Full videos only (no clip extraction)")
    print()
    
    # Confirm before starting
    if len(sys.argv) == 1:  # Only ask for confirmation in interactive mode
        if mode == 'download':
            confirm = input("Proceed with video downloads? (y/N): ").strip().lower()
        else:
            confirm = input("Proceed with clip extraction? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            if mode == 'download':
                print("Video download cancelled.")
            else:
                print("Clip extraction cancelled.")
            sys.exit(0)
    
    try:
        if mode == 'local':
            stats = process_local_folder_from_rtf(
                rtf_file=rtf_file,
                source_folder=source_folder,
                output_dir=output_dir,
                buffer_before=buffer_before,
                buffer_after=buffer_after,
            )
        else:
            extractor = ClipExtractor(output_dir, mode, buffer_before, buffer_after)
            stats = extractor.process_clips(rtf_file)
        
        print("\n" + "="*50)
        if mode == 'download':
            print("VIDEO DOWNLOAD SUMMARY")
        else:
            print("MEDIA EXTRACTION SUMMARY")
        print("="*50)
        print(f"Processing mode: {mode.upper()}")
        
        if mode == 'download':
            # Download mode summary
            print(f"Total videos downloaded: {stats['videos_downloaded']}")
            print(f"Videos converted (AV1→H.264): {stats.get('videos_converted', 0)}")
            print(f"Full videos saved: {stats.get('full_downloads_completed', 0)}")
            print(f"Errors: {stats['errors']}")
        else:
            # Clip extraction mode summary
            print(f"Total entries processed: {stats.get('total_entries', stats['total_clips'])}")
            if stats.get('total_full_downloads', 0) > 0:
                print(f"  - Full downloads: {stats.get('full_downloads_completed', 0)}")
                print(f"  - Clips to extract: {stats['total_clips']}")
            else:
                print(f"Total clips to extract: {stats['total_clips']}")
            print(f"Videos downloaded: {stats['videos_downloaded']}")
            print(f"Videos converted (AV1→H.264): {stats.get('videos_converted', 0)}")
            print(f"Clips extracted: {stats['clips_extracted']}")
            print(f"Errors: {stats['errors']}")
            if mode == 'buffer' and (buffer_before > 0 or buffer_after > 0):
                print(f"Time buffers used: {buffer_before}s before, {buffer_after}s after")
            elif mode == 'smart':
                if buffer_before > 0 or buffer_after > 0:
                    print(f"Smart mode: Used AI transcription with {buffer_before}s before, {buffer_after}s after buffer")
                else:
                    print("Smart mode: Used AI transcription for word-level precision")
        
        # List source URLs separated by success/failure
        if stats.get('source_urls'):
            print(f"\n📋 SOURCE URLs PROCESSED:")
            print("-" * 50)
            
            # Get successful URLs from downloaded videos
            successful_urls = []
            unsuccessful_urls = []
            
            # Check which URLs were successfully downloaded
            for url in stats['source_urls']:
                if url in extractor.downloaded_videos:
                    successful_urls.append(url)
                else:
                    unsuccessful_urls.append(url)
            
            # Print successful URLs
            if successful_urls:
                print("✅ SUCCESSFUL DOWNLOADS:")
                for url in successful_urls:
                    print(f"   {url}")
                print()
            
            # Print unsuccessful URLs
            if unsuccessful_urls:
                print("❌ UNSUCCESSFUL DOWNLOADS:")
                for url in unsuccessful_urls:
                    print(f"   {url}")
                print()
        
        print(f"Output directory: {output_dir}")
        if mode == 'download':
            print("\nVideos are organized in folders by video title")
            print("All videos converted to H.264 for compatibility")
        else:
            print("\nMedia files are organized in folders by video title")
            if mode == 'smart':
                print("Clip filenames use full transcribed text")
        print("="*50)
        
    except KeyboardInterrupt:
        print("\n\nExtraction interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError during extraction: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

