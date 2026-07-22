"""Тест конвейера runner на фейковых адаптерах (без внешних тулов)."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.registry import Registry
from slopcheck.runner import run


class _FakeAdapter(Adapter):
    def __init__(
        self,
        name: str,
        category: Category,
        findings: list[Finding],
        available: bool = True,
        languages: frozenset[str] = frozenset(),
    ) -> None:
        self.name = name
        self.category = category
        self.languages = languages
        self._findings = findings
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        return list(self._findings)


def _finding(category: Category, tool: str) -> Finding:
    return Finding(category=category, tool=tool, file="a.py", line=1, message="x")


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    return tmp_path


def test_runner_aggregates_findings(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(
        _FakeAdapter("dup", Category.DUPLICATION, [_finding(Category.DUPLICATION, "jscpd")])
    )
    reg.register(
        _FakeAdapter("dead", Category.DEAD_CODE, [_finding(Category.DEAD_CODE, "vulture")])
    )
    result = run(_repo(tmp_path), config=Config(), registry=reg)
    assert len(result.report.findings) == 2
    assert result.skipped == []
    assert {c.category for c in result.report.categories} == set(Category)


def test_runner_skips_unavailable_tool(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(
        _FakeAdapter("dup", Category.DUPLICATION, [_finding(Category.DUPLICATION, "jscpd")], available=False)
    )
    result = run(_repo(tmp_path), config=Config(), registry=reg)
    assert result.report.findings == []
    assert len(result.skipped) == 1
    assert "не установлен" in result.skipped[0]


def test_runner_respects_language_applicability(tmp_path: Path) -> None:
    reg = Registry()
    # Адаптер только для JS/TS — на чисто-Python репо не должен запускаться.
    reg.register(
        _FakeAdapter(
            "knip",
            Category.DEAD_CODE,
            [_finding(Category.DEAD_CODE, "knip")],
            languages=frozenset({"javascript", "typescript"}),
        )
    )
    result = run(_repo(tmp_path), config=Config(), registry=reg)
    assert result.report.findings == []
    assert result.skipped == []  # неприменимость — не skip, просто пропуск


def test_runner_normalizes_absolute_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    abs_path = str(repo / "app.py")
    reg = Registry()
    reg.register(
        _FakeAdapter(
            "abs",
            Category.DEAD_CODE,
            [Finding(category=Category.DEAD_CODE, tool="t", file=abs_path, line=1, message="x")],
        )
    )
    result = run(repo, config=Config(), registry=reg)
    assert result.report.findings[0].file == "app.py"  # приведён к относительному


def test_runner_excludes_disabled_category(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(
        _FakeAdapter("dup", Category.DUPLICATION, [_finding(Category.DUPLICATION, "jscpd")])
    )
    cfg = Config()
    cfg.categories[Category.DUPLICATION].enabled = False
    result = run(_repo(tmp_path), config=cfg, registry=reg)
    assert result.report.findings == []
    assert all(c.category is not Category.DUPLICATION for c in result.report.categories)


def test_unavailable_detector_marks_category_unmeasured(tmp_path) -> None:
    """Непоставленный тул → категория помечена непроверенной, а не чистой.

    Именно эта дыра завышала счёт: детектора нет, находок ноль, категория
    берёт 100 и тянет итог вверх.
    """
    from slopcheck.models import Category
    from slopcheck.registry import Registry
    from slopcheck.runner import run

    class MissingTool:
        name = "missing"
        category = Category.DUPLICATION
        languages = frozenset({"python"})

        def applies_to(self, languages):
            return True

        def is_available(self):
            return False

        def run(self, root, config):  # pragma: no cover — не должен вызываться
            raise AssertionError("недоступный детектор не должен запускаться")

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    registry = Registry()
    registry.register(MissingTool())

    result = run(tmp_path, registry=registry)
    duplication = next(
        c for c in result.report.categories if c.category is Category.DUPLICATION
    )
    assert duplication.measured is False
    assert Category.DUPLICATION in result.report.unmeasured
    assert any("missing" in note for note in result.skipped)


def test_crashed_detector_also_marks_category_unmeasured(tmp_path) -> None:
    """Упавший детектор тоже ничего не доказал — его ноль находок не в счёт."""
    from slopcheck.models import Category
    from slopcheck.registry import Registry
    from slopcheck.runner import run
    from slopcheck.subprocess_util import ToolExecutionError

    class BrokenTool:
        name = "broken"
        category = Category.DEAD_CODE
        languages = frozenset({"python"})

        def applies_to(self, languages):
            return True

        def is_available(self):
            return True

        def run(self, root, config):
            raise ToolExecutionError("упал")

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    registry = Registry()
    registry.register(BrokenTool())

    result = run(tmp_path, registry=registry)
    dead = next(c for c in result.report.categories if c.category is Category.DEAD_CODE)
    assert dead.measured is False
    assert Category.DEAD_CODE in result.report.unmeasured


def test_register_all_is_idempotent() -> None:
    """Повторная регистрация не плодит дублей адаптеров."""
    from slopcheck.adapters import all_adapters, register_all

    registry = Registry()
    register_all(registry)
    first = [a.name for a in registry.all()]
    register_all(registry)
    assert [a.name for a in registry.all()] == first
    assert sorted(first) == sorted(a.name for a in all_adapters())


def test_cross_category_findings_mark_category_measured(tmp_path: Path) -> None:
    """Детектор, нашедший чужую категорию, делает её измеренной, а не «слепой»."""
    finding = Finding(
        category=Category.DEAD_CODE,
        tool="fake",
        file="a.py",
        line=1,
        message="мёртвый импорт",
        severity=Severity.WARN,
    )
    registry = Registry()
    registry.register(_FakeAdapter("multi", Category.COMMENTS, [finding]))

    result = run(tmp_path, Config(), registry)
    by_cat = {c.category: c for c in result.report.categories}
    assert by_cat[Category.DEAD_CODE].measured
    assert by_cat[Category.DEAD_CODE].findings == [finding]
    assert not by_cat[Category.DUPLICATION].measured


def _at(category: Category, line: int, severity: Severity, tool: str, **kw) -> Finding:
    return Finding(
        category=category,
        tool=tool,
        file="a.py",
        line=line,
        message=f"{tool} нашёл проблему",
        severity=severity,
        **kw,
    )


def test_same_place_findings_are_collapsed(tmp_path: Path) -> None:
    """Один дефект, найденный двумя тулами, штрафует счёт один раз."""
    registry = Registry()
    registry.register(
        _FakeAdapter(
            "multi",
            Category.DEAD_CODE,
            [
                _at(Category.DEAD_CODE, 3, Severity.WARN, "aislop"),
                _at(Category.DEAD_CODE, 3, Severity.ERROR, "vulture"),
                _at(Category.DEAD_CODE, 9, Severity.WARN, "vulture"),
            ],
        )
    )
    findings = run(tmp_path, Config(), registry).report.findings
    assert [(f.line, f.tool) for f in findings] == [(3, "vulture"), (9, "vulture")]


def test_distinct_clones_on_same_line_survive(tmp_path: Path) -> None:
    """Два разных клона с одной строки — две проблемы, склеивать нельзя."""
    registry = Registry()
    registry.register(
        _FakeAdapter(
            "dup",
            Category.DUPLICATION,
            [
                _at(Category.DUPLICATION, 5, Severity.WARN, "jscpd", identity="a.py|b.py"),
                _at(Category.DUPLICATION, 5, Severity.WARN, "jscpd", identity="a.py|c.py"),
            ],
        )
    )
    assert len(run(tmp_path, Config(), registry).report.findings) == 2


def test_file_level_findings_are_not_collapsed(tmp_path: Path) -> None:
    """Находки без строки (file-level) остаются все: их на файл может быть много."""
    registry = Registry()
    registry.register(
        _FakeAdapter(
            "knip",
            Category.DEAD_CODE,
            [
                _at(Category.DEAD_CODE, 0, Severity.WARN, "knip"),
                _at(Category.DEAD_CODE, 0, Severity.WARN, "knip"),
            ],
        )
    )
    assert len(run(tmp_path, Config(), registry).report.findings) == 2
