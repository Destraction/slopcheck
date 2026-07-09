"""Тесты SARIF-репортера, включая round-trip через собственный SARIF-ридер."""

from __future__ import annotations

from slopcheck.adapters.comments import parse_sarif
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.reporters import sarif
from slopcheck.runner import RunResult


def _result() -> RunResult:
    findings = [
        Finding(category=Category.DEAD_CODE, tool="vulture", file="a.py", line=8,
                message="unused foo", severity=Severity.WARN, rule_id="unused-code"),
        Finding(category=Category.COMPLEXITY, tool="lizard", file="b.py", line=40,
                message="complex bar", severity=Severity.ERROR, rule_id="high-complexity"),
    ]
    report = Report(
        repo="demo",
        categories=[
            CategoryResult(category=Category.DEAD_CODE, findings=[findings[0]]),
            CategoryResult(category=Category.COMPLEXITY, findings=[findings[1]]),
        ],
    )
    return RunResult(report=report)


def test_sarif_structure() -> None:
    doc = sarif.to_dict(_result())
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "slopcheck"
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert rule_ids == {"unused-code", "high-complexity"}
    assert len(run["results"]) == 2


def test_sarif_levels_mapped() -> None:
    results = sarif.to_dict(_result())["runs"][0]["results"]
    levels = {r["ruleId"]: r["level"] for r in results}
    assert levels["unused-code"] == "warning"
    assert levels["high-complexity"] == "error"


def test_sarif_round_trip_through_reader() -> None:
    # SARIF, который мы пишем, должен читаться нашим же ридером (parse_sarif).
    text = sarif.render(_result())
    reparsed = parse_sarif(text, tool="slopcheck", category=Category.DEAD_CODE)
    assert len(reparsed) == 2
    by_rule = {f.rule_id: f for f in reparsed}
    assert by_rule["unused-code"].line == 8
    assert by_rule["unused-code"].severity is Severity.WARN
    assert by_rule["high-complexity"].severity is Severity.ERROR
    assert by_rule["high-complexity"].file == "b.py"


def test_sarif_startline_floor() -> None:
    # line=0 в модели → startLine >= 1 (SARIF требует 1-based).
    result = RunResult(
        report=Report(
            repo="d",
            categories=[
                CategoryResult(
                    category=Category.DEAD_CODE,
                    findings=[Finding(category=Category.DEAD_CODE, tool="knip",
                                      file="x.ts", line=0, message="unused file")],
                )
            ],
        )
    )
    region = sarif.to_dict(result)["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 1
