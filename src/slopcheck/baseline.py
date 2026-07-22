"""Delta-гейт: сравнение прогона с baseline и решение о регрессе.

Гейт красный, если PR ДОБАВИЛ находки уровня не ниже `gate_severity`.
Сравнение — по стабильному ключу находки (Finding.key), устойчивому к сдвигу
строк, с учётом кратности (две одинаковые находки vs одна).

Слепые зоны (skipped-детекторы) учитываются асимметрично и консервативно:
  - детектор работал в baseline, но пропущен в head → гейт ПАДАЕТ с ошибкой
    «ложный зелёный невозможен»: без этого детектора нельзя доказать, что
    slop не добавлен;
  - детектор был слеп в baseline, но работает в head → его находки не могут
    честно считаться «новыми» (baseline их просто не видел); они не валят
    гейт, но выводятся предупреждением для ручной проверки;
  - детектор пропущен и там, и там (симметрично, напр. тул не установлен
    в обоих окружениях) → предупреждение: категория вне контроля гейта,
    но ложного зелёного ОТНОСИТЕЛЬНО baseline нет.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from slopcheck.config import Config, default_config
from slopcheck.models import SEVERITY_RANK as _SEVERITY_RANK
from slopcheck.models import Category, Finding, Report


@dataclass
class Baseline:
    """Baseline-снимок: отчёт плюс список пропущенных на базе детекторов."""

    report: Report
    skipped: list[str] = field(default_factory=list)


@dataclass
class GateOutcome:
    """Результат delta-гейта."""

    passed: bool
    new_findings: list[Finding] = field(default_factory=list)
    blocking: list[Finding] = field(default_factory=list)
    # Не блокирующие замечания: слепые зоны baseline, симметричные пропуски.
    warnings: list[str] = field(default_factory=list)
    # Фатальные проблемы достоверности (head слеп там, где base видел).
    errors: list[str] = field(default_factory=list)


def diff_findings(base: list[Finding], head: list[Finding]) -> list[Finding]:
    """Вернуть находки из `head`, которых не было в `base` (по ключу, с кратностью)."""
    base_counts: Counter = Counter(f.key() for f in base)
    new: list[Finding] = []
    for f in head:
        key = f.key()
        if base_counts.get(key, 0) > 0:
            base_counts[key] -= 1  # погасили совпадение из baseline
        else:
            new.append(f)
    return new


def _skipped_names(skipped: list[str]) -> set[str]:
    """Имена адаптеров из строк вида `jscpd: тул не установлен`."""
    return {entry.split(":", 1)[0].strip() for entry in skipped if entry.strip()}


def _categories_of(adapter_names: set[str]) -> set[Category]:
    """Категории адаптеров по их именам (через глобальный реестр)."""
    from slopcheck.adapters import all_adapters

    by_name = {a.name: a.category for a in all_adapters()}
    return {by_name[n] for n in adapter_names if n in by_name}


def _blindspot_notes(head_names: set[str], base_names: set[str]) -> tuple[list[str], list[str]]:
    """Ошибки и предупреждения по слепым зонам детекторов (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # head слеп там, где base видел → нельзя гарантировать отсутствие регресса.
    head_blind = sorted(head_names - base_names)
    if head_blind:
        errors.append(
            "ложный зелёный невозможен: в head пропущены детекторы, "
            f"работавшие в baseline — {', '.join(head_blind)}"
        )

    # Симметричная слепота: гейт честен относительно baseline, но категория
    # вне контроля — предупреждаем, не валим (напр. опциональный тул не
    # установлен в обоих окружениях).
    both_blind = sorted(head_names & base_names)
    if both_blind:
        warnings.append(
            "детекторы пропущены и в baseline, и в head — их категории вне "
            f"контроля гейта: {', '.join(both_blind)}"
        )
    return errors, warnings


def _split_blocking(
    new: list[Finding], threshold: int, base_blind_cats: set[Category]
) -> tuple[list[Finding], list[str]]:
    """Разделить новые находки на блокирующие и «прощённые» слепотой baseline.

    Находки категорий, которых baseline не видел, не могут честно считаться
    добавленными этим PR — они не блокируют, но попадают в предупреждения.
    """
    above = [f for f in new if _SEVERITY_RANK[f.severity] >= threshold]
    blocking = [f for f in above if f.category not in base_blind_cats]
    demoted = [f for f in above if f.category in base_blind_cats]
    if not demoted:
        return blocking, []
    cats = ", ".join(sorted({f.category.value for f in demoted}))
    return blocking, [
        f"категории [{cats}] отсутствовали в baseline (детектор был "
        f"пропущен) — {len(demoted)} находок не блокируют гейт, "
        "проверьте их вручную"
    ]


def evaluate_gate(
    head: Report,
    base: Report,
    config: Config | None = None,
    *,
    head_skipped: list[str] | None = None,
    base_skipped: list[str] | None = None,
) -> GateOutcome:
    """Оценить регресс: новые находки, слепые зоны и вердикт гейта.

    `head_skipped`/`base_skipped` — списки пропущенных детекторов текущего
    прогона и baseline-снимка (формат runner'а: `имя: причина`).
    """
    config = config or default_config()
    head_names = _skipped_names(head_skipped or [])
    base_names = _skipped_names(base_skipped or [])

    errors, warnings = _blindspot_notes(head_names, base_names)
    new = diff_findings(base.findings, head.findings)
    blocking, demoted_warnings = _split_blocking(
        new,
        _SEVERITY_RANK[config.gate_severity],
        _categories_of(base_names - head_names),
    )
    warnings += demoted_warnings

    return GateOutcome(
        passed=not blocking and not errors,
        new_findings=new,
        blocking=blocking,
        warnings=warnings,
        errors=errors,
    )


def load_baseline(path: Path) -> Baseline:
    """Загрузить baseline из JSON (вывод json-репортера).

    Ключ `skipped` (пропущенные детекторы базового прогона) сохраняется:
    он нужен evaluate_gate для честной обработки слепых зон. Старые снимки
    без `skipped` читаются как «ничего не пропущено» (консервативно: любой
    пропуск в head тогда фатален).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    skipped = data.get("skipped") or []
    if not isinstance(skipped, list):
        skipped = []
    return Baseline(
        report=Report.model_validate(data),
        skipped=[str(s) for s in skipped],
    )
