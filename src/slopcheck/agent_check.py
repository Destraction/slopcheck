"""Новые находки в незакоммиченных правках — для хука агента и pre-commit.

Отличие от `run --changed`: тот показывает ВСЕ находки в изменённых файлах,
включая старый долг. Агенту, поправившему строку в старом файле, нельзя
вываливать весь долг файла — он начнёт чинить чужое. Здесь возвращается
только то, чего не было в HEAD.

Порядок ради скорости (хук бежит в конце каждого хода агента):
  1. прогон по изменённым файлам рабочего дерева;
  2. находок уровня `hook_severity` нет → готово, HEAD не трогаем;
  3. иначе — прогон тех же файлов во временном worktree на HEAD и дельта
     по стабильному ключу (`baseline.diff_findings`).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from slopcheck.baseline import diff_findings, promote_new
from slopcheck.config import Config, load_config
from slopcheck.gitchanged import STAGED, changed_files, git, has_head, working_files
from slopcheck.hints import render_hints
from slopcheck.models import SEVERITY_RANK, Finding
from slopcheck.runner import run

if TYPE_CHECKING:
    # Только для аннотаций: прямой импорт registry первым замыкает цикл
    # registry → adapters → registry.
    from slopcheck.registry import Registry


# Первая строка вывода `check-changed`, когда находки есть. По ней хук отличает
# список находок от падения с тем же кодом выхода 1 (трассировка Python).
FINDINGS_HEADER = "❌ slopcheck: правки добавили slop"


@dataclass
class AgentCheckResult:
    """Новые находки правок и диагностика прогона."""

    new: list[Finding] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# Переменные, которые git выставляет внутри своих хуков (pre-commit). Унаследованные
# `git worktree add` и детекторами (semgrep зовёт git ls-files), они направляют
# git во временный индекс коммита: worktree на HEAD не создаётся.
_GIT_HOOK_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_EXEC_PATH")


@contextmanager
def _without_git_hook_env() -> Iterator[None]:
    """Временно убрать из окружения переменные git-хука, затем вернуть как было."""
    saved = {name: os.environ.pop(name) for name in _GIT_HOOK_ENV if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _at_least(findings: list[Finding], config: Config) -> list[Finding]:
    """Находки не ниже `hook_severity`."""
    floor = SEVERITY_RANK[config.hook_severity]
    return [f for f in findings if SEVERITY_RANK[f.severity] >= floor]


def _base_findings(
    root: Path, files: list[str], config: Config, registry: Registry | None
) -> list[Finding]:
    """Находки тех же файлов в HEAD (временный worktree, удаляется в любом случае)."""
    if not has_head(root):
        return []  # первый коммит: всё в нём новое
    toplevel = Path(git(root, "rev-parse", "--show-toplevel").strip())
    subdir = root.resolve().relative_to(toplevel)
    with tempfile.TemporaryDirectory(prefix="slopcheck-head-") as tmp:
        tree = Path(tmp) / "head"
        git(toplevel, "worktree", "add", "--detach", "--quiet", str(tree), "HEAD")
        try:
            base_root = tree / subdir
            existing = [f for f in files if (base_root / f).is_file()]
            if not existing:
                return []  # все файлы новые — в HEAD их не было
            return run(base_root, config, registry, files=existing).report.findings
        finally:
            git(toplevel, "worktree", "remove", "--force", str(tree))


def check(
    root: Path,
    staged: bool = False,
    config: Config | None = None,
    registry: Registry | None = None,
) -> AgentCheckResult:
    """Новые (относительно HEAD) находки в изменённых файлах `root`.

    `staged` — только файлы из индекса (pre-commit); иначе всё рабочее дерево.
    Анализируется содержимое файлов на диске: для pre-commit с частично
    добавленным файлом это приближение — так же работает `run --changed staged`.

    Raises:
        ToolExecutionError: не git-репозиторий или сбой git.
    """
    root = root.resolve()
    config = config or load_config(root)
    files = changed_files(root, STAGED) if staged else working_files(root)
    if not files:
        return AgentCheckResult()

    # Список файлов уже взят (в pre-commit — из индекса коммита); дальше
    # переменные git-хука только мешают.
    with _without_git_hook_env():
        head_run = run(root, config, registry, files=files)
        # Подавление линтера — info, пока не доказано, что оно новое: поднимаем
        # заранее, дельта с HEAD ниже отсеет старые (ключ не зависит от уровня).
        candidates = _at_least(promote_new(head_run.report.findings), config)
        if not candidates:
            return AgentCheckResult(files=files, skipped=head_run.skipped)
        # Тот же набор файлов, что у head: у парной находки jscpd изменённый
        # файл может быть второй стороной, а не `file`.
        base = _base_findings(root, files, config, registry)
    return AgentCheckResult(
        new=_at_least(diff_findings(base, candidates), config),
        files=files,
        skipped=head_run.skipped,
    )


def format_text(result: AgentCheckResult) -> str:
    """Компактный список для агента: `файл:строка [severity] правило — сообщение`,
    под ним — как чинить, по строке на класс находки."""
    found = sorted(result.new, key=lambda f: (f.file, f.line))
    lines = [f"{f.file}:{f.line} [{f.severity.value}] {f.rule_id or f.tool} — {f.message}" for f in found]
    hints = render_hints(found)
    if hints:
        lines += ["", "Как чинить:", *hints]
    return "\n".join(lines)
