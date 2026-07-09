"""Тесты адаптера сложности (lizard).

Чистая функция — на дак-типизированных фейках; интеграция — вживую через lizard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from slopcheck.adapters.complexity import LizardAdapter, findings_from_analysis
from slopcheck.config import Config
from slopcheck.models import Category, Severity


@dataclass
class _Func:
    name: str
    cyclomatic_complexity: int
    start_line: int


@dataclass
class _File:
    filename: str
    function_list: list = field(default_factory=list)


def test_findings_threshold() -> None:
    files = [
        _File(
            "a.py",
            [
                _Func("simple", 3, 1),          # ниже порога → игнор
                _Func("busy", 12, 10),          # WARN
                _Func("monster", 25, 40),       # ERROR
            ],
        )
    ]
    findings = findings_from_analysis(files, threshold=10)
    assert len(findings) == 2
    busy = next(f for f in findings if "busy" in f.message)
    monster = next(f for f in findings if "monster" in f.message)
    assert busy.severity is Severity.WARN
    assert busy.metric == 12.0
    assert busy.line == 10
    assert monster.severity is Severity.ERROR
    assert all(f.category is Category.COMPLEXITY for f in findings)


def test_lizard_live(tmp_path: Path) -> None:
    src = tmp_path / "cplx.py"
    # Функция с заведомо высокой цикломатикой (много ветвлений).
    branches = "\n".join(
        f"    if x == {i}:\n        x += {i}" for i in range(15)
    )
    src.write_text(f"def tangled(x):\n{branches}\n    return x\n", encoding="utf-8")
    findings = LizardAdapter().run(tmp_path, Config())
    assert any("tangled" in f.message for f in findings)
    assert all(f.metric and f.metric > 10 for f in findings)
