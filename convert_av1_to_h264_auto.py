#!/usr/bin/env python3
"""
Convert AV1 clips to H.264 for Adobe Premiere compatibility (AUTO-CONFIRM VERSION)

This version automatically converts without prompting - designed for droplet use.
"""

import os
import sys
import subprocess
from pathlib import Path


def get_video_codec(video_path: str) -> str:
    """Detect the video codec"""
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
                    return codec
            except Exception as e:
                continue
        
        return "unknown"
    except Exception as e:
        return "unknown"


def convert_to_h264(input_path: str, output_path: str) -> bool:
    """Convert video to H.264/AAC"""
    try:
        print(f"  Converting: {Path(input_path).name}")
        
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
        
        cmd = [
            ffmpeg_cmd,
            '-i', input_path,
            '-map', '0:v:0',  # Explicitly map video stream
            '-map', '0:a:0?',  # Map audio stream if it exists (? makes it optional)
            '-c:v', 'libx264',  # Video codec
            '-preset', 'fast',   # Encoding speed
            '-crf', '18',        # Quality (18 = near-lossless)
            '-pix_fmt', 'yuv420p',  # Pixel format (ensures compatibility)
            '-c:a', 'aac',       # Audio codec
            '-b:a', '192k',      # Audio bitrate
            '-movflags', '+faststart',  # Web optimization
            '-y',                # Overwrite output
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
        print("Usage: python convert_av1_to_h264_auto.py <directory_or_file>")
        print("\nAuto-converts all AV1/VP9 videos to H.264 (no confirmation prompt).")
        print("Original files are preserved (new files created with _H264 suffix).")
        sys.exit(1)
    
    target = Path(sys.argv[1])
    
    if not target.exists():
        print(f"Error: Path not found: {target}")
        sys.exit(1)
    
    print("="*60)
    print("AV1 to H.264 Auto-Converter")
    print("="*60)
    print()
    
    # Find video files
    video_extensions = ['.mp4', '.mkv', '.webm', '.mov']
    video_files = []
    
    if target.is_file():
        # Single file
        if target.suffix.lower() in video_extensions:
            video_files = [target]
        else:
            print(f"Error: {target.name} is not a supported video file")
            sys.exit(1)
    elif target.is_dir():
        # Directory - find all video files
        for ext in video_extensions:
            video_files.extend(target.rglob(f'*{ext}'))
    else:
        print(f"Error: {target} is neither a file nor directory")
        sys.exit(1)
    
    if not video_files:
        print("No video files found")
        sys.exit(0)
    
    print(f"Scanning {len(video_files)} video files...")
    
    # Find AV1 files
    av1_files = []
    for video_file in video_files:
        # Skip temp files
        if '.converting' in video_file.name or '.original' in video_file.name:
            continue
            
        codec = get_video_codec(str(video_file))
        if codec in ['av1', 'av01', 'vp9']:
            av1_files.append((video_file, codec))
    
    if not av1_files:
        print("✓ No AV1/VP9 files found - all videos are already Premiere-compatible!")
        sys.exit(0)
    
    print(f"\nFound {len(av1_files)} AV1/VP9 files to convert:")
    for video_file, codec in av1_files:
        print(f"  - {video_file.name} ({codec})")
    
    print()
    print("⚠️  AUTO-CONVERTING (originals will be overwritten)")
    print()
    
    converted = 0
    failed = 0
    
    for i, (video_file, codec) in enumerate(av1_files, 1):
        print(f"[{i}/{len(av1_files)}] {video_file.name}")
        
        # Create output file with _H264 suffix to keep original safe
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
    
    print("="*60)
    print("CONVERSION SUMMARY")
    print("="*60)
    print(f"Converted: {converted}")
    print(f"Failed: {failed}")
    print()
    print("H.264 files created with '_H264' suffix")
    print("Original AV1 files are KEPT (not deleted)")
    print("You can manually delete AV1 originals after verifying conversions")
    print("="*60)


if __name__ == "__main__":
    main()

