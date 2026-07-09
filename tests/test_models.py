"""Тесты нормализованной модели: сериализация/десериализация и ключ дельты."""

from __future__ import annotations

from slopcheck.models import Category, CategoryResult, Finding, Report, Severity


def _sample_report() -> Report:
    findings = [
        Finding(
            category=Category.DUPLICATION,
            tool="jscpd",
            file="src/a.py",
            line=10,
            end_line=20,
            message="Дублирующийся блок (12 строк)",
            severity=Severity.WARN,
            rule_id="dup-block",
            metric=12.0,
        ),
        Finding(
            category=Category.DEAD_CODE,
            tool="vulture",
            file="src/b.py",
            line=3,
            message="Неиспользуемая функция unused_helper",
            severity=Severity.ERROR,
        ),
    ]
    return Report(
        repo="demo",
        languages=["python", "javascript"],
        categories=[
            CategoryResult(
                category=Category.DUPLICATION,
                findings=[findings[0]],
                metrics={"duplication_pct": 4.2},
                score=88.0,
            ),
            CategoryResult(
                category=Category.DEAD_CODE,
                findings=[findings[1]],
                metrics={"dead_symbols": 1.0},
                score=75.0,
            ),
        ],
        total_score=81.5,
    )


def test_report_round_trip() -> None:
    report = _sample_report()
    dumped = report.model_dump_json()
    restored = Report.model_validate_json(dumped)
    assert restored == report


def test_report_findings_flatten() -> None:
    report = _sample_report()
    findings = report.findings
    assert len(findings) == 2
    assert {f.tool for f in findings} == {"jscpd", "vulture"}


def test_finding_key_ignores_line() -> None:
    base = dict(
        category=Category.COMMENTS,
        tool="aislop",
        file="src/c.py",
        message="Нарративный комментарий",
        rule_id="narrative",
    )
    a = Finding(line=5, **base)
    b = Finding(line=42, **base)
    # Сдвиг строки не должен менять ключ дельты.
    assert a.key() == b.key()


def test_finding_key_distinguishes_category() -> None:
    a = Finding(
        category=Category.COMMENTS,
        tool="aislop",
        file="src/c.py",
        line=5,
        message="msg",
    )
    b = Finding(
        category=Category.COMPLEXITY,
        tool="aislop",
        file="src/c.py",
        line=5,
        message="msg",
    )
    assert a.key() != b.key()


def test_score_bounds_enforced() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CategoryResult(category=Category.DUPLICATION, score=120.0)
