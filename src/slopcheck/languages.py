"""Детект языков репозитория по расширениям файлов и маркерам.

Результат используется runner'ом, чтобы выбрать применимые адаптеры
(напр. vulture — только если есть Python, knip — только для JS/TS).
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

# Расширение → канонический язык.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".java": "java",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".kt": "kotlin",
    ".swift": "swift",
}

# Каталоги, всегда пропускаемые при детекте (независимо от конфига).
_ALWAYS_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def is_ignored(rel_parts: tuple[str, ...], ignore: list[str]) -> bool:
    """Попадает ли путь (в виде кортежа компонентов) под игнор.

    Матч по компонентам пути и glob'ам — НЕ по подстроке, чтобы `build`
    не исключал `rebuilder/`. Единый предикат: им пользуются и детект языков,
    и центральная фильтрация находок в runner.
    """
    for part in rel_parts:
        if part in _ALWAYS_SKIP:
            return True
    joined = "/".join(rel_parts)
    for pat in ignore:
        if not pat:
            continue
        if pat in rel_parts:  # точное совпадение компонента (имя каталога/файла)
            return True
        if fnmatch(joined, pat) or fnmatch(joined, f"{pat}/*") or fnmatch(joined, f"*/{pat}/*"):
            return True
    return False


def detect(root: Path, ignore: list[str] | None = None) -> list[str]:
    """Вернуть отсортированный список языков, найденных под `root`.

    `ignore` — список путей-фрагментов для исключения (обычно из конфига).
    """
    ignore = ignore or []
    root = root.resolve()
    found: set[str] = set()

    for file in root.rglob("*"):
        if not file.is_file():
            continue
        rel_parts = file.relative_to(root).parts
        if is_ignored(rel_parts, ignore):
            continue
        lang = _EXT_TO_LANG.get(file.suffix.lower())
        if lang:
            found.add(lang)

    return sorted(found)
