# Bavardage — Offline French Speech-to-Text

Real-time French voice transcription running **100% offline** using [Vosk Kaldi](https://alphacephei.com/vosk/models). No internet connection required.

## Quick Start

### 1. Prerequisites

- Python 3.8+
- A working microphone

### 2. Install

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Download the Model

Download the French speech model and place it in the project root:

1. Go to https://alphacephei.com/vosk/models
2. Download **vosk-model-small-fr-0.22** (~100 MB, recommended for speed)
3. Extract the folder so the path is: `vosk-model-small-fr-0.22/`

```
realtime-speech/
├── vosk-model-small-fr-0.22/   # ← extracted model folder
├── src/
├── requirements.txt
└── ...
```

### 4. Run

**Web UI (recommended):**

```bash
python start.py
```

Starts the server, opens your browser automatically, and listens on `http://127.0.0.1:8765`. Press `Ctrl+C` to stop.

**Terminal mode (no browser):**

```bash
python main_vosk.py
```

Streams transcription directly to the terminal. Press `Ctrl+C` to exit.

## How It Works

```
Microphone → Audio capture (16kHz mono) → Vosk Kaldi → Transcription text
```

- **Web mode**: Browser captures audio via Web Audio API, sends raw PCM to an aiohttp WebSocket server, which runs Vosk and streams results back.
- **Terminal mode**: PyAudio captures audio directly, Vosk processes it in-process, results print to stdout.

Both modes use the same French model — fully offline, no API keys, no network calls.

## Project Structure

```
main_vosk.py     # Terminal transcription (PyAudio + Vosk)
start.py         # Cross-platform launcher (server + browser + cleanup)
src/
  server.py      # aiohttp server (HTTP + WebSocket)
  static/
    index.html   # Web UI
    app.js       # Audio capture + WebSocket client
    style.css    # Dark theme styles
requirements.txt # Python dependencies
vosk-model-small-fr-0.22/  # French ASR model (~100 MB)
```

## Notes

- The model folder is ~100 MB and listed in `.gitignore` — clone the repo first, then download.
- Server auto-shuts down after 30 seconds of inactivity.
- Audio is sent as raw PCM s16le (16 kHz, mono, little-endian).

## Command Mode

The app supports a **command mode** triggered by voice keywords. This lets you control the app without touching the keyboard.

### How It Works

| Keyword    | Action                                                        |
|------------|---------------------------------------------------------------|
| `bavardage` | Toggles between **running mode** (normal transcription) and **command mode** (no transcription output) |
| `effacer`   | Clears all text from the textarea (only works in command mode) |
| `effacer ligne` | Removes the last line from the textarea (only works in running mode) |

### Workflow Example

1. Speak **"bavardage"** → app switches to command mode (transcription pauses, orange badge appears)
2. Speak **"effacer"** → textarea content is cleared
3. Speak **"bavardage"** again → app switches back to running mode (transcription resumes)

### Visual Indicator

When in command mode, an orange **"⚡ Mode commande"** badge appears in the toolbar, and the status text changes to remind you of the exit keyword.
