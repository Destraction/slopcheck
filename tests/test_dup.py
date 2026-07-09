"""Тест парсинга jscpd-отчёта в находки дублей."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.duplication import JscpdAdapter, parse_report
from slopcheck.models import Category, Severity

FIXTURE = Path(__file__).parent / "fixtures" / "jscpd-report.json"


def test_parse_report_extracts_duplicate() -> None:
    findings = parse_report(FIXTURE.read_text(encoding="utf-8"))
    assert len(findings) == 1
    f = findings[0]
    assert f.category is Category.DUPLICATION
    assert f.tool == "jscpd"
    assert f.file == "src/a.js"
    assert f.line == 1
    assert f.end_line == 6
    assert f.metric == 5.0
    assert f.severity is Severity.WARN
    assert "src/b.js" in f.message


def test_parse_report_empty() -> None:
    assert parse_report('{"duplicates": []}') == []


def test_parse_report_skips_entry_without_name() -> None:
    bad = '{"duplicates": [{"lines": 3, "firstFile": {}, "secondFile": {}}]}'
    assert parse_report(bad) == []


def test_adapter_metadata() -> None:
    adapter = JscpdAdapter()
    assert adapter.name == "jscpd"
    assert adapter.category is Category.DUPLICATION
    assert adapter.applies_to(["python"])  # мультиязычен → применим к любому
