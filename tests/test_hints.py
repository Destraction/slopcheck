"""Подсказки по починке: поиск по классу, вывод в хуке и md."""

from __future__ import annotations

import pytest

from slopcheck.adapters import all_adapters
from slopcheck.adapters.base import BuiltinAdapter
from slopcheck.agent_check import AgentCheckResult, format_text
from slopcheck.hints import NO_SUPPRESS, hint_for, hints_for
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.reporters import markdown
from slopcheck.runner import RunResult


def _f(rule: str | None, tool: str = "eslint", file: str = "a.ts", line: int = 1) -> Finding:
    return Finding(category=Category.COMPLEXITY, tool=tool, file=file, line=line,
                   message="m", rule_id=rule, severity=Severity.WARN)


def test_lookup_exact_then_last_segment_then_none() -> None:
    assert "unknown" in hint_for(_f("@typescript-eslint/no-explicit-any"))
    assert "%w" in hint_for(_f("error-no-wrap", tool="go-error-wrap"))
    assert hint_for(_f("staticcheck/S1025", tool="golangci-lint")) is None
    assert hint_for(_f("jsx-a11y/no-autofocus", tool="aislop")) is None


def test_one_hint_per_class_in_first_seen_order() -> None:
    found = hints_for([_f("react-hooks/exhaustive-deps"), _f("@typescript-eslint/no-explicit-any"),
                       _f("react-hooks/exhaustive-deps", line=9), _f("jsx-a11y/no-autofocus")])
    assert [rule for rule, _ in found] == ["exhaustive-deps", "no-explicit-any"]


def test_hook_text_ends_with_hints() -> None:
    text = format_text(AgentCheckResult(new=[_f("lint-suppression", tool="lint-suppressions", file="b.ts"),
                                             _f("staticcheck/S1025", tool="golangci-lint", file="a.go")]))
    lines = text.splitlines()
    assert lines[0].startswith("a.go:1 [warn] staticcheck/S1025")
    assert lines[2:5] == ["", "Как чинить:", NO_SUPPRESS] and len(lines) == 6
    assert lines[5].startswith("- lint-suppression: Исправь то, на что жалуется правило")


def test_hook_text_without_known_classes_has_no_hint_block() -> None:
    assert "Как чинить" not in format_text(AgentCheckResult(new=[_f("staticcheck/S1025")]))


def test_markdown_hints_for_top_findings() -> None:
    report = Report(repo="d", categories=[CategoryResult(category=Category.COMPLEXITY, findings=[
        _f("duplicate-block", tool="jscpd"), _f("duplicate-block", tool="jscpd", line=5)])])
    md = markdown.render(RunResult(report=report, skipped=[]))
    assert md.count("- duplicate-block: Вынеси общий код") == 1
    assert "### Как чинить" in md and NO_SUPPRESS in md


# Встроенные эвристики slopcheck: их rule_id известны заранее, подсказка обязана быть.
_BUILTIN_RULES = ["trivial-comment", "separator-comment", "error-no-wrap", "single-impl-interface",
                  "lint-suppression", "duplicate-block", "high-complexity", "unused-code", "unused-file",
                  "missing-package", "missing-docstring"]


@pytest.mark.parametrize("rule", _BUILTIN_RULES)
def test_builtin_rules_have_hints(rule: str) -> None:
    assert hint_for(_f(rule, tool="slopcheck")) is not None


def test_builtin_rule_list_is_complete() -> None:
    # Появилась новая встроенная эвристика → добавь её rule_id в _BUILTIN_RULES и подсказку в hints.py.
    builtin = {a.name for a in all_adapters() if isinstance(a, BuiltinAdapter)}
    assert builtin == {"restating-comments", "separator-comments", "go-error-wrap", "go-single-impl",
                       "lint-suppressions"}
