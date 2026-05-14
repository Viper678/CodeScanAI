from __future__ import annotations

import time

from app.core.uuid7 import uuid7, uuid7_timestamp_ms


def test_uuid7_sets_version_7() -> None:
    generated = uuid7()

    assert generated.version == 7


def test_uuid7_values_are_monotonic() -> None:
    generated = [uuid7() for _ in range(20)]

    assert [value.int for value in generated] == sorted(value.int for value in generated)
    assert len({value.int for value in generated}) == len(generated)


def test_uuid7_embeds_current_timestamp() -> None:
    before_ms = time.time_ns() // 1_000_000
    generated = uuid7()
    after_ms = time.time_ns() // 1_000_000

    assert before_ms <= uuid7_timestamp_ms(generated) <= after_ms
