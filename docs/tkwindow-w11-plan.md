# tkwindow Windows 11 Migration Plan

## Prerequisites: OOP Refactoring

Before tackling Windows 11 support, the monolithic `src/tkwindow.py` (~400 lines) must be refactored into a clean package-oriented architecture. This decouples platform concerns and makes the Windows migration incremental and testable.

### Target Package Structure

```
src/tkwindow/
├── __init__.py          # Public API: TkWindow, main, list_devices
├── cli.py               # CLI argument parsing (argparse), logging setup
├── devices.py           # Device enumeration (platform-specific)
│   ├── __init__.py      # Re-exports _list_all_sources
│   └── linux.py         # pactl-based listing (_list_monitor_sources, _list_microphone_sources)
│   └── windows.py       # PyAudio-based listing (_list_devices_windows)
├── audio.py             # Audio capture abstraction
│   ├── __init__.py      # Re-exports AudioCapture, create_audio_capture
│   ├── base.py          # Abstract base: BaseAudioCapture (read(), start(), stop(), close())
│   ├── linux.py         # PulseAudio/PipeWire capture via parec subprocess
│   └── windows.py       # PyAudio stream capture (with sample-rate handling)
├── renderer.py          # Canvas rendering logic (extracted from TkWindow._render_canvas, _render)
│   ├── __init__.py      # Re-exports CanvasRenderer
│   └── pool.py          # Canvas text item pool pre-allocation and management
├── gui.py               # Tkinter GUI construction (extracted from TkWindow._build_gui)
│   ├── __init__.py      # Re-exports build_window
│   ├── controls.py      # Top bar: source combo, quick-select buttons, Start/Stop, Clear
│   └── canvases.py      # Dual-canvas layout, resize/mousewheel bindings, font config
└── window.py            # Main TkWindow class (orchestrator only, ~100 lines)
    └── __init__.py      # Re-exports TkWindow
```

### Refactoring Steps

#### Step 1: Extract device listing (`devices/`)

Extract the three module-level functions into `src/tkwindow/devices/linux.py`:
- `_list_monitor_sources()` → `_list_monitor_sources()` (Linux-only, pactl-based)
- `_list_microphone_sources()` → `_list_microphone_sources()` (Linux-only, pactl-based)
- `_list_all_sources()` → `_list_all_sources()` (unified entry point, currently Linux-only)

**Result:** `devices/linux.py` contains ~60 lines of pure Linux code with zero Tkinter dependencies. `devices/__init__.py` re-exports `_list_all_sources()`.

#### Step 2: Extract audio capture (`audio/`)

Create an abstract base `BaseAudioCapture` in `audio/base.py`:
```python
class BaseAudioCapture(ABC):
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def read(self, frames: int) -> bytes: ...
    @abstractmethod
    def close(self) -> None: ...
```

- `audio/linux.py`: `PulseAudioCapture` — wraps the `parec` subprocess, reads from stdout pipe
- `audio/windows.py`: `PyAudioCapture` — wraps PyAudio stream, handles sample-rate conversion

Factory function in `audio/__init__.py`:
```python
def create_audio_capture(source_name: str, source_type: str) -> BaseAudioCapture:
    if sys.platform == "win32":
        from .windows import PyAudioCapture
        return PyAudioCapture(source_name, source_type)
    else:
        from .linux import PulseAudioCapture
        return PulseAudioCapture(source_name)
```

**Result:** `_start()`, `_stop()`, `_kill()`, `_process_loop()` in `TkWindow` no longer contain platform-specific subprocess/stream logic. They delegate to `self.capture: BaseAudioCapture`.

#### Step 3: Extract rendering (`renderer/`)

Move canvas rendering out of `TkWindow` into `renderer.py`:
- `_render_canvas(canvas, items, lines, partial)` → `CanvasRenderer.render(canvas, items, lines, partial)`
- `_render()` (ping-pong logic) → `CanvasRenderer.render_ping_pong()`
- Pre-allocation of text items → `ItemPool` class in `pool.py`

The renderer owns the canvas text item pool, font configuration, and rendering logic. `TkWindow` holds references to two `CanvasRenderer` instances (top/bottom) and alternates which one is "active" vs "committed".

**Result:** `TkWindow` loses ~80 lines of rendering code. The renderer is now a pure display module with no audio or device knowledge.

#### Step 4: Extract GUI construction (`gui/`)

Move widget creation out of `TkWindow._build_gui()` into dedicated modules:
- `gui/controls.py`: Source dropdown, quick-select speaker/mic buttons, Start/Stop, Clear, status label — all wired to their callbacks
- `gui/canvases.py`: Dual-canvas layout, resize bindings, mousewheel bindings, background rects, font setup
- `gui/__init__.py`: `build_window(root)` — assembles controls + canvases, returns configured `TkWindow`

The `TkWindow` class provides callback methods (`_on_source_selected`, `_select_speaker`, `_select_mic`, `_toggle`, `_clear`) that the GUI layer binds to widgets. This is a classic presenter pattern: `TkWindow` is the presenter, `gui/` modules are the view.

**Result:** `_build_gui()` is replaced by `gui.build_window()` (~50 lines of assembly code). `TkWindow.__init__()` no longer builds widgets.

#### Step 5: Extract CLI (`cli.py`)

Move `main()` and argparse setup into `src/tkwindow/cli.py`:
- Argument parsing (`--list-devices`, `--vosk-model`, `--debug`, `--user-speaker`, `--volume`, `--device`)
- Logging setup (`loguru` configuration)
- Entry point that instantiates `TkWindow` and calls `run()`

**Result:** `if __name__ == "__main__": main()` becomes a thin wrapper: `from src.tkwindow.cli import main; main()`.

#### Step 6: Slim `TkWindow` (`window.py`)

After all extractions, `TkWindow` becomes a ~100-line orchestrator:
```python
class TkWindow:
    def __init__(self, model_path, user_speaker, volume, device): ...
    # Callback methods (bound by gui/ layer)
    def _toggle(self) -> None: ...
    def _clear(self) -> None: ...
    def _on_source_selected(self) -> None: ...
    def _select_speaker(self) -> None: ...
    def _select_mic(self) -> None: ...
    # Core logic
    def _start(self) -> None: ...  # delegates to self.audio_capture.start()
    def _stop(self) -> None: ...   # delegates to self.audio_capture.stop()
    def _process_loop(self) -> None: ...  # delegates to self.audio_capture.read()
    def run(self) -> None: ...      # entry point
```

Platform-specific logic is pushed into `devices/` and `audio/` modules. Rendering is in `renderer/`. GUI construction is in `gui/`. CLI is in `cli.py`.

### Migration Order

1. Create `src/tkwindow/` directory structure with empty `__init__.py` files
2. Extract `devices/linux.py` — verify `--list-devices` still works
3. Extract `audio/base.py` + `audio/linux.py` — verify Linux capture still works
4. Extract `renderer/` — verify canvas rendering is unchanged
5. Extract `gui/` — verify GUI construction is unchanged
6. Extract `cli.py` — verify `python -m src.tkwindow` still works
7. Slim `TkWindow` in `window.py` — verify end-to-end functionality
8. Delete `src/tkwindow.py` — only if all tests pass

### Invariants

- **No behavioral changes** during refactoring. Every step must produce a working application.
- **No new dependencies** added.
- **Platform detection** (`sys.platform == "win32"`) remains in `devices/__init__.py` and `audio/__init__.py` only — not scattered across `TkWindow`.
- **Public API** (`src/tkwindow/__init__.py`) re-exports `TkWindow`, `main`, and `list_devices` so existing imports (`from src.tkwindow import TkWindow`) continue to work.

---

## Overview

`src/tkwindow.py` currently relies on **PulseAudio/PipeWire** tools (`pactl`, `parec`) which are Linux-only. This plan details the changes needed to support Windows 11 while preserving all Linux functionality.

`src/tkwindow.py` currently relies on **PulseAudio/PipeWire** tools (`pactl`, `parec`) which are Linux-only. This plan details the changes needed to support Windows 11 while preserving all Linux functionality.

---

## Current Architecture (Linux)

```
┌─────────────────────────────────────────────────────┐
│  tkwindow.py                                         │
│                                                      │
│  Device listing: pactl list sources                  │
│  Audio capture:  parec --device NAME --format s16le  │
│                       --rate 16000 --channels 1      │
│                       → stdout pipe → read(1024)     │
│                                                      │
│  Vosk: KaldiRecognizer.AcceptWaveform(data)          │
│  Rendering: canvas text items via root.after(16)     │
└─────────────────────────────────────────────────────┘
```

**Linux-specific calls:**
- `_list_monitor_sources()` / `_list_microphone_sources()` / `_list_all_sources()` — all call `pactl list sources`
- `_start()` — spawns `parec --device NAME --format s16le --rate 16000 --channels 1` as a subprocess
- `_stop()` / `_kill()` — SIGTERM/KILL the `parec` process

---

## Target Architecture (Cross-Platform)

```
┌──────────────────────────────────────────────────────────┐
│  tkwindow.py (cross-platform)                             │
│                                                           │
│  Device listing:                                          │
│    Linux → pactl list sources (existing)                  │
│    Windows → PyAudio PortAudio enumerate                  │
│                                                           │
│  Audio capture:                                           │
│    Linux → parec subprocess (existing)                    │
│    Windows → PyAudio stream (new)                         │
│                                                           │
│  Vosk: KaldiRecognizer.AcceptWaveform(data) — unchanged   │
│  Rendering: canvas text items via root.after(16)          │
│            — unchanged                                    │
└──────────────────────────────────────────────────────────┘
```

**Key principle:** Linux behavior stays exactly the same. Windows gets a new code path behind a `sys.platform == "win32"` guard.

---

## Phase 1: Device Listing

### 1.1 Linux (unchanged)

Keep existing `pactl`-based listing. No changes needed.

```python
# Current behavior — preserved
def _list_monitor_sources_linux() -> list[tuple[str, str]]:
    out = subprocess.check_output(["pactl", "list", "sources"], ...)
    # Parse Source #, Name:, Description: blocks
    # Filter for "monitor" in name
```

### 1.2 Windows (new)

Replace `pactl` with PyAudio's PortAudio bindings. PyAudio is already a project dependency (`pyproject.toml:16`).

```python
import pyaudio

def _list_devices_windows() -> list[tuple[str, str, str]]:
    """List audio devices on Windows using PyAudio/PortAudio."""
    audio = pyaudio.PyAudio()
    sources = []
    try:
        count = audio.get_device_count()
        for i in range(count):
            info = audio.get_device_info_by_index(i)
            # Only input-capable devices
            if info.get("maxInputChannels", 0) == 0:
                continue
            name = info.get("name", f"Device {i}")
            channels = info.get("maxInputChannels", 0)
            rate = info.get("defaultSampleRate", 44100)

            # Classify device type
            name_lower = name.lower()
            if any(kw in name_lower for kw in ("loopback", "stereo mix", "what u hear", "sum", "mix")):
                dtype = "loopback"  # Windows speaker output capture
            elif any(kw in name_lower for kw in ("mic", "input", "headset", "webcam", "camera")):
                dtype = "mic"
            else:
                dtype = "input"  # default classification

            desc = f"{channels}ch @ {rate:.0f}Hz"
            sources.append((name, desc, dtype))
    finally:
        audio.terminate()
    return sources
```

### 1.3 Unified entry point

```python
def _list_all_sources() -> list[tuple[str, str, str]]:
    if sys.platform == "win32":
        return _list_devices_windows()
    else:
        # Linux: keep existing pactl-based implementation
        sources: list[tuple[str, str, str]] = []
        for name, desc in _list_monitor_sources():
            sources.append((name, desc, "monitor"))
        for name, desc in _list_microphone_sources():
            sources.append((name, desc, "mic"))
        return sources
```

### 1.4 Device classification heuristics

| Platform | Type | Naming heuristic | Notes |
|----------|------|------------------|-------|
| Linux | `monitor` | `"monitor"` in source name | PulseAudio monitor sources capture speaker output |
| Linux | `mic` | Input source, no "monitor" | Microphone/input devices |
| Windows | `loopback` | "stereo mix", "what u hear", "sum", "loopback" | WASAPI loopback for system audio |
| Windows | `mic` | "mic", "input", "headset", "webcam", "camera" | Microphone devices |
| Windows | `input` | (fallback) | Anything else with input channels |

### 1.5 Quick-select buttons

The existing `_find_speaker_device()` and `_find_mic_device()` methods use heuristics on device names. These need minor updates:

- `_find_speaker_device()`: on Windows, search for `loopback` type instead of `"monitor"`
- `_find_mic_device()`: keep existing logic (works for both platforms)

---

## Phase 2: Audio Capture

### 2.1 Linux (unchanged)

Keep the `parec` subprocess approach. No changes needed.

### 2.2 Windows (new)

Replace `parec` with a PyAudio stream opened directly in the process.

#### 2.2.1 Stream lifecycle

```python
# In __init__:
self.pyaudio: pyaudio.PyAudio | None = None
self.stream: pyaudio.Stream | None = None

# In _start():
self.pyaudio = pyaudio.PyAudio()
# ... load Vosk model ...
self.stream = self.pyaudio.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=16000,
    input=True,
    input_device_index=device_index,
    frames_per_buffer=CHUNK_SIZE,  # ~100ms at 16kHz = 1600 samples
)

# In _process_loop():
data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)

# In _stop():
if self.stream:
    self.stream.stop_stream()
    self.stream.close()
    self.stream = None
if self.pyaudio:
    self.pyaudio.terminate()
    self.pyaudio = None
```

#### 2.2.2 Chunk size

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `frames_per_buffer` (stream) | 1600 | 100ms at 16kHz mono s16le |
| `stream.read()` | 1600 (or 3200) | Match stream buffer; 200ms chunks work well with Vosk |
| `root.after()` interval | 16ms | ~60fps render loop, same as current |

**Recommended:** Open stream with `frames_per_buffer=1600` (100ms). In `_process_loop()`, call `self.stream.read(3200)` to get ~200ms of audio per iteration. This gives Vosk enough audio for reliable VAD while keeping latency low.

#### 2.2.3 Sample rate handling

**Critical difference:** `parec` handles sample-rate conversion automatically. PyAudio streams at the **device's native sample rate**.

On Windows, most audio devices report 44100 or 48000 Hz as default rate. Vosk expects exactly 16000 Hz. Two approaches:

**Option A: Request 16kHz from PyAudio (simple, but not always available)**

```python
self.stream = self.pyaudio.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=16000,  # Request 16kHz
    input=True,
    input_device_index=device_index,
    frames_per_buffer=1600,
)
```

- **Pros:** Simple, no extra code
- **Cons:** PyAudio may silently resample with poor quality, or fail on devices that don't support 16kHz natively
- **Test first:** Try on target Windows machines before committing

**Option B: Stream at native rate, resample in Python (reliable)**

```python
import numpy as np
from scipy.signal import resample

def _get_native_rate(audio, device_index):
    info = audio.get_device_info_by_index(device_index)
    return int(info.get("defaultSampleRate", 44100))

# Open at native rate
native_rate = _get_native_rate(self.pyaudio, device_index)
self.stream = self.pyaudio.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=native_rate,
    input=True,
    input_device_index=device_index,
    frames_per_buffer=frames_per_buffer,
)

# In _process_loop:
raw_data = self.stream.read(frames_per_buffer, exception_on_overflow=False)
# Resample to 16kHz
target_frames = int(len(raw_data) // 2 * 16000 / native_rate)
samples = np.frombuffer(raw_data, dtype=np.int16)
resampled = resample(samples, target_frames)
data = resampled.astype(np.int16).tobytes()
```

- **Pros:** Always works, high-quality resampling
- **Cons:** Slightly more CPU, requires `scipy` (not a current dependency)

**Recommendation: Try Option A first.** If it produces poor quality or fails on any target machine, fall back to Option B. If Option B is needed, add `scipy` to `pyproject.toml` dependencies.

**Alternative lightweight resampling (no scipy dependency):**

```python
def _resample_s16le(data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample 16kHz mono s16le PCM using linear interpolation."""
    import numpy as np
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    num_target = int(len(samples) * to_rate / from_rate)
    indices = np.linspace(0, len(samples) - 1, num_target)
    resampled = np.interp(indices, np.arange(len(samples)), samples)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()
```

This is a pure NumPy implementation — no scipy needed. Since `numpy` is already a dependency, this is the safest default.

#### 2.2.4 WASAPI loopback (Windows speaker capture)

To capture system speaker output on Windows (equivalent to Linux `monitor` sources):

**Approach: Use "Stereo Mix" or WASAPI loopback device**

```python
def _open_loopback_stream(self, audio, device_index):
    """Open a WASAPI loopback stream for speaker capture."""
    # On Windows, WASAPI loopback is accessed by opening an OUTPUT device
    # as an INPUT device. PyAudio/PortAudio handles this when:
    # - input_device_index points to an output device
    # - host_api_specific is set for WASAPI
    import ctypes
    wasapi_info = {
        "flags": pyaudio.paClipOff,  # disable clipping to avoid distortion
    }
    self.stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=1600,
        # host_api_specific_stream_info=wasapi_info  # optional, for fine control
    )
```

**Key Windows loopback devices to look for:**
- "Stereo Mix"
- "What U Hear"
- "Stereo Mix (Realtek Audio)"
- "Loopback"
- "Microsoft Wave Mapper"

If no loopback device exists, the user must enable it:
1. Right-click volume icon → Sound Settings → More sound settings
2. Playback tab → right-click → Show Disabled Devices
3. Enable "Stereo Mix"

**Recommendation:** Add a warning dialog in the GUI if `--user-speaker` is requested but no loopback device is found.

### 2.3 Volume amplification

The existing `_amplify()` function works on raw `bytes` (s16le PCM) and is **platform-agnostic**. No changes needed.

```python
def _amplify(data: bytes, volume: float) -> bytes:
    """Amplify raw int16 PCM samples."""
    import numpy as np
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()
```

---

## Phase 3: Code Changes Summary

### 3.1 New functions

| Function | Platform | Purpose |
|----------|----------|---------|
| `_list_devices_windows()` | Windows | Enumerate devices via PyAudio |
| `_resample_s16le(data, from_rate, to_rate)` | Windows | Resample PCM to 16kHz (if native rate != 16kHz) |
| `_open_stream(audio, device_index, rate, is_loopback)` | Windows | Open PyAudio stream (with WASAPI config for loopback) |

### 3.2 Modified functions

| Function | Change |
|----------|--------|
| `_list_all_sources()` | Branch on `sys.platform == "win32"` → call `_list_devices_windows()` or existing `pactl` |
| `_find_speaker_device()` | On Windows, match `loopback` type instead of `monitor` keyword |
| `_find_mic_device()` | No change (heuristic works for both platforms) |
| `__init__()` | Add `self.pyaudio` and `self.stream` attributes; remove `self.proc` |
| `_start()` | Branch: Linux → keep `parec` subprocess; Windows → open PyAudio stream |
| `_stop()` | Branch: Linux → kill `parec`; Windows → close stream + terminate PyAudio |
| `_kill()` | Branch: Linux → kill `proc`; Windows → close stream |
| `_process_loop()` | Branch: Linux → read from `proc.stdout`; Windows → read from `self.stream.read()` |

### 3.3 Attributes to add/remove

**Remove:**
```python
self.proc: subprocess.Popen[bytes] | None  # Linux-only
```

**Add:**
```python
self.pyaudio: pyaudio.PyAudio | None  # Windows-only
self.stream: pyaudio.Stream | None    # Windows-only
```

### 3.4 Import changes

```python
# Add at top (conditional import — PyAudio may not be available on all systems)
try:
    import pyaudio
except ImportError:
    pyaudio = None  # Graceful degradation
```

---

## Phase 4: Testing Checklist

### 4.1 Linux (ensure no regression)

- [ ] `--list-devices` shows monitor + mic sources
- [ ] `--user-speaker` selects a monitor source
- [ ] Start/Stop transcription works with microphone
- [ ] Start/Stop transcription works with monitor (speaker) source
- [ ] Canvas rendering (ping-pong) works correctly
- [ ] Quick-select buttons (speaker/mic) work
- [ ] Volume amplification works
- [ ] `--debug` logging works

### 4.2 Windows 11

- [ ] `--list-devices` shows all input devices with channel/rate info
- [ ] Microphone device is correctly classified as `mic`
- [ ] Stereo Mix / loopback device is correctly classified as `loopback`
- [ ] Start/Stop transcription works with microphone
- [ ] Start/Stop transcription works with loopback (speaker capture)
- [ ] Audio quality is acceptable (no excessive noise, correct speed)
- [ ] Sample rate conversion is transparent (if Option B is used)
- [ ] Quick-select buttons work (speaker → loopback, mic → mic)
- [ ] Volume amplification works
- [ ] GUI rendering is smooth (no flicker, correct font rendering on Windows)
- [ ] Window icon loads correctly (`.png` → convert or use `tk.PhotoImage` with fallback)
- [ ] `--debug` logging works
- [ ] Ctrl+Close (window X) stops cleanly
- [ ] Device disconnect is handled gracefully

### 4.3 Edge cases

- [ ] No audio devices available → shows "No sources found"
- [ ] Only loopback devices, no microphones → works with loopback
- [ ] Only microphones, no loopback → `--user-speaker` shows warning, falls back to mic
- [ ] Multiple microphones → user can select from dropdown
- [ ] Device name contains special characters / non-ASCII → displays correctly in dropdown
- [ ] Long transcription sessions (10+ minutes) → no memory leaks, no drift
- [ ] PyAudio not installed → clear error message

---

## Phase 5: Dependencies

### 5.1 Existing (already in `pyproject.toml`)

| Package | Used for | Platform |
|---------|----------|----------|
| `pyaudio>=0.2.14` | Audio capture (Windows) | All |
| `numpy>=1.24.0` | Volume amplification, resampling | All |
| `vosk>=0.3.45` | Transcription engine | All |
| `ttkbootstrap` | GUI framework | All |
| `loguru` | Logging | All |

### 5.2 Potential additions

| Package | When needed | Reason |
|---------|-------------|--------|
| `scipy` | Only if Option B resampling is chosen | High-quality `resample()` function |

**Recommendation:** Start with pure NumPy resampling (no scipy). Only add scipy if NumPy linear interpolation produces unacceptable quality.

---

## Audio Advice for Windows

### 5.1 Microphone capture

Most straightforward path. Windows recognizes microphones natively. PyAudio/PortAudio will list them as input devices. No special configuration needed.

**Potential issues:**
- **Exclusive mode:** Some applications (Discord, VoIP) may lock the microphone in exclusive mode, preventing PyAudio from accessing it. Solution: user must close the competing application.
- **Enhancements:** Windows audio enhancements (noise suppression, echo cancellation) may interfere. Solution: disable in Windows Sound Settings → Recording device → Properties → Enhancements.

### 5.2 Speaker output capture (loopback)

This is the trickiest part on Windows. Unlike Linux PulseAudio (which provides monitor sources natively), Windows requires explicit setup.

**Methods:**

1. **Stereo Mix** (legacy, most compatible)
   - Built into most Realtek audio drivers
   - May be hidden/disabled by default
   - Enable via: Sound Settings → Playback → Show Disabled → Enable "Stereo Mix"

2. **WASAPI Loopback** (modern, higher quality)
   - Available via WASAPI host API in PortAudio
   - Captures at sample-accurate resolution
   - Requires Windows Vista or later
   - PyAudio supports this through PortAudio's WASAPI integration

3. **Third-party virtual cables** (fallback)
   - VB-Audio Virtual Cable (free)
   - Voicemeeter (free)
   - Creates a virtual audio device that routes system output to an input
   - User must install separately

**Recommendation:** Prioritize Stereo Mix detection. If not found, suggest WASAPI loopback via WASAPI-enabled output devices. Provide clear user instructions for enabling Stereo Mix.

### 5.3 Sample rate gotchas

Windows audio devices report their native rate via `defaultSampleRate`. Common values:
- 44100 Hz (CD quality)
- 48000 Hz (DVD/DV quality)
- 96000 Hz (high-res audio)

**Vosk requires 16000 Hz.** Always verify the stream rate matches. If using Option A (request 16kHz), log a warning if PyAudio reports a different actual rate.

**Debug tip:** Add this to `_start()` for diagnostics:
```python
if sys.platform == "win32":
    info = self.pyaudio.get_device_info_by_index(device_index)
    logger.debug(f"Device {device_index}: {info['name']} @ {info['defaultSampleRate']}Hz")
```

### 5.4 Latency considerations

PyAudio stream latency depends on the host API:
- **WASAPI (Windows exclusive mode):** ~10-50ms (very low)
- **WASAPI (Windows shared mode):** ~100-200ms
- **DirectSound (Windows legacy):** ~100-300ms

For real-time transcription, shared mode latency is acceptable. If latency is a concern, recommend WASAPI exclusive mode via host API specific info.

---

## Implementation Order

1. **Device listing on Windows** (`_list_devices_windows()` + unified `_list_all_sources()`)
   - Smallest change, easiest to test independently
   - Validates PyAudio is working on the target machine

2. **PyAudio stream capture on Windows** (`_start()`, `_stop()`, `_process_loop()` branches)
   - Core functionality, requires Vosk model loading to test
   - Test with microphone first, then loopback

3. **Sample rate handling** (resampling if needed)
   - Depends on whether Option A or Option B is chosen
   - Test with multiple device sample rates

4. **Quick-select button updates** (`_find_speaker_device()` for Windows)
   - Polish step, depends on Phase 1 working

5. **Error handling and edge cases**
   - Device disconnect, missing PyAudio, no loopback device
   - User-facing warnings and fallbacks

6. **Testing and refinement**
   - Run through the full testing checklist
   - Adjust chunk sizes, sample rates, and latency settings
