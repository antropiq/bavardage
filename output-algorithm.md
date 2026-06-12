# Output Algorithm — Fragment-Based Rendering

## Problem

When LLM post-processing is enabled, the frontend display is a single flat string. Vosk sends a `final` message that replaces text from `cursorPos` onward, then adds a trailing space. Later, `final_llm` replaces the same range again. This causes:

1. **Visual flicker** — raw text appears, then gets overwritten by LLM-corrected text
2. **User must wait** — if the user starts speaking while LLM is processing, new Vosk `final`/`partial` messages collide with the LLM replacement range, causing missing or duplicated words
3. **No concurrency** — display is a single shared mutable string; two writers (Vosk live, LLM corrections) conflict

## Solution: Fragment Queue + Two-Lane Rendering

Replace the flat `outputEl.textContent` model with a **fragment queue** on the frontend. Each fragment owns a position range `[charBeginAt, charEndAt)`. The display is rendered by joining fragments in order.

Vosk writes to the **hot lane** (always live, always visible).
LLM writes to the **cold lane** (FIFO queue, processed at its own speed).

---

## Data Model

### Fragment Object

```typescript
interface Fragment {
  /** Unique auto-incrementing ID */
  id: number;
  /** Character offset in the rendered output where this fragment starts */
  charBeginAt: number;
  /** Character offset where this fragment ends (exclusive) */
  charEndAt: number;
  /** The text content */
  content: string;
  /** Source lane */
  lane: "vosk" | "llm";
  /** Processing state */
  state: "draft" | "final" | "llm-pending" | "llm-done" | "llm-error";
  /** LLM-corrected content (populated when state === "llm-done") */
  llmContent?: string;
}
```

### State Machine

```
vosk + "draft"    →  (silence detected)  →  vosk + "final"  →  (queued to LLM)  →  vosk + "llm-pending"
                                                                                       ↓
                                                                              llm-ok → "llm-done"
                                                                              llm-fail → "llm-error"
```

- **"draft"**: Vosk partial output, updates live
- **"final"**: Vosk finished a sentence fragment, sent to frontend as `final`
- **"llm-pending"**: Fragment is in the LLM processing queue
- **"llm-done"**: LLM returned corrected text, replaces `content` with `llmContent`
- **"llm-error"**: LLM call failed, keeps original `content`

### Frontend State

```typescript
let fragments: Fragment[] = [];
let nextFragmentId = 0;
let llmQueue: Array<{ fragmentId: number; rawText: string }> = [];
let llmProcessing = false;
```

---

## Rendering Algorithm

### `render()` — called whenever fragments change

```
1. Build display string by iterating fragments in order:
   display = ""
   for frag in fragments:
     if frag.lane == "llm" and frag.state == "llm-pending":
       // Skip LLM-pending fragments from display entirely
       // They will be rendered once LLM responds
       continue
     display += frag.content

2. Also append the current Vosk partial (if any):
   lastVosk = fragments.findLast(f => f.lane == "vosk" && f.state == "draft")
   if lastVosk:
     display += lastVosk.content

3. Set outputEl.textContent = display
4. Scroll to bottom
```

### Key rule: LLM-pending fragments are **invisible** in the display.

This means:
- When Vosk sends `[FINAL1]`, it becomes a `final` fragment → visible
- Immediately, it's queued to LLM → state becomes `llm-pending` → hidden from display
- The NEXT Vosk fragment `[DRAFT2]` is appended after the position where FINAL1 was
- When LLM responds with `[CLEAN1]`, the fragment becomes `llm-done` → visible again
- Display recalculates: `[CLEAN1][DRAFT2]` — DRAFT2 automatically shifts right

---

## WebSocket Message Handling

### `final` message (from Vosk)

```
onFinal(text):
  1. Calculate charBeginAt = sum(charEndAt of all visible fragments)
     "visible" = all llm-done + llm-error fragments (not llm-pending or draft vosk)
  
  2. Create fragment:
     frag = {
       id: nextFragmentId++,
       charBeginAt: charBeginAt,
       charEndAt: charBeginAt + text.length,
       content: text,
       lane: "vosk",
       state: "final"
     }
  
  3. Append to fragments array
  
  4. Queue for LLM processing:
     llmQueue.push({ fragmentId: frag.id, rawText: text })
  
  5. Immediately set state to "llm-pending" (if LLM enabled):
     frag.state = "llm-pending"
  
  6. render()
  7. startLlmWorker()
```

### `final_llm` message (from LLM correction)

```
onFinalLlm(text):
  1. Dequeue from llmQueue:
     if llmQueue is empty:
       // LLM responded but we didn't queue — ignore or fallback
       return
     queueItem = llmQueue.shift()
  
  2. Find fragment by ID:
     frag = fragments.find(f => f.id == queueItem.fragmentId)
  
  3. Update fragment:
     frag.llmContent = text
     frag.content = text          // Replace in-place for rendering
     frag.state = "llm-done"
  
  4. Recalculate charEndAt for ALL subsequent fragments:
     offset = frag.content.length - (frag.charEndAt - frag.charBeginAt)
     for laterFrag in fragments after frag:
       laterFrag.charBeginAt += offset
       laterFrag.charEndAt += offset
  
  5. render()
```

### `partial` message (from Vosk live transcription)

```
onPartial(text):
  1. Find the last "draft" vosk fragment:
     lastVosk = fragments.findLast(f => f.lane == "vosk" && f.state == "draft")
  
  2. If no draft exists, create one:
     if !lastVosk:
       charBeginAt = sum(charEndAt of all visible fragments)
       lastVosk = {
         id: nextFragmentId++,
         charBeginAt: charBeginAt,
         charEndAt: charBeginAt,
         content: "",
         lane: "vosk",
         state: "draft"
       }
       fragments.push(lastVosk)
  
  3. Update the draft fragment:
     lastVosk.content = text
     lastVosk.charEndAt = lastVosk.charBeginAt + text.length
  
  4. render()
```

### LLM Worker (background processor)

```
startLlmWorker():
  if llmProcessing: return
  llmProcessing = true
  
  while llmQueue.length > 0:
    item = llmQueue[0]  // Peek, don't dequeue yet
    
    // Call LLM API (via existing WebSocket or HTTP)
    result = await callLlm(item.rawText)
    
    // Send result back to frontend
    if result.success:
      sendToClient({ type: "final_llm", text: result.text, fragmentId: item.fragmentId })
      llmQueue.shift()  // Remove from queue only after successful send
    else:
      // Mark as error, keep original text
      frag = fragments.find(f => f.id == item.fragmentId)
      if frag: frag.state = "llm-error"
      llmQueue.shift()
  
  llmProcessing = false
```

---

## Position Recalculation

When an LLM result replaces a fragment, the text length may change. All subsequent fragment positions must shift:

```
Before LLM response for fragment at [0, 7] ("Hello "):
  Fragment 0: [0, 7] "Hello "
  Fragment 1: [7, 13] "monde "
  Fragment 2: [13, 18] "ici"

LLM returns "Bonjour " (8 chars instead of 6):
  delta = 8 - 6 = +2

After:
  Fragment 0: [0, 8] "Bonjour "
  Fragment 1: [9, 15] "monde "   // shifted by +2
  Fragment 2: [15, 20] "ici"       // shifted by +2
```

**Implementation:**
```
recalculatePositions(affectedFragmentIndex):
  for i from affectedFragmentIndex + 1 to fragments.length - 1:
    frag = fragments[i]
    frag.charBeginAt += delta
    frag.charEndAt += delta
```

---

## Edge Cases

### 1. LLM fails for a fragment
- Fragment state → `"llm-error"`
- Content stays as original Vosk text
- Fragment becomes visible (no more hidden)
- Subsequent fragments are not affected

### 2. LLM responds out of order
- Use `fragmentId` for matching, not queue order
- Each `final_llm` message must include `fragmentId`
- Fragment is updated by ID lookup, position recalculation is independent of order

### 3. User stops talking mid-draft
- Vosk sends `final` for the draft → it becomes `final` state → queued to LLM
- New partial creates a new draft fragment after it
- No conflict

### 4. Multiple rapid finals
- Each creates its own fragment with correct position
- All queued to LLM FIFO
- Display shows all of them immediately (as pending)

### 5. Clear all / stop recording
```
clearAll():
  fragments = []
  llmQueue = []
  llmProcessing = false
  nextFragmentId = 0
  render()

stopRecording():
  clearAll()
  // Also close WebSocket
```

### 6. LLM disabled (no --llm-url)
- Same flow, but fragments stay `"vosk" + "final"` / `"vosk" + "draft"`
- No LLM queue, no LLM worker
- Display is simply all fragments joined
- **This is the simplest case — identical to current behavior**

### 7. Partial arrives for a fragment that's already been sent as final
- The partial replaces the content of the last draft fragment
- If no draft exists, the last `final` fragment is converted to `draft` state
- This handles Vosk resending partials of the same sentence

---

## Server-Side Changes

### WebSocket message format

**`final` message** — add `fragmentId`:
```json
{"type": "final", "text": "Hello ", "fragmentId": 0}
```

**`final_llm` message** — add `fragmentId`:
```json
{"type": "final_llm", "text": "Bonjour ", "fragmentId": 0}
```

### `session_manager.py` changes

In `_send_final()`, generate a `fragmentId` and pass it through:
```python
async def _send_final(self, text: str, fragment_id: int) -> None:
    await self._ws.send_json({"type": "final", "text": text, "fragmentId": fragment_id})
    if self._llm_processor and self._llm_processor.enabled:
        polished = await self._llm_processor.process(text)
        if polished:
            await self._ws.send_json({"type": "final_llm", "text": polished, "fragmentId": fragment_id})
```

The `fragment_id` is assigned in `handle_message()` when a final result arrives:
```python
# In handle_message(), when processing a final result:
fragment_id = self._next_fragment_id
self._next_fragment_id += 1
await self._send_final(raw_text, fragment_id)
```

### `transcription_buffer.py` changes

No changes needed — the buffer still accumulates fragments and flushes on silence/overflow. The `fragmentId` is just an ID assigned by the session manager.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/session_manager.py` | Assign `fragmentId` to each final, pass it through `_send_final()` and LLM flush paths |
| `src/static/app.js` | Rewrite output rendering: fragment queue, `render()`, LLM worker, position recalculation |
| `src/static/style.css` | Minor: ensure output div handles dynamic content correctly |

No changes to:
- `transcription_buffer.py` — buffer logic unchanged
- `llm_post_processor.py` — processing logic unchanged
- `index.html` — DOM structure unchanged

---

## Implementation Order

1. **Server**: Add `fragmentId` to `session_manager.py` (simple, backward-compatible)
2. **Frontend**: Implement fragment data model + `render()` function
3. **Frontend**: Wire up `final` handler to create fragments + queue to LLM
4. **Frontend**: Wire up `final_llm` handler to update fragments + recalculate positions
5. **Frontend**: Wire up `partial` handler to update draft fragment
6. **Frontend**: Implement LLM worker (background processor)
7. **Frontend**: Handle edge cases (clear, stop, LLM error)
8. **Test**: Verify with LLM on and off

---

## Visual Flow Example

```
User says: "Bonjour le monde ici"

Step 1 — Vosk partial:
  fragments: [{ id:0, [0,0], "", draft }]
  display: ""

Step 2 — Vosk partial updates:
  fragments: [{ id:0, [0,7], "Bonjour ", draft }]
  display: "Bonjour "

Step 3 — Vosk final:
  fragments: [{ id:0, [0,7], "Bonjour ", final }]
  display: "Bonjour "
  llmQueue: [{ fragmentId: 0, rawText: "Bonjour " }]
  → state → llm-pending
  display: ""  (pending fragment hidden)

Step 4 — User keeps talking, Vosk partial:
  fragments: [
    { id:0, [0,7], "Bonjour ", llm-pending },   // hidden
    { id:1, [0,4], "le monde ", draft }          // visible, position=0 because frag0 is hidden
  ]
  display: "le monde "

Step 5 — LLM responds for frag 0:
  fragments: [
    { id:0, [0,8], "Bonjour ", llm-done },       // visible, 7→8 chars
    { id:1, [9,13], "le monde ", draft }         // shifted +1
  ]
  display: "Bonjour le monde "

Step 6 — User stops:
  fragments: [
    { id:0, [0,8], "Bonjour ", final },          // queued to LLM → llm-pending
    { id:1, [8,18], "le monde ", final },        // new fragment after frag0
    { id:2, [18,23], "ici ", draft }             // current partial
  ]
  display: "le monde ici "  (frag0 hidden, frag1+frag2 visible)

Final state (all LLM done):
  display: "Bonjour le monde ici "
```
