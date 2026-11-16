"""Адаптер Go на golangci-lint (v2): мёртвый код, проглоченные ошибки, доки.

Набор линтеров — в пакетном `slopcheck/rules/golangci.yml`, а не в конфиге
проверяемого репозитория: гейт должен мерить все проекты одной линейкой.
Один прогон golangci-lint даёт находки трёх категорий; раскладка — по линтеру
и коду правила (`classify`).

golangci-lint работает по модулю, а не по файлу: запускаем его в каждом
каталоге с go.mod. Если код не компилируется, линтеры молчат и остаётся одна
находка typecheck — это сбой проверки, а не «чистый код».
"""

from __future__ import annotations

import json
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import is_ignored, is_test_file
from slopcheck.models import Category, Finding, Severity
from slopcheck.subprocess_util import ToolExecutionError, crashed, run_tool, tool_available

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "rules" / "golangci.yml"

# Линтеры, все находки которых — мёртвый код.
_DEAD_CODE_LINTERS = {"unused", "ineffassign"}
# Правила (код staticcheck, анализатор govet, правило revive) → категория.
_RULE_CATEGORIES = {
    "unreachable": Category.DEAD_CODE,
    "SA4006": Category.DEAD_CODE,  # значение присвоено и не прочитано
    "exported": Category.COMMENTS,
    "ST1000": Category.COMMENTS,  # нет комментария пакета
    "ST1020": Category.COMMENTS,  # doc-комментарий не по форме
    "ST1021": Category.COMMENTS,
    "ST1022": Category.COMMENTS,
}


def _rule_of(linter: str, text: str) -> str:
    """Код правила внутри линтера.

    revive, govet и staticcheck пишут его префиксом текста
    (`exported: ...`, `unreachable: ...`, `S1003: ...`); у остальных правило
    одно и совпадает с именем линтера.
    """
    if linter in {"revive", "govet", "staticcheck"} and ": " in text:
        return text.split(": ", 1)[0]
    return linter


def classify(linter: str, text: str) -> tuple[Category, Severity, str]:
    """Категория, severity и rule_id находки golangci-lint."""
    rule = _rule_of(linter, text)
    rule_id = linter if rule == linter else f"{linter}/{rule}"
    if linter in _DEAD_CODE_LINTERS:
        return Category.DEAD_CODE, Severity.WARN, rule_id
    category = _RULE_CATEGORIES.get(rule, Category.COMPLEXITY)
    if category is Category.COMMENTS:
        # Как у interrogate: нехватка доков — долг, а не дефект.
        return category, Severity.INFO, rule_id
    # S/ST/QF у staticcheck — упрощения и стиль, SA — вероятные баги.
    if linter == "staticcheck" and not rule.startswith("SA"):
        return category, Severity.INFO, rule_id
    return category, Severity.WARN, rule_id


def parse_report(report_json: str, skip_test_docs: bool = True) -> list[Finding]:
    """Разобрать JSON golangci-lint (`output.formats.json`).

    Raises:
        ToolExecutionError: код не компилируется (находки typecheck) —
            остальные линтеры в таком случае не отработали.
    """
    data = json.loads(report_json)
    issues = data.get("Issues") or []
    broken = [i for i in issues if i.get("FromLinter") == "typecheck"]
    if broken:
        raise ToolExecutionError(
            f"Go-код не компилируется, линтеры не отработали: {broken[0].get('Text', '')[:200]}"
        )
    findings = (_finding(issue) for issue in issues)
    return [
        f
        for f in findings
        if not (skip_test_docs and f.category is Category.COMMENTS and is_test_file(f.file))
    ]


def _finding(issue: dict) -> Finding:
    """Одна находка из элемента `Issues` отчёта golangci-lint."""
    linter = issue.get("FromLinter", "golangci-lint")
    text = issue.get("Text", "")
    pos = issue.get("Pos") or {}
    category, severity, rule_id = classify(linter, text)
    return Finding(
        category=category,
        tool="golangci-lint",
        file=pos.get("Filename", "?"),
        line=int(pos.get("Line", 0) or 0),
        message=text,
        severity=severity,
        rule_id=rule_id,
    )


def module_dirs(root: Path, ignore: list[str]) -> list[Path]:
    """Каталоги Go-модулей (с go.mod) под `root`, кроме игнорируемых."""
    return sorted(
        mod.parent
        for mod in root.rglob("go.mod")
        if not is_ignored(mod.relative_to(root).parts, ignore)
    )


class GolangciLintAdapter(Adapter):
    """Go: мёртвый код, проигнорированные ошибки, пустые блоки, доки экспорта."""

    name = "golangci-lint"
    category = Category.COMPLEXITY
    measures = frozenset({Category.DEAD_CODE, Category.COMMENTS})
    languages = frozenset({"go"})

    def is_available(self) -> bool:
        """Нужны golangci-lint и Go-тулчейн (линтеры грузят пакеты через go)."""
        return tool_available("golangci-lint") and tool_available("go")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Прогнать golangci-lint в каждом Go-модуле репозитория."""
        # Анализ идёт по пакетам целиком; в инкрементальном режиме находки
        # вне изменённых файлов отсечёт центральный фильтр runner'а.
        if files is not None and not self.select_files(files):
            return []
        modules = module_dirs(root, config.ignore)
        if not modules:
            raise ToolExecutionError("нет go.mod — golangci-lint работает только по модулю")
        findings: list[Finding] = []
        for module in modules:
            result = run_tool(
                [
                    "golangci-lint", "run",
                    "--config", str(_CONFIG_FILE),
                    "--path-mode", "abs",
                    "--show-stats=false",
                    "./...",
                ],
                cwd=module,
                timeout=900.0,
            )
            # Коды: 0 — чисто, 1 — есть находки; прочие — сбой загрузки/конфига.
            if crashed(result, ok_returncodes=(0, 1)) or not result.stdout.strip():
                raise ToolExecutionError(
                    f"golangci-lint упал в {module.name}: {result.stderr.strip()[:200]}"
                )
            findings += parse_report(result.stdout, config.docstrings_skip_tests)
        return findings


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (GolangciLintAdapter(),)
