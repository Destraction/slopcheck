"""Тесты детекта языков репозитория."""

from __future__ import annotations

from pathlib import Path

from slopcheck.languages import detect


def _touch(root: Path, rel: str) -> None:
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("x", encoding="utf-8")


def test_detect_multiple_languages(tmp_path: Path) -> None:
    _touch(tmp_path, "src/app.py")
    _touch(tmp_path, "web/index.ts")
    _touch(tmp_path, "web/util.jsx")
    _touch(tmp_path, "cmd/main.go")
    langs = detect(tmp_path)
    assert langs == ["go", "javascript", "python", "typescript"]


def test_detect_skips_vendor_dirs(tmp_path: Path) -> None:
    _touch(tmp_path, "src/app.py")
    _touch(tmp_path, "node_modules/pkg/index.js")
    _touch(tmp_path, ".venv/lib/thing.py")
    langs = detect(tmp_path)
    assert langs == ["python"]  # только src/app.py, node_modules пропущен


def test_detect_respects_ignore(tmp_path: Path) -> None:
    _touch(tmp_path, "src/app.py")
    _touch(tmp_path, "generated/schema.ts")
    langs = detect(tmp_path, ignore=["generated"])
    assert langs == ["python"]


def test_detect_empty_repo(tmp_path: Path) -> None:
    assert detect(tmp_path) == []
