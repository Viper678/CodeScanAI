"""UUIDv7 helper for worker-side row inserts.

Mirrors ``apps/api/app/core/uuid7.py`` so worker-inserted rows share the same
time-ordered key shape. (Worker doesn't import api code; see file_types.py.)
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_RAND_MASK = (1 << 74) - 1
_RAND_B_MASK = (1 << 62) - 1
_lock = threading.Lock()
_last_timestamp_ms = -1
_last_random = 0


def uuid7() -> uuid.UUID:
    """Return a monotonic UUIDv7."""

    global _last_timestamp_ms, _last_random

    current_ms = time.time_ns() // 1_000_000

    with _lock:
        timestamp_ms = current_ms if current_ms > _last_timestamp_ms else _last_timestamp_ms
        if timestamp_ms == _last_timestamp_ms:
            random_bits = (_last_random + 1) & _RAND_MASK
        else:
            random_bits = secrets.randbits(74)

        _last_timestamp_ms = timestamp_ms
        _last_random = random_bits

    rand_a = random_bits >> 62
    rand_b = random_bits & _RAND_B_MASK

    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
