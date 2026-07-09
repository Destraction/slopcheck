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
