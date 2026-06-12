# Prompt Area Enhancement: Single Output Area

## Goal

Simplify the UI by consolidating into a single output area (`#output`). The `#partial` div continues to show live streaming text, but when LLM is enabled, the final output in `#output` is **replaced** with the LLM-corrected version instead of being appended to.

## Current State

```
┌─────────────────────────────┐
│  [toolbar]                  │
├─────────────────────────────┤
│  "Bonjour tout le monde"    │  ← #output (final, appended)
│  <u>et aujourd'hui</u>       │  ← #partial (live streaming, italic)
│                             │
│  [conversation area]        │  ← #conversation (Q&A only)
└─────────────────────────────┘
```

Flow:
- `final` WS message → `appendText()` → appends to `#output` with newline
- `partial` WS message → updates `#partial` text content
- LLM question → `#conversation` gets Q&A pair

## Target State

### Without LLM (unchanged)
```
┌─────────────────────────────┐
│  [toolbar]                  │
├─────────────────────────────┤
│  "Bonjour tout le monde"    │  ← #output (final, appended)
│  <u>et aujourd'hui</u>       │  ← #partial (live streaming, italic)
└─────────────────────────────┘
```

### With LLM enabled
```
┌─────────────────────────────┐
│  [toolbar]                  │
├─────────────────────────────┤
│  "Bonjour, tout le monde."  │  ← #output (LLM-corrected, REPLACES raw)
│  <u>et aujourd'hui</u>       │  ← #partial (live streaming, italic)
└─────────────────────────────┘
```

Key difference: when LLM is enabled, `#output` is **cleared and replaced** with the LLM-corrected text instead of being appended to. The raw Vosk text never appears in `#output` — it only lives in `#partial` during recording.

## Changes Required

### 1. `src/static/app.js` — `ws.onmessage` handler

**Current** (lines 87-90):
```js
if (data.type === "final") {
    appendText(data.text);
    partialEl.textContent = "";
    lastPartialText = "";
}
```

**Proposed**:
```js
if (data.type === "final") {
    partialEl.textContent = "";
    lastPartialText = "";
    if (llmEnabled) {
        // LLM will send corrected text — wait for it
        // If no LLM response arrives within timeout, keep raw text
        _pendingFinal = data.text;
        _finalTimeout = setTimeout(() => {
            if (_pendingFinal) {
                outputEl.textContent = _pendingFinal;
                _pendingFinal = null;
            }
        }, 3000); // 3s fallback
    } else {
        appendText(data.text);
    }
}
```

A new `final` WS message type from the server carrying the LLM-corrected text:
```js
if (data.type === "final_llm") {
    // LLM corrected the last final result — replace in-place
    if (_pendingFinal !== null) {
        clearTimeout(_finalTimeout);
        // Replace the last line in #output with LLM text
        const lines = outputEl.textContent.split("\n");
        lines[lines.length - 1] = data.text;
        outputEl.textContent = lines.join("\n");
        _pendingFinal = null;
    }
}
```

### 2. `src/static/app.js` — new state variables

Add near line 16:
```js
let _pendingFinal: string | null = null;
let _finalTimeout: ReturnType<typeof setTimeout> | null = null;
```

### 3. `src/static/app.js` — `clearAll()` and `clearLastLine()`

Update to handle the pending state:
```js
function clearAll() {
    outputEl.textContent = "";
    _pendingFinal = null;
    if (_finalTimeout) {
        clearTimeout(_finalTimeout);
        _finalTimeout = null;
    }
}

function clearLastLine() {
    if (_pendingFinal !== null) {
        _pendingFinal = null;
        if (_finalTimeout) {
            clearTimeout(_finalTimeout);
            _finalTimeout = null;
        }
        return;
    }
    const lines = outputEl.textContent.split("\n");
    if (lines.length > 0) {
        lines.pop();
        outputEl.textContent = lines.join("\n");
    }
}
```

### 4. `src/static/app.js` — `stopRecording()`

Clear pending state on stop:
```js
function stopRecording() {
    // ... existing cleanup ...
    _pendingFinal = null;
    if (_finalTimeout) {
        clearTimeout(_finalTimeout);
        _finalTimeout = null;
    }
    // ... rest of existing cleanup ...
}
```

### 5. `src/server.py` — WebSocket handler

When LLM is enabled, after LLM post-processing completes, send the corrected text back as a separate message type:

```python
# After LLM processing completes:
await ws.send_json({
    "type": "final_llm",
    "text": corrected_text,
    "raw": raw_text  # optional, for debugging
})
```

The raw Vosk `final` message is still sent first (so the client knows a sentence completed), followed by the `final_llm` message with the corrected text.

### 6. `src/session_manager.py` / `src/console.py` — TranscriptionBuffer

No changes needed — the buffer already accumulates fragments and flushes to LLM. The server just needs to send the corrected result back as a `final_llm` WS message in addition to (or instead of) the raw `final` message.

## Edge Cases

1. **LLM timeout** (3s): If LLM doesn't respond in time, fall back to raw text in `#output`.
2. **LLM failure**: If LLM returns an error, use raw text as fallback (existing behavior).
3. **Rapid sentences**: Each `final` triggers a new pending state; the timeout resets. The `final_llm` replaces only the last line in `#output`.
4. **User clears text during pending**: `clearAll()`/`clearLastLine()` both clear the pending state.
5. **User stops recording during pending**: `stopRecording()` clears pending state.

## Files to Modify

| File | Change |
|------|--------|
| `src/static/app.js` | `ws.onmessage`, `clearAll()`, `clearLastLine()`, `stopRecording()`, new state vars |
| `src/server.py` | WebSocket handler: send `final_llm` message type after LLM processing |
| `src/session_manager.py` | Wire LLM result back as `final_llm` WS message |

## Not Changing

- `#partial` behavior — still shows live streaming text
- `#conversation` — Q&A flow unchanged
- CSS — no style changes needed
- Audio capture / resampling — unchanged
- Vosk engine — unchanged
- TranscriptionBuffer / LLMPostProcessor logic — unchanged (just the message delivery)
