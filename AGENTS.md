# Realtime Speech Transcription

French speech-to-text project using **Vosk Kaldi** (fully offline).

## Structure

```
main_vosk.py     # Terminal-based transcription (PyAudio + Vosk)
start.py         # Cross-platform launcher (server + browser + cleanup)
start.ps1        # Windows PowerShell launcher
src/
  server.py      # aiohttp server (HTTP + WebSocket)
  static/
    index.html   # Web UI
    app.js       # Audio capture + WebSocket client
    style.css    # Dark theme styles
  requirements.txt
vosk-model-small-fr-0.22/   # Vosk French model (~100MB, don't commit)
.venv/           # Python virtual environment
```

## Commands

```bash
# Activate environment
.venv/Scripts/activate

# Install dependencies
pip install -r requirements.txt

# Run terminal transcription (direct mic → Vosk, no browser needed)
python main_vosk.py

# Run web server (HTTP + WebSocket on port 8765, opens browser, auto-closes)
python start.py

# Windows PowerShell launcher
.\start.ps1
```

No build, test, or lint commands — this is a script-based project.

## Architecture

All transcription uses **Vosk Kaldi** — fully offline, no network required.

### Terminal mode (`main_vosk.py`)

- Loads `vosk-model-small-fr-0.22` eagerly at startup
- Opens PyAudio stream at 16kHz mono, 4000 bytes per read
- `KaldiRecognizer.AcceptWaveform()` on each chunk → `FinalResult()` for completed sentences, `PartialResult()` for live text
- Final results printed in **bold yellow** with ANSI escape codes
- Partial results overwrite the terminal line with `\r` (carriage return)
- Exits on `Ctrl+C`

### Web mode (`src/server.py` + `start.py`)

- **`src/server.py`** — aiohttp server on port 8765
  - Loads `vosk-model-small-fr-0.22` eagerly on startup (blocks until ready)
  - **Health endpoint** (`GET /health`): returns `{"status":"ready"}` (200) when model loaded, `{"status":"loading"}` (202) otherwise
  - **WebSocket endpoint** (`GET /ws`): receives raw audio, streams transcription back
    - Audio from browser: raw PCM s16le at 16kHz mono, sent via `ws.send()`
    - Server sends `{"type":"final","text":"..."}` and `{"type":"partial","text":"..."}` back
    - `KaldiRecognizer.SetWords(True)` enabled for word-level timing
    - Ping/pong keepalive (client pings every 10s)
  - **Heartbeat auto-shutdown**: after 30s without client activity, server shuts down automatically
  - **Static files**: serves `index.html`, `style.css`, `app.js` from `src/static/`
  - Routes: `/`, `/style.css`, `/app.js`, `/health`, `/ws`

- **`src/static/app.js`** — browser client
  - Polls `/health` every 500ms until model is ready
  - Uses Web Audio API: `AudioContext` → `MediaStream` (mic, mono, echo cancellation, noise suppression) → `createScriptProcessor(4096)`
  - **Sample rate conversion**: downsamples from device sample rate to 16kHz via linear interpolation
  - Sends raw PCM s16le buffer via WebSocket binary frames
  - UI: dark theme, toolbar with status indicator (pulses green while listening), large textarea for final text, italic gray for partial text

- **`start.py`** — cross-platform launcher
  - Finds Python executable (venv first, falls back to `sys.executable`)
  - Starts `src/server.py` as subprocess, waits for TCP connection on port 8765
  - Opens default browser to `http://127.0.0.1:8765`
  - Handles Ctrl+C/Ctrl+SIGTERM with cleanup (kills server process, waits up to 5s then forces kill)

- **`start.ps1`** — Windows PowerShell launcher (same behavior, PowerShell-native)

## Gotchas

- **Never name a script `vosk.py`** — it shadows the `vosk` package and causes a circular import (`ImportError: cannot import name 'Model' from partially initialized module 'vosk'`). This is why the original `vosk.py` was renamed to `main_vosk.py`.
- **Vosk model**: `vosk-model-small-fr-0.22/` is ~100MB. Listed in `.gitignore`. Download from https://alphacephei.com/vosk/models (README.txt has the link).
- **stdout flushing is critical** — `main_vosk.py` calls `sys.stdout.flush()` explicitly because real-time output depends on it. Don't remove.
- **`main_vosk.py` partial results use `\r`** — overwrites the terminal line with carriage return. This won't work in piped/redirected output.
- **Microphone init blocks** — `main_vosk.py` opens the PyAudio stream at startup, which blocks until the mic is ready.
- **Server auto-shutdown** — after 30s of no client activity, the server shuts down. A client ping resets the timer.
- **Single `requirements.txt`** — all dependencies (`vosk`, `pyaudio`, `aiohttp`) are in the root file. Install once.
- **Audio format** — browser sends raw PCM s16le (little-endian signed 16-bit) at 16kHz mono. The client does linear interpolation resampling from the device's native sample rate.
