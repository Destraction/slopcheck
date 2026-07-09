"""Тесты фиксов ревью: сбой детектора не молчит, игнор централизован и точен."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import is_ignored
from slopcheck.models import Category, Finding
from slopcheck.registry import Registry
from slopcheck.runner import run
from slopcheck.subprocess_util import (
    ToolExecutionError,
    ToolResult,
    crashed,
    run_tool,
)


# --------------------------------------------------------------- сбой детектора

class _CrashingAdapter(Adapter):
    name = "boom"
    category = Category.DUPLICATION

    def is_available(self) -> bool:
        return True

    def run(self, root: Path, config: Config) -> list[Finding]:
        raise ToolExecutionError("детектор упал")


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    return tmp_path


def test_tool_failure_surfaces_as_skip_not_silent_empty(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(_CrashingAdapter())
    result = run(_repo(tmp_path), config=Config(), registry=reg)
    # Критично: сбой попал в skipped, а не растворился в «находок нет».
    assert result.report.findings == []
    assert any("сбой запуска" in note for note in result.skipped)


def test_crashed_strict() -> None:
    # Любой код вне ok_returncodes — сбой, независимо от stdout/stderr:
    # частичный вывод опаснее пустого (гейт ложно позеленеет).
    assert crashed(ToolResult(returncode=1, stdout="", stderr="Traceback..."))
    assert crashed(ToolResult(returncode=1, stdout="", stderr=""))
    assert crashed(ToolResult(returncode=1, stdout="finding", stderr=""))
    assert crashed(ToolResult(returncode=2, stdout="partial", stderr=""))
    # чистый успех
    assert not crashed(ToolResult(returncode=0, stdout="", stderr=""))
    # штатный ненулевой код «нашли проблемы» перечисляется вызывающим явно
    assert not crashed(
        ToolResult(returncode=1, stdout="finding", stderr=""), ok_returncodes=(0, 1)
    )
    assert crashed(
        ToolResult(returncode=2, stdout="", stderr=""), ok_returncodes=(0, 1)
    )


def test_run_tool_timeout_raises() -> None:
    import pytest

    with pytest.raises(ToolExecutionError):
        run_tool(["sleep", "5"], timeout=0.05)


# --------------------------------------------------------------- игнор

def test_is_ignored_component_match_not_substring() -> None:
    ignore = ["build", "node_modules"]
    assert is_ignored(("build", "out.js"), ignore)
    assert is_ignored(("pkg", "node_modules", "x.js"), ignore)
    # 'rebuilder' содержит 'build' как подстроку — НЕ должен исключаться
    assert not is_ignored(("src", "rebuilder", "app.py"), ignore)


def test_is_ignored_glob() -> None:
    assert is_ignored(("gen", "schema.ts"), ["gen/*"])


def test_runner_central_ignore_filters_findings(tmp_path: Path) -> None:
    # Адаптер нашёл в игнорируемом каталоге — runner должен отфильтровать.
    class _Adapter(Adapter):
        name = "x"
        category = Category.DEAD_CODE

        def is_available(self) -> bool:
            return True

        def run(self, root: Path, config: Config) -> list[Finding]:
            return [
                Finding(category=Category.DEAD_CODE, tool="t", file="generated/a.py",
                        line=1, message="dead"),
                Finding(category=Category.DEAD_CODE, tool="t", file="src/b.py",
                        line=1, message="dead"),
            ]

    reg = Registry()
    reg.register(_Adapter())
    cfg = Config()
    cfg.ignore = ["generated"]
    result = run(_repo(tmp_path), config=cfg, registry=reg)
    files = {f.file for f in result.report.findings}
    assert files == {"src/b.py"}  # generated/ отфильтрован централизованно


class _PythonApiCrashingAdapter(Adapter):
    """Python-API адаптер, кидающий произвольное исключение (не ToolExecutionError)."""

    name = "pyboom"
    category = Category.DUPLICATION

    def is_available(self) -> bool:
        return True

    def run(self, root: Path, config: Config) -> list[Finding]:
        raise RuntimeError("внутренняя поломка Python-API")


def test_python_api_failure_surfaces_as_skip(tmp_path: Path) -> None:
    # Произвольное исключение (lizard/interrogate) — тоже пропуск, не падение прогона.
    reg = Registry()
    reg.register(_PythonApiCrashingAdapter())
    result = run(_repo(tmp_path), config=Config(), registry=reg)
    assert result.report.findings == []
    assert any("pyboom" in note and "сбой детектора" in note for note in result.skipped)


# ----------------------------------------------------- ignore-глобы для тулов


def test_vulture_excludes_component_not_substring() -> None:
    from slopcheck.adapters.deadcode import vulture_excludes

    pats = vulture_excludes(["build"])
    # Явные глобы по компоненту пути, а не подстрочный *build*.
    assert "*/build/*" in pats and "*/build" in pats
    assert "build" not in pats  # голый паттерн vulture обернул бы в *build*
    # wildcard-паттерны передаются как есть
    assert vulture_excludes(["*.min.js"]) == ["*.min.js"]


def test_lizard_exclude_globs_cover_files_and_dirs() -> None:
    from slopcheck.adapters.complexity import exclude_globs

    globs = exclude_globs(["build", "*.min.js"])
    assert "*/build/*" in globs
    assert "*.min.js" in globs  # файловый паттерн не ломается обёрткой


def test_jscpd_ignore_globs_cover_files_and_dirs() -> None:
    from slopcheck.adapters.duplication import _ignore_globs

    globs = _ignore_globs(["build", "*.min.js"])
    assert "**/build/**" in globs
    assert "*.min.js" in globs
