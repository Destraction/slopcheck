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
