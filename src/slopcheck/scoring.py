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
    """Счётчики находок категории: всего и по каждому уровню severity."""
    metrics = {
        "findings": float(len(findings)),
        "error": 0.0,
        "warn": 0.0,
        "info": 0.0,
    }
    for f in findings:
        metrics[f.severity.value] += 1.0
    return metrics


def _total_score(scored: list[CategoryResult], config: Config) -> float:
    """Взвешенное среднее по измеренным категориям.

    Категория без единого отработавшего детектора в счёт не идёт: иначе
    «не проверяли» неотличимо от «чисто» (находок ноль, score 100), и итог
    завышается ровно на непроверенное.
    """
    measured = [c for c in scored if c.measured]
    weights = [
        config.categories[c.category].weight if c.category in config.categories else 1.0
        for c in measured
    ]
    weight_total = sum(weights)
    if weight_total:
        return round(sum(c.score * w for c, w in zip(measured, weights)) / weight_total, 2)
    if measured:
        # Все веса обнулены — не рисуем фиктивные 100, берём невзвешенное среднее.
        return round(sum(c.score for c in measured) / len(measured), 2)
    # Не измерено ничего. Ноль честнее сотни: сотня означала бы, что код
    # проверен и чист, а проверок не было вовсе.
    return 0.0


def score_report(report: Report, config: Config | None = None) -> Report:
    """Вернуть копию отчёта с рассчитанными score категорий и total_score."""
    config = config or default_config()
    scored = [
        cat_result.model_copy(
            update={
                "score": _category_score(
                    sum(_SEVERITY_PENALTY[f.severity] for f in cat_result.findings)
                ),
                "metrics": _category_metrics(cat_result.findings),
            }
        )
        for cat_result in report.categories
    ]
    return report.model_copy(
        update={
            "categories": scored,
            "total_score": _total_score(scored, config),
            "unmeasured": [c.category for c in scored if not c.measured],
        }
    )
