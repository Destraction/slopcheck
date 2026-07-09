"""Адаптеры детекторов: обёртки над внешними тулами, дающие Finding.

Импорт этого пакета регистрирует все конкретные адаптеры в default_registry.
"""

from slopcheck.adapters import duplication as duplication  # noqa: F401
from slopcheck.adapters import deadcode as deadcode  # noqa: F401
from slopcheck.adapters import comments as comments  # noqa: F401
