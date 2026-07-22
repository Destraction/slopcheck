"""Адаптеры мёртвого кода и зависимостей.

Три тула, одна категория DEAD_CODE:
  - vulture — неиспользуемый Python-код (текстовый вывод);
  - deptry  — лишние/отсутствующие Python-зависимости (JSON);
  - knip    — неиспользуемые файлы/экспорты/зависимости JS/TS (JSON).

Парсинг каждого вынесен в чистую функцию для тестов без запуска тулов.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.registry import default_registry
from slopcheck.subprocess_util import (
    ToolExecutionError,
    crashed,
    run_tool,
    tool_available,
)

# ---------------------------------------------------------------- vulture

_VULTURE_LINE = re.compile(r"^(?P<file>.+):(?P<line>\d+): (?P<msg>.+) \((?P<conf>\d+)% confidence\)$")


def parse_vulture(text: str) -> list[Finding]:
    """Разобрать текстовый вывод vulture."""
    findings: list[Finding] = []
    for raw in text.splitlines():
        m = _VULTURE_LINE.match(raw.strip())
        if not m:
            continue
        findings.append(
            Finding(
                category=Category.DEAD_CODE,
                tool="vulture",
                file=m.group("file"),
                line=int(m.group("line")),
                message=m.group("msg"),
                severity=Severity.WARN,
                rule_id="unused-code",
                metric=float(m.group("conf")),
            )
        )
    return findings


def vulture_excludes(ignore: list[str]) -> list[str]:
    """Точные исключения для vulture из паттернов конфига.

    vulture оборачивает паттерн без wildcard'ов в `*pattern*` (матч по
    ПОДСТРОКЕ пути!), из-за чего `build` исключал бы и `rebuilder/`. Даём
    явные glob'ы по компоненту пути; паттерны с wildcard передаём как есть.
    """
    patterns: list[str] = []
    for pat in ignore:
        if any(ch in pat for ch in "*?["):
            patterns.append(pat)
        else:
            patterns += [f"*/{pat}/*", f"*/{pat}"]
    return patterns


class VultureAdapter(Adapter):
    """Неиспользуемый Python-код."""

    name = "vulture"
    category = Category.DEAD_CODE
    languages = frozenset({"python"})

    def is_available(self) -> bool:
        return tool_available("vulture")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        if files is None:
            targets = [str(root)]
        else:
            targets = self.select_files(files)
            if not targets:
                return []
        cmd = ["vulture", *targets]
        excludes = vulture_excludes(config.ignore)
        if excludes:
            cmd += ["--exclude", ",".join(excludes)]
        result = run_tool(cmd, cwd=root)
        # Коды vulture: 0 — мёртвого кода нет, 3 — найден (штатно); 1/2 — сбой.
        if crashed(result, ok_returncodes=(0, 3)):
            raise ToolExecutionError(f"vulture упал: {result.stderr.strip()[:200]}")
        return parse_vulture(result.stdout)


# ---------------------------------------------------------------- deptry

def parse_deptry(report_json: str) -> list[Finding]:
    """Разобрать JSON-отчёт deptry."""
    data = json.loads(report_json)
    findings: list[Finding] = []
    for item in data:
        error = item.get("error", {})
        loc = item.get("location", {})
        findings.append(
            Finding(
                category=Category.DEAD_CODE,
                tool="deptry",
                file=loc.get("file") or "pyproject.toml",
                line=int(loc.get("line") or 0),
                message=error.get("message", "проблема зависимости"),
                severity=Severity.WARN,
                rule_id=error.get("code", "deptry"),
            )
        )
    return findings


class DeptryAdapter(Adapter):
    """Лишние/отсутствующие Python-зависимости."""

    name = "deptry"
    category = Category.DEAD_CODE
    languages = frozenset({"python"})
    # Анализ зависимостей осмыслен только по проекту целиком.
    file_scoped = False

    def is_available(self) -> bool:
        return tool_available("deptry")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "deptry.json"
            result = run_tool(["deptry", str(root), "--json-output", str(report)], cwd=root)
            if not report.exists():
                if crashed(result):
                    raise ToolExecutionError(f"deptry упал: {result.stderr.strip()[:200]}")
                return []  # нет проекта с зависимостями — штатно пусто
            return parse_deptry(report.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- knip

# Категория проблемы knip → человекочитаемая метка.
_KNIP_ISSUE_KINDS = {
    "dependencies": "неиспользуемая зависимость",
    "devDependencies": "неиспользуемая dev-зависимость",
    "unlisted": "незаявленная зависимость",
    "exports": "неиспользуемый экспорт",
    "types": "неиспользуемый тип",
    "enumMembers": "неиспользуемый член enum",
    "duplicates": "дублирующийся экспорт",
}


def _knip_entry_fields(entry: object) -> tuple[str, int]:
    """knip отдаёт элементы как строку или объект {name,line,col}."""
    if isinstance(entry, dict):
        return str(entry.get("name", "?")), int(entry.get("line", 0) or 0)
    return str(entry), 0


def parse_knip(report_json: str) -> list[Finding]:
    """Разобрать JSON-отчёт knip (неиспользуемые файлы/экспорты/зависимости)."""
    data = json.loads(report_json)
    findings: list[Finding] = []

    for unused_file in data.get("files", []):
        findings.append(
            Finding(
                category=Category.DEAD_CODE,
                tool="knip",
                file=str(unused_file),
                line=0,
                message="Неиспользуемый файл",
                severity=Severity.WARN,
                rule_id="unused-file",
            )
        )

    for issue in data.get("issues", []):
        file = issue.get("file", "?")
        for kind, label in _KNIP_ISSUE_KINDS.items():
            for entry in issue.get(kind, []) or []:
                name, line = _knip_entry_fields(entry)
                findings.append(
                    Finding(
                        category=Category.DEAD_CODE,
                        tool="knip",
                        file=file,
                        line=line,
                        message=f"{label}: {name}",
                        severity=Severity.WARN,
                        rule_id=f"knip-{kind}",
                    )
                )
    return findings


class KnipAdapter(Adapter):
    """Неиспользуемые файлы/экспорты/зависимости JS/TS."""

    name = "knip"
    category = Category.DEAD_CODE
    languages = frozenset({"javascript", "typescript"})
    # «Неиспользуемый экспорт/файл» вычислим только по всему графу проекта.
    file_scoped = False

    def is_available(self) -> bool:
        return tool_available("knip")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        result = run_tool(
            ["knip", "--reporter", "json", "--directory", str(root)], cwd=root
        )
        # Коды knip: 0 — чисто, 1 — есть находки (штатно); прочие — сбой.
        if crashed(result, ok_returncodes=(0, 1)):
            raise ToolExecutionError(f"knip упал: {result.stderr.strip()[:200]}")
        if not result.stdout.strip():
            if result.returncode != 0:
                # Код «есть находки» без вывода — недостоверный результат.
                raise ToolExecutionError("knip вернул код 1 без JSON-вывода")
            return []
        return parse_knip(result.stdout)


for _adapter in (VultureAdapter(), DeptryAdapter(), KnipAdapter()):
    default_registry.register(_adapter)
