"""Тесты JS/TS/React-адаптера на ESLint: парсер по фикстуре и живой прогон."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slopcheck.adapters.eslint import EslintAdapter, parse_report
from slopcheck.config import Config
from slopcheck.models import Category, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _findings(skip_test_docs: bool = True):
    report = (FIXTURES / "eslint-report.json").read_text(encoding="utf-8")
    return parse_report(report, skip_test_docs)


def test_parse_report_rules() -> None:
    rules = {f.rule_id for f in _findings()}
    assert {
        "react-hooks/exhaustive-deps",
        "react/no-array-index-key",
        "@typescript-eslint/no-explicit-any",
        "jsdoc/require-jsdoc",
    } <= rules
    assert all(f.tool == "eslint" for f in _findings())


def test_noise_dropped() -> None:
    files = {f.file for f in _findings()}
    rules = {f.rule_id for f in _findings()}
    # Отключение правила чужого плагина и ошибка парсинга — не находки.
    assert "@next/next/no-img-element" not in rules
    assert "/repo/web/src/broken.ts" not in files


def test_categories() -> None:
    by_rule = {f.rule_id: f for f in _findings()}
    assert by_rule["jsdoc/require-jsdoc"].category is Category.COMMENTS
    assert by_rule["jsdoc/require-jsdoc"].severity is Severity.INFO
    assert by_rule["react-hooks/exhaustive-deps"].category is Category.COMPLEXITY


def test_docs_in_test_files_skipped() -> None:
    assert "/repo/web/src/App.test.tsx" not in {f.file for f in _findings()}
    assert "/repo/web/src/App.test.tsx" in {f.file for f in _findings(skip_test_docs=False)}


def _has_plugins() -> bool:
    adapter = EslintAdapter()
    return shutil.which("eslint") is not None and adapter.is_available()


@pytest.mark.skipif(not _has_plugins(), reason="eslint с плагинами не установлен")
def test_live_run(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "List.tsx").write_text(
        "import { useEffect, useState } from 'react';\n\n"
        "export function List({ id, items }: { id: string; items: string[] }) {\n"
        "  const [d, setD] = useState<any>(null);\n"
        "  useEffect(() => { fetch(id).then(setD); }, []);\n"
        "  return <ul>{items.map((x, i) => <li key={i}>{x}{d}</li>)}</ul>;\n"
        "}\n"
    )
    findings = EslintAdapter().run(tmp_path, Config())
    rules = {f.rule_id for f in findings}
    assert {
        "react-hooks/exhaustive-deps",
        "react/no-array-index-key",
        "@typescript-eslint/no-explicit-any",
        "jsdoc/require-jsdoc",
    } <= rules
    assert {f.file for f in findings} == {str(tmp_path / "src" / "List.tsx")}


def test_typed_projects_require_node_modules(tmp_path: Path) -> None:
    from slopcheck.adapters.eslint import typed_projects

    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "tsconfig.json").write_text("{}")
    assert typed_projects(tmp_path, []) == ([], True)
    (tmp_path / "node_modules").mkdir()  # hoisting: зависимости в корне монорепо
    (tmp_path / "web" / "sub").mkdir()
    (tmp_path / "web" / "sub" / "tsconfig.json").write_text("{}")
    assert typed_projects(tmp_path, []) == ([tmp_path / "web"], True)
    assert typed_projects(tmp_path / "web" / "sub", []) == ([], True)


def test_typed_without_node_modules_is_skip(tmp_path: Path) -> None:
    from slopcheck.adapters.eslint import EslintTypedAdapter
    from slopcheck.subprocess_util import ToolExecutionError

    (tmp_path / "tsconfig.json").write_text("{}")
    with pytest.raises(ToolExecutionError, match="node_modules"):
        EslintTypedAdapter().run(tmp_path, Config())


def test_typed_silent_without_typescript_project(tmp_path: Path) -> None:
    from slopcheck.adapters.eslint import EslintTypedAdapter

    (tmp_path / "app.js").write_text("export const a = 1;\n")
    assert EslintTypedAdapter().run(tmp_path, Config()) == []


@pytest.mark.skipif(not _has_plugins(), reason="eslint с плагинами не установлен")
def test_typed_live_floating_promise(tmp_path: Path) -> None:
    import shutil as sh

    from slopcheck.adapters.eslint import EslintTypedAdapter

    project = tmp_path / "typed"
    sh.copytree(FIXTURES / "typed", project)
    findings = EslintTypedAdapter().run(project, Config())
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["@typescript-eslint/no-floating-promises"].line == 4
    assert by_rule["@typescript-eslint/no-unnecessary-type-assertion"].severity is Severity.INFO
