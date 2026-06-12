# TODO — Realtime Speech Transcription Enhancements

## 🎯 Accuracy Enhancements

| # | Enhancement | Why | DONE |
|---|---|---|---|
| 1 | **Client-side Voice Activity Detection (VAD)** | Vosk processes silence as speech, causing hallucinated words. Only sending audio during actual speech dramatically improves accuracy. |   |
| 2 | **RMS/energy-based silence detection** | Skip sending silent chunks entirely — reduces noise floor confusing the recognizer. |   |
| 3 | **High-quality resampling** | Linear interpolation in `audio-processor.js:62-68` is basic. At least-order is fine for real-time, but a better algorithm (e.g., sinc or Web Audio's native resampling) would preserve more detail. |   |
| 4 | **Audio preprocessing: high-pass filter + AGC** | Remove low-frequency hum (fan, AC) and normalize varying mic levels so Vosk gets consistent amplitude. |   |
| 5 | **Use larger French model** | `vosk-model-small-fr-0.22` is fast but less accurate. Medium/large models would improve word error rate. |   |
| 6 | **Reset on silence boundaries** | Instead of fixed 45s resets (can cut mid-sentence), detect silence and reset between utterances. |   |
| 7 | **Custom language model / hotwords** | Vosk supports `SetGrammar()` for domain-specific vocab — useful if transcribing specific terminology. |   |
| 8 | **Tune Vosk parameters** | Explore confidence thresholds, acoustic model settings, and French-specific tuning. |   |

## ⚡ Speed / Performance Enhancements

| # | Enhancement | Why | DONE |
|---|---|---|---|
| 9 | **Replace ScriptProcessor with AudioWorklet** | `ScriptProcessor` is deprecated, runs on main thread, causes audio glitches. AudioWorklet runs in a dedicated audio thread with lower latency. | X |
| 10 | **Move audio processing to Web Worker** | Resampling + WebSocket sends block the main thread → UI jank. A Web Worker isolates audio work. |   |
| 11 | **Fixed-size chunks at 16kHz** | Current chunks vary in size after resampling. Fixed 1024-sample chunks (64ms) give Vosk more consistent input and reduce JSON serialization overhead. | X |
| 12 | **Optimize heartbeat checker** | `wait_for + TimeoutError` polling is wasteful. Replace with `asyncio.sleep(5)` loop. | X |
| 13 | **Recognizer pooling** | Creating a new `KaldiRecognizer` per session has overhead. Pool or reuse when possible. | X |
| 14 | **WebSocket compression** | Enable per-message deflate for text results to reduce bandwidth. | X |

## 🏗️ Architecture / Robustness

| # | Enhancement | Why | DONE |
|---|---|---|---|
| 15 | **Multi-client resource limits** | Currently fine for single client, but no limits if multiple users connect. |   |
| 16 | **`/stats` endpoint** | Expose chunks processed, resets, session duration for debugging. | X |
| 17 | **Partial result smoothing** | Reduce UI flicker when partial text updates rapidly (debounce or interpolation). | X |
| 18 | **Audio format validation** | Server should validate incoming audio format and give clear errors for misconfigured clients. |   |

---

## Priority Guide

**Highest impact / lowest effort:**
- #4 — Silence detection (RMS threshold before sending audio)
- #11 — Fixed-size chunks at 16kHz (more consistent Vosk input)
- #16 — `/stats` endpoint (debugging visibility)
- #10 — Web Worker migration (remove main-thread blocking)

**Highest impact overall:**
- #1 — VAD (biggest accuracy improvement, eliminates hallucinations)
- #9 — AudioWorklet (lower latency, no main-thread blocking)
- #5 — Larger French model (better WER, trade-off: slower + more memory)
- #3 — Better resampling (preserves more audio detail)

## Files Affected

| Enhancement | Files to modify |
|---|---|
| #1, #2, #4 | `src/static/audio-processor.js` (client audio pipeline) |
| #3 | `src/static/audio-processor.js` (resampling logic) |
| #5 | `src/vosk_engine.py` (model path config) |
| #6 | `src/audio_processor.py`, `src/session_manager.py` (reset logic) |
| #7 | `src/vosk_engine.py`, `src/audio_processor.py` (grammar API) |
| #8 | `src/vosk_engine.py` (recognizer config) |
| #10 | `src/static/audio-processor.js` + new worker file |
| #16 | `src/server_app.py` (new route) |
| #18 | `src/session_manager.py`, `src/audio_processor.py` |
