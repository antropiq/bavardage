"""VoskEngine: manages model loading, recognizer creation, and state resets."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path

from vosk import KaldiRecognizer, Model

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = PROJECT_ROOT / "vosk-model-fr-0.22"

# Number of pre-created recognizers in the pool
POOL_SIZE = 4


class RecognizerPool:
    """Pre-creates a pool of KaldiRecognizer instances to reduce per-session overhead.

    Vosk's KaldiRecognizer construction involves model lookup and internal state
    initialization. By pre-creating recognizers, subsequent sessions skip this
    cost. Recognizers are borrowed and returned via async lock for thread safety.
    """

    def __init__(self, model: Model, sample_rate: int = 16000) -> None:
        self._sample_rate = sample_rate
        self._pool: deque[KaldiRecognizer] = deque()
        self._lock = asyncio.Lock()

        for i in range(POOL_SIZE):
            rec = KaldiRecognizer(model, sample_rate)
            rec.SetWords(True)
            self._pool.append(rec)
        log.info("Recognizer pool initialized with %d recognizers", POOL_SIZE)

    async def borrow(self) -> KaldiRecognizer:
        """Borrow a recognizer from the pool. Creates one on-demand if pool is empty."""
        async with self._lock:
            if self._pool:
                return self._pool.popleft()
        # Pool exhausted — create on-demand (fallback)
        log.debug("Pool exhausted, creating recognizer on-demand")
        rec = KaldiRecognizer(self._pool[0]._model if self._pool else Model(str(MODEL_PATH)), self._sample_rate)
        rec.SetWords(True)
        return rec

    async def return_recognizer(self, recognizer: KaldiRecognizer) -> None:
        """Return a recognizer to the pool for reuse."""
        async with self._lock:
            if recognizer:
                recognizer.Reset()
                self._pool.append(recognizer)

    @property
    def available(self) -> int:
        """Number of recognizers currently in the pool."""
        return len(self._pool)


class VoskEngine:
    """Encapsulates the Vosk ML library: model loading and recognizer lifecycle."""

    def __init__(self, model_path: Path | None = None, pool_size: int = POOL_SIZE) -> None:
        self._model: Model | None = None
        self._model_path = model_path or MODEL_PATH
        self._loaded = False
        self._pool: RecognizerPool | None = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the Vosk model eagerly. Blocks until ready."""
        if self._loaded:
            return
        if not self._model_path.is_dir():
            log.error("Vosk model not found at %s", self._model_path)
            raise FileNotFoundError(f"Vosk model not found at {self._model_path}")
        log.info("Loading Vosk model from %s (this may take a moment)...", self._model_path)
        self._model = Model(str(self._model_path))
        self._loaded = True
        self._pool = RecognizerPool(self._model)
        log.info("Vosk model loaded.")

    async def create_recognizer(self) -> KaldiRecognizer:
        """Create or borrow a KaldiRecognizer from the pool at 16kHz with word timing."""
        if not self._loaded or self._model is None:
            self.load()
        if self._pool:
            return await self._pool.borrow()
        # Fallback: create directly (no pool available)
        recognizer = KaldiRecognizer(self._model, 16000)
        recognizer.SetWords(True)
        return recognizer

    async def return_recognizer(self, recognizer: KaldiRecognizer) -> None:
        """Return a recognizer to the pool for reuse."""
        if self._pool:
            await self._pool.return_recognizer(recognizer)

    def parse_final_result(self, result_str: str) -> dict | None:
        """Parse and validate a FinalResult JSON string."""
        try:
            result = json.loads(result_str)
        except json.JSONDecodeError:
            log.warning("Bad FinalResult JSON: %r", result_str[:200])
            return None
        text = result.get("text", "").strip()
        if not text:
            return None
        return result

    def parse_partial_result(self, partial_str: str) -> dict | None:
        """Parse and validate a PartialResult JSON string."""
        try:
            partial = json.loads(partial_str)
        except json.JSONDecodeError:
            return None
        return partial

    def get_health_status(self) -> dict:
        """Return health status for the /health endpoint."""
        if self._loaded:
            return {"status": "ready"}
        return {"status": "loading"}
