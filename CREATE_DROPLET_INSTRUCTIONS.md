# How to Create a Drag-and-Drop Droplet for AV1 Conversion

## Option 1: Automator Droplet (Recommended - Native macOS)

### Step-by-Step Instructions:

1. **Open Automator**
   - Press `Cmd+Space` and type "Automator"
   - Or find in `/Applications/Automator.app`

2. **Create New Application**
   - Click "New Document"
   - Choose **"Application"** (NOT Workflow)
   - Click "Choose"

3. **Add Actions**
   
   **Step 1:** In the search box (top left), type "Run Shell Script"
   
   **Step 2:** Drag "Run Shell Script" action to the right panel
   
   **Step 3:** Configure the action settings:
   
   **CRITICAL:** Make sure these settings are EXACTLY as shown:
   - **Shell:** `/bin/bash` (use the dropdown menu)
   - **Pass input:** **"as arguments"** (NOT "to stdin" - use the dropdown!)
   
   **Step 4:** Replace the script content:
   - Delete ALL the default text in the script box
   - Paste this ONE line:
   
   ```bash
   /full/path/to/VideoGrabber/automator_wrapper.sh "$@"
   ```

   Use the real path where you keep this project (the script is portable and resolves its own folder).
   
   **Important:** The `"$@"` passes the dropped files to the script.
   
   That's it! Just one simple line that calls the wrapper script.

4. **Save the Application**
   - Press `Cmd+S`
   - Name it: **"Convert AV1 to H.264"**
   - Save location: Desktop or Applications folder
   - Click "Save"

5. **Done!** You now have a droplet icon

### How to Use:

Simply **drag and drop** a folder (or individual files) onto the "Convert AV1 to H.264" app icon:
- Terminal window opens showing progress
- Automatically converts all AV1/VP9 files (no confirmation needed)
- Creates new H.264 versions with `_H264.mp4` suffix
- Original files are preserved (never deleted)
- Shows macOS notification when complete
- Full log saved to your Desktop: `av1_converter_log.txt`

### Troubleshooting:

If the droplet shows an error or doesn't work:
1. Check the log file on your Desktop: `av1_converter_log.txt`
2. Make sure **"Pass input"** is set to **"as arguments"** (not "to stdin")
3. Verify the wrapper script path is correct in the Automator script
4. Open Terminal and test the wrapper script manually:
   ```bash
   /full/path/to/VideoGrabber/automator_wrapper.sh "/path/to/test/folder"
   ```

---

## Option 2: AppleScript Droplet (Alternative)

### Create with Script Editor:

1. **Open Script Editor**
   - `Cmd+Space` → "Script Editor"

2. **Paste this code:**

```applescript
on open droppedItems
	repeat with anItem in droppedItems
		set itemPath to POSIX path of anItem
		
		-- Show notification that conversion is starting
		display notification "Converting AV1 files to H.264..." with title "Video Converter"
		
		-- Run the Python script
		set pythonScript to "/full/path/to/VideoGrabber/convert_av1_to_h264.py"
		set pythonPath to "/usr/bin/python3"
		
		-- Execute in Terminal so user can see progress
		tell application "Terminal"
			activate
			do script pythonPath & " " & quoted form of pythonScript & " " & quoted form of itemPath
		end tell
	end repeat
end open
```

3. **Save as Application:**
   - File → Save
   - File Format: **Application**
   - Name: "Convert AV1 to H.264"
   - Save to Desktop

4. **Done!** Drag folders onto it to convert

---

## Option 3: Simple Double-Click Script

If you just want a double-click script (not drag-and-drop):

1. **I've already created it:** `convert_av1_droplet.sh`

2. **Make it double-clickable:**
   - Right-click `convert_av1_droplet.sh`
   - Choose "Get Info"
   - Under "Open with:" select "Terminal"
   - Click "Change All..."

3. **Use it:**
   - Double-click the script
   - It will prompt you for a folder path
   - Or modify it to hardcode your clips folder

---

## Testing Your Droplet

1. Create a test folder with one AV1 clip
2. Drag it onto your droplet icon
3. Should see Terminal open and show:
   ```
   Found 1 video files
   Checking codecs...
   
   Found 1 AV1/VP9 files that need conversion:
     - video-name.mp4 (av1)
   
   Convert 1 files to H.264? (y/N):
   ```

4. Type `y` and watch it convert!

---

## Converting Your Existing Clips

For your current project clips:

### Using the Droplet
Drag your project folder (the one containing AV1/VP9 files) onto the droplet.

### Or run directly
```bash
cd /full/path/to/VideoGrabber
python3 convert_av1_to_h264.py "/path/to/your/video/folder"
```

---

## Customization

### To use a specific Python

Set the environment variable (works with `automator_wrapper.sh` and `convert_av1_droplet.sh`):

```bash
export VIDEOGRABBER_PYTHON="/path/to/python3"
```

### To Skip Confirmation:

Edit `convert_av1_to_h264.py` and comment out lines with `input()`:
```python
# confirm = input(f"Convert {len(av1_files)} files to H.264? (y/N): ").strip().lower()
# if confirm not in ['y', 'yes']:
#     print("Cancelled")
#     sys.exit(0)
confirm = 'y'  # Auto-confirm
```

---

## Troubleshooting

### Droplet doesn't work:
- Ensure `python3` is on your `PATH`, or set `VIDEOGRABBER_PYTHON` to your interpreter
- Ensure script has execute permissions: `chmod +x convert_av1_droplet.sh`
- Try running the shell script directly in Terminal first

### Permission denied:
- Right-click droplet → Open (first time only)
- macOS may block unsigned applications

### Nothing happens:
- Check System Preferences → Security & Privacy
- Allow Terminal/Automator to run scripts

---

## Which Method Should You Use?

| Method | Pros | Cons |
|--------|------|------|
| **Automator** | Native, visual, official | Requires setup |
| **AppleScript** | Clean, simple | Requires Script Editor |
| **Shell Script** | Already created, ready | Need to navigate to folder |

**Recommendation:** Use **Automator** method - most Mac-like experience with drag-and-drop!

