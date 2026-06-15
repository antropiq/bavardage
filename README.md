# Bavardage — Offline French Speech-to-Text

Real-time French voice transcription running **100% offline** using [Vosk Kaldi](https://alphacephei.com/vosk/models) and [faster-whisper (CTranslate2)](https://huggingface.co/Systran). No internet connection required.

## Quick Start

### 1. Prerequisites

- Python 3.10+
- A working microphone

### 2. Install

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# see GPU Support (CUDA) for optional cuda dependencies
```

### 3. Download the Models

**Vosk model** (required for Vosk engine):

1. Go to https://alphacephei.com/vosk/models
2. Download **vosk-model-small-fr-0.22** (~100 MB, recommended for speed)
3. Extract the folder so the path is: `vosk-model-small-fr-0.22/`

**Whisper models** (required for Whisper engine):

- Models are downloaded automatically from HuggingFace on first use (e.g., `Systran/faster-whisper-small`)
- Or download manually and provide a local path via `--whisper-model`

```
realtime-speech/
├── vosk-model-small-fr-0.22/   # ← Vosk model folder (optional, ~100 MB)
├── faster-whisper-models/      # ← Whisper models (optional, downloaded automatically)
├── src/
├── pyproject.toml
└── ...
```

### 4. Run

**Web UI (recommended):**

```bash
python start.py
```

Starts the server, displays the URL, and listens on `http://127.0.0.1:8765`. Press `Ctrl+C` to stop.

**Terminal mode (no browser):**

```bash
# With Vosk (default)
python -m src.console

# With Whisper
python -m src.console --engine whisper --whisper-model small

# Via start.py
python start.py --console
```

Streams transcription directly to the terminal. Press `Ctrl+C` to exit.

**GUI mode (Tkinter window):**

```bash
# List available audio devices
python -m src.tkwindow --list-devices

# Run with Vosk (default)
python -m src.tkwindow

# Run with custom model and speaker capture
python -m src.tkwindow --vosk-model /path/to/model --user-speaker --volume 3.0 --debug
```

Opens a floating window with Start/Stop button, device selector, and live transcription display with committed (bold) and partial (italic) text.

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--engine` | Transcription engine (`vosk` or `whisper`) | `vosk` |
| `--vosk-model` | Path to Vosk model directory | `vosk-model-small-fr-0.22` |
| `--whisper-model` | Whisper model size or local path (`tiny`, `base`, `small`, `medium`, `large`) | `small` |
| `--whisper-language` | Language code for Whisper | `fr` |
| `--whisper-device` | Whisper compute device (`auto`, `cpu`, `cuda`) | `auto` |
| `--llm-url` | LLM API URL for post-processing (disabled if not set) | *(disabled)* |
| `--llm-key` | LLM API key | *(none)* |
| `--llm-model` | LLM model name | `llama3` |
| `--llm-timeout` | LLM API timeout in seconds | `15.0` |
| `--llm-buffer-max` | Max buffer size in chars before forced flush | `500` |
| `--llm-silence-threshold` | Seconds of silence to trigger LLM flush | `2.0` |
| `--llm-buffer-min` | Min buffer size to avoid tiny flushes | `20` |
| `--ssl` | Enable HTTPS with self-signed certificate | `false` |
| `--ssl-certfile` | Path to SSL certificate file | *(auto-generated)* |
| `--ssl-keyfile` | Path to SSL private key file | *(auto-generated)* |
| `--debug` | Enable DEBUG-level logging | `false` |
| `--console` | Run in console mode (terminal transcription, no server) | `false` |
| `--list-devices` | List available audio devices and exit (tkwindow) | `false` |
| `--user-speaker` | Capture system speaker output (tkwindow) | `false` |
| `--volume` | Input volume multiplier (tkwindow) | `1.0` |
| `--device` | Audio device index (tkwindow) | `None` |

## How It Works

```
Microphone → Audio capture (16kHz mono) → Engine (Vosk / Whisper) → Transcription text
```

- **Web mode**: Browser captures audio via Web Audio API (AudioWorklet), sends raw PCM to an aiohttp WebSocket server, which runs Vosk or Whisper and streams results back.
- **Terminal mode**: PyAudio captures audio directly, Vosk/Whisper processes it in-process, results print to stdout.
- **GUI mode**: Tkinter window with canvas rendering, device selector, and Start/Stop controls. Uses the same transcription engines as terminal mode.

Both modes use the same engine abstractions — fully offline, no API keys, no network calls (unless LLM post-processing is enabled).

## Architecture

### Engine Abstraction

Both transcription engines implement the `BaseEngine` interface (`src/base_engine.py`):

- `is_loaded`: Whether the model is ready
- `load()`: Load the model (blocking)
- `create_recognizer()`: Create/borrow a recognizer instance
- `return_recognizer()`: Return a recognizer to the pool
- `parse_final_result()`: Parse a final transcription result
- `parse_partial_result()`: Parse a partial transcription result
- `get_health_status()`: Return health status for `/health`

Both processors implement the `BaseProcessor` interface (`src/base_processor.py`):

- `chunk_count`: Number of chunks processed
- `process_chunk(data)`: Feed an audio chunk, return result dict or None
- `needs_reset(now)`: Check if reset is needed
- `get_stats()`: Return processor statistics

This design makes engines and processors plug-and-play interchangeable.

### Vosk Engine (`src/vosk_engine.py`)

- Loads the Vosk Kaldi model eagerly on startup
- **Recognizer pool**: Pre-creates 4 `KaldiRecognizer` instances to reduce per-session overhead
- `KaldiRecognizer.SetWords(True)` enabled for word-level timing
- Periodic reset every 45 seconds to prevent accuracy decay on long sessions

### Whisper Engine (`src/whisper_engine.py`)

- Uses faster-whisper (CTranslate2) for GPU-accelerated transcription
- **Silence-based triggering**: Audio accumulates while the user speaks, transcribed after 2 seconds of silence (sentence boundary)
- VAD (Voice Activity Detection) filtering with configurable parameters
- Language-specific initial prompts for better accuracy
- Max buffer of 30 seconds to prevent unbounded growth

### GPU Support (CUDA)

Whisper engine uses **faster-whisper** with CTranslate2 for GPU acceleration via CUDA. To enable GPU mode:

1. Install PyTorch with CUDA support matching your CUDA toolkit version:

```bash
# CUDA 12.8 (recommended)
pip install torch --index-url https://download.pytorch.org/whl/cu128

# CUDA 12.1
pip install torch --index-url https://download.pytorch.org/whl/cu121

# CUDA 11.8
pip install torch --index-url https://download.pytorch.org/whl/cu118
```

2. Run with `--whisper-device cuda`:

```bash
python start.py --engine whisper --whisper-device cuda
```

Without CUDA, Whisper runs on CPU (no extra dependencies needed).

### Audio Processing

- **AudioProcessor** (`src/audio_processor.py`): Processes audio chunks through Vosk recognizer with partial deduplication (last N words comparison)
- **WhisperProcessor** (`src/whisper_processor.py`): Wraps WhisperRecognizer for batched transcription with silence detection
- Both implement the `BaseProcessor` interface

### LLM Post-Processing (`src/llm_post_processor.py`)

Optional post-processing layer that sends transcribed text to an external LLM (OpenAI-compatible API) for punctuation, capitalization, and grammar correction.

- **Buffer accumulation**: `TranscriptionBuffer` (`src/transcription_buffer.py`) accumulates fragments and flushes on silence detection or buffer overflow
- **Resilient**: Falls back to raw text if LLM is unavailable or fails
- **Chat endpoint**: `/api/llm-chat` allows asking questions about the transcribed text
- Uses `tenacity` for automatic retry with exponential backoff
- Configurable via `--llm-url`, `--llm-key`, `--llm-model`, etc.

### Configuration (`src/config.py`)

Pydantic-based configuration models (`LLMConfig`, `ServerConfig`) with validation and IDE autocomplete.

### Server (`src/server.py` + `src/server_app.py`)

- aiohttp server on port 8765
- **Health endpoint** (`GET /health`): returns `{"status":"ready"}` (200) when model loaded, `{"status":"loading"}` (202) otherwise, includes `llm_enabled` flag
- **WebSocket endpoint** (`GET /ws`): receives raw audio, streams transcription back
  - Audio from browser: raw PCM s16le at 16kHz mono, sent via `ws.send()`
  - Server sends `{"type":"final","text":"..."}` and `{"type":"partial","text":"..."}` back
  - Ping/pong keepalive (client pings every 10s)
  - Periodic reset every 45 seconds
  - Server stays alive after disconnect — allows reconnection at any time
- **LLM chat endpoint** (`POST /api/llm-chat`): send user text, get LLM response
- **Static files**: serves `index.html`, `style.css`, `app.js` from `src/static/`
- **SSL support**: `--ssl` generates a self-signed certificate automatically

### Web UI (`src/static/`)

- **`index.html`**: Dark theme UI with toolbar (clear last line, clear all, ask question buttons)
- **`app.js`**: Audio capture via AudioWorklet, WebSocket client, LLM chat integration
- **`audio-processor.js`**: AudioWorklet processor — resamples from device sample rate to 16kHz, converts Float32 → Int16 PCM, emits 1024-sample chunks
- **`style.css`**: Dark theme with pulsing green status indicator

### Console Mode (`src/console.py`)

- Accessible via `python -m src.console`, `python src/server.py --console`, or `python start.py --console`
- Defaults to Vosk with `vosk-model-small-fr-0.22`
- Opens PyAudio stream at 16kHz mono, 4000 bytes per read
- Final results printed in **bold yellow** with ANSI escape codes
- Partial results overwrite the terminal line with `\r` (carriage return)
- Whisper mode: silence-based triggering with flush on Ctrl+C

### Tkinter GUI (`src/tkwindow/`)

OOP-refactored package providing a floating transcription window with device selector and Start/Stop controls.

- **Package structure**: `cli.py` (argparse, entry point), `window.py` (TkWindow orchestrator), `settings.py` (persistence), `devices/` (platform-specific enumeration), `audio/` (capture abstraction), `renderer/` (canvas rendering), `gui/` (widget construction)
- **Dual-canvas rendering**: Ping-pong architecture with committed (final) and active (partial) canvases for flicker-free display
- **Device management**: Linux uses `pactl` for PulseAudio/PipeWire sources; Windows uses PyAudio/PortAudio enumeration
- **Audio capture**: Linux captures via `parec` subprocess; Windows uses PyAudio stream
- **CanvasRenderer**: Manages pre-allocated text item pools, font configuration, and render logic
- **ItemPool**: Pre-allocates canvas text items for smooth in-place updates
- **Settings**: Persists device indices and window geometry in `~/.bavardage/settings.json`
- **Cross-platform**: Platform detection centralized in `devices/__init__.py` and `audio/__init__.py`

### Launcher (`start.py`)

- Cross-platform launcher (Windows/macOS/Linux)
- Finds Python executable (venv first, falls back to `sys.executable`)
- Starts `src/server.py` as subprocess, forwards all CLI args
- Waits for TCP connection on port 8765
- Displays both local LAN IP and `127.0.0.1` URLs
- Handles Ctrl+C/Ctrl+SIGTERM with cleanup (kills server process, waits up to 5s then forces kill)
- Special handling for `--help` and `--console` flags

### Session Management (`src/session_manager.py`)

Manages WebSocket session lifecycle: audio processing, partial deduplication, LLM buffer, and clean shutdown with remaining text flush.

## Project Structure

```
start.py              # Cross-platform launcher (server + browser + cleanup)
start.ps1             # Windows PowerShell launcher
src/
  server.py           # CLI entry point (Typer) + server orchestration
  server_app.py       # ServerApp: aiohttp app, routes, WebSocket handler
  console.py          # Console mode: terminal transcription using src modules
  session_manager.py  # WebSocket session management (dedup, buffer, LLM)
  config.py           # Pydantic configuration models (LLMConfig, ServerConfig)
  base_engine.py      # Abstract engine interface
  base_processor.py   # Abstract processor interface
  vosk_engine.py      # Vosk model/loading/pooling
  whisper_engine.py   # faster-whisper (CTranslate2) model/loading
  audio_processor.py  # Audio chunk processing (Vosk)
  whisper_processor.py# Audio chunk processing (Whisper)
  transcription_buffer.py  # Fragment accumulation & silence detection
  llm_post_processor.py    # LLM post-processing (optional)
  tkwindow/           # Tkinter GUI package (OOP refactored)
    __init__.py       # Public API: TkWindow, main
    __main__.py       # Entry point for python -m src.tkwindow
    cli.py            # CLI argument parsing, logging setup
    window.py         # TkWindow orchestrator class
    settings.py       # Settings persistence
    devices/          # Device enumeration (platform-specific)
      __init__.py     # Unified entry point
      linux.py        # pactl-based listing
      windows.py      # PyAudio-based listing
    audio/            # Audio capture abstraction
      __init__.py     # Factory: create_audio_capture()
      base.py         # Abstract base: BaseAudioCapture
      linux.py        # PulseAudio/PipeWire via parec
      windows.py      # PyAudio stream capture
      utils/
        amplify.py    # Volume amplification for PCM samples
    renderer/         # Canvas rendering logic
      __init__.py     # CanvasRenderer class
      pool.py         # Canvas text item pool pre-allocation
    gui/              # Tkinter GUI construction
      __init__.py     # build_window() assembly
      controls.py     # Top bar: buttons, status, quick-select
      canvases.py     # Dual-canvas layout, resize/mousewheel
  static/
    index.html        # Web UI
    app.js            # Audio capture + WebSocket client
    style.css         # Dark theme styles
    audio-processor.js# AudioWorklet resampling processor
pyproject.toml        # Python dependencies & project config
tests/                # Unit tests
vosk-model-small-fr-0.22/   # Vosk French model (~100MB, don't commit)
faster-whisper-models/      # Whisper models (optional)
.venv/                # Python virtual environment
```

## Commands

```bash
# Run web server (HTTP + WebSocket on port 8765)
python start.py

# Run with Whisper engine
python start.py --engine whisper --whisper-model small

# Run with LLM post-processing (requires external LLM server)
python start.py --llm-url http://192.168.1.100:8080 --llm-model llama3

# Run with LLM + API key
python start.py --llm-url http://192.168.1.100:8080 --llm-key my-secret-key

# Run with HTTPS (required for LAN microphone access)
python start.py --ssl

# Run with debug logging
python start.py --debug

# Run terminal transcription
python -m src.console
python -m src.console --engine whisper --whisper-model small

# Run GUI transcription window
python -m src.tkwindow --list-devices
python -m src.tkwindow --vosk-model /path/to/model --user-speaker --volume 3.0

# Run tests
python -m pytest tests/ -v

# Audit dependencies for CVE vulnerabilities
pip-audit
```

## Notes

- The model folders (`vosk-model-small-fr-0.22/`, `faster-whisper-models/`) are listed in `.gitignore` — clone the repo first, then download.
- **Server stays alive after disconnect** — after a client stops recording, the server remains running indefinitely, allowing reconnection. Server only stops when stopped with `Ctrl+C`.
- **Audio format** — browser sends raw PCM s16le (16 kHz, mono, little-endian). The AudioWorklet processor handles resampling from the device's native sample rate using linear interpolation.
- **Console mode** — partial results use `\r` to overwrite the terminal line; won't work in piped/redirected output.
- **Tkinter GUI** — requires `python3-tk` system package (`apt install python3-tk` on Debian/Ubuntu) and `ttkbootstrap` Python package. Uses the `darkly` theme for a modern flat UI.
- **LLM post-processing** is fully optional and non-blocking. If the LLM is unavailable or fails, raw transcription text is used as fallback.
- **No build command** — this is a script-based project.
- **GPU acceleration** is optional. Install the matching CUDA version of PyTorch before running Whisper in `cuda` mode.
