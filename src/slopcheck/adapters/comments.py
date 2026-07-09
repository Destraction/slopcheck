"""Адаптеры категории «комментарии + документация».

  - aislop     — AI-slop паттерны (нарративные комментарии и пр.); потребляем
                 его стандартный SARIF-вывод, чтобы не зависеть от кастомной схемы;
  - interrogate — покрытие Python-докстрингами; зовём через Python-API
                 (структурный результат вместо парсинга текста).

В v1 все находки aislop относим к категории COMMENTS (детектор AI-slop как
единый bucket); более тонкое разнесение по категориям — v2.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.registry import default_registry
from slopcheck.subprocess_util import run_tool, tool_available

_SARIF_LEVEL_TO_SEVERITY = {
    "error": Severity.ERROR,
    "warning": Severity.WARN,
    "note": Severity.INFO,
    "none": Severity.INFO,
}


def parse_sarif(sarif_json: str, tool: str, category: Category) -> list[Finding]:
    """Разобрать SARIF 2.1.0 в находки.

    Читает `runs[].results[]`: ruleId, level, message.text и первую физическую
    локацию (файл + начальная строка).
    """
    data = json.loads(sarif_json)
    findings: list[Finding] = []
    for run in data.get("runs", []):
        for result in run.get("results", []):
            message = (result.get("message") or {}).get("text", "")
            severity = _SARIF_LEVEL_TO_SEVERITY.get(result.get("level", "warning"), Severity.WARN)
            file, line = _first_location(result)
            findings.append(
                Finding(
                    category=category,
                    tool=tool,
                    file=file,
                    line=line,
                    message=message or (result.get("ruleId") or "находка"),
                    severity=severity,
                    rule_id=result.get("ruleId"),
                )
            )
    return findings


def _first_location(result: dict) -> tuple[str, int]:
    locations = result.get("locations") or []
    if not locations:
        return ("?", 0)
    phys = (locations[0].get("physicalLocation") or {})
    uri = (phys.get("artifactLocation") or {}).get("uri", "?")
    line = (phys.get("region") or {}).get("startLine", 0) or 0
    return (uri, int(line))


class AislopAdapter(Adapter):
    """AI-slop паттерны (нарративные комментарии и пр.) через aislop."""

    name = "aislop"
    category = Category.COMMENTS
    languages = frozenset()  # мультиязычен

    def is_available(self) -> bool:
        return tool_available("aislop")

    def run(self, root: Path, config: Config) -> list[Finding]:
        result = run_tool(["aislop", "scan", str(root), "--sarif"], cwd=root)
        if not result.stdout.strip():
            return []
        return parse_sarif(result.stdout, tool="aislop", category=Category.COMMENTS)


class InterrogateAdapter(Adapter):
    """Покрытие Python-докстрингами (interrogate)."""

    name = "interrogate"
    category = Category.COMMENTS
    languages = frozenset({"python"})

    def is_available(self) -> bool:
        return importlib.util.find_spec("interrogate") is not None

    def run(self, root: Path, config: Config) -> list[Finding]:
        from interrogate.coverage import InterrogateCoverage

        cov = InterrogateCoverage(paths=[str(root)])
        results = cov.get_coverage()

        findings: list[Finding] = []
        for file_result in results.file_results:
            for node in file_result.nodes:
                if node.covered or node.lineno is None:
                    continue
                findings.append(
                    Finding(
                        category=Category.COMMENTS,
                        tool="interrogate",
                        file=file_result.filename,
                        line=int(node.lineno),
                        message=f"Отсутствует докстринг: {node.node_type} {node.name}",
                        severity=Severity.INFO,
                        rule_id="missing-docstring",
                    )
                )
        return findings


for _adapter in (AislopAdapter(), InterrogateAdapter()):
    default_registry.register(_adapter)
