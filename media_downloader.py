#!/usr/bin/env python3
"""
Media Downloader - Downloads videos and images from URLs extracted from RTF files

This script parses RTF files to extract URLs, then downloads:
- Videos using yt-dlp (highest quality)
- Images using requests

Features:
- Skips already downloaded files
- Progress tracking
- Error handling and logging
- Support for multiple video platforms via yt-dlp
"""

import os
import re
import sys
import requests
import logging
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Tuple, Optional
import json
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import yt_dlp
except ImportError:
    print("yt-dlp not found. Please install it with: pip install yt-dlp")
    sys.exit(1)


class MediaDownloader:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Setup logging
        log_file = self.output_dir / "download_log.txt"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Image extensions
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff'}
        
        # Track downloaded URLs to prevent duplicates
        self.downloaded_urls = self.load_downloaded_urls()
        
        # Stats tracking
        self.stats = {
            'videos_downloaded': 0,
            'images_downloaded': 0,
            'skipped_existing': 0,
            'errors': 0,
            'total_urls': 0
        }
        
    def load_downloaded_urls(self) -> set:
        """Load previously downloaded URLs from a tracking file"""
        url_file = self.output_dir / "downloaded_urls.txt"
        if url_file.exists():
            try:
                with open(url_file, 'r', encoding='utf-8') as f:
                    return set(line.strip() for line in f if line.strip())
            except Exception as e:
                self.logger.warning(f"Could not load downloaded URLs: {e}")
        return set()
    
    def save_downloaded_url(self, url: str):
        """Save a downloaded URL to the tracking file"""
        self.downloaded_urls.add(url)
        url_file = self.output_dir / "downloaded_urls.txt"
        try:
            with open(url_file, 'a', encoding='utf-8') as f:
                f.write(f"{url}\n")
        except Exception as e:
            self.logger.warning(f"Could not save downloaded URL: {e}")
        
    def extract_urls_from_rtf(self, rtf_file: str) -> List[Tuple[str, str]]:
        """Extract URLs from RTF hyperlink fields"""
        self.logger.info(f"Parsing RTF file: {rtf_file}")
        
        try:
            with open(rtf_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"Error reading RTF file: {e}")
            return []
        
        # Pattern to match RTF hyperlinks: {\field{\*\fldinst{HYPERLINK "URL"}}{\fldrslt LINK_TEXT}}
        pattern = r'\{\\field\{\\\\?\*\\fldinst\{HYPERLINK "([^"]+)"\}\}\{\\fldrslt[^}]*\}([^}]*)\}'
        
        urls = []
        matches = re.findall(pattern, content, re.MULTILINE | re.DOTALL)
        
        for url, title_part in matches:
            # Clean up the title part to extract actual title
            # Remove RTF formatting codes
            title_clean = re.sub(r'\\[a-z]+\d*\s*', ' ', title_part)
            title_clean = re.sub(r'\s+', ' ', title_clean).strip()
            
            if not title_clean:
                title_clean = "Untitled"
                
            urls.append((url, title_clean))
            self.logger.info(f"Found URL: {url} - Title: {title_clean}")
        
        self.logger.info(f"Extracted {len(urls)} URLs from RTF file")
        return urls
    
    def is_image_url(self, url: str) -> bool:
        """Check if URL points to an image based on extension or content type"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Check file extension
        for ext in self.image_extensions:
            if path.endswith(ext):
                return True
                
        # For URLs without clear extensions, we'll try to check content-type
        try:
            response = requests.head(url, timeout=10, allow_redirects=True)
            content_type = response.headers.get('content-type', '').lower()
            return content_type.startswith('image/')
        except:
            return False
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to be filesystem safe across all operating systems"""
        if not filename:
            return "Untitled"
            
        # Remove or replace filesystem-unsafe characters
        # Windows reserved: < > : " / \ | ? *
        # Also handle additional problematic chars: # % & { } [ ] @ ! $ ' ` ~ + =
        unsafe_chars = r'[<>:"/\\|?*#%&{}[\]@!$\'`~+=]'
        filename = re.sub(unsafe_chars, '-', filename)
        
        # Remove control characters and other problematic Unicode characters
        filename = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', filename)
        
        # Handle periods at the end (Windows doesn't like them)
        filename = filename.rstrip('.')
        
        # Remove multiple consecutive dashes, spaces, and underscores
        filename = re.sub(r'[-\s_]+', '-', filename)
        
        # Clean up the result
        filename = filename.strip('-').strip()
        
        # Windows reserved names (case insensitive)
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        if filename.upper() in reserved_names:
            filename = f"_{filename}"
        
        # Limit length (leave room for extension and quality suffix)
        if len(filename) > 80:
            filename = filename[:80].rstrip('-')
        
        # Final fallback
        if not filename:
            filename = "Untitled"
            
        return filename
    
    def file_exists(self, title: str, url: str) -> Optional[str]:
        """Check if file already exists with various naming patterns"""
        base_name = self.sanitize_filename(title)
        
        # Check for various possible filenames
        patterns = [
            f"{base_name}.*",
            f"*{base_name}*.*",
        ]
        
        for pattern in patterns:
            matches = list(self.output_dir.glob(pattern))
            if matches:
                return str(matches[0].name)
        
        return None
    
    def download_image(self, url: str, title: str) -> bool:
        """Download an image file"""
        try:
            # Check if URL was already downloaded
            if url in self.downloaded_urls:
                self.logger.info(f"Image URL already downloaded: {url}")
                self.stats['skipped_existing'] += 1
                return True
            
            # Check if file already exists by filename
            existing = self.file_exists(title, url)
            if existing:
                self.logger.info(f"Image already exists: {existing}")
                self.save_downloaded_url(url)  # Mark as downloaded
                self.stats['skipped_existing'] += 1
                return True
            
            self.logger.info(f"Downloading image: {title}")
            
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()
            
            # Determine file extension
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type:
                ext = '.jpg'
            elif 'png' in content_type:
                ext = '.png'
            elif 'gif' in content_type:
                ext = '.gif'
            elif 'webp' in content_type:
                ext = '.webp'
            else:
                # Try to get extension from URL
                parsed = urlparse(url)
                _, ext = os.path.splitext(parsed.path)
                if not ext or ext not in self.image_extensions:
                    ext = '.jpg'  # Default
            
            filename = self.sanitize_filename(title) + ext
            filepath = self.output_dir / filename
            
            # Ensure unique filename if it exists
            counter = 1
            while filepath.exists():
                name_part = self.sanitize_filename(title)
                filename = f"{name_part}-{counter}{ext}"
                filepath = self.output_dir / filename
                counter += 1
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.save_downloaded_url(url)
            self.logger.info(f"Image saved: {filename}")
            self.stats['images_downloaded'] += 1
            return True
            
        except Exception as e:
            self.logger.error(f"Error downloading image {title}: {e}")
            self.stats['errors'] += 1
            return False
    
    def download_video(self, url: str, title: str) -> bool:
        """Download a video using yt-dlp"""
        try:
            # Check if URL was already downloaded
            if url in self.downloaded_urls:
                self.logger.info(f"Video URL already downloaded: {url}")
                self.stats['skipped_existing'] += 1
                return True
            
            self.logger.info(f"Extracting video info for: {title}")
            
            # First, extract video info to get actual title and quality
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    actual_title = info.get('title', title)
                    video_height = info.get('height', 'unknown')
                    video_ext = info.get('ext', 'mp4')
                    
                    self.logger.info(f"Actual video title: {actual_title}")
                    self.logger.info(f"Video quality: {video_height}p")
                    
            except Exception as e:
                self.logger.warning(f"Could not extract video info for {url}: {e}")
                actual_title = title
                video_height = 'unknown'
                video_ext = 'mp4'
            
            # Use the actual video title (from YouTube page) instead of RTF title
            sanitized_actual_title = self.sanitize_filename(actual_title)
            
            # Create filename with actual title and quality
            if video_height != 'unknown':
                final_filename = f"{sanitized_actual_title}-{video_height}p.{video_ext}"
            else:
                final_filename = f"{sanitized_actual_title}.{video_ext}"
            
            expected_path = self.output_dir / final_filename
            
            # Check if this specific file already exists
            if expected_path.exists():
                self.logger.info(f"Video already exists: {final_filename}")
                self.save_downloaded_url(url)
                self.stats['skipped_existing'] += 1
                return True
            
            # Check for similar files with the actual title
            pattern = f"{sanitized_actual_title}-*.*"
            existing_files = list(self.output_dir.glob(pattern))
            if existing_files:
                self.logger.info(f"Similar video already exists: {existing_files[0].name}")
                self.save_downloaded_url(url)
                self.stats['skipped_existing'] += 1
                return True
            
            # Also check with the RTF title for backward compatibility
            sanitized_rtf_title = self.sanitize_filename(title)
            rtf_pattern = f"{sanitized_rtf_title}-*.*"
            rtf_existing_files = list(self.output_dir.glob(rtf_pattern))
            if rtf_existing_files:
                self.logger.info(f"Video with RTF title already exists: {rtf_existing_files[0].name}")
                self.save_downloaded_url(url)
                self.stats['skipped_existing'] += 1
                return True
            
            # Set up custom output template using actual video title
            output_template = str(self.output_dir / f'{sanitized_actual_title}-%(height)sp.%(ext)s')
            
            # yt-dlp options for highest quality - prefer non-fragmented formats for speed
            ydl_opts = {
                'outtmpl': output_template,
                'format': (
                    'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/'
                    'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
                ),
                'merge_output_format': 'mp4',
                'writesubtitles': False,
                'writeautomaticsub': False,
                'ignoreerrors': True,
                'no_warnings': False,
                'restrictfilenames': True,  # Additional filename restrictions
                'prefer_free_formats': False,  # Prefer higher quality over free formats
            }
            
            self.logger.info(f"Starting download of: {actual_title}")
            self.logger.info(f"Target filename: {final_filename}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download the video
                ydl.download([url])
            
            self.save_downloaded_url(url)
            self.logger.info(f"Video downloaded successfully: {final_filename}")
            self.stats['videos_downloaded'] += 1
            return True
            
        except Exception as e:
            self.logger.error(f"Error downloading video {title}: {e}")
            self.stats['errors'] += 1
            return False
    
    def download_from_rtf(self, rtf_file: str) -> dict:
        """Main method to download all media from RTF file"""
        urls = self.extract_urls_from_rtf(rtf_file)
        self.stats['total_urls'] = len(urls)
        
        if not urls:
            self.logger.warning("No URLs found in RTF file")
            return self.stats
        
        # Remove duplicate URLs from this session
        unique_urls = []
        seen_urls = set()
        for url, title in urls:
            if url not in seen_urls:
                unique_urls.append((url, title))
                seen_urls.add(url)
            else:
                self.logger.info(f"Skipping duplicate URL in RTF: {url}")
                self.stats['skipped_existing'] += 1
        
        self.logger.info(f"Starting sequential download of {len(unique_urls)} unique items...")
        self.logger.info("Downloads will be processed one at a time to avoid overwhelming servers")
        
        for i, (url, title) in enumerate(unique_urls, 1):
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Processing {i}/{len(unique_urls)}: {title}")
            self.logger.info(f"URL: {url}")
            self.logger.info(f"{'='*60}")
            
            try:
                if self.is_image_url(url):
                    self.download_image(url, title)
                else:
                    self.download_video(url, title)
            except Exception as e:
                self.logger.error(f"Unexpected error processing {url}: {e}")
                self.stats['errors'] += 1
            
            # Small delay between downloads to be respectful to servers
            if i < len(unique_urls):
                import time
                time.sleep(1)
        
        # Save final stats
        stats_file = self.output_dir / "download_stats.json"
        with open(stats_file, 'w') as f:
            json.dump({
                **self.stats,
                'timestamp': datetime.now().isoformat(),
                'rtf_file': rtf_file,
                'output_dir': str(self.output_dir),
                'unique_urls_processed': len(unique_urls)
            }, f, indent=2)
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info("DOWNLOAD SESSION COMPLETED")
        self.logger.info(f"{'='*60}")
        
        return self.stats


def select_source_file() -> str:
    """Open a file dialog to select the RTF source file"""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    # Set up file dialog
    file_types = [
        ("Rich Text Format", "*.rtf"),
        ("Text files", "*.txt"),
        ("All files", "*.*")
    ]
    
    print("Opening file dialog to select source file...")
    source_file = filedialog.askopenfilename(
        title="Select RTF file containing video/image links",
        filetypes=file_types,
        initialdir=os.path.expanduser("~")
    )
    
    root.destroy()
    
    if not source_file:
        print("No file selected. Exiting.")
        sys.exit(0)
    
    return source_file


def get_target_directory(source_file: str) -> str:
    """Get target directory, defaulting to source file's directory"""
    source_path = Path(source_file)
    default_target = source_path.parent
    
    print(f"\nSource file: {source_file}")
    print(f"Default target directory: {default_target}")
    
    while True:
        choice = input("\nChoose an option:\n"
                      "1. Use default target directory (same as source)\n"
                      "2. Choose different target directory\n"
                      "3. Create new folder in default location\n"
                      "Enter choice (1-3): ").strip()
        
        if choice == "1":
            return str(default_target)
        
        elif choice == "2":
            root = tk.Tk()
            root.withdraw()
            
            print("Opening folder dialog...")
            target_dir = filedialog.askdirectory(
                title="Select target directory for downloads",
                initialdir=str(default_target)
            )
            
            root.destroy()
            
            if target_dir:
                return target_dir
            else:
                print("No directory selected. Using default.")
                return str(default_target)
        
        elif choice == "3":
            folder_name = input("Enter new folder name: ").strip()
            if folder_name:
                new_folder = default_target / folder_name
                new_folder.mkdir(exist_ok=True)
                print(f"Created/using folder: {new_folder}")
                return str(new_folder)
            else:
                print("No folder name provided. Using default.")
                return str(default_target)
        
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")


def main():
    print("="*60)
    print("VideoGrabber - RTF Media Downloader")
    print("="*60)
    print("This tool downloads videos and images from URLs in RTF files.")
    print()
    
    # Support both command line and interactive modes
    if len(sys.argv) == 3:
        # Command line mode (backward compatibility)
        rtf_file = sys.argv[1]
        output_dir = sys.argv[2]
        
        if not os.path.exists(rtf_file):
            print(f"Error: RTF file '{rtf_file}' not found")
            sys.exit(1)
    else:
        # Interactive mode
        try:
            rtf_file = select_source_file()
            output_dir = get_target_directory(rtf_file)
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(0)
        except Exception as e:
            print(f"Error during file selection: {e}")
            sys.exit(1)
    
    print(f"\nFinal settings:")
    print(f"Source file: {rtf_file}")
    print(f"Target directory: {output_dir}")
    print()
    
    # Confirm before starting
    if len(sys.argv) != 3:  # Only ask for confirmation in interactive mode
        confirm = input("Proceed with download? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("Download cancelled.")
            sys.exit(0)
    
    try:
        downloader = MediaDownloader(output_dir)
        stats = downloader.download_from_rtf(rtf_file)
        
        print("\n" + "="*50)
        print("DOWNLOAD SUMMARY")
        print("="*50)
        print(f"Total URLs found: {stats['total_urls']}")
        print(f"Videos downloaded: {stats['videos_downloaded']}")
        print(f"Images downloaded: {stats['images_downloaded']}")
        print(f"Skipped (already exist/duplicate): {stats['skipped_existing']}")
        print(f"Errors: {stats['errors']}")
        print(f"Output directory: {output_dir}")
        print("\nNote: All filenames have been sanitized for cross-platform compatibility")
        print("Check 'downloaded_urls.txt' for a record of processed URLs")
        print("="*50)
        
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user.")
        print("Partial progress has been saved.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError during download: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
