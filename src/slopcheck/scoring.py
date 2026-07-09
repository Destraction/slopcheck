"""Скоринг: метрики и slop-score по категориям и агрегатный total_score.

Модель детерминированная: каждая находка даёт штраф по severity, штрафы
категории сворачиваются в score 0..100 через мягкую убывающую функцию,
total_score — взвешенное (по конфигу) среднее категорий.
"""

from __future__ import annotations

from slopcheck.config import Config, default_config
from slopcheck.models import CategoryResult, Finding, Report, Severity

# Штраф за находку по уровню.
_SEVERITY_PENALTY = {
    Severity.INFO: 1.0,
    Severity.WARN: 3.0,
    Severity.ERROR: 8.0,
}
# Масштаб убывания: при penalty == SCALE score == 50.
_SCALE = 20.0


def _category_score(penalty: float) -> float:
    """Свернуть суммарный штраф в score 0..100 (100 при нуле находок)."""
    return round(100.0 * _SCALE / (_SCALE + penalty), 2)


def _category_metrics(findings: list[Finding]) -> dict[str, float]:
    metrics = {
        "findings": float(len(findings)),
        "error": 0.0,
        "warn": 0.0,
        "info": 0.0,
    }
    for f in findings:
        metrics[f.severity.value] += 1.0
    return metrics


def score_report(report: Report, config: Config | None = None) -> Report:
    """Вернуть копию отчёта с рассчитанными score категорий и total_score."""
    config = config or default_config()

    scored: list[CategoryResult] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for cat_result in report.categories:
        penalty = sum(_SEVERITY_PENALTY[f.severity] for f in cat_result.findings)
        score = _category_score(penalty)
        metrics = _category_metrics(cat_result.findings)

        scored.append(
            cat_result.model_copy(update={"score": score, "metrics": metrics})
        )

        weight = config.categories.get(cat_result.category)
        weight_value = weight.weight if weight else 1.0
        weighted_sum += score * weight_value
        weight_total += weight_value

    if weight_total:
        total = round(weighted_sum / weight_total, 2)
    elif scored:
        # Все веса обнулены — не рисуем фиктивные 100, берём невзвешенное среднее.
        total = round(sum(c.score for c in scored) / len(scored), 2)
    else:
        total = 100.0
    return report.model_copy(update={"categories": scored, "total_score": total})
