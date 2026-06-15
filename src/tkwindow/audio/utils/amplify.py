"""Volume amplification for raw int16 PCM samples."""

from __future__ import annotations

import numpy as np


def amplify(data: bytes, volume: float) -> bytes:
    """Amplify raw int16 PCM samples by the given volume factor."""
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()
