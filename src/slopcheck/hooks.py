"""Хуки: Stop-хук Claude Code и git pre-commit поверх `check-changed`.

Stop-хук вызывается в конце каждого хода агента. Новые относительно HEAD
находки возвращаются агенту (exit 2 + stderr), и он чинит их в том же ходе.
Хук не должен мешать работе: вне репозитория с `.slopcheck.yml`, при сбое
или таймауте проверки он молча пропускает ход.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from slopcheck.agent_check import FINDINGS_HEADER
from slopcheck.config import CONFIG_FILENAME

# Время на проверку: хук бежит в конце каждого хода, дольше — мешает работе.
CHECK_TIMEOUT = 120.0
# Таймаут записи в settings.json — с запасом над CHECK_TIMEOUT.
SETTINGS_TIMEOUT = 150
HOOK_COMMAND = "hook claude"
PRE_COMMIT_MARKER = "# slopcheck pre-commit"

_FIX_PROMPT = (
    "slopcheck: твои незакоммиченные правки добавили slop (старый долг не показан).\n"
    "Исправь находки ниже, сохранив поведение кода. Если находка ложная — не обходи её,\n"
    "а скажи пользователю, какое правило стоит добавить в ignore_rules в .slopcheck.yml.\n"
)


@dataclass
class HookDecision:
    """Что хук возвращает Claude Code: код выхода и текст в stderr."""

    exit_code: int
    message: str = ""


def _git_toplevel(cwd: Path) -> Path | None:
    """Корень git-репозитория, содержащего `cwd` (None — не репозиторий)."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 else None


def _slopcheck_cmd() -> list[str]:
    """Как вызвать slopcheck из хука: тот же интерпретатор, что исполняет хук."""
    return [sys.executable, "-m", "slopcheck.cli"]


def claude_stop(payload: dict, timeout: float = CHECK_TIMEOUT) -> HookDecision:
    """Решение Stop-хука по JSON, который Claude Code подаёт на stdin."""
    if payload.get("stop_hook_active"):
        # Агент уже получал находки в этом ходе и отработал их — не зацикливаем.
        return HookDecision(0)
    root = _git_toplevel(Path(payload.get("cwd") or "."))
    if root is None or not (root / CONFIG_FILENAME).exists():
        return HookDecision(0)
    try:
        proc = subprocess.run(
            [*_slopcheck_cmd(), "check-changed", str(root)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return HookDecision(0, f"slopcheck: проверка не уложилась в {timeout:g} с — пропущена.")
    if proc.returncode == 1 and proc.stdout.startswith(FINDINGS_HEADER):
        findings = proc.stdout.split("\n", 1)[1] if "\n" in proc.stdout else ""
        return HookDecision(2, _FIX_PROMPT + findings.strip())
    if proc.returncode != 0:
        return HookDecision(0, f"slopcheck: проверка не выполнена — {proc.stderr.strip()[-300:]}")
    return HookDecision(0)


# ------------------------------------------------------------ установка


def _hook_command() -> str:
    """Команда в settings.json: абсолютный путь к slopcheck, если он в PATH."""
    return f"{shutil.which('slopcheck') or 'slopcheck'} {HOOK_COMMAND}"


def install_claude(settings_path: Path) -> str:
    """Добавить Stop-хук в settings.json Claude Code (идемпотентно, с бэкапом)."""
    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    stop_groups = settings.setdefault("hooks", {}).setdefault("Stop", [])
    for group in stop_groups:
        for hook in group.get("hooks", []):
            if hook.get("command", "").endswith(HOOK_COMMAND) and "slopcheck" in hook["command"]:
                return f"уже установлен: {settings_path}"
    stop_groups.append(
        {"hooks": [{"type": "command", "command": _hook_command(), "timeout": SETTINGS_TIMEOUT}]}
    )
    if settings_path.exists():
        backup = settings_path.with_name(settings_path.name + ".bak-slopcheck")
        shutil.copy2(settings_path, backup)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return f"Stop-хук добавлен: {settings_path}"


def install_git(repo: Path, force: bool = False) -> str:
    """Записать pre-commit хук git, зовущий `check-changed --staged`.

    Raises:
        FileExistsError: чужой pre-commit уже есть, а `force` не задан.
        ValueError: `repo` — не git-репозиторий.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"{repo}: не git-репозиторий")
    hooks_dir = Path(proc.stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = repo / hooks_dir
    hook = hooks_dir / "pre-commit"
    if hook.exists() and PRE_COMMIT_MARKER not in hook.read_text(encoding="utf-8", errors="replace"):
        if not force:
            raise FileExistsError(f"{hook} уже есть и он не от slopcheck (перезаписать — --force)")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        f"#!/bin/sh\n{PRE_COMMIT_MARKER}\nexec slopcheck check-changed --staged .\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return f"pre-commit хук записан: {hook}"
