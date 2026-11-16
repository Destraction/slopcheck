"""Тесты Go-адаптера на golangci-lint: парсер по фикстуре и живой прогон."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from slopcheck.adapters.golangci import GolangciLintAdapter, classify, module_dirs, parse_report
from slopcheck.config import Config
from slopcheck.models import Category, Severity
from slopcheck.subprocess_util import ToolExecutionError

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture() -> str:
    return (FIXTURES / "golangci-report.json").read_text(encoding="utf-8")


def test_parse_report_categories() -> None:
    by_rule = {f.rule_id: f for f in parse_report(_fixture())}
    assert by_rule["unused"].category is Category.DEAD_CODE
    assert by_rule["ineffassign"].category is Category.DEAD_CODE
    assert by_rule["govet/unreachable"].category is Category.DEAD_CODE
    assert by_rule["errcheck"].category is Category.COMPLEXITY
    assert by_rule["revive/empty-block"].severity is Severity.WARN
    assert by_rule["revive/exported"].category is Category.COMMENTS
    assert by_rule["revive/exported"].severity is Severity.INFO
    # S1003 — упрощение, а не баг.
    assert by_rule["staticcheck/S1003"].severity is Severity.INFO
    assert all(f.tool == "golangci-lint" for f in by_rule.values())


def test_classify_staticcheck_bug_is_warn() -> None:
    assert classify("staticcheck", "SA5011: possible nil pointer dereference")[1] is Severity.WARN
    assert classify("staticcheck", "SA4006: this value of x is never used")[0] is Category.DEAD_CODE
    assert classify("staticcheck", "ST1000: at least one file in a package should have a package comment")[0] is Category.COMMENTS


def test_typecheck_is_failure_not_clean() -> None:
    report = json.dumps({"Issues": [{"FromLinter": "typecheck", "Text": "declared and not used: x", "Pos": {"Filename": "a.go", "Line": 1}}]})
    with pytest.raises(ToolExecutionError, match="не компилируется"):
        parse_report(report)


def test_docs_in_test_files_skipped() -> None:
    report = json.dumps({"Issues": [
        {"FromLinter": "revive", "Text": "exported: exported function Helper should have comment", "Pos": {"Filename": "/r/x_test.go", "Line": 3}},
        {"FromLinter": "errcheck", "Text": "Error return value is not checked", "Pos": {"Filename": "/r/x_test.go", "Line": 5}},
    ]})
    assert [f.rule_id for f in parse_report(report)] == ["errcheck"]
    assert len(parse_report(report, skip_test_docs=False)) == 2


def test_module_dirs_respects_ignore(tmp_path: Path) -> None:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "go.mod").write_text("module svc\n")
    (tmp_path / "vendor" / "dep").mkdir(parents=True)
    (tmp_path / "vendor" / "dep" / "go.mod").write_text("module dep\n")
    assert module_dirs(tmp_path, ["vendor"]) == [tmp_path / "svc"]


def test_no_module_is_failure(tmp_path: Path) -> None:
    (tmp_path / "main.go").write_text("package main\n")
    with pytest.raises(ToolExecutionError, match="go.mod"):
        GolangciLintAdapter().run(tmp_path, Config())


@pytest.mark.skipif(
    not (shutil.which("golangci-lint") and shutil.which("go")), reason="golangci-lint/go не установлены"
)
def test_live_run(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/x\n\ngo 1.22\n")
    (tmp_path / "x.go").write_text(
        "package x\n\nimport \"os\"\n\n"
        "func unused() {}\n\n"
        "func Open() {\n\tos.Chdir(\"f\")\n}\n"
    )
    rules = {f.rule_id for f in GolangciLintAdapter().run(tmp_path, Config())}
    assert {"unused", "errcheck", "revive/exported"} <= rules
