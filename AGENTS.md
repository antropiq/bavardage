# Realtime Speech Transcription

French speech-to-text project using **Vosk Kaldi** (fully offline).

## Structure

```
main_vosk.py     # Terminal-based transcription (PyAudio + Vosk)
start.py         # Cross-platform launcher (server + browser + cleanup)
start.ps1        # Windows PowerShell launcher
src/
  server.py      # aiohttp server (HTTP + WebSocket)
  server_app.py  # ServerApp orchestration
  session_manager.py  # WebSocket session management
  vosk_engine.py     # Vosk model/loading/pooling
  audio_processor.py # Audio chunk processing
  transcription_buffer.py  # Fragment accumulation & silence detection
  llm_post_processor.py    # LLM post-processing (optional)
  static/
    index.html   # Web UI
    app.js       # Audio capture + WebSocket client
    style.css    # Dark theme styles
    audio-processor.js  # Web Audio API utilities
  requirements.txt
vosk-model-fr-0.22/     # Vosk French model (~100MB, don't commit)
.venv/           # Python virtual environment
tests/           # Unit tests
  test_transcription_buffer.py
  test_llm_post_processor.py
llm-migration-layer.md       # LLM post-processing migration spec
llm-migration-layer-todo-list.md  # Implementation tracking
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

# Run with LLM post-processing (requires external LLM server)
python start.py --llm-url http://192.168.1.100:8080 --llm-model llama3

# Run with LLM + custom buffer settings
python start.py --llm-url http://192.168.1.100:8080 \
    --llm-buffer-max 300 \
    --llm-silence-threshold 1.5 \
    --llm-buffer-min 10

# Run with LLM + API key
python start.py --llm-url http://192.168.1.100:8080 --llm-key my-secret-key

# Run server directly with CLI args
PYTHONPATH=. .venv/Scripts/python.exe src/server.py --llm-url http://192.168.1.100:8080

# Run unit tests
.venv/Scripts/python.exe tests/test_transcription_buffer.py
.venv/Scripts/python.exe tests/test_llm_post_processor.py

# Windows PowerShell launcher
.\start.ps1
```

No build command — this is a script-based project.

### Testing
```bash
# Unit tests for TranscriptionBuffer
.venv/Scripts/python.exe tests/test_transcription_buffer.py

# Unit tests for LLMPostProcessor
.venv/Scripts/python.exe tests/test_llm_post_processor.py
```

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
    - **Periodic reset** (`RESET_INTERVAL = 45`): resets Vosk internal state every 45 s to prevent accuracy decay on long sessions. Overlap chunking is disabled by default because Vosk's internal VAD gets confused by repeated audio frames.
    - **Client counter**: server stays alive after client disconnects; only shuts down after `HEARTBEAT_TIMEOUT` (30 s) with zero connected clients.
    - **LLM post-processing** (optional): when `--llm-url` is set, final transcription fragments are accumulated in a `TranscriptionBuffer` and flushed to an external LLM API for punctuation, capitalization, and grammar correction. The LLM is accessed via OpenAI-compatible API (works with llama-swap, Ollama, vLLM). If LLM fails, raw text is used as fallback. See `llm-migration-layer.md` for full spec.
    - **Command mode** (voice-activated): the server detects the keyword "bavardage" in final transcription results to toggle between running mode and command mode. In command mode, transcription output is suppressed and specific keywords trigger actions. See "Command Mode" section below.
  - **Heartbeat auto-shutdown**: after 30s without client activity, server shuts down automatically
  - **Static files**: serves `index.html`, `style.css`, `app.js` from `src/static/`
  - Routes: `/`, `/style.css`, `/app.js`, `/health`, `/ws`

- **`src/static/app.js`** — browser client
  - Polls `/health` every 500ms until model is ready
  - Uses Web Audio API: `AudioContext` → `MediaStream` (mic, mono, echo cancellation, noise suppression) → `createScriptProcessor(2048)`
  - **Sample rate conversion**: downsamples from device sample rate to 16kHz via linear interpolation
  - Sends raw PCM s16le buffer via WebSocket binary frames (~128 ms chunks)
  - Client-side partial deduplication to prevent UI flicker from server overlap duplicates
  - UI: dark theme, toolbar with status indicator (pulses green while listening), large textarea for final text, italic gray for partial text, orange badge in command mode

- **`start.py`** — cross-platform launcher
  - Finds Python executable (venv first, falls back to `sys.executable`)
  - Starts `src/server.py` as subprocess, **forwards all CLI args** (`sys.argv[1:]`)
  - Waits for TCP connection on port 8765
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
- **Server stays alive after disconnect** — after a client stops recording, the server remains running for `HEARTBEAT_TIMEOUT` (30 s) seconds, allowing reconnection. Adjust `HEARTBEAT_TIMEOUT` in `src/server_app.py` if needed.
- **LLM post-processing** — when enabled via `--llm-url`, the server buffers transcription fragments and sends them to an external LLM for post-processing. The LLM is optional and non-blocking; if unavailable, raw transcription is used. Key flags:
  - `--llm-url`: LLM API URL (e.g., `http://192.168.1.100:8080`)
  - `--llm-key`: API key (if required)
  - `--llm-model`: Model name (default: `llama3`)
  - `--llm-timeout`: API timeout in seconds (default: 5.0)
  - `--llm-buffer-max`: Max buffer size in chars before forced flush (default: 500)
  - `--llm-silence-threshold`: Seconds of silence to trigger flush (default: 2.0)
  - `--llm-buffer-min`: Min buffer size to avoid tiny flushes (default: 20)

### Command Mode

Voice-activated command mode lets you control the app without touching the keyboard.

**Keywords** (case-insensitive, detected in final transcription):

| Keyword     | Action                                                                 |
|-------------|------------------------------------------------------------------------|
| `bavardage` | Toggles between running mode (normal transcription) and command mode   |
| `effacer`   | Clears all text from the textarea (only works in command mode)         |
| `effacer ligne` | Removes the last line from the textarea (only works in running mode) |

**Flow:**
1. **Running mode** (default): normal transcription, text appears in textarea
2. Say "bavardage" → switches to **command mode** (transcription suppressed, orange badge appears)
3. Say "effacer" → textarea content is cleared
4. Say "bavardage" again → switches back to **running mode**
5. Say "effacer ligne" → removes the last line from the textarea (running mode only)

**Implementation:**
- `SessionManager.COMMAND_MODE_KEYWORD` = "bavardage"
- `SessionManager.CLEAR_COMMAND_KEYWORD` = "effacer"
- `SessionManager.CLEAR_LAST_LINE_KEYWORD` = "effacer ligne"
- Server sends `{"type":"mode_change","mode":"command|running"}` on toggle
- Server sends `{"type":"command","action":"clear"}` on clear command
- Server sends `{"type":"command","action":"clear_last_line"}` on clear last line command
- Client displays orange "⚡ Mode commande" badge and updates status text in command mode
- Each WebSocket session maintains its own command mode state independently
