"""Тесты semgrep-адаптера смеллов (v2). Вживую — semgrep из PyPI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slopcheck.adapters.smells import SemgrepSmellsAdapter, _clean_rule_id
from slopcheck.config import Config
from slopcheck.models import Category, Severity


def test_clean_rule_id() -> None:
    assert _clean_rule_id("Users.imarkov.slopcheck.rules.eq-none") == "eq-none"
    assert _clean_rule_id("eq-none") == "eq-none"
    assert _clean_rule_id(None) is None


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep не установлен")
def test_semgrep_smells_live(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "def f(x=[]):\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
        "    if x == None:\n"
        "        return 0\n",
        encoding="utf-8",
    )
    findings = SemgrepSmellsAdapter().run(tmp_path, Config())
    rule_ids = {f.rule_id for f in findings}
    assert "swallowed-exception" in rule_ids
    assert "mutable-default-arg" in rule_ids
    assert "eq-none" in rule_ids
    assert all(f.category is Category.COMPLEXITY for f in findings)
    # severity взята из определения правила (eq-none = INFO)
    eq = next(f for f in findings if f.rule_id == "eq-none")
    assert eq.severity is Severity.INFO
    swallowed = next(f for f in findings if f.rule_id == "swallowed-exception")
    assert swallowed.severity is Severity.WARN


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep не установлен")
def test_semgrep_smells_js_live(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text(
        "function f(x) {\n"
        "  try {\n"
        "    risky();\n"
        "  } catch (e) {}\n"
        "  if (x == null) return;\n"
        "  debugger;\n"
        "}\n",
        encoding="utf-8",
    )
    rule_ids = {f.rule_id for f in SemgrepSmellsAdapter().run(tmp_path, Config())}
    assert "empty-catch" in rule_ids
    assert "debugger-statement" in rule_ids
    assert "loose-eq-null" in rule_ids


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep не установлен")
def test_semgrep_smells_go_live(tmp_path: Path) -> None:
    (tmp_path / "b.go").write_text(
        "package main\n\nfunc do() {\n\t_ = mayFail()\n\tpanic(\"boom\")\n}\n",
        encoding="utf-8",
    )
    rule_ids = {f.rule_id for f in SemgrepSmellsAdapter().run(tmp_path, Config())}
    assert "swallowed-error-go" in rule_ids
    assert "bare-panic-go" in rule_ids
