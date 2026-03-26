#!/usr/bin/env python3
"""
Convert AV1 clips to H.264 for Adobe Premiere compatibility

This script finds all AV1-encoded video files in a directory and converts them
to H.264 (MP4) format that Adobe Premiere can use.
"""

import os
import sys
import subprocess
from pathlib import Path


def get_video_codec(video_path: str) -> str:
    """Detect the video codec"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
        return "unknown"
    except Exception:
        return "unknown"


def convert_to_h264(input_path: str, output_path: str) -> bool:
    """Convert video to H.264/AAC"""
    try:
        print(f"  Converting: {Path(input_path).name}")
        
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-map', '0:v:0',      # Explicitly map video stream
            '-map', '0:a:0?',     # Map audio stream if exists (? = optional)
            '-c:v', 'libx264',    # Video codec
            '-preset', 'fast',    # Encoding speed
            '-crf', '18',         # Near-lossless quality
            '-pix_fmt', 'yuv420p',  # Pixel format for compatibility
            '-c:a', 'aac',        # Audio codec
            '-b:a', '192k',       # Audio bitrate
            '-movflags', '+faststart',  # Optimization for editing
            '-y',
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes max
        )
        
        if result.returncode == 0:
            print(f"  ✓ Converted successfully")
            return True
        else:
            print(f"  ✗ Error: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python convert_av1_to_h264.py <directory>")
        print("\nConverts all AV1/VP9 videos in directory to H.264 for Adobe Premiere.")
        print("Original files are kept with '.original' extension.")
        sys.exit(1)
    
    directory = Path(sys.argv[1])
    
    if not directory.exists():
        print(f"Error: Directory not found: {directory}")
        sys.exit(1)
    
    # Find all video files
    video_extensions = ['.mp4', '.mkv', '.webm', '.mov']
    video_files = []
    
    for ext in video_extensions:
        video_files.extend(directory.rglob(f'*{ext}'))
    
    if not video_files:
        print("No video files found in directory")
        sys.exit(0)
    
    print(f"Found {len(video_files)} video files")
    print("Checking codecs...\n")
    
    # Find AV1 files
    av1_files = []
    for video_file in video_files:
        # Skip already converted originals
        if '.original' in video_file.name:
            continue
            
        codec = get_video_codec(str(video_file))
        if codec in ['av1', 'av01', 'vp9']:
            av1_files.append((video_file, codec))
    
    if not av1_files:
        print("✓ No AV1/VP9 files found - all videos are Premiere-compatible!")
        sys.exit(0)
    
    print(f"Found {len(av1_files)} AV1/VP9 files that need conversion:\n")
    for video_file, codec in av1_files:
        print(f"  - {video_file.name} ({codec})")
    
    print()
    confirm = input(f"Convert {len(av1_files)} files to H.264? (y/N): ").strip().lower()
    
    if confirm not in ['y', 'yes']:
        print("Cancelled")
        sys.exit(0)
    
    print("\nConverting files (creating _H264 versions)...\n")
    
    converted = 0
    failed = 0
    
    for i, (video_file, codec) in enumerate(av1_files, 1):
        print(f"[{i}/{len(av1_files)}] {video_file.name}")
        
        # Create output file with _H264 suffix (keeps original safe)
        stem = video_file.stem
        parent = video_file.parent
        output_file = parent / f"{stem}_H264.mp4"
        
        # Convert to H.264
        if convert_to_h264(str(video_file), str(output_file)):
            print(f"  ✓ Created H.264 version: {output_file.name}")
            print(f"  ℹ️  Original AV1 kept: {video_file.name}")
            converted += 1
        else:
            # Clean up failed conversion
            if output_file.exists():
                output_file.unlink()
            failed += 1
        
        print()
    
    print("="*50)
    print("CONVERSION SUMMARY")
    print("="*50)
    print(f"Converted: {converted}")
    print(f"Failed: {failed}")
    print()
    print("✓ H.264 files created with '_H264' suffix")
    print("✓ Original AV1 files are KEPT (safe)")
    print("ℹ️  You can delete AV1 originals after verifying H.264 versions work")
    print("="*50)


if __name__ == "__main__":
    main()

