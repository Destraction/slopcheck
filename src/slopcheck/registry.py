"""Реестр адаптеров.

Адаптеры регистрируются явным `slopcheck.adapters.register_all()`. Runner берёт
из реестра адаптеры включённых категорий. Тесты создают отдельный Registry,
чтобы не зависеть от глобального состояния.
"""

from __future__ import annotations

from slopcheck.adapters.base import Adapter
from slopcheck.models import Category


class Registry:
    """Коллекция адаптеров с выборкой по категории."""

    def __init__(self) -> None:
        """Создать пустой реестр."""
        self._adapters: list[Adapter] = []

    def register(self, adapter: Adapter) -> Adapter:
        """Добавить адаптер в реестр."""
        self._adapters.append(adapter)
        return adapter

    def all(self) -> list[Adapter]:
        """Все зарегистрированные адаптеры в порядке регистрации."""
        return list(self._adapters)

    def for_categories(self, categories: list[Category]) -> list[Adapter]:
        """Адаптеры, чья категория входит в `categories`."""
        wanted = set(categories)
        return [a for a in self._adapters if a.category in wanted]


# Глобальный реестр, в который регистрируются реальные адаптеры.
default_registry = Registry()
