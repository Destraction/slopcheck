"""Утилиты работы с путями, общие для runner'а и адаптеров.

Вынесены в отдельный модуль, чтобы адаптеры могли нормализовать пути
той же логикой, что и runner, без циклического импорта.
"""

from __future__ import annotations

import os
from pathlib import Path


def relativize(path_str: str, root: Path) -> str:
    """Привести путь к относительному от `root`, если это возможно.

    Абсолютный путь внутри `root` становится относительным. Путь вне `root`,
    но с общим префиксом глубже корня ФС (например, соседний worktree),
    приводится через `..` (`os.path.relpath`) — иначе ключи delta-гейта
    зависели бы от абсолютного расположения чекаута. Путь без общего
    префикса остаётся как есть.
    """
    path = Path(path_str)
    if not path.is_absolute():
        return path_str
    resolved = path.resolve()
    root = root.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        pass
    try:
        common = os.path.commonpath([str(resolved), str(root)])
    except ValueError:
        # Разные диски (Windows) — общего префикса нет вовсе.
        return path_str
    if Path(common) == Path(Path(common).anchor):
        # Общий только корень ФС — относительный путь был бы бессмысленным.
        return path_str
    return os.path.relpath(str(resolved), str(root))
