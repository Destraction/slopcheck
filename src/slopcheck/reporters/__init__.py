"""Репортеры: превращают RunResult в вывод (console/json/sarif/md)."""

from __future__ import annotations

from slopcheck.reporters import console, json_report, sarif
from slopcheck.runner import RunResult

# Форматы, печатающие в stdout сами (rich).
_PRINTERS = {
    "console": console.render,
}
# Форматы, возвращающие текст.
_TEXT = {
    "json": json_report.render,
    "sarif": sarif.render,
}


def available_formats() -> list[str]:
    return sorted({*_PRINTERS, *_TEXT})


def emit(result: RunResult, fmt: str) -> None:
    """Вывести результат в выбранном формате в stdout."""
    if fmt in _PRINTERS:
        _PRINTERS[fmt](result)
        return
    if fmt in _TEXT:
        print(_TEXT[fmt](result))
        return
    raise ValueError(f"неизвестный формат отчёта: {fmt} (доступно: {available_formats()})")
