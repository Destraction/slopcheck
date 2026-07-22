"""Оркестратор: выбирает адаптеры, запускает их, собирает Report.

Скоринг (F8) здесь не считается — категориям выставляется дефолтный score,
который позже пересчитает движок скоринга.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from slopcheck import languages as lang_detect
from slopcheck.adapters import register_all
from slopcheck.adapters.base import Adapter
from slopcheck.languages import is_ignored
from slopcheck.config import Config, load_config
from slopcheck.models import Category, CategoryResult, Finding, Report
from slopcheck.pathutil import relativize
from slopcheck.registry import Registry
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


def _touches_changed(finding: Finding, changed: set[str]) -> bool:
    """Задевает ли находка хоть один изменённый файл.

    Для парных находок (jscpd) вторая сторона дубля лежит в `identity`
    (`a.py:1-10<->b.py:5-15`) — проверяем и её, иначе дубль «изменённый
    файл копирует старый» потеряется при прогоне от неизменённой стороны.
    """
    if finding.file in changed:
        return True
    return any(part in finding.identity for part in changed) if changed else False


def _run_adapter(
    adapter: Adapter, root: Path, config: Config, files: list[str] | None
) -> tuple[list[Finding], str | None]:
    """Прогнать один детектор: находки либо причина пропуска (не оба сразу).

    Сбой детектора НЕ превращается в молчаливый пустой список: без пометки
    о пропуске delta-гейт ложно зеленел бы на неполном наборе находок.
    """
    if files is not None and not adapter.file_scoped:
        # deptry/knip считают по графу всего проекта — на срезе файлов
        # дадут ложные «неиспользуемые». Честнее пропустить с пометкой.
        return [], f"{adapter.name}: пропущен в инкрементальном режиме"
    if not adapter.is_available():
        return [], f"{adapter.name}: тул не установлен"
    try:
        return adapter.run(root, config, files=files), None
    except ToolNotFound as exc:
        return [], f"{adapter.name}: тул не найден ({exc})"
    except ToolExecutionError as exc:
        return [], f"{adapter.name}: сбой запуска — {exc}"
    except Exception as exc:  # noqa: BLE001 — Python-API адаптеры (lizard,
        # interrogate) кидают произвольные исключения; один сломанный
        # детектор не должен ронять весь прогон — фиксируем как пропуск.
        return [], f"{adapter.name}: сбой детектора — {exc!r}"


def _filter_findings(
    findings: list[Finding], root: Path, config: Config, files: list[str] | None
) -> list[Finding]:
    """Нормализовать пути и отсеять игнорируемое и не задетое изменениями."""
    findings = _normalize_paths(findings, root)
    findings = [
        f for f in findings if not is_ignored(Path(f.file).parts, config.ignore)
    ]
    if files is None:
        return findings
    # Часть детекторов сканирует root целиком (aislop, jscpd) — срезаем
    # находки, не задевшие изменённые файлы, единообразно для всех.
    changed = set(files)
    return [f for f in findings if _touches_changed(f, changed)]


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
    registry = registry if registry is not None else register_all()

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
        adapter_findings, skip_note = _run_adapter(adapter, root, config, files)
        if skip_note:
            skipped.append(skip_note)
            continue
        findings.extend(adapter_findings)
        # Мультикатегорийный детектор (aislop) кладёт находки не только в свою
        # «домашнюю» категорию — измеренной считается любая, где он что-то нашёл.
        measured.add(adapter.category)
        measured.update(f.category for f in adapter_findings)

    findings = _filter_findings(findings, root, config, files)
    report = Report(
        repo=root.name,
        languages=languages,
        categories=_group_into_categories(enabled, findings, measured),
    )
    report = score_report(report, config)
    return RunResult(report=report, skipped=skipped, root=root)
