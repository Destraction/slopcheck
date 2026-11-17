"""Обходы линтера (lint-suppressions): разбор директив и подъём новых до warn."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from slopcheck.adapters.suppress import SuppressionAdapter, find_suppressions
from slopcheck.agent_check import check
from slopcheck.baseline import evaluate_gate
from slopcheck.config import Config
from slopcheck.models import Category, CategoryResult, Report, Severity
from slopcheck.registry import Registry


@pytest.mark.parametrize(("lang", "src", "expected"), [
    ("typescript",
     "// eslint-disable-next-line react-hooks/exhaustive-deps\n"
     "f(); // eslint-disable-line no-console -- отладка CLI\n"
     "/* eslint-disable */\n"
     "// @ts-ignore\n"
     "// @ts-expect-error no types for this lib\n"
     "{/* eslint-disable-next-line @next/next/no-img-element */}\n"
     "// biome-ignore lint/suspicious/noExplicitAny: legacy API\n"
     "// eslint-disabled feature flag\n",
     [(1, False), (2, True), (3, False), (4, False), (5, True), (6, False), (7, True)]),
    ("go",
     "x := f() //nolint:errcheck\n"
     "y := g() //nolint:gosec // G703 intentionally user-controlled\n"
     "//lint:ignore SA1019 still needed for go1.20\n"
     "// nolint\n"
     "// nolintable text\n",
     [(1, False), (2, True), (3, True), (4, False)]),
    ("python",
     "import x  # noqa: F401\n"
     "import y  # noqa: E402 — путь нужен до импорта\n"
     "z = 1  # type: ignore[assignment]\n"
     "w = 2  # some text  # noqa\n"
     "q = 3  # pylint: disable=invalid-name\n",
     [(1, False), (2, True), (3, False), (4, False), (5, False)]),
])
def test_directives_and_reasons(lang: str, src: str, expected: list[tuple[int, bool]]) -> None:
    assert [(line, justified) for line, _d, justified in find_suppressions(src, lang)] == expected


def test_directives_inside_strings_ignored() -> None:
    assert find_suppressions('s = "// eslint-disable-next-line"\nt = `/* @ts-ignore */`\n', "typescript") == []
    assert find_suppressions('s = "//nolint"\n', "go") == []
    assert find_suppressions('"""Пример: x  # noqa"""\ns = "# noqa"\n', "python") == []


def test_adapter_info_with_rule_by_reason(tmp_path: Path) -> None:
    (tmp_path / "a.ts").write_text("// @ts-ignore\nx();\n// @ts-expect-error нет типов\ny();\n")
    found = SuppressionAdapter().run(tmp_path, Config())
    assert [(f.line, f.rule_id, f.severity) for f in found] == [
        (1, "lint-suppression", Severity.INFO),
        (3, "lint-suppression-justified", Severity.INFO),
    ]


def _report(findings) -> Report:
    return Report(repo="d", categories=[CategoryResult(category=Category.COMMENTS, findings=findings)])


def test_gate_blocks_only_new_unjustified(tmp_path: Path) -> None:
    (tmp_path / "a.go").write_text("x := f() //nolint:errcheck\n")
    base = SuppressionAdapter().run(tmp_path, Config())
    (tmp_path / "a.go").write_text(
        "x := f() //nolint:errcheck\ny := g() //nolint:gosec\nz := h() //nolint:gosec // путь задаёт пользователь\n"
    )
    head = SuppressionAdapter().run(tmp_path, Config())
    outcome = evaluate_gate(_report(head), _report(base), Config())
    assert [(f.line, f.severity) for f in outcome.blocking] == [(2, Severity.WARN)]
    assert not outcome.passed


def _git(root: Path, *args: str) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def test_hook_returns_new_suppression_only(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.py").write_text("import x  # noqa: F401\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    (tmp_path / "a.py").write_text("import x  # noqa: F401\nimport y  # noqa: F401, E402\n")
    registry = Registry()
    registry.register(SuppressionAdapter())
    result = check(tmp_path, config=Config(), registry=registry)
    assert [(f.line, f.rule_id, f.severity) for f in result.new] == [(2, "lint-suppression", Severity.WARN)]
