# Bavardage — Offline French Speech-to-Text

Real-time French voice transcription running **100% offline** using [Vosk Kaldi](https://alphacephei.com/vosk/models) and [faster-whisper (CTranslate2)](https://huggingface.co/Systran). No internet connection required.

## Quick Start

### 1. Prerequisites

- Python 3.10+
- A working microphone
- **Linux users**: Install system dependencies: `sudo apt install python3-tk` (or equivalent)
- **Audio system**: Requires PipeWire/PulseAudio (`parec` + `pactl`) on target systems.

### 2. Install

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# For GPU-accelerated Whisper support (CUDA 12.8)
pip install -e ".[dev,cuda]"
```

### 3. Download the Models

**Vosk model** (required for Vosk engine):

1. Go to https://alphacephei.com/vosk/models
2. Download **vosk-model-small-fr-0.22** (~100 MB, recommended for speed)
3. Extract the folder so the path is: `vosk-model-small-fr-0.22/`

**Whisper models** (required for Whisper engine):

- Models are downloaded automatically from HuggingFace on first use (e.g., `Systran/faster-whisper-small`)
- Or download manually and provide a local path via `--whisper-model`

```text
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

### Audio Processing
- **AudioProcessor** (`src/audio_processor.py`): Processes audio chunks through Vosk recognizer with partial deduplication (last N words comparison)
- **WhisperProcessor** (`src/whisper_processor.py`): Wraps WhisperRecognizer for batched transcription with silence detection
- Both implement the `BaseProcessor` interface

### LLM Post-Processing (`src/llm_post_processor.py`)
Optional post-processing layer that sends transcribed text to an external LLM (OpenAI-compatible API) for punctuation, capitalization, and grammar correction.
- **Buffer accumulation**: `TranscriptionBuffer` (`src/transcription_buffer.py`) accumulates fragments and flushes on silence detection or buffer overflow
- **Resilient**: Falls back to raw text if LLM is unavailable or fails

## Operational Gotchas

- **Naming Restrictions**: Never name a script `vosk.py` — it shadows the `vosk` package and causes a circular import.
- **Vosk Model**: Path must be correctly set to the extracted model folder.
- **Stdout Flushing**: `src/console.py` calls `sys.stdout.flush()` explicitly because real-time output depends on it.
- **Terminal Results**: `src/console.py` partial results use `\r` to overwrite the terminal line.
- **Blocking Init**: Microphone initialization in `src/console.py` blocks until the mic is ready.
- **No Build Command**: This is a script-based project; use `pip install -e ".[dev]"` for installation.
- **Tkinter Requirements**: `src/tkwindow/` requires `python3-tk` and `ttkbootstrap`.
- **Audio Format**: Browser sends raw PCM s16le (little-endian signed 16-bit) at 16kHz mono. The client does linear interpolation resampling.
- **Persistence**: The server stays alive after a client disconnects, allowing reconnection.

## GPU Support (CUDA)

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

## Build & Distribution

### Standalone Linux Binary
You can build a standalone Linux binary using PyInstaller.

```bash
pip install PyInstaller
python scripts/build_tkwindow.py
```

**Distribution notes:**
- **Dependencies**: Requires `python3-tk` system package and PipeWire/PulseAudio (`parec` + `pactl`) on target systems.
- **Bundling**: The binary bundles `libvosk.so` and all Python dependencies (NO model).
- **User Requirement**: User **MUST** provide the model via `--vosk-model` at runtime.
- **Output**: `dist/vosk-tkwindow`, `dist/bavardage.png`, `dist/vosk-tkwindow.desktop` (~58 MB ELF).

## Testing

```bash
# Run all tests together
.venv/Scripts/python.exe -m pytest tests/ -v

# Audit dependencies for CVE vulnerabilities
.venv/Scripts/python.exe pip-audit
```
