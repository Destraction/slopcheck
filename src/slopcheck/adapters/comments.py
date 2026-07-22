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
from slopcheck.subprocess_util import ToolExecutionError, crashed, run_tool, tool_available

_SARIF_LEVEL_TO_SEVERITY = {
    "error": Severity.ERROR,
    "warning": Severity.WARN,
    "note": Severity.INFO,
    "none": Severity.INFO,
}


def _rule_levels(run: dict) -> dict[str, str]:
    """Собрать severity правил из driver.rules (id → defaultConfiguration.level).

    Нужно для источников (напр. semgrep), которые не кладут level в сам result,
    а держат его в определении правила.
    """
    driver = (run.get("tool") or {}).get("driver") or {}
    levels: dict[str, str] = {}
    for rule in driver.get("rules") or []:
        rule_id = rule.get("id")
        level = (rule.get("defaultConfiguration") or {}).get("level")
        if rule_id and level:
            levels[rule_id] = level
    return levels


def parse_sarif(sarif_json: str, tool: str, category: Category) -> list[Finding]:
    """Разобрать SARIF 2.1.0 в находки.

    Читает `runs[].results[]`: ruleId, level, message.text и первую физическую
    локацию. Если у result нет level, берёт его из определения правила.
    """
    data = json.loads(sarif_json)
    findings: list[Finding] = []
    for run in data.get("runs", []):
        rule_levels = _rule_levels(run)
        for result in run.get("results", []):
            message = (result.get("message") or {}).get("text", "")
            level = result.get("level") or rule_levels.get(result.get("ruleId"), "warning")
            severity = _SARIF_LEVEL_TO_SEVERITY.get(level, Severity.WARN)
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
    """Файл и строка первой физической локации SARIF-результата."""
    locations = result.get("locations") or []
    if not locations:
        return ("?", 0)
    phys = (locations[0].get("physicalLocation") or {})
    uri = (phys.get("artifactLocation") or {}).get("uri", "?")
    line = (phys.get("region") or {}).get("startLine", 0) or 0
    return (uri, int(line))


# Куда относить находку aislop по фрагменту её rule_id. Проверяется по
# вхождению подстроки, сверху вниз; что не совпало — COMPLEXITY (общий bucket
# смеллов: lint-правила про a11y, хуки и типы — точно не про комментарии).
_AISLOP_RULE_CATEGORIES: tuple[tuple[str, Category], ...] = (
    ("comment", Category.COMMENTS),
    ("todo", Category.COMMENTS),
    ("doc", Category.COMMENTS),
    ("unused-import", Category.DEAD_CODE),
    ("unused-var", Category.DEAD_CODE),
    ("no-unused", Category.DEAD_CODE),
    ("f401", Category.DEAD_CODE),
    ("dead-code", Category.DEAD_CODE),
    ("unreachable", Category.DEAD_CODE),
    ("duplicate", Category.DUPLICATION),
    ("copy-paste", Category.DUPLICATION),
)


def category_for_aislop_rule(rule_id: str | None) -> Category:
    """Категория slopcheck для правила aislop.

    aislop покрывает все четыре категории сразу, поэтому его находки нельзя
    сваливать в COMMENTS: иначе «мёртвый импорт» не попадёт в dead_code,
    а счёт по категориям перестанет отражать реальность.
    """
    rule = (rule_id or "").lower()
    for fragment, category in _AISLOP_RULE_CATEGORIES:
        if fragment in rule:
            return category
    return Category.COMPLEXITY


class AislopAdapter(Adapter):
    """AI-slop паттерны (нарративные комментарии и пр.) через aislop."""

    name = "aislop"
    category = Category.COMMENTS
    languages = frozenset()  # мультиязычен

    def is_available(self) -> bool:
        """Есть ли в PATH бинарник aislop."""
        return tool_available("aislop")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Прогнать aislop и вернуть его SARIF-находки."""
        # aislop сканирует путь целиком; в инкрементальном режиме находки
        # вне изменённых файлов отсечёт центральный фильтр runner'а.
        result = run_tool(["aislop", "scan", str(root), "--sarif"], cwd=root)
        # Как и у других subprocess-адаптеров: сбой не глотаем (иначе delta-гейт
        # ложно зеленеет). Код 1 у сканеров — «есть находки», штатно.
        if crashed(result, ok_returncodes=(0, 1)):
            raise ToolExecutionError(f"aislop упал: {result.stderr.strip()[:200]}")
        if not result.stdout.strip():
            return []
        findings = parse_sarif(result.stdout, tool="aislop", category=Category.COMMENTS)
        ignored = {rule.lower() for rule in config.aislop_ignore_rules}
        kept: list[Finding] = []
        for f in findings:
            if (f.rule_id or "").lower() in ignored:
                continue
            f.category = category_for_aislop_rule(f.rule_id)
            kept.append(f)
        return kept


def _is_test_file(path: str) -> bool:
    """Тестовый ли файл: `test_*.py`, `*_test.py` или что-то в каталоге `tests`."""
    p = Path(path)
    if p.name.startswith("test_") or p.stem.endswith("_test"):
        return True
    return any(part in {"test", "tests"} for part in p.parts)


class InterrogateAdapter(Adapter):
    """Покрытие Python-докстрингами (interrogate)."""

    name = "interrogate"
    category = Category.COMMENTS
    languages = frozenset({"python"})

    def is_available(self) -> bool:
        """interrogate зовём как библиотеку — проверяем импортируемость."""
        return importlib.util.find_spec("interrogate") is not None

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Посчитать покрытие докстрингами; находка = непокрытый узел."""
        from interrogate.coverage import InterrogateCoverage

        paths = self.resolve_targets(root, files, absolute=True)
        if paths is None:
            return []
        # interrogate матчит исключения как `fnmatch(path, pattern + "*")`,
        # т.е. по префиксу пути — паттерн конфига оборачиваем в glob-компонент,
        # иначе `.venv` не отсеется и мы прочитаем полдиска ради находок,
        # которые runner всё равно выбросит.
        excluded = tuple(f"*/{pattern}/" for pattern in config.ignore)
        cov = InterrogateCoverage(paths=paths, excluded=excluded)
        results = cov.get_coverage()

        findings: list[Finding] = []
        for file_result in results.file_results:
            if config.docstrings_skip_tests and _is_test_file(file_result.filename):
                continue
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


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (AislopAdapter(), InterrogateAdapter())
