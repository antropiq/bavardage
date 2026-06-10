# LLM Migration Layer — Implementation Todo List

## Phase 1: TranscriptionBuffer ✅
- [x] Create `src/transcription_buffer.py` with `TranscriptionBuffer` class
  - [x] Accumulate fragments, detect silence gaps, flush on trigger
  - [x] Unit tests pass

## Phase 2: LLMPostProcessor ✅
- [x] Create `src/llm_post_processor.py` with `LLMPostProcessor` class
  - [x] OpenAI-compatible API client, async, retry, fallback to raw text
  - [x] Unit tests pass

## Phase 3: SessionManager Integration ✅
- [x] Modify `src/session_manager.py`
  - [x] Accept `llm_processor` and `buffer_config` in `__init__`
  - [x] Integrate `TranscriptionBuffer` in `_setup`
  - [x] Route final results through buffer → LLM in `handle_message`
  - [x] Flush remaining buffer on `close`

## Phase 4: ServerApp + CLI Arguments ✅
- [x] Modify `src/server_app.py`
  - [x] Accept `llm_processor` and `buffer_config` in `__init__`
  - [x] Pass them to `SessionManager` in `_websocket_handler`
  - [x] Add `from_args()` classmethod
- [x] Modify `src/server.py`
  - [x] Add `--llm-url`, `--llm-key`, `--llm-model`, `--llm-timeout`
  - [x] Add `--llm-buffer-max`, `--llm-silence-threshold`, `--llm-buffer-min`
  - [x] Wire args to `ServerApp.from_args()`

## Phase 5: start.py Forwarding ✅
- [x] Modify `start.py`
  - [x] Forward `sys.argv[1:]` to server subprocess

## Phase 6: Testing ✅
- [x] Verify server starts without `--llm-url` (unchanged behavior)
- [x] Verify server starts with `--llm-url` (LLM enabled logging)
- [x] Unit tests for TranscriptionBuffer (6 tests)
- [x] Unit tests for LLMPostProcessor (8 tests)
