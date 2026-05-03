"""Coverage for every row of the default-exclusion table in FILE_HANDLING.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from worker.files.classify import classify


def _make(root: Path, rel: str, body: bytes | str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_bytes(body)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "extract"


def test_oversize_excluded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Lower the cap so the test stays fast.
    monkeypatch.setattr("worker.files.classify.settings.max_scan_file_size_mb", 0)
    f = _make(root, "big.py", "x" * 10)
    meta = classify(f, root)
    assert meta.excluded_reason == "oversize"
    assert meta.is_excluded_by_default is True


def test_vendor_dir_node_modules(root: Path) -> None:
    f = _make(root, "node_modules/lodash/index.js", "module.exports = {};\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "vendor_dir"


def test_vendor_dir_pycache(root: Path) -> None:
    # Use plaintext so the binary heuristic doesn't intercept first.
    f = _make(root, "src/__pycache__/foo.cpython-312.pyc", "fake-pyc\n")
    meta = classify(f, root)
    # __pycache__ should win over the .pyc build_artifact rule because vendor
    # dir matching beats extension matching.
    assert meta.excluded_reason == "vendor_dir"


def test_vcs_dir(root: Path) -> None:
    f = _make(root, ".git/HEAD", "ref: refs/heads/main\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "vcs_dir"


def test_ide_dir(root: Path) -> None:
    f = _make(root, ".vscode/settings.json", "{}\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "ide_dir"


def test_lockfile(root: Path) -> None:
    f = _make(root, "package-lock.json", "{}\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "lockfile"


def test_build_artifact_extension(root: Path) -> None:
    # Plain text content so we exercise the build_artifact rule (binary check
    # would otherwise win — see priority table in FILE_HANDLING.md).
    f = _make(root, "foo.class", "fake-class\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "build_artifact"


def test_build_artifact_min_js(root: Path) -> None:
    f = _make(root, "vendor/x.min.js", "var x=1;\n")
    # vendor dir wins over build_artifact per priority order.
    meta = classify(f, root)
    assert meta.excluded_reason == "vendor_dir"


def test_build_artifact_min_js_at_root(root: Path) -> None:
    f = _make(root, "x.min.js", "var x=1;\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "build_artifact"


def test_image_extension(root: Path) -> None:
    # Plain text disguised as png so we exercise the ext rule, not binary.
    f = _make(root, "logo.png", "fake-png")
    meta = classify(f, root)
    assert meta.excluded_reason == "image"


def test_font_extension(root: Path) -> None:
    f = _make(root, "fonts/Inter.woff2", "fake")
    meta = classify(f, root)
    assert meta.excluded_reason == "font"


def test_media_extension(root: Path) -> None:
    f = _make(root, "demo.mp3", "fake")
    meta = classify(f, root)
    assert meta.excluded_reason == "media"


def test_archive_extension(root: Path) -> None:
    f = _make(root, "nested.tar.gz", "fake")
    meta = classify(f, root)
    assert meta.excluded_reason == "archive"


def test_dotfile(root: Path) -> None:
    f = _make(root, ".prettierrc", "{}\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "dotfile"


def test_dotfile_env_is_scanned(root: Path) -> None:
    # `.env` is allowlisted so the security scanner can hunt for secrets.
    f = _make(root, ".env", "API_KEY=fake\n")
    meta = classify(f, root)
    assert meta.is_excluded_by_default is False
    assert meta.excluded_reason is None


def test_dotfile_gitignore_is_scanned(root: Path) -> None:
    f = _make(root, ".gitignore", "*.log\n")
    meta = classify(f, root)
    assert meta.is_excluded_by_default is False


def test_unknown_extension(root: Path) -> None:
    f = _make(root, "weird.xyzqq", "hello\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "unknown_ext"


def test_no_extension_unknown(root: Path) -> None:
    f = _make(root, "BUILD", "filegroup(...)\n")
    meta = classify(f, root)
    assert meta.excluded_reason == "unknown_ext"


def test_dockerfile_is_scanned(root: Path) -> None:
    f = _make(root, "Dockerfile", "FROM python:3.12\n")
    meta = classify(f, root)
    assert meta.is_excluded_by_default is False
    assert meta.language == "dockerfile"


def test_python_source_is_scanned(root: Path) -> None:
    f = _make(root, "src/main.py", "print('hi')\n")
    meta = classify(f, root)
    assert meta.is_excluded_by_default is False
    assert meta.language == "python"
    assert meta.parent_path == "src"
    assert meta.name == "main.py"
    assert meta.path == "src/main.py"
    assert meta.sha256  # populated
