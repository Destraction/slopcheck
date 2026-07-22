"""Адаптеры детекторов: обёртки над внешними тулами, дающие Finding.

Регистрация — явная, через `register_all()`. Импорт пакета сам по себе
глобальное состояние не меняет: побочные эффекты при импорте выглядят как
неиспользуемый импорт и рвутся при любой перестановке строк.
"""

from __future__ import annotations

from slopcheck.adapters import comments, complexity, deadcode, duplication, smells
from slopcheck.adapters.base import Adapter
from slopcheck.registry import Registry, default_registry

_MODULES = (duplication, deadcode, comments, complexity, smells)


def all_adapters() -> list[Adapter]:
    """Экземпляры всех известных адаптеров в стабильном порядке."""
    return [adapter for module in _MODULES for adapter in module.ADAPTERS]


def register_all(registry: Registry | None = None) -> Registry:
    """Зарегистрировать все адаптеры в реестре (по умолчанию — глобальном).

    Идемпотентно: повторный вызов не плодит дублей, поэтому вызывать можно
    из любой точки входа (runner, gate) без оглядки на порядок импортов.
    """
    registry = registry if registry is not None else default_registry
    known = {adapter.name for adapter in registry.all()}
    for adapter in all_adapters():
        if adapter.name not in known:
            registry.register(adapter)
    return registry
