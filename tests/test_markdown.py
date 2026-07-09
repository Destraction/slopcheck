"""Тесты Markdown-репортера."""

from __future__ import annotations

from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.reporters import markdown
from slopcheck.runner import RunResult


def _result(findings: list[Finding], skipped: list[str] | None = None) -> RunResult:
    report = Report(
        repo="demo",
        categories=[CategoryResult(category=Category.DEAD_CODE, findings=findings, score=76.9)],
        total_score=76.9,
    )
    return RunResult(report=report, skipped=skipped or [])


def test_markdown_contains_summary() -> None:
    f = Finding(category=Category.DEAD_CODE, tool="vulture", file="a.py", line=8,
                message="unused foo", severity=Severity.WARN)
    md = markdown.render(_result([f]))
    assert "## slopcheck — `demo`" in md
    assert "76.9 / 100" in md
    assert "| Категория | Score |" in md
    assert "unused foo" in md
    assert "`a.py:8`" in md


def test_markdown_escapes_pipe() -> None:
    f = Finding(category=Category.DEAD_CODE, tool="t", file="a.py", line=1,
                message="a | b union", severity=Severity.INFO)
    md = markdown.render(_result([f]))
    assert "a \\| b union" in md


def test_markdown_no_findings() -> None:
    md = markdown.render(_result([]))
    assert "_Находок нет._" in md


def test_markdown_lists_skipped() -> None:
    md = markdown.render(_result([], skipped=["knip: тул не установлен"]))
    assert "Пропущенные детекторы" in md
    assert "knip: тул не установлен" in md
