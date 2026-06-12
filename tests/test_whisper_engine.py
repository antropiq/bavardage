"""Unit tests for WhisperEngine and WhisperRecognizer."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.whisper_engine import WhisperEngine, WhisperRecognizer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_silent_audio(length=16000):
    """Create silent audio (int16 PCM, 16kHz)."""
    return np.zeros(length, dtype=np.int16).tobytes()


def _make_speaking_audio(length=16000, amplitude=10000):
    """Create non-silent audio (int16 PCM, 16kHz)."""
    return np.full(length, amplitude, dtype=np.int16).tobytes()


def _make_silent_samples(length=16000):
    """Create silent float32 samples."""
    return np.zeros(length, dtype=np.float32)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_model_transcribe():
    """Create a mock model with transcribe method. Patched where it's used."""
    model = MagicMock()
    segment = MagicMock()
    segment.text = "hello world"
    model.transcribe = MagicMock(return_value=([segment], {"language": "fr"}))
    return model


@pytest.fixture
def loaded_engine():
    """Create a WhisperEngine with mocked dependencies, already loaded."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng.load()
        return eng, wm, model


# ── Tests: WhisperRecognizer ─────────────────────────────────────────────────

def test_recognizer_init(mock_model_transcribe):
    """Recognizer initializes with correct defaults."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000, language="fr")
    assert rec._model is mock_model_transcribe
    assert rec._sample_rate == 16000
    assert rec._language == "fr"
    assert rec._audio_buffer == []
    assert rec._total_samples == 0
    assert rec._last_transcript == ""
    assert rec._silence_start is None
    assert rec._is_speaking is True
    assert rec._last_chunk_time == 0.0
    assert rec._last_final_text == ""


def test_recognizer_default_silence_threshold():
    """Default silence threshold is 2.0 seconds."""
    assert WhisperRecognizer.SILENCE_THRESHOLD_SECONDS == 2.0


def test_recognizer_default_min_audio():
    """Default min audio is 0.5 seconds."""
    assert WhisperRecognizer.MIN_AUDIO_SECONDS == 0.5


def test_recognizer_default_max_buffer():
    """Default max buffer is 30.0 seconds."""
    assert WhisperRecognizer.MAX_BUFFER_SECONDS == 30.0


def test_recognizer_is_silent_empty(mock_model_transcribe):
    """Empty audio is considered silent."""
    rec = WhisperRecognizer(mock_model_transcribe)
    assert rec._is_silent(np.array([], dtype=np.float32)) is True


def test_recognizer_is_silent_low_energy(mock_model_transcribe):
    """Low RMS energy is considered silent."""
    rec = WhisperRecognizer(mock_model_transcribe)
    samples = np.zeros(1600, dtype=np.float32)
    assert rec._is_silent(samples) == True


def test_recognizer_is_silent_high_energy(mock_model_transcribe):
    """High RMS energy is not silent."""
    rec = WhisperRecognizer(mock_model_transcribe)
    samples = np.full(1600, 0.5, dtype=np.float32)
    assert rec._is_silent(samples) == False


def test_recognizer_total_samples_property(mock_model_transcribe):
    """total_samples property returns _total_samples."""
    rec = WhisperRecognizer(mock_model_transcribe)
    rec._total_samples = 42
    assert rec.total_samples == 42


@pytest.mark.parametrize("language,prompt", [
    ("fr", "Transcription en français."),
    ("en", "Transcription in English."),
    ("es", "Transcripción en español."),
    ("de", "Transkription auf Deutsch."),
    ("it", "Trascrizione in italiano."),
    ("pt", "Transcrição em português."),
    ("zh", "中文转录。"),
    ("ja", "日本語のトランスクリプション。"),
    ("ru", "Транскрипция на русском."),
    ("ar", "النقل باللغة العربية."),
])
def test_recognizer_initial_prompt_known_languages(mock_model_transcribe, language, prompt):
    """Known languages return their specific prompt."""
    rec = WhisperRecognizer(mock_model_transcribe, language=language)
    assert rec._initial_prompt() == prompt


def test_recognizer_initial_prompt_unknown_language(mock_model_transcribe):
    """Unknown languages get a generic prompt."""
    rec = WhisperRecognizer(mock_model_transcribe, language="xy")
    assert rec._initial_prompt() == "This is a transcription in xy. Use correct punctuation and grammar."


def test_recognizer_initial_prompt_lowercase(mock_model_transcribe):
    """Language is lowercased before lookup."""
    rec = WhisperRecognizer(mock_model_transcribe, language="FR")
    assert rec._initial_prompt() == "Transcription en français."


# ── Tests: WhisperRecognizer.process_chunk ───────────────────────────────────

def test_process_chunk_not_enough_audio_no_silence(mock_model_transcribe):
    """Without silence threshold met, returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    with patch("time.time", return_value=100.0):
        result = rec.process_chunk(_make_speaking_audio(1600))
    assert result is None


def test_process_chunk_silence_triggers_transcribe(mock_model_transcribe):
    """Silence exceeding threshold triggers transcription."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)

    # First chunk: speaking
    with patch("time.time", return_value=100.0):
        rec.process_chunk(_make_speaking_audio(1600))
    assert rec._is_speaking is True

    # Second chunk: become silent (not enough time yet)
    with patch("time.time", return_value=101.0):
        rec.process_chunk(_make_silent_audio(1600))
    assert rec._silence_start is not None

    # Third chunk: silence exceeds threshold → transcribe
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text="hello world")],
        {"language": "fr"},
    )
    with patch("time.time", return_value=103.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result == {"type": "final", "text": "hello world"}


def test_process_chunk_resets_silence_on_speaking(mock_model_transcribe):
    """Speaking after silence resets silence tracking."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)

    # Become silent
    with patch("time.time", return_value=100.0):
        rec.process_chunk(_make_silent_audio(32000))
    assert rec._silence_start is not None

    # Start speaking again
    with patch("time.time", return_value=101.0):
        rec.process_chunk(_make_speaking_audio(1600))
    assert rec._silence_start is None
    assert rec._is_speaking is True


def test_process_chunk_max_buffer_flush(mock_model_transcribe):
    """Buffer exceeding max size triggers flush."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)

    with patch("time.time", return_value=100.0):
        for _ in range(300):
            rec.process_chunk(_make_speaking_audio(1600))
    assert mock_model_transcribe.transcribe.called


def test_process_chunk_duplicate_transcript_returns_none(mock_model_transcribe):
    """Duplicate transcript returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text="same text")],
        {"language": "fr"},
    )

    # First: become silent to trigger silence tracking
    with patch("time.time", return_value=100.0):
        rec.process_chunk(_make_silent_audio(32000))
    assert rec._silence_start is not None

    # Second: silence exceeds threshold → transcribe
    with patch("time.time", return_value=103.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result == {"type": "final", "text": "same text"}

    # Same transcript again → None
    with patch("time.time", return_value=104.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result is None


def test_process_chunk_transcribe_exception_returns_none(mock_model_transcribe, caplog):
    """Transcription exception returns None and logs warning."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    mock_model_transcribe.transcribe.side_effect = RuntimeError("transcription error")

    with patch("time.time", return_value=103.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result is None


def test_process_chunk_empty_text_segments_returns_none(mock_model_transcribe):
    """Empty text segments return None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text=""), MagicMock(text="   ")],
        {"language": "fr"},
    )

    with patch("time.time", return_value=103.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result is None


def test_process_chunk_multiple_segments_joined(mock_model_transcribe):
    """Multiple segments are joined with spaces."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    segments = [MagicMock(text="hello "), MagicMock(text="world")]
    mock_model_transcribe.transcribe.return_value = (segments, {"language": "fr"})

    # First: become silent to trigger silence tracking
    with patch("time.time", return_value=100.0):
        rec.process_chunk(_make_silent_audio(32000))

    # Second: silence exceeds threshold → transcribe
    with patch("time.time", return_value=103.0):
        result = rec.process_chunk(_make_silent_audio(32000))
    assert result == {"type": "final", "text": "hello world"}


# ── Tests: WhisperRecognizer._transcribe ─────────────────────────────────────

def test_transcribe_not_enough_audio(mock_model_transcribe):
    """Transcription with insufficient audio returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._total_samples = 100
    result = rec._transcribe()
    assert result is None
    assert rec._audio_buffer == []
    assert rec._total_samples == 0


def test_transcribe_success(mock_model_transcribe):
    """Successful transcription returns final result."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._total_samples = 32000
    rec._audio_buffer = [_make_silent_samples(16000)]
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text="test")],
        {"language": "fr"},
    )
    result = rec._transcribe()
    assert result == {"type": "final", "text": "test"}


def test_transcribe_resets_state(mock_model_transcribe):
    """Transcription resets internal state."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._total_samples = 32000
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._silence_start = 100.0
    mock_model_transcribe.transcribe.return_value = ([MagicMock(text="test")], {"language": "fr"})
    rec._transcribe()
    assert rec._audio_buffer == []
    assert rec._total_samples == 0
    assert rec._silence_start is None


def test_transcribe_exception_handled(mock_model_transcribe, caplog):
    """Exception during transcription is logged and returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._total_samples = 32000
    rec._audio_buffer = [_make_silent_samples(16000)]
    mock_model_transcribe.transcribe.side_effect = ValueError("model error")
    result = rec._transcribe()
    assert result is None


# ── Tests: WhisperRecognizer.flush ───────────────────────────────────────────

def test_flush_empty_buffer_returns_none(mock_model_transcribe):
    """Flush with empty buffer returns None."""
    rec = WhisperRecognizer(mock_model_transcribe)
    assert rec.flush() is None


def test_flush_with_buffer(mock_model_transcribe):
    """Flush transcribes remaining buffer."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 32000
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text="flushed text")],
        {"language": "fr"},
    )
    result = rec.flush()
    assert result == "flushed text"


def test_flush_resets_state(mock_model_transcribe):
    """Flush resets internal state."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 32000
    rec._silence_start = 100.0
    mock_model_transcribe.transcribe.return_value = ([MagicMock(text="test")], {"language": "fr"})
    rec.flush()
    assert rec._audio_buffer == []
    assert rec._total_samples == 0
    assert rec._silence_start is None


def test_flush_empty_segments_returns_none(mock_model_transcribe):
    """Flush with empty segments returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 32000
    mock_model_transcribe.transcribe.return_value = ([MagicMock(text="")], {"language": "fr"})
    assert rec.flush() is None


def test_flush_exception_handled(mock_model_transcribe, caplog):
    """Exception during flush is logged."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 32000
    mock_model_transcribe.transcribe.side_effect = RuntimeError("flush error")
    assert rec.flush() is None


def test_flush_duplicate_text_returns_none(mock_model_transcribe):
    """Flush with duplicate text returns None."""
    rec = WhisperRecognizer(mock_model_transcribe, sample_rate=16000)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 32000
    rec._last_transcript = "same text"
    mock_model_transcribe.transcribe.return_value = (
        [MagicMock(text="same text")],
        {"language": "fr"},
    )
    assert rec.flush() is None


# ── Tests: WhisperRecognizer.reset ───────────────────────────────────────────

def test_recognizer_reset(mock_model_transcribe):
    """Reset clears all state."""
    rec = WhisperRecognizer(mock_model_transcribe)
    rec._audio_buffer = [_make_silent_samples(16000)]
    rec._total_samples = 1000
    rec._last_transcript = "hello"
    rec._silence_start = 100.0
    rec._is_speaking = False
    rec._last_final_text = "hello"

    rec.reset()

    assert rec._audio_buffer == []
    assert rec._total_samples == 0
    assert rec._last_transcript == ""
    assert rec._silence_start is None
    assert rec._is_speaking is True
    assert rec._last_final_text == ""


# ── Tests: WhisperEngine initialization ──────────────────────────────────────

def test_engine_init_defaults():
    """Engine initializes with default values."""
    eng = WhisperEngine()
    assert eng._model_path is None
    assert eng._model_size == "small"
    assert eng._language == "fr"
    assert eng._device == "auto"
    assert eng._loaded is False
    assert eng._model is None


def test_engine_init_custom_model_path():
    """Engine accepts a custom model path."""
    eng = WhisperEngine(model_path="/path/to/model")
    assert eng._model_path == "/path/to/model"


def test_engine_init_custom_model_size():
    """Engine accepts a custom model size."""
    eng = WhisperEngine(model_size="base")
    assert eng._model_size == "base"


def test_engine_init_custom_language():
    """Engine accepts a custom language."""
    eng = WhisperEngine(language="en")
    assert eng._language == "en"


def test_engine_init_custom_device():
    """Engine accepts a custom device."""
    eng = WhisperEngine(device="cpu")
    assert eng._device == "cpu"


def test_engine_is_loaded_property():
    """is_loaded returns _loaded status."""
    eng = WhisperEngine()
    assert eng.is_loaded is False
    eng._loaded = True
    assert eng.is_loaded is True


# ── Tests: WhisperEngine.load ────────────────────────────────────────────────

def test_load_already_loaded():
    """Calling load() when already loaded is a no-op."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng.load()
        first_model = eng._model
        eng.load()
        assert eng._model is first_model


def test_load_missing_package():
    """Loading without faster-whisper raises ImportError."""
    with patch.dict(sys.modules, {"faster_whisper": None}):
        eng = WhisperEngine(model_size="tiny")
        with pytest.raises(ImportError):
            eng.load()


def test_load_success():
    """Successful model loading sets all state."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng.load()
        assert eng.is_loaded is True
        assert eng._model is not None


def test_load_uses_model_path_over_size():
    """Model path takes precedence over model size."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_path="/custom/path", model_size="large")
        eng.load()
        wm.assert_called_once()
        assert wm.call_args[0][0] == "/custom/path"


def test_load_cpu_device():
    """Loading with device='cpu' uses int8 compute type."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", device="cpu")
        eng.load()
        kwargs = wm.call_args[1]
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"


def test_load_cuda_device():
    """Loading with device='cuda' uses float16 compute type."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", device="cuda")
        eng.load()
        kwargs = wm.call_args[1]
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "float16"


def test_load_auto_detects_cuda():
    """Auto device detects CUDA when available."""
    with patch("faster_whisper.WhisperModel") as wm, \
         patch("torch.cuda.is_available", return_value=True):
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", device="auto")
        eng.load()
        kwargs = wm.call_args[1]
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "float16"


def test_load_auto_falls_back_to_cpu():
    """Auto device falls back to CPU when CUDA unavailable."""
    with patch("faster_whisper.WhisperModel") as wm, \
         patch("torch.cuda.is_available", return_value=False):
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", device="auto")
        eng.load()
        kwargs = wm.call_args[1]
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"


def test_load_auto_torch_not_installed():
    """Auto device falls back to CPU when torch raises ImportError."""
    with patch("faster_whisper.WhisperModel") as wm, \
         patch.dict("sys.modules", {"torch": None}):
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", device="auto")
        eng.load()
        kwargs = wm.call_args[1]
        assert kwargs["device"] == "cpu"


# ── Tests: WhisperEngine.create_recognizer ───────────────────────────────────

@pytest.mark.asyncio
async def test_create_recognizer_auto_loads():
    """If not loaded, create_recognizer triggers load()."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        assert eng.is_loaded is False
        recognizer = await eng.create_recognizer()
        assert eng.is_loaded is True
        assert isinstance(recognizer, WhisperRecognizer)


@pytest.mark.asyncio
async def test_create_recognizer_passes_language():
    """create_recognizer passes language to WhisperRecognizer."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny", language="en")
        eng.load()
        recognizer = await eng.create_recognizer()
        assert recognizer._language == "en"


@pytest.mark.asyncio
async def test_create_recognizer_reloads_if_model_none():
    """If model is None, create_recognizer triggers load()."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng._loaded = False
        eng._model = None
        recognizer = await eng.create_recognizer()
        assert eng._model is not None
        assert isinstance(recognizer, WhisperRecognizer)


# ── Tests: WhisperEngine.return_recognizer ───────────────────────────────────

@pytest.mark.asyncio
async def test_return_recognizer_resets():
    """Returning a recognizer calls reset()."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng.load()
        recognizer = await eng.create_recognizer()
        recognizer._total_samples = 1000
        await eng.return_recognizer(recognizer)
        assert recognizer._total_samples == 0
        assert recognizer._audio_buffer == []


@pytest.mark.asyncio
async def test_return_recognizer_none_is_safe():
    """Returning None doesn't crash."""
    with patch("faster_whisper.WhisperModel") as wm:
        model = MagicMock()
        wm.return_value = model
        eng = WhisperEngine(model_size="tiny")
        eng.load()
        await eng.return_recognizer(None)


# ── Tests: WhisperEngine.parse_final_result ──────────────────────────────────

def test_parse_final_result_valid():
    """Valid final result returns dict."""
    eng = WhisperEngine()
    result = eng.parse_final_result(json.dumps({"text": "bonjour le monde"}))
    assert result == {"text": "bonjour le monde"}


def test_parse_final_result_empty_text():
    """Empty text returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result(json.dumps({"text": ""}))
    assert result is None


def test_parse_final_result_whitespace_text():
    """Whitespace-only text returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result(json.dumps({"text": "   "}))
    assert result is None


def test_parse_final_result_bad_json():
    """Invalid JSON returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result("not json {{{")
    assert result is None


def test_parse_final_result_not_a_dict():
    """Non-dict result returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result(json.dumps("just a string"))
    assert result is None


def test_parse_final_result_already_dict():
    """Already a dict, passes through."""
    eng = WhisperEngine()
    result = eng.parse_final_result({"text": "hello"})
    assert result == {"text": "hello"}


def test_parse_final_result_already_dict_empty():
    """Already a dict with empty text returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result({"text": ""})
    assert result is None


def test_parse_final_result_type_error():
    """TypeError on parse returns None."""
    eng = WhisperEngine()
    result = eng.parse_final_result(None)
    assert result is None


# ── Tests: WhisperEngine.parse_partial_result ────────────────────────────────

def test_parse_partial_result_valid():
    """Valid partial result returns dict."""
    eng = WhisperEngine()
    result = eng.parse_partial_result(json.dumps({"partial": "bonj"}))
    assert result == {"partial": "bonj"}


def test_parse_partial_result_bad_json():
    """Invalid JSON returns None."""
    eng = WhisperEngine()
    result = eng.parse_partial_result("{invalid")
    assert result is None


def test_parse_partial_result_not_a_dict():
    """Non-dict returns None."""
    eng = WhisperEngine()
    result = eng.parse_partial_result(json.dumps("just text"))
    assert result is None


def test_parse_partial_result_already_dict():
    """Already a dict passes through."""
    eng = WhisperEngine()
    result = eng.parse_partial_result({"partial": "hello"})
    assert result == {"partial": "hello"}


def test_parse_partial_result_type_error():
    """TypeError on parse returns None."""
    eng = WhisperEngine()
    result = eng.parse_partial_result(None)
    assert result is None


# ── Tests: WhisperEngine.get_health_status ───────────────────────────────────

def test_health_status_ready(loaded_engine):
    """Health status is 'ready' when loaded."""
    eng, _, _ = loaded_engine
    status = eng.get_health_status()
    assert status == {"status": "ready"}


def test_health_status_loading():
    """Health status is 'loading' when not loaded."""
    eng = WhisperEngine()
    status = eng.get_health_status()
    assert status == {"status": "loading"}


# ── Tests: BaseEngine interface conformance ──────────────────────────────────

def test_is_subclass_of_base_engine():
    from src.base_engine import BaseEngine
    assert issubclass(WhisperEngine, BaseEngine)


def test_implements_is_loaded():
    eng = WhisperEngine()
    assert hasattr(eng, "is_loaded")
    assert isinstance(type(eng).is_loaded, property)


def test_implements_load():
    eng = WhisperEngine()
    assert callable(eng.load)


def test_implements_create_recognizer():
    eng = WhisperEngine()
    assert callable(eng.create_recognizer)


def test_implements_return_recognizer():
    eng = WhisperEngine()
    assert callable(eng.return_recognizer)


def test_implements_parse_final_result():
    eng = WhisperEngine()
    assert callable(eng.parse_final_result)


def test_implements_parse_partial_result():
    eng = WhisperEngine()
    assert callable(eng.parse_partial_result)


def test_implements_get_health_status():
    eng = WhisperEngine()
    assert callable(eng.get_health_status)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
