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
    enabled: list[Category], findings: list[Finding]
) -> list[CategoryResult]:
    by_cat: dict[Category, list[Finding]] = {cat: [] for cat in enabled}
    for f in findings:
        by_cat.setdefault(f.category, []).append(f)
    return [CategoryResult(category=cat, findings=by_cat[cat]) for cat in enabled]


def _touches_changed(finding: Finding, changed: set[str]) -> bool:
    """Задевает ли находка хоть один изменённый файл.

    Для парных находок (jscpd) вторая сторона дубля лежит в `identity`
    (`a.py:1-10<->b.py:5-15`) — проверяем и её, иначе дубль «изменённый
    файл копирует старый» потеряется при прогоне от неизменённой стороны.
    """
    if finding.file in changed:
        return True
    return any(part in finding.identity for part in changed) if changed else False


def run(
    root: Path,
    config: Config | None = None,
    registry: Registry | None = None,
    files: list[str] | None = None,
) -> RunResult:
    """Прогнать все применимые адаптеры по репозиторию `root`.

    `files` — инкрементальный режим (--changed): относительные posix-пути
    изменённых файлов. Пустой список — валидный вход (нечего проверять):
    вернём пустой отчёт, а не полный прогон.
    """
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
        if files is not None and not adapter.file_scoped:
            # deptry/knip считают по графу всего проекта — на срезе файлов
            # дадут ложные «неиспользуемые». Честнее пропустить с пометкой.
            skipped.append(f"{adapter.name}: пропущен в инкрементальном режиме")
            continue
        if not adapter.is_available():
            skipped.append(f"{adapter.name}: тул не установлен")
            continue
        try:
            findings.extend(adapter.run(root, config, files=files))
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
    if files is not None:
        # Часть детекторов сканирует root целиком (aislop, jscpd) — срезаем
        # находки, не задевшие изменённые файлы, единообразно для всех.
        changed = set(files)
        findings = [f for f in findings if _touches_changed(f, changed)]
    report = Report(
        repo=root.name,
        languages=languages,
        categories=_group_into_categories(enabled, findings),
    )
    report = score_report(report, config)
    return RunResult(report=report, skipped=skipped, root=root)
