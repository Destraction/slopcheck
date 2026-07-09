"""Тесты движка скоринга."""

from __future__ import annotations

from slopcheck.config import Config
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.scoring import score_report


def _finding(category: Category, severity: Severity) -> Finding:
    return Finding(category=category, tool="t", file="a", line=1, message="m", severity=severity)


def _report(categories: list[CategoryResult]) -> Report:
    return Report(repo="demo", categories=categories)


def test_clean_category_scores_100() -> None:
    report = _report([CategoryResult(category=Category.DUPLICATION)])
    scored = score_report(report)
    assert scored.categories[0].score == 100.0
    assert scored.total_score == 100.0


def test_penalty_lowers_score_and_is_deterministic() -> None:
    findings = [_finding(Category.DEAD_CODE, Severity.WARN) for _ in range(2)]
    report = _report([CategoryResult(category=Category.DEAD_CODE, findings=findings)])
    a = score_report(report).categories[0].score
    b = score_report(report).categories[0].score
    assert a == b  # детерминизм
    # penalty = 2*3 = 6, score = 100*20/26 ≈ 76.92
    assert a == 76.92


def test_error_penalised_more_than_info() -> None:
    err = _report([CategoryResult(category=Category.COMMENTS, findings=[_finding(Category.COMMENTS, Severity.ERROR)])])
    info = _report([CategoryResult(category=Category.COMMENTS, findings=[_finding(Category.COMMENTS, Severity.INFO)])])
    assert score_report(err).categories[0].score < score_report(info).categories[0].score


def test_metrics_breakdown() -> None:
    findings = [
        _finding(Category.COMPLEXITY, Severity.ERROR),
        _finding(Category.COMPLEXITY, Severity.WARN),
        _finding(Category.COMPLEXITY, Severity.WARN),
    ]
    report = _report([CategoryResult(category=Category.COMPLEXITY, findings=findings)])
    metrics = score_report(report).categories[0].metrics
    assert metrics["findings"] == 3.0
    assert metrics["error"] == 1.0
    assert metrics["warn"] == 2.0
    assert metrics["info"] == 0.0


def test_total_score_respects_weights() -> None:
    cats = [
        CategoryResult(category=Category.DUPLICATION),  # чистая, score 100
        CategoryResult(
            category=Category.DEAD_CODE,
            findings=[_finding(Category.DEAD_CODE, Severity.ERROR) for _ in range(5)],
        ),
    ]
    report = _report(cats)

    cfg = Config()
    cfg.categories[Category.DEAD_CODE].weight = 3.0  # грязная категория весит больше
    heavy = score_report(report, cfg).total_score

    cfg2 = Config()
    cfg2.categories[Category.DEAD_CODE].weight = 1.0
    light = score_report(report, cfg2).total_score

    # Больший вес грязной категории тянет total ниже.
    assert heavy < light
