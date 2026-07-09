"""Delta-гейт: сравнение прогона с baseline и решение о регрессе.

Гейт красный, если PR ДОБАВИЛ находки уровня не ниже `gate_severity`.
Сравнение — по стабильному ключу находки (Finding.key), устойчивому к сдвигу
строк, с учётом кратности (две одинаковые находки vs одна).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from slopcheck.config import Config, default_config
from slopcheck.models import Finding, Report, Severity

# Ранг severity: чем выше, тем серьёзнее.
_SEVERITY_RANK = {Severity.INFO: 0, Severity.WARN: 1, Severity.ERROR: 2}


@dataclass
class GateOutcome:
    """Результат delta-гейта."""

    passed: bool
    new_findings: list[Finding] = field(default_factory=list)
    blocking: list[Finding] = field(default_factory=list)


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


def evaluate_gate(
    head: Report, base: Report, config: Config | None = None
) -> GateOutcome:
    """Оценить регресс: новые находки и те из них, что валят гейт по порогу."""
    config = config or default_config()
    threshold = _SEVERITY_RANK[config.gate_severity]

    new = diff_findings(base.findings, head.findings)
    blocking = [f for f in new if _SEVERITY_RANK[f.severity] >= threshold]
    return GateOutcome(passed=not blocking, new_findings=new, blocking=blocking)


def load_baseline(path: Path) -> Report:
    """Загрузить baseline-отчёт из JSON (вывод json-репортера).

    Лишние ключи (напр. `skipped`) игнорируются моделью.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return Report.model_validate(data)
