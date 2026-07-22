"""Список изменённых файлов через git — инкрементальный режим (--changed).

Два источника:
  - "staged"  — файлы в индексе (`git diff --cached`), сценарий pre-commit;
  - <ref>     — файлы, изменённые относительно merge-base с ref
                (`git diff ref...HEAD`), сценарий CI по ветке.

Удалённые файлы исключаются (--diff-filter=d): детекторам нечего сканировать.
Пути возвращаются относительными от `root` в posix-виде — тот же формат,
что у находок после нормализации в runner.
"""

from __future__ import annotations

from pathlib import Path

from slopcheck.subprocess_util import ToolExecutionError, crashed, run_tool

# Специальное значение --changed: брать файлы из индекса (pre-commit).
STAGED = "staged"


def _git(root: Path, *args: str) -> str:
    """Выполнить git в `root` и вернуть stdout; сбой git — исключение."""
    result = run_tool(["git", "-C", str(root), *args])
    if crashed(result):
        raise ToolExecutionError(
            f"git {args[0]} не удался: {result.stderr.strip()[:200]}"
        )
    return result.stdout


def changed_files(root: Path, ref: str) -> list[str]:
    """Изменённые файлы под `root`, относительные пути в posix-виде.

    Raises:
        ToolExecutionError: не git-репозиторий, битый ref или git недоступен.
    """
    root = root.resolve()
    # git diff отдаёт пути от верха репозитория; root может быть подкаталогом —
    # приводим к путям от root и отбрасываем файлы вне его.
    toplevel = Path(_git(root, "rev-parse", "--show-toplevel").strip())

    if ref == STAGED:
        out = _git(root, "diff", "--cached", "--name-only", "--diff-filter=d")
    else:
        out = _git(root, "diff", "--name-only", "--diff-filter=d", f"{ref}...HEAD")

    files: list[str] = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        abs_path = toplevel / name
        # --diff-filter=d уже отсёк удалённые в diff, но файл мог исчезнуть
        # после (unstaged-удаление, rename) — проверяем на диске.
        if not abs_path.is_file():
            continue
        try:
            rel = abs_path.relative_to(root)
        except ValueError:
            continue  # файл вне root (root — подкаталог репо)
        files.append(rel.as_posix())
    return files
