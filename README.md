

# MFH Screen Recorder

**MFH — Mouse For Hunt**

A lightweight Python screen recorder and video player with a simple desktop interface. It can record your screen, capture audio, browse recorded videos, and play them back with timeline controls.

## Features

- 🎥 Screen recording
- 🎙️ Audio recording
- ▶️ Built-in video player
- ⏯️ Play / pause controls
- ⏪⏩ Timeline seeking
- 🔊 Audio/video synchronization
- 📁 Media library
- 🖱️ Drag-and-drop support
- 📂 Drag a folder to change the recording/output directory
- 🎬 Drag a supported video file into the app to open it
- ⌨️ Keyboard shortcuts
- 🔄 Refresh media library
- 🌙 Dark desktop UI

## Requirements

- Python 3.9+ recommended
- Windows is recommended because the project uses `PyAudioWPatch` for audio/WASAPI loopback capture.
- A working display/desktop environment
- For Linux, Tkinter may need to be installed separately.

## Installation

### 1. Download the project

Put these files in the same folder:

```text
MFH/
├── main.py
├── requirements.txt
└── README.md
```

### 2. Create a virtual environment

This is recommended so MFH does not interfere with other Python projects.

**Windows:**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the Python dependencies

```bash
pip install -r requirements.txt
```

### Tkinter

Tkinter is part of the standard Python installation on most Windows installations, so it normally does not need to be installed with pip.

On Debian/Ubuntu-based Linux systems, if Tkinter is missing:

```bash
sudo apt install python3-tk
```

## Running MFH

From the project folder:

**Windows:**

```powershell
python main.py
```

**Linux/macOS:**

```bash
python3 main.py
```

## Using the Recorder

1. Open MFH.
2. Choose your recording/output location if needed.
3. Start the recording.
4. Record your screen.
5. Stop the recording when finished.
6. The resulting video will appear in the media library.

## Using the Video Player

You can open a recorded video from the media library, or drag a supported video file into the application.

Supported video formats:

```text
.mp4
.avi
.mkv
.mov
.webm
.m4v
```

### Playback controls

- **Play** — starts playback.
- **Pause** — pauses both video and audio.
- **Timeline** — jump to another position in the video.
- **Stop** — stops the current playback.
- **Seek** — use the timeline or keyboard shortcuts to move through the video.

### Audio playback

MFH keeps the video and audio position synchronized when:

- starting playback
- pausing
- resuming
- seeking through the timeline

If playback is paused and resumed, audio should continue from the correct position instead of requiring the timeline to be touched.

## Drag and Drop

MFH supports drag and drop in several parts of the interface.

### Drop a video

Drag a supported video file onto the application/player area to open it.

### Drop a folder

Drag a folder into the application to use that folder as the recording/output location.

### Drop onto the media library

You can also use drag and drop with the media-library area for supported files.

> Drag-and-drop support uses `tkinterdnd2`, which is included in `requirements.txt`.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Space` | Play / Pause |
| `Left Arrow` | Seek backward 5 seconds |
| `Right Arrow` | Seek forward 5 seconds |
| `Ctrl + O` | Open a video |

## Troubleshooting

### `ModuleNotFoundError`

Make sure the virtual environment is activated and install the dependencies again:

```bash
pip install -r requirements.txt
```

### Tkinter error

On Debian/Ubuntu:

```bash
sudo apt install python3-tk
```

### Audio does not work

MFH uses `PyAudioWPatch` for Windows audio capture. Make sure you are running on Windows with a working audio device and that Python has access to it.

### Drag and drop does not work

Make sure `tkinterdnd2` is installed:

```bash
pip install tkinterdnd2
```

Then restart MFH.

### Video playback problems

Make sure the video file is in one of the supported formats and that OpenCV can read it.

## Project Structure

```text
MFH/
├── main.py              # Main application
├── requirements.txt     # Python dependencies
└── README.md            # Documentation
```

## Dependencies

MFH uses:

- `opencv-python` — video processing and playback
- `mss` — screen capture
- `numpy` — frame/image processing
- `imageio` — media handling
- `imageio-ffmpeg` — FFmpeg support
- `PyAudioWPatch` — Windows audio capture
- `pygame` — audio playback
- `Pillow` — image/UI handling
- `tkinterdnd2` — drag-and-drop support

Python standard-library modules such as `os`, `threading`, `time`, `wave`, `queue`, `subprocess`, and `tkinter` are not listed as pip dependencies.

## Notes

MFH is designed to stay relatively lightweight and easy to run from source. The project is primarily intended for desktop use.

For the most reliable setup, use a recent Python version on Windows and install the dependencies using the provided `requirements.txt`.

## License

Add your license here if you plan to distribute the project publicly.

---

**MFH — Mouse For Hunt**
