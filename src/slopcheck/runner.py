"""Оркестратор: выбирает адаптеры, запускает их, собирает Report.

Скоринг (F8) здесь не считается — категориям выставляется дефолтный score,
который позже пересчитает движок скоринга.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import slopcheck.adapters  # noqa: F401  — регистрирует адаптеры в default_registry
from slopcheck import languages as lang_detect
from slopcheck.languages import is_ignored
from slopcheck.config import Config, load_config
from slopcheck.models import Category, CategoryResult, Finding, Report
from slopcheck.pathutil import relativize
from slopcheck.registry import Registry, default_registry
from slopcheck.scoring import score_report
from slopcheck.subprocess_util import ToolExecutionError, ToolNotFound


@dataclass
class RunResult:
    """Результат прогона: отчёт плюс диагностика пропущенных адаптеров."""

    report: Report
    skipped: list[str] = field(default_factory=list)
    root: Path = field(default_factory=lambda: Path("."))


def _normalize_paths(findings: list[Finding], root: Path) -> list[Finding]:
    """Привести пути находок к относительным от корня репозитория.

    Разные тулы отдают то абсолютные, то относительные пути; единый вид нужен
    для консистентного отчёта и стабильных ключей delta-гейта (F12). Пути вне
    репозитория с общим префиксом (например, соседний worktree) приводятся
    через `..` — см. pathutil.relativize.
    """
    normalized: list[Finding] = []
    for f in findings:
        rel = relativize(f.file, root)
        if rel != f.file:
            f = f.model_copy(update={"file": rel})
        normalized.append(f)
    return normalized


def _group_into_categories(
    enabled: list[Category],
    findings: list[Finding],
    measured: set[Category] | None = None,
) -> list[CategoryResult]:
    """Свернуть находки в результаты категорий.

    `measured` — категории, по которым отработал хотя бы один детектор. Не
    попавшие туда помечаются как непроверенные: ноль находок у непроведённой
    проверки не должен читаться как чистый код.
    """
    measured = set(enabled) if measured is None else measured
    by_cat: dict[Category, list[Finding]] = {cat: [] for cat in enabled}
    for f in findings:
        by_cat.setdefault(f.category, []).append(f)
    return [
        CategoryResult(
            category=cat, findings=by_cat[cat], measured=cat in measured
        )
        for cat in enabled
    ]


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
    # Категории, по которым детектор реально отработал. Пропущенный и упавший
    # детектор сюда не попадают: их «ноль находок» ничего не доказывает.
    measured: set[Category] = set()

    for adapter in registry.for_categories(enabled):
        if not adapter.applies_to(languages):
            continue
        if not adapter.is_available():
            skipped.append(f"{adapter.name}: тул не установлен")
            continue
        try:
            findings.extend(adapter.run(root, config))
            measured.add(adapter.category)
        except ToolNotFound as exc:
            skipped.append(f"{adapter.name}: тул не найден ({exc})")
        except ToolExecutionError as exc:
            # Сбой детектора — НЕ молчаливый [] (иначе delta-гейт ложно зеленеет).
            skipped.append(f"{adapter.name}: сбой запуска — {exc}")
        except Exception as exc:  # noqa: BLE001 — Python-API адаптеры (lizard,
            # interrogate) кидают произвольные исключения; один сломанный
            # детектор не должен ронять весь прогон — фиксируем как пропуск.
            skipped.append(f"{adapter.name}: сбой детектора — {exc!r}")

    findings = _normalize_paths(findings, root)
    findings = [
        f for f in findings if not is_ignored(Path(f.file).parts, config.ignore)
    ]
    report = Report(
        repo=root.name,
        languages=languages,
        categories=_group_into_categories(enabled, findings, measured),
    )
    report = score_report(report, config)
    return RunResult(report=report, skipped=skipped, root=root)
