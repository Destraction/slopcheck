"""Тесты адаптеров комментариев и документации.

aislop — по SARIF-фикстуре; interrogate — вживую через Python-API.
"""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.comments import InterrogateAdapter, parse_sarif
from slopcheck.config import Config
from slopcheck.models import Category, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sarif_aislop() -> None:
    findings = parse_sarif(
        (FIXTURES / "aislop.sarif").read_text(encoding="utf-8"),
        tool="aislop",
        category=Category.COMMENTS,
    )
    assert len(findings) == 2
    narrative = findings[0]
    assert narrative.rule_id == "narrative-comment"
    assert narrative.file == "src/a.js"
    assert narrative.line == 10
    assert narrative.severity is Severity.WARN
    swallowed = findings[1]
    assert swallowed.severity is Severity.ERROR
    assert swallowed.line == 42


def test_parse_sarif_no_locations() -> None:
    sarif = (
        '{"runs":[{"results":[{"ruleId":"x","level":"note",'
        '"message":{"text":"m"}}]}]}'
    )
    findings = parse_sarif(sarif, tool="aislop", category=Category.COMMENTS)
    assert len(findings) == 1
    assert findings[0].file == "?"
    assert findings[0].line == 0
    assert findings[0].severity is Severity.INFO


def test_interrogate_live(tmp_path: Path) -> None:
    (tmp_path / "doc.py").write_text(
        'def documented():\n    """Doc."""\n    return 1\n\n\n'
        "def undocumented(x):\n    return x\n",
        encoding="utf-8",
    )
    adapter = InterrogateAdapter()
    assert adapter.is_available()
    findings = adapter.run(tmp_path, Config())
    # Только undocumented без докстринга; documented покрыт, модуль (lineno None) исключён.
    assert len(findings) == 1
    assert findings[0].message.endswith("undocumented")
    assert findings[0].category is Category.COMMENTS
    assert findings[0].rule_id == "missing-docstring"


def test_aislop_run_raises_on_crash(monkeypatch) -> None:
    # Сбой aislop — не молчаливый [] (иначе delta-гейт ложно зеленеет).
    import pytest

    from slopcheck.adapters import comments as mod
    from slopcheck.adapters.comments import AislopAdapter
    from slopcheck.subprocess_util import ToolExecutionError, ToolResult

    monkeypatch.setattr(
        mod,
        "run_tool",
        lambda *_a, **_kw: ToolResult(returncode=2, stdout="", stderr="boom"),
    )
    with pytest.raises(ToolExecutionError):
        AislopAdapter().run(Path("."), Config())


def test_aislop_run_code1_is_findings(monkeypatch) -> None:
    # Код 1 у сканера — «есть находки», штатно; пустой SARIF → [].
    from slopcheck.adapters import comments as mod
    from slopcheck.adapters.comments import AislopAdapter
    from slopcheck.subprocess_util import ToolResult

    monkeypatch.setattr(
        mod,
        "run_tool",
        lambda *_a, **_kw: ToolResult(returncode=1, stdout="", stderr=""),
    )
    assert AislopAdapter().run(Path("."), Config()) == []


def test_interrogate_skips_tests_by_default(tmp_path: Path) -> None:
    """Докстринги в тестах не требуются: имя теста и есть описание."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_something():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")

    adapter = InterrogateAdapter()
    default_files = {f.file for f in adapter.run(tmp_path, Config())}
    assert not any("test_x.py" in f for f in default_files)
    assert any("app.py" in f for f in default_files)

    with_tests = {f.file for f in adapter.run(tmp_path, Config(docstrings_skip_tests=False))}
    assert any("test_x.py" in f for f in with_tests)


def test_interrogate_honours_ignore_paths(tmp_path: Path) -> None:
    """Каталоги из ignore не читаются вовсе (иначе сканируем полдиска)."""
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")

    files = {f.file for f in InterrogateAdapter().run(tmp_path, Config())}
    assert not any(".venv" in f for f in files)
    assert any("app.py" in f for f in files)


def test_aislop_rule_category_mapping() -> None:
    """Находки aislop раскладываются по категориям, а не валятся в comments."""
    from slopcheck.adapters.comments import category_for_aislop_rule

    assert category_for_aislop_rule("ruff/F401") is Category.DEAD_CODE
    assert category_for_aislop_rule("ai-slop/unused-import") is Category.DEAD_CODE
    assert category_for_aislop_rule("eslint/no-unused-vars") is Category.DEAD_CODE
    assert category_for_aislop_rule("code-quality/duplicate-block") is Category.DUPLICATION
    assert category_for_aislop_rule("ai-slop/narrative-comment") is Category.COMMENTS
    assert category_for_aislop_rule("ai-slop/todo-stub") is Category.COMMENTS
    # Незнакомое lint-правило — смелл, а не «комментарий».
    assert category_for_aislop_rule("jsx-a11y/no-autofocus") is Category.COMPLEXITY
    assert category_for_aislop_rule(None) is Category.COMPLEXITY


def _aislop_sarif(*rule_ids: str) -> str:
    results = ", ".join(
        '{"ruleId": "%s", "level": "warning", "message": {"text": "x"},'
        ' "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"},'
        ' "region": {"startLine": 1}}}]}' % rule_id
        for rule_id in rule_ids
    )
    return '{"runs": [{"results": [%s]}]}' % results


def test_aislop_run_applies_categories_and_ignores(monkeypatch) -> None:
    """Игнор-правила отсекаются, остальным проставляется своя категория."""
    from slopcheck.adapters import comments as mod
    from slopcheck.adapters.comments import AislopAdapter
    from slopcheck.subprocess_util import ToolResult

    sarif = _aislop_sarif("python-formatting", "ruff/F401")
    monkeypatch.setattr(
        mod, "run_tool", lambda *_a, **_kw: ToolResult(returncode=1, stdout=sarif, stderr="")
    )
    (finding,) = AislopAdapter().run(Path("."), Config())
    assert finding.rule_id == "ruff/F401"
    assert finding.category is Category.DEAD_CODE

    both = AislopAdapter().run(Path("."), Config(aislop_ignore_rules=[]))
    assert len(both) == 2
