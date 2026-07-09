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


class ToolExecutionError(Exception):
    """Детектор запустился, но упал/завис — результат недостоверен.

    Отличать от «находок нет»: молча вернуть [] при сбое опасно (delta-гейт
    ложно позеленеет). Runner ловит это как пропуск с пометкой в отчёте.
    """


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
    input_text: str | None = None,
) -> ToolResult:
    """Запустить внешний тул `cmd`.

    `input_text` подаётся в stdin процесса (напр. код для gemini -p).

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
            input=input_text,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(
            f"{cmd[0]} превысил таймаут {timeout:g}s"
        ) from exc
    return ToolResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def crashed(result: ToolResult) -> bool:
    """Похоже ли на сбой: ненулевой код, пустой stdout и есть текст в stderr.

    Многие тулы (vulture, deptry, knip) штатно возвращают ненулевой код, когда
    НАШЛИ проблемы — поэтому одного кода мало; сбоем считаем лишь отсутствие
    вывода при наличии диагностики в stderr.
    """
    return result.returncode != 0 and not result.stdout.strip() and bool(result.stderr.strip())
