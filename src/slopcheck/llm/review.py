"""Опциональный LLM-ревью: шов, выключенный по умолчанию.

Детерминированное ядро slopcheck не использует ИИ. Этот модуль — точка
расширения для субъективного ревью (имена, абстракции, границы модулей),
которое статика не берёт. В v1 реализация — заглушка (`StubReviewer`),
не делающая внешних вызовов; включается только явным флагом `--llm-review`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from slopcheck.config import Config
from slopcheck.models import Finding
from slopcheck.runner import RunResult


@runtime_checkable
class LLMReviewer(Protocol):
    """Контракт LLM-ревьюера: по результату прогона даёт доп. находки."""

    def review(self, result: RunResult, config: Config) -> list[Finding]:
        """Вернуть находки ревью по результату прогона детекторов."""
        ...


class StubReviewer:
    """v1-заглушка: без внешних вызовов, находок не добавляет.

    Существует, чтобы зафиксировать интерфейс и путь включения; реальную
    интеграцию с LLM подключают заменой этого ревьюера.
    """

    def review(self, result: RunResult, config: Config) -> list[Finding]:
        """Находок не даёт: заглушка существует ради интерфейса."""
        return []


def run_review(
    result: RunResult, config: Config, reviewer: LLMReviewer | None = None
) -> list[Finding]:
    """Прогнать LLM-ревью и вернуть дополнительные находки.

    По умолчанию — `StubReviewer` (пусто). Ядро остаётся детерминированным.
    """
    reviewer = reviewer or StubReviewer()
    return reviewer.review(result, config)
