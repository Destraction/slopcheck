"""Репортеры: превращают RunResult в вывод (console/json/sarif/md)."""

from __future__ import annotations

import sys

from slopcheck.reporters import console, json_report, markdown, sarif
from slopcheck.runner import RunResult

# Форматы, печатающие в stdout сами (rich).
_PRINTERS = {
    "console": console.render,
}
# Форматы, возвращающие текст.
_TEXT = {
    "json": json_report.render,
    "sarif": sarif.render,
    "md": markdown.render,
}


def available_formats() -> list[str]:
    """Имена поддерживаемых форматов вывода."""
    return sorted({*_PRINTERS, *_TEXT})


def emit(result: RunResult, fmt: str) -> None:
    """Вывести результат в выбранном формате в stdout."""
    if fmt in _PRINTERS:
        _PRINTERS[fmt](result)
        return
    if fmt in _TEXT:
        # Не print: JSON/SARIF/MD уходят в пайп как есть, без переносов и
        # разметки, которые могли бы добавить print-обёртки поверх stdout.
        sys.stdout.write(_TEXT[fmt](result) + "\n")
        return
    raise ValueError(f"неизвестный формат отчёта: {fmt} (доступно: {available_formats()})")
