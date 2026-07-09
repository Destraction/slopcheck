"""Тесты console/JSON репортеров и CLI-команды run."""

from __future__ import annotations

import json

from rich.console import Console
from typer.testing import CliRunner

from slopcheck.cli import app
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.reporters import available_formats, console as console_reporter, json_report
from slopcheck.runner import RunResult


def _result() -> RunResult:
    findings = [
        Finding(category=Category.DEAD_CODE, tool="vulture", file="a.py", line=8,
                message="unused function foo", severity=Severity.WARN),
        Finding(category=Category.COMPLEXITY, tool="lizard", file="b.py", line=40,
                message="High complexity (25): bar", severity=Severity.ERROR, metric=25.0),
    ]
    report = Report(
        repo="demo",
        languages=["python"],
        categories=[
            CategoryResult(category=Category.DEAD_CODE, findings=[findings[0]], score=76.9),
            CategoryResult(category=Category.COMPLEXITY, findings=[findings[1]], score=71.4),
        ],
        total_score=74.2,
    )
    return RunResult(report=report, skipped=["knip: тул не установлен"])


def test_json_report_round_trips_and_includes_skipped() -> None:
    text = json_report.render(_result())
    data = json.loads(text)
    assert data["repo"] == "demo"
    assert data["total_score"] == 74.2
    assert data["skipped"] == ["knip: тул не установлен"]
    assert len(data["categories"]) == 2


def test_console_render_outputs_key_facts() -> None:
    buffer = Console(record=True, width=120)
    console_reporter.render(_result(), console=buffer)
    text = buffer.export_text()
    assert "demo" in text
    assert "74.2" in text
    assert "unused function foo" in text
    assert "knip" in text  # пропущенный тул показан


def test_available_formats() -> None:
    fmts = available_formats()
    assert "console" in fmts
    assert "json" in fmts


def test_cli_run_json_on_repo(tmp_path) -> None:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(app, ["run", str(tmp_path), "--format", "json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["repo"] == tmp_path.name
    assert "categories" in data


def test_cli_run_rejects_unknown_format(tmp_path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["run", str(tmp_path), "--format", "bogus"])
    assert res.exit_code == 2
