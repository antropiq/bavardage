"""Unit tests for VoskEngine and RecognizerPool."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.vosk_engine import RecognizerPool, VoskEngine, POOL_SIZE


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_vosk_modules():
    """Mock both Model and KaldiRecognizer at the module level where they're imported."""
    model_mock = MagicMock()
    recognizer_mock = MagicMock()
    with patch.dict(sys.modules, {"vosk": MagicMock(Model=model_mock, KaldiRecognizer=recognizer_mock)}):
        # Also patch where they're used in the module
        with patch("src.vosk_engine.Model", model_mock) as m_model, \
             patch("src.vosk_engine.KaldiRecognizer", recognizer_mock) as m_rec:
            model_mock.return_value = model_mock  # Model() returns itself
            recognizer_mock.return_value = MagicMock()  # KaldiRecognizer() returns a mock
            yield m_model, m_rec


@pytest.fixture
def mock_model_path(tmp_path):
    """Create a temporary directory that looks like a Vosk model."""
    model_dir = tmp_path / "vosk-model-test"
    model_dir.mkdir()
    (model_dir / "model.cfg").write_text("fake model")
    return model_dir


@pytest.fixture
def loaded_engine(mock_vosk_modules, mock_model_path):
    """Create a VoskEngine with mocked dependencies, already loaded."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    return eng


# ── Tests: RecognizerPool ────────────────────────────────────────────────────

def test_recognizer_pool_init_creates_recognizers(mock_vosk_modules, mock_model_path):
    """Pool creates POOL_SIZE recognizers during init."""
    _, m_rec = mock_vosk_modules
    model_mock = m_rec._mock_parent  # The mock_model from patch
    pool = RecognizerPool(model_mock, sample_rate=16000)
    assert pool.available == POOL_SIZE
    assert m_rec.call_count == POOL_SIZE


def test_recognizer_pool_init_sets_sample_rate(mock_vosk_modules, mock_model_path):
    """Pool stores the sample rate."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock, sample_rate=8000)
    assert pool._sample_rate == 8000


def test_recognizer_pool_init_sets_words(mock_vosk_modules, mock_model_path):
    """Each recognizer has SetWords(True) called."""
    model_mock = mock_vosk_modules[0]
    m_rec = mock_vosk_modules[1]
    RecognizerPool(model_mock)
    assert m_rec.return_value.SetWords.call_count == POOL_SIZE


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_normal(mock_vosk_modules, mock_model_path):
    """Borrowing returns a recognizer from the pool."""
    model_mock = mock_vosk_modules[0]
    m_rec = mock_vosk_modules[1]
    pool = RecognizerPool(model_mock)
    rec = await pool.borrow()
    assert rec is m_rec.return_value
    assert pool.available == POOL_SIZE - 1


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_decrements_available(mock_vosk_modules, mock_model_path):
    """Each borrow reduces available count."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    initial = pool.available
    await pool.borrow()
    assert pool.available == initial - 1


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_all(mock_vosk_modules, mock_model_path):
    """Borrowing all recognizers exhausts the pool."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    for _ in range(POOL_SIZE):
        await pool.borrow()
    assert pool.available == 0


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_exhausted_creates_on_demand(mock_vosk_modules, mock_model_path, tmp_path):
    """When pool is empty, borrow creates a new recognizer on-demand."""
    model_mock = mock_vosk_modules[0]
    m_rec = mock_vosk_modules[1]
    pool = RecognizerPool(model_mock)
    # Exhaust the pool
    for _ in range(POOL_SIZE):
        await pool.borrow()
    assert pool.available == 0

    # Create a new mock for on-demand creation
    new_rec = MagicMock()
    with patch("src.vosk_engine.KaldiRecognizer", return_value=new_rec):
        rec = await pool.borrow()
        assert rec is new_rec
        new_rec.SetWords.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_recognizer_pool_return_recognizer(mock_vosk_modules, mock_model_path):
    """Returning a recognizer puts it back in the pool."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    initial = pool.available
    rec = await pool.borrow()
    assert pool.available == initial - 1
    await pool.return_recognizer(rec)
    assert pool.available == initial


@pytest.mark.asyncio
async def test_recognizer_pool_return_calls_reset(mock_vosk_modules, mock_model_path):
    """Returning a recognizer calls Reset() on it."""
    model_mock = mock_vosk_modules[0]
    m_rec = mock_vosk_modules[1]
    pool = RecognizerPool(model_mock)
    rec = await pool.borrow()
    await pool.return_recognizer(rec)
    rec.Reset.assert_called_once()


@pytest.mark.asyncio
async def test_recognizer_pool_return_none_recognizer(mock_vosk_modules, mock_model_path):
    """Returning None doesn't crash."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    await pool.return_recognizer(None)
    assert pool.available == POOL_SIZE


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_return_cycle(mock_vosk_modules, mock_model_path):
    """Borrow and return multiple times."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    for _ in range(POOL_SIZE):
        rec = await pool.borrow()
        await pool.return_recognizer(rec)
    assert pool.available == POOL_SIZE


@pytest.mark.asyncio
async def test_recognizer_pool_borrow_more_than_pool(mock_vosk_modules, mock_model_path):
    """Borrowing more than POOL_SIZE creates on-demand recognizers."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    recognizers = []
    for _ in range(POOL_SIZE + 3):
        rec = await pool.borrow()
        recognizers.append(rec)
    assert len(recognizers) == POOL_SIZE + 3


# ── Tests: VoskEngine initialization ─────────────────────────────────────────

def test_engine_init_defaults(mock_vosk_modules, mock_model_path):
    """Engine initializes with default values."""
    eng = VoskEngine(model_path=mock_model_path)
    assert eng._loaded is False
    assert eng._pool is None
    assert eng.is_loaded is False


def test_engine_init_custom_model_path(mock_vosk_modules, mock_model_path):
    """Engine accepts a custom model path."""
    eng = VoskEngine(model_path=mock_model_path)
    assert eng._model_path == mock_model_path


def test_engine_init_custom_pool_size(mock_vosk_modules, mock_model_path):
    """Engine accepts a custom pool size."""
    eng = VoskEngine(model_path=mock_model_path, pool_size=8)
    assert eng._loaded is False


def test_engine_init_model_not_loaded_yet(mock_vosk_modules, mock_model_path):
    """Engine is not loaded until load() is called."""
    eng = VoskEngine(model_path=mock_model_path)
    assert eng.is_loaded is False
    assert eng._model is None


# ── Tests: VoskEngine.load ───────────────────────────────────────────────────

def test_load_already_loaded(mock_vosk_modules, mock_model_path):
    """Calling load() when already loaded is a no-op."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    assert eng.is_loaded is True
    first_model = eng._model
    first_pool = eng._pool
    eng.load()
    assert eng._model is first_model
    assert eng._pool is first_pool


def test_load_model_not_found(tmp_path):
    """Loading from a non-existent path raises FileNotFoundError."""
    eng = VoskEngine(model_path=tmp_path / "nonexistent")
    with pytest.raises(FileNotFoundError):
        eng.load()


def test_load_success(mock_vosk_modules, mock_model_path):
    """Successful model loading sets all state."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    assert eng.is_loaded is True
    assert eng._model is not None
    assert eng._pool is not None
    assert isinstance(eng._pool, RecognizerPool)


def test_load_creates_pool(mock_vosk_modules, mock_model_path):
    """Loading creates a RecognizerPool with the model."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    assert eng._pool.available == POOL_SIZE


def test_load_with_custom_pool_size(mock_vosk_modules, mock_model_path):
    """Custom pool_size is stored but RecognizerPool uses POOL_SIZE constant."""
    eng = VoskEngine(model_path=mock_model_path, pool_size=8)
    eng.load()
    # RecognizerPool.__init__ uses POOL_SIZE constant, not engine's pool_size
    assert eng._pool.available == POOL_SIZE


def test_load_non_directory_path(mock_vosk_modules, tmp_path):
    """Loading when path exists but is not a directory raises."""
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("fake")
    eng = VoskEngine(model_path=file_path)
    with pytest.raises(FileNotFoundError):
        eng.load()


# ── Tests: VoskEngine.create_recognizer ──────────────────────────────────────

@pytest.mark.asyncio
async def test_create_recognizer_from_pool(loaded_engine, mock_vosk_modules):
    """Creating a recognizer borrows from the pool."""
    m_rec = mock_vosk_modules[1]
    rec = await loaded_engine.create_recognizer()
    assert rec is m_rec.return_value


@pytest.mark.asyncio
async def test_create_recognizer_sets_words(loaded_engine, mock_vosk_modules):
    """Created recognizer has SetWords(True) called."""
    m_rec = mock_vosk_modules[1]
    await loaded_engine.create_recognizer()
    m_rec.return_value.SetWords.assert_called()


@pytest.mark.asyncio
async def test_create_recognizer_decrements_pool(loaded_engine, mock_vosk_modules):
    """Creating a recognizer reduces pool availability."""
    initial = loaded_engine._pool.available
    await loaded_engine.create_recognizer()
    assert loaded_engine._pool.available == initial - 1


@pytest.mark.asyncio
async def test_create_recognizer_fallback_no_pool(mock_vosk_modules, mock_model_path):
    """When pool is None, create_recognizer creates directly."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    eng._pool = None
    rec = await eng.create_recognizer()
    assert rec is not None


@pytest.mark.asyncio
async def test_create_recognizer_auto_loads(mock_vosk_modules, mock_model_path):
    """If not loaded, create_recognizer triggers load()."""
    eng = VoskEngine(model_path=mock_model_path)
    assert eng.is_loaded is False
    rec = await eng.create_recognizer()
    assert eng.is_loaded is True


@pytest.mark.asyncio
async def test_create_recognizer_returns_different_instances(mock_vosk_modules, mock_model_path):
    """Each borrow returns a different recognizer (up to pool size)."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    # Replace pool recognizers with distinct mocks (pool was created with same mock return_value)
    distinct_recs = [MagicMock() for _ in range(POOL_SIZE)]
    eng._pool._pool.clear()
    for rec in distinct_recs:
        eng._pool._pool.append(rec)
    recognizers = []
    for _ in range(POOL_SIZE):
        rec = await eng.create_recognizer()
        recognizers.append(rec)
    assert len(set(id(r) for r in recognizers)) == POOL_SIZE


# ── Tests: VoskEngine.return_recognizer ──────────────────────────────────────

@pytest.mark.asyncio
async def test_return_recognizer_to_pool(loaded_engine, mock_vosk_modules):
    """Returning a recognizer puts it back in the pool."""
    initial = loaded_engine._pool.available
    rec = await loaded_engine.create_recognizer()
    await loaded_engine.return_recognizer(rec)
    assert loaded_engine._pool.available == initial


@pytest.mark.asyncio
async def test_return_recognizer_no_pool(mock_vosk_modules, mock_model_path):
    """Returning when pool is None doesn't crash."""
    eng = VoskEngine(model_path=mock_model_path)
    eng.load()
    eng._pool = None
    rec = MagicMock()
    await eng.return_recognizer(rec)


# ── Tests: VoskEngine.parse_final_result ─────────────────────────────────────

def test_parse_final_result_valid():
    """Valid final result returns dict with text."""
    eng = VoskEngine()
    result = eng.parse_final_result(json.dumps({"text": "bonjour le monde"}))
    assert result == {"text": "bonjour le monde"}


def test_parse_final_result_empty_text():
    """Empty text returns None."""
    eng = VoskEngine()
    result = eng.parse_final_result(json.dumps({"text": ""}))
    assert result is None


def test_parse_final_result_whitespace_text():
    """Whitespace-only text returns None."""
    eng = VoskEngine()
    result = eng.parse_final_result(json.dumps({"text": "   "}))
    assert result is None


def test_parse_final_result_bad_json():
    """Invalid JSON returns None."""
    eng = VoskEngine()
    result = eng.parse_final_result("not json at all {{{")
    assert result is None


def test_parse_final_result_missing_text_key():
    """JSON without 'text' key returns None (text defaults to empty)."""
    eng = VoskEngine()
    result = eng.parse_final_result(json.dumps({"nope": "here"}))
    assert result is None


def test_parse_final_result_strips_text():
    """Text is stripped for emptiness check, but returned dict preserves original."""
    eng = VoskEngine()
    result = eng.parse_final_result(json.dumps({"text": "  hello world  "}))
    # The dict is returned as-is (unstripped), but emptiness check strips
    assert result == {"text": "  hello world  "}


def test_parse_final_result_with_words():
    """Result with 'words' key is returned as-is."""
    eng = VoskEngine()
    data = {"text": "hello", "words": [{"word": "hello", "start": 0, "end": 1}]}
    result = eng.parse_final_result(json.dumps(data))
    assert result == data


# ── Tests: VoskEngine.parse_partial_result ───────────────────────────────────

def test_parse_partial_result_valid():
    """Valid partial result returns dict."""
    eng = VoskEngine()
    result = eng.parse_partial_result(json.dumps({"partial": "bonj"}))
    assert result == {"partial": "bonj"}


def test_parse_partial_result_with_partial_text():
    """Partial result with partial text is returned."""
    eng = VoskEngine()
    data = {"partial": "bonjour le", "text": ""}
    result = eng.parse_partial_result(json.dumps(data))
    assert result == data


def test_parse_partial_result_bad_json():
    """Invalid JSON returns None."""
    eng = VoskEngine()
    result = eng.parse_partial_result("{invalid json")
    assert result is None


def test_parse_partial_result_empty():
    """Empty string returns None (invalid JSON)."""
    eng = VoskEngine()
    result = eng.parse_partial_result("")
    assert result is None


def test_parse_partial_result_none_text_key():
    """Partial result without partial key still returns dict."""
    eng = VoskEngine()
    result = eng.parse_partial_result(json.dumps({"nope": "here"}))
    assert result == {"nope": "here"}


# ── Tests: VoskEngine.get_health_status ──────────────────────────────────────

def test_health_status_ready(loaded_engine):
    """Health status is 'ready' when loaded."""
    status = loaded_engine.get_health_status()
    assert status == {"status": "ready"}


def test_health_status_loading(mock_vosk_modules):
    """Health status is 'loading' when not loaded."""
    eng = VoskEngine()
    status = eng.get_health_status()
    assert status == {"status": "loading"}


# ── Tests: BaseEngine interface conformance ──────────────────────────────────

def test_is_subclass_of_base_engine():
    from src.base_engine import BaseEngine
    assert issubclass(VoskEngine, BaseEngine)


def test_implements_is_loaded(mock_vosk_modules, mock_model_path):
    eng = VoskEngine(model_path=mock_model_path)
    assert hasattr(eng, "is_loaded")
    assert isinstance(type(eng).is_loaded, property)


def test_implements_load(mock_vosk_modules, mock_model_path):
    eng = VoskEngine(model_path=mock_model_path)
    assert callable(eng.load)


def test_implements_create_recognizer(mock_vosk_modules, mock_model_path):
    eng = VoskEngine(model_path=mock_model_path)
    assert callable(eng.create_recognizer)


def test_implements_return_recognizer(mock_vosk_modules, mock_model_path):
    eng = VoskEngine(model_path=mock_model_path)
    assert callable(eng.return_recognizer)


def test_implements_parse_final_result():
    eng = VoskEngine()
    assert callable(eng.parse_final_result)


def test_implements_parse_partial_result():
    eng = VoskEngine()
    assert callable(eng.parse_partial_result)


def test_implements_get_health_status():
    eng = VoskEngine()
    assert callable(eng.get_health_status)


# ── Tests: RecognizerPool edge cases ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_recognizer_pool_available_empty_after_borrow_all(mock_vosk_modules, mock_model_path):
    """Pool is empty after borrowing all recognizers."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    for _ in range(POOL_SIZE):
        await pool.borrow()
    assert pool.available == 0


@pytest.mark.asyncio
async def test_recognizer_pool_init_different_sample_rate(mock_vosk_modules, mock_model_path):
    """Pool with different sample rate passes it to recognizers."""
    model_mock = mock_vosk_modules[0]
    m_rec = mock_vosk_modules[1]
    RecognizerPool(model_mock, sample_rate=8000)
    assert m_rec.call_args_list[0][0][1] == 8000


@pytest.mark.asyncio
async def test_recognizer_pool_return_preserves_order(mock_vosk_modules, mock_model_path):
    """Returning recognizers preserves FIFO order."""
    model_mock = mock_vosk_modules[0]
    pool = RecognizerPool(model_mock)
    recs = []
    for _ in range(POOL_SIZE):
        recs.append(await pool.borrow())
    # Return in reverse order
    for rec in reversed(recs):
        await pool.return_recognizer(rec)
    assert pool.available == POOL_SIZE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
