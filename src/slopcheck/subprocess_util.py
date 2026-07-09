"""Безопасный запуск внешних детекторов.

Тулы вызываются как subprocess. Здесь — единая точка с таймаутом, аккуратной
обработкой отсутствующего бинарника и захватом stdout/stderr.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ToolNotFound(Exception):
    """Бинарник детектора не найден в PATH."""


@dataclass
class ToolResult:
    """Результат запуска внешнего тула."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def tool_available(binary: str) -> bool:
    """Есть ли исполняемый файл `binary` в PATH."""
    return shutil.which(binary) is not None


def run_tool(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: float = 300.0,
) -> ToolResult:
    """Запустить внешний тул `cmd`.

    Raises:
        ToolNotFound: если бинарника нет в PATH.
    """
    if not cmd:
        raise ValueError("cmd не может быть пустым")
    if not tool_available(cmd[0]):
        raise ToolNotFound(cmd[0])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolResult(
            returncode=-1,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
        )
    return ToolResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
