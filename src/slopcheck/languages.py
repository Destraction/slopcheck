"""Детект языков репозитория по расширениям файлов и маркерам.

Результат используется runner'ом, чтобы выбрать применимые адаптеры
(напр. vulture — только если есть Python, knip — только для JS/TS).
"""

from __future__ import annotations

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


def _is_ignored(rel_parts: tuple[str, ...], ignore: list[str]) -> bool:
    for part in rel_parts:
        if part in _ALWAYS_SKIP:
            return True
    joined = "/".join(rel_parts)
    return any(pat and pat in joined for pat in ignore)


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
        if _is_ignored(rel_parts, ignore):
            continue
        lang = _EXT_TO_LANG.get(file.suffix.lower())
        if lang:
            found.add(lang)

    return sorted(found)
