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


def test_crashed_heuristic() -> None:
    assert crashed(ToolResult(returncode=1, stdout="", stderr="Traceback..."))
    # штатный ненулевой код с выводом (нашли проблемы) — не сбой
    assert not crashed(ToolResult(returncode=1, stdout="finding", stderr=""))
    # чистый успех
    assert not crashed(ToolResult(returncode=0, stdout="", stderr=""))


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
