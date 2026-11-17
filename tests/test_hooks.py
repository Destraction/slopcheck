"""Stop-хук Claude Code и установка хуков."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from slopcheck import hooks
from slopcheck.hooks import claude_stop, install_claude, install_git

_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _repo(tmp_path: Path, config: bool = True) -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
        env={**_ENV, "HOME": str(tmp_path)},
    )
    if config:
        (tmp_path / ".slopcheck.yml").write_text("{}\n")
    return tmp_path


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _fake_check(monkeypatch, proc: _Proc | Exception) -> list[list[str]]:
    """Подменить запуск check-changed (git rev-parse оставить настоящим)."""
    calls: list[list[str]] = []
    real_run = subprocess.run

    def fake(cmd, **kw):
        if "check-changed" in cmd:
            calls.append(cmd)
            if isinstance(proc, Exception):
                raise proc
            return proc
        return real_run(cmd, **kw)

    monkeypatch.setattr(hooks.subprocess, "run", fake)
    return calls


def test_stop_hook_active_never_blocks(tmp_path, monkeypatch) -> None:
    calls = _fake_check(monkeypatch, _Proc(1, "x\na.ts:1 [warn] r — m"))
    decision = claude_stop({"cwd": str(_repo(tmp_path)), "stop_hook_active": True})
    assert decision.exit_code == 0 and calls == []


def test_silent_without_config(tmp_path, monkeypatch) -> None:
    calls = _fake_check(monkeypatch, _Proc(1, "x\ny"))
    assert claude_stop({"cwd": str(_repo(tmp_path, config=False))}).exit_code == 0
    assert calls == []


def test_silent_outside_git(tmp_path, monkeypatch) -> None:
    calls = _fake_check(monkeypatch, _Proc(1, "x\ny"))
    assert claude_stop({"cwd": str(tmp_path)}).exit_code == 0
    assert calls == []


def test_findings_block_with_fix_prompt(tmp_path, monkeypatch) -> None:
    _fake_check(monkeypatch, _Proc(1, "❌ slopcheck: правки добавили slop — 1:\na.ts:7 [warn] no-empty — пусто"))
    decision = claude_stop({"cwd": str(_repo(tmp_path))})
    assert decision.exit_code == 2
    assert "a.ts:7 [warn] no-empty — пусто" in decision.message
    assert "ignore_rules" in decision.message
    assert "❌" not in decision.message


def test_failure_and_timeout_do_not_block(tmp_path, monkeypatch) -> None:
    root = str(_repo(tmp_path))
    _fake_check(monkeypatch, _Proc(2, stderr="не git"))
    assert claude_stop({"cwd": root}).exit_code == 0
    # Падение Python тоже даёт код 1, но без заголовка находок — агенту не отдаём.
    _fake_check(monkeypatch, _Proc(1, stderr="Traceback …\nTypeError: …"))
    decision = claude_stop({"cwd": root})
    assert decision.exit_code == 0 and "не выполнена" in decision.message
    _fake_check(monkeypatch, subprocess.TimeoutExpired(cmd="x", timeout=1))
    decision = claude_stop({"cwd": root}, timeout=1)
    assert decision.exit_code == 0 and "не уложилась" in decision.message


def test_install_claude_idempotent_with_backup(tmp_path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
    install_claude(settings)
    assert "уже установлен" in install_claude(settings)
    data = json.loads(settings.read_text())
    commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert commands[0] == "other"
    assert sum(c.endswith("slopcheck hook claude") or c == "slopcheck hook claude" for c in commands) == 1
    assert data["model"] == "x"
    assert (tmp_path / "settings.json.bak-slopcheck").exists()


def test_install_claude_creates_missing_file(tmp_path) -> None:
    settings = tmp_path / "sub" / "settings.json"
    install_claude(settings)
    assert json.loads(settings.read_text())["hooks"]["Stop"][0]["hooks"][0]["timeout"] == hooks.SETTINGS_TIMEOUT


def test_install_git_respects_foreign_hook(tmp_path) -> None:
    root = _repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(FileExistsError):
        install_git(root)
    install_git(root, force=True)
    assert "check-changed --staged" in hook.read_text()
    # Свой хук перезаписывается без --force (повторная установка).
    install_git(root)
    assert hook.stat().st_mode & 0o111
