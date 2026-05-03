"""Binary-detection heuristic: NUL byte and non-text-byte ratio."""

from __future__ import annotations

from pathlib import Path

from worker.files.classify import classify, is_binary


def test_is_binary_for_nul_byte(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"hello\x00world")
    assert is_binary(path) is True


def test_is_binary_for_high_non_text_ratio(tmp_path: Path) -> None:
    path = tmp_path / "noisy.bin"
    # > 30% bytes outside the text set; avoid NUL so we exercise the ratio
    # branch specifically. 0x01..0x07 are control bytes excluded from the set.
    payload = bytes(range(0x01, 0x08)) * 200  # 1400 bytes, all non-text
    path.write_bytes(payload)
    assert is_binary(path) is True


def test_is_binary_false_for_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "hello.py"
    path.write_text("print('hello, world')\n", encoding="utf-8")
    assert is_binary(path) is False


def test_is_binary_false_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.touch()
    assert is_binary(path) is False


def test_is_binary_false_for_high_byte_utf8(tmp_path: Path) -> None:
    # Non-ASCII UTF-8 is text; bytes in 0x80-0xFF count as text in our heuristic.
    path = tmp_path / "umlauts.txt"
    path.write_text("héllo wörld" * 100, encoding="utf-8")
    assert is_binary(path) is False


def test_classify_marks_binary_excluded(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    blob = root / "data.bin"
    blob.write_bytes(b"\x00" * 1024)

    meta = classify(blob, root)
    assert meta.is_binary is True
    assert meta.is_excluded_by_default is True
    assert meta.excluded_reason == "binary"
    assert meta.language is None
