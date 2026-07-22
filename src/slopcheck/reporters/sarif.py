"""SARIF 2.1.0 репортер для интеграции с GitHub Code Scanning."""

from __future__ import annotations

import json

from slopcheck import __version__
from slopcheck.models import Report, Severity
from slopcheck.runner import RunResult

_SEVERITY_TO_LEVEL = {
    Severity.ERROR: "error",
    Severity.WARN: "warning",
    Severity.INFO: "note",
}

_SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def _rules(report: Report) -> list[dict]:
    """Уникальные правила отчёта для driver.rules (id = rule_id или тул)."""
    seen: dict[str, dict] = {}
    for f in report.findings:
        rule_id = f.rule_id or f.tool
        if rule_id not in seen:
            seen[rule_id] = {"id": rule_id, "name": rule_id}
    return list(seen.values())


def _results(report: Report) -> list[dict]:
    """Находки отчёта в виде SARIF-результатов."""
    results: list[dict] = []
    for f in report.findings:
        results.append(
            {
                "ruleId": f.rule_id or f.tool,
                "level": _SEVERITY_TO_LEVEL[f.severity],
                "message": {"text": f.message},
                "properties": {"category": f.category.value, "tool": f.tool},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file},
                            "region": {"startLine": max(f.line, 1)},
                        }
                    }
                ],
            }
        )
    return results


def to_dict(result: RunResult) -> dict:
    """Собрать SARIF-документ из результата прогона."""
    report = result.report
    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "slopcheck",
                        "version": __version__,
                        "informationUri": "https://github.com/Destraction/slopcheck",
                        "rules": _rules(report),
                    }
                },
                "results": _results(report),
            }
        ],
    }


def render(result: RunResult) -> str:
    """Вернуть SARIF-документ как JSON-строку."""
    return json.dumps(to_dict(result), ensure_ascii=False, indent=2)
