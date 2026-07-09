"""Базовый интерфейс адаптера детектора."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from slopcheck.config import Config
from slopcheck.models import Category, Finding


class Adapter(ABC):
    """Обёртка над одним детектором.

    Наследник объявляет:
      - `name` — идентификатор адаптера (для отчёта о skip);
      - `category` — категория, в которую попадают его находки;
      - `languages` — языки, к которым применим (пустой набор = любой язык).
    и реализует `is_available()` и `run()`.
    """

    name: str = "adapter"
    category: Category
    languages: frozenset[str] = frozenset()

    def applies_to(self, languages: list[str]) -> bool:
        """Актуален ли адаптер для набора языков репозитория."""
        if not self.languages:
            return True
        return bool(self.languages.intersection(languages))

    @abstractmethod
    def is_available(self) -> bool:
        """Установлен ли требуемый внешний тул."""
        raise NotImplementedError

    @abstractmethod
    def run(self, root: Path, config: Config) -> list[Finding]:
        """Прогнать детектор по `root` и вернуть нормализованные находки."""
        raise NotImplementedError
