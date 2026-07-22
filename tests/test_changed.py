"""Инкрементальный режим (--changed): gitchanged + фильтрация в runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.gitchanged import changed_files
from slopcheck.models import Category, Finding
from slopcheck.registry import Registry
from slopcheck.runner import run
from slopcheck.subprocess_util import ToolExecutionError


# ---------------------------------------------------------------- gitchanged


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(root),  # игнорируем глобальный ~/.gitconfig (hooks и пр.)
        },
    )


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "old.py").write_text("print(1)\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_changed_files_staged(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "new.py").write_text("print(2)\n", encoding="utf-8")
    _git(root, "add", "new.py")
    assert changed_files(root, "staged") == ["new.py"]


def test_changed_files_against_ref(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _git(root, "checkout", "-b", "feature")
    (root / "feat.py").write_text("print(3)\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "feat")
    assert changed_files(root, "main") == ["feat.py"]


def test_changed_files_skips_deleted(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "gone.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "gone.py")
    (root / "gone.py").unlink()  # unstaged-удаление после add
    assert changed_files(root, "staged") == []


def test_changed_files_bad_ref_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(ToolExecutionError):
        changed_files(root, "no-such-ref")


# ------------------------------------------------------------------- runner


class _Recorder(Adapter):
    """Фейк: запоминает полученный files и отдаёт заданные находки."""

    name = "rec"
    category = Category.DEAD_CODE

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings
        self.seen_files: list[str] | None = None

    def is_available(self) -> bool:
        return True

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        self.seen_files = files
        return list(self._findings)


class _ProjectWide(_Recorder):
    """Фейк не-file_scoped адаптера (deptry/knip)."""

    name = "wide"
    file_scoped = False


def _plain_repo(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("print(2)\n", encoding="utf-8")
    return tmp_path


def _finding(file: str, identity: str = "") -> Finding:
    return Finding(
        category=Category.DEAD_CODE,
        tool="t",
        file=file,
        line=1,
        message="x",
        identity=identity,
    )


def test_incremental_passes_files_and_filters_findings(tmp_path: Path) -> None:
    adapter = _Recorder([_finding("a.py"), _finding("b.py")])
    reg = Registry()
    reg.register(adapter)
    result = run(_plain_repo(tmp_path), config=Config(), registry=reg, files=["a.py"])
    assert adapter.seen_files == ["a.py"]
    # Находка по неизменённому b.py срезана центральным фильтром.
    assert {f.file for f in result.report.findings} == {"a.py"}


def test_incremental_skips_project_wide_adapters(tmp_path: Path) -> None:
    adapter = _ProjectWide([_finding("a.py")])
    reg = Registry()
    reg.register(adapter)
    result = run(_plain_repo(tmp_path), config=Config(), registry=reg, files=["a.py"])
    assert result.report.findings == []
    assert any("инкрементальном" in s for s in result.skipped)


def test_incremental_keeps_pair_via_identity(tmp_path: Path) -> None:
    # Дубль: находка висит на неизменённом файле, но вторая сторона пары
    # (в identity) — изменённый. Такая находка должна выжить.
    pair = _finding("b.py", identity="b.py:1-5<->a.py:1-5")
    adapter = _Recorder([pair])
    reg = Registry()
    reg.register(adapter)
    result = run(_plain_repo(tmp_path), config=Config(), registry=reg, files=["a.py"])
    assert len(result.report.findings) == 1


def test_incremental_empty_list_is_empty_report(tmp_path: Path) -> None:
    adapter = _Recorder([_finding("a.py")])
    reg = Registry()
    reg.register(adapter)
    result = run(_plain_repo(tmp_path), config=Config(), registry=reg, files=[])
    assert result.report.findings == []
