"""check-changed: только новые относительно HEAD находки незакоммиченных правок."""

from __future__ import annotations

import subprocess
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.agent_check import check, format_text
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.registry import Registry

_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        env={**_ENV, "HOME": str(root)},
    )


class _MarkerAdapter(Adapter):
    """Находка на каждую строку со словом SLOP (INFO — со словом note)."""

    name = "marker"
    category = Category.COMPLEXITY

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def is_available(self) -> bool:
        return True

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        self.calls.append(root)
        findings = []
        for rel in files or []:
            for no, text in enumerate((root / rel).read_text().splitlines(), 1):
                if "SLOP" in text:
                    findings.append(Finding(
                        category=Category.COMPLEXITY, tool="marker", file=rel, line=no,
                        message="маркер", rule_id="marker",
                        severity=Severity.INFO if "note" in text else Severity.WARN,
                        identity=text.strip(),
                    ))
        return findings


def _setup(tmp_path: Path) -> tuple[Path, Registry, _MarkerAdapter]:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "old.py").write_text("x = 1  # SLOP old debt\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    adapter = _MarkerAdapter()
    registry = Registry()
    registry.register(adapter)
    return tmp_path, registry, adapter


def test_only_new_findings_in_changed_file(tmp_path: Path) -> None:
    root, registry, _ = _setup(tmp_path)
    (root / "old.py").write_text("x = 1  # SLOP old debt\ny = 2  # SLOP fresh\n")
    result = check(root, config=Config(), registry=registry)
    assert [f.identity for f in result.new] == ["y = 2  # SLOP fresh"]
    assert "old.py:2 [warn] marker — маркер" in format_text(result)


def test_untracked_file_counts_and_is_new(tmp_path: Path) -> None:
    root, registry, _ = _setup(tmp_path)
    (root / "new.py").write_text("z = 3  # SLOP\n")
    result = check(root, config=Config(), registry=registry)
    assert [f.file for f in result.new] == ["new.py"]


def test_clean_changes_skip_head_run(tmp_path: Path) -> None:
    """Нет кандидатов — worktree на HEAD не создаётся (хук остаётся быстрым)."""
    root, registry, adapter = _setup(tmp_path)
    (root / "old.py").write_text("clean = True\n")
    result = check(root, config=Config(), registry=registry)
    assert result.new == [] and result.files == ["old.py"]
    assert adapter.calls == [root.resolve()]


def test_below_hook_severity_ignored(tmp_path: Path) -> None:
    root, registry, _ = _setup(tmp_path)
    (root / "new.py").write_text("a = 1  # SLOP note\n")
    assert check(root, config=Config(), registry=registry).new == []
    info_cfg = Config(hook_severity=Severity.INFO)
    assert len(check(root, config=info_cfg, registry=registry).new) == 1


def test_staged_mode_only_index(tmp_path: Path) -> None:
    root, registry, _ = _setup(tmp_path)
    (root / "staged.py").write_text("s = 1  # SLOP\n")
    (root / "unstaged.py").write_text("u = 1  # SLOP\n")
    _git(root, "add", "staged.py")
    result = check(root, staged=True, config=Config(), registry=registry)
    assert [f.file for f in result.new] == ["staged.py"]


def test_no_head_everything_is_new(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1  # SLOP\n")
    registry = Registry()
    registry.register(_MarkerAdapter())
    assert len(check(tmp_path, config=Config(), registry=registry).new) == 1


def test_head_worktree_removed(tmp_path: Path) -> None:
    root, registry, _ = _setup(tmp_path)
    (root / "old.py").write_text("x = 1  # SLOP old debt\ny = 2  # SLOP fresh\n")
    check(root, config=Config(), registry=registry)
    out = subprocess.run(
        ["git", "-C", str(root), "worktree", "list"], capture_output=True, text=True, check=True
    ).stdout
    assert len(out.strip().splitlines()) == 1


def test_works_inside_git_hook_env(tmp_path: Path, monkeypatch) -> None:
    """В pre-commit git выставляет GIT_INDEX_FILE: worktree на HEAD всё равно создаётся."""
    import os

    root, registry, _ = _setup(tmp_path)
    (root / "old.py").write_text("x = 1  # SLOP old debt\ny = 2  # SLOP fresh\n")
    _git(root, "add", "old.py")
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / ".git" / "index"))
    result = check(root, staged=True, config=Config(), registry=registry)
    assert [f.identity for f in result.new] == ["y = 2  # SLOP fresh"]
    assert os.environ["GIT_INDEX_FILE"] == str(root / ".git" / "index")
