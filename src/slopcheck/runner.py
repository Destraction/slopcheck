"""Оркестратор: выбирает адаптеры, запускает их, собирает Report.

Скоринг (F8) здесь не считается — категориям выставляется дефолтный score,
который позже пересчитает движок скоринга.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import slopcheck.adapters  # noqa: F401  — регистрирует адаптеры в default_registry
from slopcheck import languages as lang_detect
from slopcheck.config import Config, load_config
from slopcheck.models import Category, CategoryResult, Finding, Report
from slopcheck.registry import Registry, default_registry
from slopcheck.scoring import score_report
from slopcheck.subprocess_util import ToolNotFound


@dataclass
class RunResult:
    """Результат прогона: отчёт плюс диагностика пропущенных адаптеров."""

    report: Report
    skipped: list[str] = field(default_factory=list)


def _normalize_paths(findings: list[Finding], root: Path) -> list[Finding]:
    """Привести пути находок к относительным от корня репозитория.

    Разные тулы отдают то абсолютные, то относительные пути; единый вид нужен
    для консистентного отчёта и стабильных ключей delta-гейта (F12).
    """
    normalized: list[Finding] = []
    for f in findings:
        path = Path(f.file)
        if path.is_absolute():
            try:
                rel = path.resolve().relative_to(root)
                f = f.model_copy(update={"file": str(rel)})
            except ValueError:
                pass  # путь вне репозитория — оставляем как есть
        normalized.append(f)
    return normalized


def _group_into_categories(
    enabled: list[Category], findings: list[Finding]
) -> list[CategoryResult]:
    by_cat: dict[Category, list[Finding]] = {cat: [] for cat in enabled}
    for f in findings:
        by_cat.setdefault(f.category, []).append(f)
    return [CategoryResult(category=cat, findings=by_cat[cat]) for cat in enabled]


def run(
    root: Path,
    config: Config | None = None,
    registry: Registry | None = None,
) -> RunResult:
    """Прогнать все применимые адаптеры по репозиторию `root`."""
    root = root.resolve()
    config = config or load_config(root)
    registry = registry if registry is not None else default_registry

    languages = config.languages or lang_detect.detect(root, config.ignore)
    enabled = config.enabled_categories()

    findings: list[Finding] = []
    skipped: list[str] = []

    for adapter in registry.for_categories(enabled):
        if not adapter.applies_to(languages):
            continue
        if not adapter.is_available():
            skipped.append(f"{adapter.name}: тул не установлен")
            continue
        try:
            findings.extend(adapter.run(root, config))
        except ToolNotFound as exc:
            skipped.append(f"{adapter.name}: тул не найден ({exc})")

    findings = _normalize_paths(findings, root)
    report = Report(
        repo=root.name,
        languages=languages,
        categories=_group_into_categories(enabled, findings),
    )
    report = score_report(report, config)
    return RunResult(report=report, skipped=skipped)
