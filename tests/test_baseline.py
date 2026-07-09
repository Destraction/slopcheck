"""Тесты delta-гейта."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slopcheck.baseline import diff_findings, evaluate_gate, load_baseline
from slopcheck.cli import app
from slopcheck.config import Config
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity


def _f(msg: str, sev: Severity = Severity.WARN, line: int = 1, file: str = "a.py") -> Finding:
    return Finding(category=Category.DEAD_CODE, tool="vulture", file=file, line=line,
                   message=msg, severity=sev, rule_id="unused-code")


def _report(findings: list[Finding]) -> Report:
    return Report(repo="d", categories=[CategoryResult(category=Category.DEAD_CODE, findings=findings)])


def test_diff_detects_new_only() -> None:
    base = [_f("foo"), _f("bar")]
    head = [_f("foo"), _f("bar"), _f("baz")]
    new = diff_findings(base, head)
    assert len(new) == 1
    assert new[0].message == "baz"


def test_diff_ignores_line_shift() -> None:
    # Та же находка сместилась по строке — не «новая» (ключ игнорирует line).
    base = [_f("foo", line=10)]
    head = [_f("foo", line=55)]
    assert diff_findings(base, head) == []


def test_diff_respects_multiplicity() -> None:
    base = [_f("foo")]
    head = [_f("foo"), _f("foo")]
    new = diff_findings(base, head)
    assert len(new) == 1  # добавился второй экземпляр


def test_gate_passes_when_no_new() -> None:
    base = _report([_f("foo")])
    head = _report([_f("foo")])
    outcome = evaluate_gate(head, base, Config())
    assert outcome.passed
    assert outcome.blocking == []


def test_gate_fails_on_new_above_threshold() -> None:
    base = _report([])
    head = _report([_f("foo", Severity.WARN)])
    outcome = evaluate_gate(head, base, Config())  # gate_severity=WARN по умолчанию
    assert not outcome.passed
    assert len(outcome.blocking) == 1


def test_gate_ignores_new_below_threshold() -> None:
    base = _report([])
    head = _report([_f("foo", Severity.INFO)])
    cfg = Config()
    cfg.gate_severity = Severity.WARN  # INFO ниже порога
    outcome = evaluate_gate(head, base, cfg)
    assert outcome.passed
    assert len(outcome.new_findings) == 1  # находка новая, но не блокирующая


def test_load_baseline_ignores_extra_keys(tmp_path: Path) -> None:
    payload = _report([_f("foo")]).model_dump(mode="json")
    payload["skipped"] = ["knip: тул не установлен"]  # лишний ключ из json-репортера
    file = tmp_path / "base.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    report = load_baseline(file)
    assert len(report.findings) == 1


@pytest.mark.skipif(shutil.which("vulture") is None, reason="vulture не установлен")
def test_cli_gate_fails_on_regression(tmp_path: Path) -> None:
    # baseline без находок; в коде — мёртвая функция → vulture найдёт → гейт красный.
    base = tmp_path / "base.json"
    base.write_text(json.dumps(_report([]).model_dump(mode="json")), encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text(
        "def used():\n    return 1\n\n\ndef unused_helper():\n    return 2\n\n\nprint(used())\n",
        encoding="utf-8",
    )

    res = CliRunner().invoke(app, ["gate", str(repo), "--baseline", str(base)])
    # vulture доступен в окружении теста → регресс → exit 1.
    assert res.exit_code == 1
    assert "добавил slop" in res.stdout
