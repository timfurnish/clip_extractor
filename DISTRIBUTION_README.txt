================================================================================
VideoGrabber — portable package (run from any folder)
================================================================================

WHAT YOU NEED
  • Python 3.10 or newer (python3 --version)
  • ffmpeg on your PATH (macOS: brew install ffmpeg)
  • Internet access for pip and video downloads

SETUP (first time only)
  1. Unzip this folder anywhere you like (Desktop, Documents, USB drive).

  2. Open Terminal, go into the unzipped folder:
       cd /path/to/VideoGrabber

  3. Create a virtual environment (recommended):
       python3 -m venv .venv
       source .venv/bin/activate
     On Windows:
       python -m venv .venv
       .venv\Scripts\activate

  4. Install dependencies:
       pip install -r requirements.txt

RUN THE CLIP EXTRACTOR / DOWNLOADER
  • Interactive (you will be asked to pick RTF file and DESTINATION FOLDER):
       ./run_clip_extractor.sh
     or:
       python3 clip_extractor.py

  • Optional: use a specific Python if the wrong one is on PATH:
       export VIDEOGRABBER_PYTHON="/path/to/python3"
       ./run_clip_extractor.sh

OTHER TOOLS IN THIS PACKAGE
  • media_downloader.py — download from RTF URLs (interactive)
  • convert_av1_to_h264.py — convert AV1/VP9 to H.264 (see README.md)

DOCUMENTATION
  • README_PORTABLE.md — full portable install notes
  • QUICKSTART.md — quick overview
  • README_CLIP_EXTRACTION.md — RTF columns and clip modes

OPTIONAL: YOUTUBE COOKIES
  If downloads are blocked or quality is low, export cookies from your browser
  as Netscape format and save as youtube_cookies.txt next to these scripts.
  Do not share that file — it is like a login session.

FILES NOT INCLUDED (you create locally; never share publicly)
  • youtube_cookies.txt and similar cookie files
  • .last_destination.txt (remembers last folder for single-video mode)

================================================================================
