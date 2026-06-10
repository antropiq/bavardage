# LLM Post-Processing Layer — Migration Plan

## Objective

Add an optional LLM-powered post-processing layer that takes raw speech recognition output from Vosk or Whisper and improves it by:

1. **Fixing phrasing** — correct minor ASR errors, normalize grammar
2. **Adding punctuation** — insert commas, periods, question marks, capitalization
3. **Improving readability** — produce clean, professional French text

The LLM service is external (llama.cpp + llama-swap on a separate machine), accessed via OpenAI-compatible API.

---

## 1. Problem Statement

### Current behavior

```
User speaks: "bonjour comment allez vous je voudrais savoir"
Vosk outputs: "bonjour" → "comment allez vous" → "je voudrais savoir"
Textarea shows: "bonjourcomment allez vousje voudrais savoir"
```

Raw ASR output is unpunctuated, uncapitalized, and lacks proper word boundaries. The user sees fragmented text that requires manual editing.

### Desired behavior

```
User speaks: "bonjour comment allez vous je voudrais savoir"
Buffer accumulates: "bonjour comment allez vous je voudrais savoir"
LLM processes: "Bonjour, comment allez-vous ? Je voudrais savoir..."
Textarea shows: "Bonjour, comment allez-vous ? Je voudrais savoir..."
```

Clean, readable text appears automatically.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (app.js)                         │
│  Mic → WebAudio → WebSocket (raw PCM) → Server                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ WebSocket binary frames
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Server (src/server.py)                      │
│                                                                 │
│  WebSocket Handler                                             │
│       │                                                        │
│       ▼                                                        │
│  SessionManager                                                │
│       │                                                        │
│       ├──► TranscriptionBuffer (NEW)                           │
│       │       - Accumulates final texts                        │
│       │       - Detects silence gaps                           │
│       │       - Flushes on trigger                             │
│       │                                                        │
│       ├──► LLMPostProcessor (NEW)                              │
│       │       - Connects to external LLM API                   │
│       │       - Sends batch text                               │
│       │       - Receives polished text                         │
│       │       - Handles failures (fallback to raw)             │
│       │                                                        │
│       ├──► VoskEngine / WhisperEngine                          │
│       │       - Transcribes audio                              │
│       │       - Emits final texts to buffer                    │
│       │                                                        │
│       ▼                                                        │
│  WebSocketResponse ← {"type":"final","text":"..."}             │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              External LLM Service (llama-swap)                  │
│  URL: http://<llm-host>:<port>/v1/chat/completions             │
│  Compatible with OpenAI API format                              │
│  Model: Llama 3, Mistral, etc.                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key design principles

1. **LLM is optional** — if disabled or unavailable, transcription works normally (raw output)
2. **No blocking** — LLM calls are async; raw text is buffered while waiting
3. **Graceful degradation** — if LLM fails, raw text is used as fallback
4. **Zero browser changes** — the WebSocket protocol is unchanged; the server handles all post-processing
5. **Engine-agnostic** — works with both Vosk and Whisper

---

## 3. Component Design

### 3.1 TranscriptionBuffer

**File:** `src/transcription_buffer.py`

**Responsibility:** Accumulate raw transcription fragments and determine when to flush them to the LLM.

```python
class TranscriptionBuffer:
    """Accumulates transcription fragments and flushes on silence detection."""

    def __init__(
        self,
        max_buffer_size: int = 500,       # max characters before forced flush
        silence_threshold: float = 2.0,   # seconds of silence to trigger flush
        min_buffer_size: int = 20,        # min characters to avoid tiny flushes
    ):
        self._fragments: list[str] = []
        self._raw_text: str = ""
        self._last_flush_time: float = 0.0
        self._last_fragment_time: float = 0.0
        self._max_buffer_size = max_buffer_size
        self._silence_threshold = silence_threshold
        self._min_buffer_size = min_buffer_size

    def add_fragment(self, text: str, now: float) -> tuple[str, bool]:
        """Add a transcription fragment.

        Returns:
            (accumulated_text, should_flush):
            - accumulated_text: current buffer content
            - should_flush: True if buffer should be sent to LLM
        """
        self._fragments.append(text)
        self._raw_text = " ".join(self._fragments)
        self._last_fragment_time = now

        # Check flush conditions
        should_flush = False
        if len(self._raw_text) >= self._max_buffer_size:
            should_flush = True  # Forced flush: buffer too large
        elif (now - self._last_flush_time) >= self._silence_threshold:
            # Time since last flush exceeds silence threshold
            if len(self._raw_text) >= self._min_buffer_size:
                should_flush = True  # Silence detected, buffer has content

        return self._raw_text, should_flush

    def flush(self) -> str:
        """Clear buffer and return accumulated text."""
        text = self._raw_text
        self._fragments.clear()
        self._raw_text = ""
        self._last_flush_time = asyncio.get_event_loop().time()
        return text

    @property
    def raw_text(self) -> str:
        return self._raw_text

    @property
    def fragment_count(self) -> int:
        return len(self._fragments)
```

**Flush triggers:**

| Trigger | Condition | Rationale |
|---|---|---|
| **Silence detection** | No new fragment for 2s + buffer > 20 chars | User paused speaking |
| **Buffer overflow** | Buffer > 500 chars | Prevent unbounded memory growth |
| **Forced flush** | Explicit call (session close) | Clean up remaining text |

### 3.2 LLMPostProcessor

**File:** `src/llm_post_processor.py`

**Responsibility:** Send buffered text to the external LLM and return polished text.

```python
class LLMPostProcessor:
    """Post-processes transcribed text via an OpenAI-compatible LLM API."""

    def __init__(
        self,
        api_url: str,
        api_key: str | None = None,
        model: str = "llama3",
        system_prompt: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 1,
    ):
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt or self._default_system_prompt
        self._timeout = timeout
        self._max_retries = max_retries
        self._enabled = bool(api_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are a French text post-processor for speech recognition output. "
            "Your task is to: "
            "1. Add proper punctuation (commas, periods, question marks, exclamation marks) "
            "2. Capitalize correctly "
            "3. Fix minor ASR errors (wrong words, missing spaces) "
            "4. Preserve the original meaning and tone "
            "5. Output ONLY the corrected French text, nothing else "
            "Do not add greetings, explanations, or any text beyond the corrected transcription."
        )

    async def process(self, raw_text: str) -> str:
        """Send raw text to LLM and return polished text.

        On failure, returns the original raw_text (fallback).
        """
        if not self._enabled or not raw_text.strip():
            return raw_text

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._call_llm(raw_text)
                polished = self._extract_text(response)
                return polished if polished else raw_text
            except Exception as e:
                log.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, self._max_retries + 1, e)
                if attempt == self._max_retries:
                    return raw_text  # Fallback to raw text
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff

    async def _call_llm(self, raw_text: str) -> dict:
        """Call the OpenAI-compatible API."""
        import aiohttp

        url = f"{self._api_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": raw_text},
            ],
            "max_tokens": 1024,
            "temperature": 0.0,  # Deterministic output
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=self._timeout)) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text from LLM API response."""
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return ""
```

**Key design decisions:**

| Decision | Rationale |
|---|---|
| **OpenAI-compatible API** | Works with llama-swap, Ollama, vLLM, any OpenAI-compatible server |
| **`temperature=0.0`** | Deterministic output — same input always produces same output |
| **5s timeout** | Prevents hanging if LLM is slow; raw text is used as fallback |
| **1 retry with backoff** | Handles transient network errors |
| **Fallback to raw text** | If LLM fails, user still gets transcription (just unpolished) |
| **No streaming** | Simpler implementation; latency is acceptable for post-processing |

### 3.3 Integration with SessionManager

**File:** `src/session_manager.py` (modified)

```python
class SessionManager:
    """Manages a single WebSocket session with optional LLM post-processing."""

    def __init__(
        self,
        engine: BaseEngine,
        reset_interval: float = 45.0,
        partial_word_history: int = 5,
        llm_processor: LLMPostProcessor | None = None,
        buffer_config: dict | None = None,
    ):
        self._engine = engine
        self._llm_processor = llm_processor
        self._buffer = TranscriptionBuffer(**(buffer_config or {}))
        # ... existing initialization ...

    async def handle_message(self, msg, ws, now: float) -> None:
        """Process a single WebSocket message."""
        # ... existing message handling (ping, audio) ...

        # Process audio chunk
        result = self._processor.process_chunk(data)
        if result and result["type"] == "final":
            # Add fragment to buffer
            raw_text, should_flush = self._buffer.add_fragment(result["text"], now)

            if should_flush:
                # Flush buffer to LLM for post-processing
                buffered_text = self._buffer.flush()
                polished_text = await self._llm_processor.process(buffered_text) if self._llm_processor else buffered_text
                await ws.send_json({"type": "final", "text": polished_text})
            else:
                # Show raw fragment immediately (user sees progress)
                await ws.send_json({"type": "final", "text": result["text"]})

        # ... existing partial handling ...
```

**Behavior:**

| Scenario | What the user sees |
|---|---|
| **LLM disabled** | Raw Vosk/Whisper output (unchanged behavior) |
| **LLM enabled, fast response** | Raw fragment appears → polished text replaces it (subtle update) |
| **LLM enabled, slow response** | Raw fragment appears → polished text appears after LLM responds |
| **LLM fails** | Raw fragment appears (fallback, no polished text) |

### 3.4 ServerApp Integration

**File:** `src/server_app.py` (modified)

```python
class ServerApp:
    def __init__(
        self,
        engine: BaseEngine | None = None,
        llm_processor: LLMPostProcessor | None = None,
        buffer_config: dict | None = None,
    ):
        self._engine = engine or VoskEngine()
        self._llm_processor = llm_processor
        self._buffer_config = buffer_config or {}
        # ...

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "ServerApp":
        # ... existing engine creation ...

        llm_processor = None
        if args.llm_url:
            llm_processor = LLMPostProcessor(
                api_url=args.llm_url,
                api_key=args.llm_key,
                model=args.llm_model,
                timeout=args.llm_timeout,
            )

        return cls(
            engine=engine,
            llm_processor=llm_processor,
            buffer_config={
                "max_buffer_size": args.llm_buffer_max,
                "silence_threshold": args.llm_silence_threshold,
                "min_buffer_size": args.llm_buffer_min,
            },
        )
```

### 3.5 CLI Arguments

**File:** `src/server.py` (modified)

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Speech transcription server")

    # Existing arguments
    parser.add_argument("--engine", choices=["vosk", "whisper"], default="vosk")
    parser.add_argument("--whisper-model", choices=["tiny", "base", "small", "medium"],
                        default="medium")

    # New LLM arguments
    parser.add_argument("--llm-url", default=None,
                        help="LLM API URL (e.g., http://192.168.1.100:8080). "
                             "If not set, LLM post-processing is disabled.")
    parser.add_argument("--llm-key", default=None,
                        help="LLM API key (if required by the server)")
    parser.add_argument("--llm-model", default="llama3",
                        help="LLM model name (default: llama3)")
    parser.add_argument("--llm-timeout", type=float, default=5.0,
                        help="LLM API timeout in seconds (default: 5.0)")
    parser.add_argument("--llm-buffer-max", type=int, default=500,
                        help="Max buffer size in characters before forced flush (default: 500)")
    parser.add_argument("--llm-silence-threshold", type=float, default=2.0,
                        help="Silence threshold in seconds to trigger flush (default: 2.0)")
    parser.add_argument("--llm-buffer-min", type=int, default=20,
                        help="Min buffer size in characters to avoid tiny flushes (default: 20)")

    args = parser.parse_args()
    app = ServerApp.from_args(args)
    app.run()
```

---

## 4. Usage Examples

### 4.1 Vosk only (default, unchanged)

```bash
python start.py
```

### 4.2 Vosk + LLM post-processing

```bash
python start.py --llm-url http://192.168.1.100:8080 --llm-model llama3
```

### 4.3 Vosk + LLM with API key

```bash
python start.py --llm-url http://192.168.1.100:8080 --llm-key my-secret-key --llm-model mistral
```

### 4.4 Whisper medium + LLM

```bash
python start.py --engine whisper --whisper-model medium --llm-url http://192.168.1.100:8080
```

### 4.5 Tuned buffer settings

```bash
python start.py --llm-url http://192.168.1.100:8080 \
    --llm-buffer-max 300 \
    --llm-silence-threshold 1.5 \
    --llm-buffer-min 10
```

---

## 5. Configuration Reference

| Flag | Default | Description |
|---|---|---|
| `--engine` | `vosk` | Transcription engine |
| `--whisper-model` | `medium` | Whisper model size |
| `--llm-url` | `None` | LLM API URL (if not set, LLM is disabled) |
| `--llm-key` | `None` | LLM API key |
| `--llm-model` | `llama3` | LLM model name |
| `--llm-timeout` | `5.0` | LLM API timeout (seconds) |
| `--llm-buffer-max` | `500` | Max buffer size (characters) |
| `--llm-silence-threshold` | `2.0` | Silence threshold (seconds) |
| `--llm-buffer-min` | `20` | Min buffer size (characters) |

---

## 6. File Change Summary

| Action | File | Description |
|---|---|---|
| **New** | `src/transcription_buffer.py` | TranscriptionBuffer class |
| **New** | `src/llm_post_processor.py` | LLMPostProcessor class |
| **Modify** | `src/session_manager.py` | Integrate buffer + LLM processor |
| **Modify** | `src/server_app.py` | Add LLM configuration, `from_args()` |
| **Modify** | `src/server.py` | Add CLI arguments |
| **Modify** | `start.py` | Forward CLI args to server |
| **Unchanged** | `src/static/app.js` | No browser changes needed |
| **Unchanged** | `src/static/index.html` | No HTML changes needed |
| **Unchanged** | `src/static/style.css` | No CSS changes needed |
| **Unchanged** | `src/engines/*` | Engine layer unchanged |

---

## 7. Testing Checklist

### 7.1 Unit tests

- [ ] `TranscriptionBuffer.add_fragment()` accumulates text correctly
- [ ] `TranscriptionBuffer.add_fragment()` triggers flush on silence
- [ ] `TranscriptionBuffer.add_fragment()` triggers flush on buffer overflow
- [ ] `LLMPostProcessor.process()` calls API and returns polished text
- [ ] `LLMPostProcessor.process()` returns raw text on API failure
- [ ] `LLMPostProcessor.process()` returns raw text when disabled

### 7.2 Integration tests

- [ ] Server starts with `--llm-url http://...` and logs "LLM enabled"
- [ ] Server starts without `--llm-url` and logs "LLM disabled"
- [ ] WebSocket session with LLM enabled: raw fragment → polished text
- [ ] WebSocket session with LLM disabled: raw fragment only (unchanged)
- [ ] LLM timeout: raw fragment shown, no crash
- [ ] LLM server down: raw fragment shown, no crash
- [ ] Buffer overflow: forced flush occurs, polished text shown
- [ ] Session close: remaining buffer flushed and sent

### 7.3 Accuracy tests

Run side-by-side tests with known French audio:

| Test | Raw Vosk | Vosk + LLM |
|---|---|---|
| Clear speech | Baseline | Should be better |
| Speech without punctuation | "bonjour comment allez" | "Bonjour, comment allez-vous ?" |
| Fast speech | Fragmented | Should be more coherent |
| Technical vocabulary | May miss terms | May correct or preserve |

### 7.4 Performance tests

| Metric | Target |
|---|---|
| LLM latency (local network) | < 1s |
| LLM latency (WAN) | < 3s |
| Memory increase (LLM enabled) | < 50MB |
| No LLM impact on transcription | 0% (disabled = no overhead) |

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **LLM server unreachable** | High | Fallback to raw text; log warning |
| **LLM API slow (>5s timeout)** | Medium | Configurable timeout; raw text shown while waiting |
| **LLM introduces errors** | Medium | `temperature=0.0` for deterministic output; system prompt tuned for French |
| **Network latency (WAN)** | Medium | Buffer settings tuned for latency; consider increasing `silence_threshold` |
| **LLM cost (if using paid API)** | Low | Not applicable for local llama-swap; documented for OpenAI users |
| **Buffer grows unbounded** | Low | `max_buffer_size` forces flush; session close flushes remaining |
| **Concurrent sessions overwhelm LLM** | Medium | LLM calls are async; queue requests if needed (future enhancement) |

---

## 9. Future Enhancements (Out of Scope)

These are not part of this migration but could be added later:

1. **Streaming LLM output** — Show polished text character-by-character as LLM generates it
2. **LLM context window** — Maintain conversation history across sessions for better coherence
3. **Multiple languages** — Auto-detect language or let user specify
4. **Custom system prompts** — Allow users to customize LLM behavior via config
5. **LLM health endpoint** — Check LLM availability before starting transcription
6. **Rate limiting** — Queue LLM requests to prevent overwhelming the LLM server
7. **Batch multiple sessions** — Share a single LLM call across multiple sessions for efficiency
8. **Whisper + LLM** — Whisper outputs are already more accurate; LLM post-processing may be less impactful

---

## 10. Estimated Effort

| Phase | Effort | Complexity |
|---|---|---|
| 1. TranscriptionBuffer | 2 hours | Low |
| 2. LLMPostProcessor | 3 hours | Medium |
| 3. SessionManager integration | 2 hours | Medium |
| 4. ServerApp + CLI args | 1 hour | Low |
| 5. Testing | 2-3 hours | Medium |
| **Total** | **~10-11 hours** | |

---

## Appendix A: Example LLM API Request/Response

### Request

```json
POST http://192.168.1.100:8080/v1/chat/completions
Content-Type: application/json
Authorization: Bearer my-secret-key

{
  "model": "llama3",
  "messages": [
    {
      "role": "system",
      "content": "You are a French text post-processor for speech recognition output..."
    },
    {
      "role": "user",
      "content": "bonjour comment allez vous je voudrais savoir"
    }
  ],
  "max_tokens": 1024,
  "temperature": 0.0
}
```

### Response

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Bonjour, comment allez-vous ? Je voudrais savoir..."
      }
    }
  ]
}
```

---

## Appendix B: llama-swap Configuration

Example `docker-compose.yml` for the LLM service:

```yaml
version: "3.8"
services:
  llama-swap:
    image: ghcr.io/techkim/llama-swap:latest
    ports:
      - "8080:8080"
    volumes:
      - ./models:/models
    environment:
      - DEFAULT_MODEL=llama3
      - MODEL_DIR=/models
    command: >
      --model /models/llama3.gguf
      --host 0.0.0.0
      --port 8080
```

The service exposes an OpenAI-compatible API at `http://<host>:8080/v1/chat/completions`.

---

## Appendix C: System Prompt Tuning

The default system prompt is:

```
You are a French text post-processor for speech recognition output. Your task is to:
1. Add proper punctuation (commas, periods, question marks, exclamation marks)
2. Capitalize correctly
3. Fix minor ASR errors (wrong words, missing spaces)
4. Preserve the original meaning and tone
5. Output ONLY the corrected French text, nothing else
Do not add greetings, explanations, or any text beyond the corrected transcription.
```

This prompt can be customized via `--llm-system-prompt` in future versions.
