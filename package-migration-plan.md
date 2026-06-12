# Package Migration Plan

## Overview

This document outlines packages that can simplify the realtime-speech codebase, ordered by impact/effort ratio.

---
## 4. `aiohttp.static` — Simplify static file serving

**File**: `src/server_app.py` (lines 123–126)

**Problem**: Manual route registration for each static file with dedicated handler methods.

```python
# Before: 4 manual routes + 4 handler methods
self._app.router.add_get("/", self._index_handler)
self._app.router.add_get("/style.css", self._css_handler)
self._app.router.add_get("/app.js", self._js_handler)
self._app.router.add_get("/audio-processor.js", self._js_handler)

async def _index_handler(self, request): ...
async def _css_handler(self, request): ...
async def _js_handler(self, request): ...

# After: single static route
STATIC_DIR = Path(__file__).parent / "static"

def build_app(self):
    self._engine.load()
    self._app = web.Application()
    self._app.router.add_static('/static/', str(STATIC_DIR), name='static')
    self._app.router.add_get("/", self._index_handler)
    self._app.router.add_get("/health", self._health_handler)
    self._app.router.add_post("/api/llm-chat", self._llm_chat_handler)
    self._app.router.add_get("/ws", self._websocket_handler)
    return self._app
```

Note: This requires updating `index.html` to reference `/static/style.css`, `/static/app.js`, etc., or using an index route that falls back to `static/`.

**Impact**: -4 routes, -3 handler methods, automatic `Content-Type` detection, caching headers.

---

## 5. `loguru` — Replace `logging`

**File**: All Python files (`*.py`)

**Problem**: Manual `logging.basicConfig()` setup, verbose `logging.getLogger(__name__)` in every file.

```python
# Before:
import logging
log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)

# After:
from loguru import logger
logger.add(sys.stderr, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
```

**Impact**: One-line setup, colored output in terminals, automatic file rotation, structured logging support.

---

## 6. `pydantic` — Structured configuration

**Files**: `src/server.py`, `src/server_app.py`, `src/llm_post_processor.py`

**Problem**: Configuration passed as scattered CLI args and raw dicts — no validation, no IDE autocomplete.

```python
# Before:
def __init__(self, api_url: str, api_key: str | None = None, model: str = "llama3", ...):
    self._api_url = api_url.rstrip("/")
    ...

# After:
from pydantic import BaseModel, HttpUrl, Field

class LLMConfig(BaseModel):
    api_url: HttpUrl
    api_key: str | None = None
    model: str = "llama3"
    timeout: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=1, ge=0)
    system_prompt: str | None = None

class ServerConfig(BaseModel):
    engine: str = Field(default="vosk", pattern="^(vosk|whisper)$")
    whisper_model: str = "small"
    whisper_language: str = "fr"
    whisper_device: str = "auto"
    llm: LLMConfig | None = None
    ssl: bool = False
    debug: bool = False

# Usage:
config = ServerConfig(**vars(args))
app = ServerApp.from_config(config)
```

**Impact**: Validated config, IDE autocomplete, automatic CLI integration via `pydantic-settings`.

---

## Summary

| # | Package | Impact | Effort | Files Changed |
|---|---------|--------|--------|---------------|
| 4 | `aiohttp.static` | Low | Low | `src/server_app.py`, `index.html` |
| 5 | `loguru` | Low | Low | All `*.py` |
| 6 | `pydantic` | Medium | Medium | `src/server.py`, `src/server_app.py`, `src/llm_post_processor.py` |

## Recommended Order

4. **`openai` SDK** — cleaner LLM integration (only if LLM feature is actively used)
5. **`loguru`** — cosmetic improvement, optional
6. **`aiohttp.static`** — only if static file count grows

## Dependencies to Add

```txt
# requirements.txt additions
pydantic>=2.0.0
loguru>=0.7.0
```
