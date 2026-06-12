# Realtime Speech Transcription

French speech-to-text project supporting **Vosk Kaldi** and **Whisper** engines (fully offline).

## Structure

```
start.py         # Cross-platform launcher (server + browser + cleanup)
start.ps1        # Windows PowerShell launcher
src/
  server.py      # aiohttp server (HTTP + WebSocket) + --console entry point
  console.py     # Console mode: terminal transcription using src modules
  server_app.py  # ServerApp orchestration
  session_manager.py     # WebSocket session management
  base_engine.py # Abstract engine interface
  base_processor.py      # Abstract processor interface
  vosk_engine.py         # Vosk model/loading/pooling
  whisper_engine.py      # faster-whisper (CTranslate2) model/loading
  audio_processor.py     # Audio chunk processing (Vosk)
  whisper_processor.py   # Audio chunk processing (Whisper)
  transcription_buffer.py  # Fragment accumulation & silence detection
  llm_post_processor.py    # LLM post-processing (optional)
  static/
    index.html   # Web UI
    app.js       # Audio capture + WebSocket client
    style.css    # Dark theme styles
    audio-processor.js  # Web Audio API utilities
  pyproject.toml        # Python dependencies & project config
vosk-model-small-fr-0.22/   # Vosk French model (~100MB, don't commit)
.venv/           # Python virtual environment
tests/           # Unit tests
  test_transcription_buffer.py
  test_llm_post_processor.py
  test_session_manager.py
llm-migration-layer.md       # LLM post-processing migration spec
llm-migration-layer-todo-list.md  # Implementation tracking
```

## Commands

```bash
# Activate environment
.venv/Scripts/activate

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# Or with CUDA support for GPU-accelerated Whisper
pip install -e ".[dev,cuda]"

# Run terminal transcription (direct mic → Vosk, no browser needed)
python -m src.console

# Run terminal transcription with custom Vosk model
python -m src.console --vosk-model /path/to/vosk-model

# Run terminal transcription with Whisper
python -m src.console --engine whisper --whisper-model small

# Run terminal transcription via start.py
python start.py --console

# Run terminal transcription via server.py
python src/server.py --console --engine whisper

# Run web server (HTTP + WebSocket on port 8765, opens browser, auto-closes)
python start.py

# Run with custom Vosk model
python start.py --vosk-model /path/to/vosk-model

# Run with Whisper engine
python start.py --engine whisper --whisper-model path/to/ggml-base.bin

# Run with LLM post-processing (requires external LLM server)
python start.py --llm-url http://192.168.1.100:8080 --llm-model llama3

# Run with LLM + custom buffer settings
python start.py --llm-url http://192.168.1.100:8080 \
    --llm-buffer-max 300 \
    --llm-silence-threshold 1.5 \
    --llm-buffer-min 10

# Run with LLM + API key
python start.py --llm-url http://192.168.1.100:8080 --llm-key my-secret-key

# Run with HTTPS (required for LAN microphone access)
python start.py --ssl

# Run with debug logging
python start.py --debug

# Run server directly with CLI args
PYTHONPATH=. .venv/Scripts/python.exe src/server.py --llm-url http://192.168.1.100:8080

# Run unit tests
.venv/Scripts/python.exe tests/test_transcription_buffer.py
.venv/Scripts/python.exe tests/test_llm_post_processor.py
.venv/Scripts/python.exe tests/test_session_manager.py

# Or run all tests together
.venv/Scripts/python.exe -m pytest tests/ -v

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

# Unit tests for AudioProcessor
.venv/Scripts/python.exe tests/test_audio_processor.py

# Unit tests for SessionManager
.venv/Scripts/python.exe tests/test_session_manager.py

# Run all tests together
.venv/Scripts/python.exe -m pytest tests/ -v

# Audit dependencies for CVE vulnerabilities
.venv/Scripts/python.exe pip-audit
```

## Architecture

All transcription uses **Vosk Kaldi** or **faster-whisper (CTranslate2)** — fully offline, no network required.

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

### Console mode (`src/console.py`)

- Accessible via `python -m src.console`, `python src/server.py --console`, or `python start.py --console`
- Defaults to Vosk with `vosk-model-small-fr-0.22`
- Opens PyAudio stream at 16kHz mono, 4000 bytes per read
- Uses existing `src/` modules: `VoskEngine`/`WhisperEngine` + `AudioProcessor`/`WhisperProcessor`
- With Vosk: `KaldiRecognizer.AcceptWaveform()` → `FinalResult()` for completed sentences, `PartialResult()` for live text
- With Whisper: uses `WhisperRecognizer` with silence-based triggering
- Final results printed in **bold yellow** with ANSI escape codes
- Partial results overwrite the terminal line with `\r` (carriage return)
- Exits on `Ctrl+C`

### Web mode (`src/server.py` + `start.py`)

- **`src/server.py`** — aiohttp server on port 8765
  - Engine selected via `--engine` flag (`vosk` or `whisper`)
  - Vosk model path via `--vosk-model` flag (default: `vosk-model-small-fr-0.22`)
  - With Vosk: loads model eagerly on startup (blocks until ready)
  - With Whisper: loads faster-whisper model eagerly on startup (blocks until ready)
  - **Health endpoint** (`GET /health`): returns `{"status":"ready"}` (200) when model loaded, `{"status":"loading"}` (202) otherwise
  - **WebSocket endpoint** (`GET /ws`): receives raw audio, streams transcription back
    - Audio from browser: raw PCM s16le at 16kHz mono, sent via `ws.send()`
    - Server sends `{"type":"final","text":"..."}` and `{"type":"partial","text":"..."}` back
    - Vosk: `KaldiRecognizer.SetWords(True)` enabled for word-level timing
    - Whisper: accumulates audio chunks, transcribes when ≥1s available (faster-whisper CTranslate2)
    - Ping/pong keepalive (client pings every 10s)
    - **Periodic reset** (`RESET_INTERVAL = 45`): resets engine internal state every 45 s to prevent accuracy decay on long sessions. Overlap chunking is disabled by default because Vosk's internal VAD gets confused by repeated audio frames.
    - **Client counter**: server stays alive after client disconnects, allowing reconnection at any time. No auto-shutdown — server runs until stopped with Ctrl+C.
    - **LLM post-processing** (optional): when `--llm-url` is set, final transcription fragments are accumulated in a `TranscriptionBuffer` and flushed to an external LLM API for punctuation, capitalization, and grammar correction. The LLM is accessed via OpenAI-compatible API (works with llama-swap, Ollama, vLLM). If LLM fails, raw text is used as fallback. See `llm-migration-layer.md` for full spec.
  - **Static files**: serves `index.html`, `style.css`, `app.js` from `src/static/`
  - Routes: `/`, `/style.css`, `/app.js`, `/health`, `/ws`

- **`src/static/app.js`** — browser client
  - Polls `/health` every 500ms until model is ready
  - Uses Web Audio API: `AudioContext` → `MediaStream` (mic, mono, echo cancellation, noise suppression) → `createScriptProcessor(2048)`
  - **Sample rate conversion**: downsamples from device sample rate to 16kHz via linear interpolation
  - Sends raw PCM s16le buffer via WebSocket binary frames (~128 ms chunks)
  - Client-side partial deduplication to prevent UI flicker from server overlap duplicates
  - UI: dark theme, toolbar with status indicator (pulses green while listening), large textarea for final text, italic gray for partial text

- **`start.py`** — cross-platform launcher
  - Finds Python executable (venv first, falls back to `sys.executable`)
  - Starts `src/server.py` as subprocess, **forwards all CLI args** (`sys.argv[1:]`)
  - Waits for TCP connection on port 8765
  - Displays the URL `http://127.0.0.1:8765` in the console
  - Handles Ctrl+C/Ctrl+SIGTERM with cleanup (kills server process, waits up to 5s then forces kill)

- **`start.ps1`** — Windows PowerShell launcher (same behavior, PowerShell-native)

## Gotchas

- **Never name a script `vosk.py`** — it shadows the `vosk` package and causes a circular import (`ImportError: cannot import name 'Model' from partially initialized module 'vosk'`). This is why the original `vosk.py` was renamed to `main_vosk.py` and later moved to `src/console.py`.
- **Vosk model**: `vosk-model-small-fr-0.22/` is ~100MB. Listed in `.gitignore`. Download from https://alphacephei.com/vosk/models (README.txt has the link). Custom path via `--vosk-model`.
- **stdout flushing is critical** — `src/console.py` calls `sys.stdout.flush()` explicitly because real-time output depends on it. Don't remove.
- **`src/console.py` partial results use `\r`** — overwrites the terminal line with carriage return. This won't work in piped/redirected output.
- **Microphone init blocks** — `src/console.py` opens the PyAudio stream at startup, which blocks until the mic is ready.
- **No build command** — this is a script-based project. Install with `pip install -e ".[dev]"`.
- **CUDA support** — install `torch` with CUDA 12.8 via `pip install -e ".[dev,cuda]"` for GPU-accelerated Whisper mode (`--whisper-device cuda`).
- **Audio format** — browser sends raw PCM s16le (little-endian signed 16-bit) at 16kHz mono. The client does linear interpolation resampling from the device's native sample rate.
- **Server stays alive after disconnect** — after a client stops recording, the server remains running indefinitely, allowing reconnection. Server only stops when stopped with Ctrl+C.
- **Whisper engine** — uses faster-whisper (CTranslate2), automatically downloads models from HuggingFace on first use or accepts local paths. Key flags:
  - `--engine whisper`: Select Whisper engine
  - `--whisper-model`: Model size (`tiny`, `base`, `small`, `medium`, `large`) or local path (default: `tiny`)
  - `--whisper-language`: Language code (default: `fr`)
  - Models from HuggingFace: `Systran/faster-whisper-tiny`, etc.
- **LLM post-processing** — when enabled via `--llm-url`, the server buffers transcription fragments and sends them to an external LLM for post-processing. The LLM is optional and non-blocking; if unavailable, raw transcription is used. Key flags:
  - `--llm-url`: LLM API URL (e.g., `http://192.168.1.100:8080`)
  - `--llm-key`: API key (if required)
  - `--llm-model`: Model name (default: `llama3`)
  - `--llm-timeout`: API timeout in seconds (default: 5.0)
  - `--llm-buffer-max`: Max buffer size in chars before forced flush (default: 500)
  - `--llm-silence-threshold`: Seconds of silence to trigger flush (default: 2.0)
  - `--llm-buffer-min`: Min buffer size to avoid tiny flushes (default: 20)
