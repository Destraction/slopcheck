"""Тесты адаптеров мёртвого кода.

vulture и deptry прогоняются вживую (Python-тулы), knip — по фикстуре.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slopcheck.adapters.deadcode import (
    DeptryAdapter,
    VultureAdapter,
    parse_deptry,
    parse_knip,
    parse_vulture,
)
from slopcheck.config import Config
from slopcheck.models import Category

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------- unit (парсеры)

def test_parse_vulture() -> None:
    text = (
        "/repo/mod.py:1: unused import 'os' (90% confidence)\n"
        "/repo/mod.py:8: unused function 'unused_helper' (60% confidence)\n"
        "garbage line without match\n"
    )
    findings = parse_vulture(text)
    assert len(findings) == 2
    assert findings[0].file == "/repo/mod.py"
    assert findings[0].line == 1
    assert findings[0].metric == 90.0
    assert findings[1].message == "unused function 'unused_helper'"
    assert all(f.category is Category.DEAD_CODE for f in findings)


def test_parse_deptry() -> None:
    report = (
        '[{"error": {"code": "DEP002", "message": "\'requests\' unused"},'
        ' "module": "requests",'
        ' "location": {"file": "pyproject.toml", "line": null, "column": null}}]'
    )
    findings = parse_deptry(report)
    assert len(findings) == 1
    assert findings[0].rule_id == "DEP002"
    assert findings[0].file == "pyproject.toml"
    assert findings[0].line == 0


def test_parse_knip() -> None:
    findings = parse_knip((FIXTURES / "knip-report.json").read_text(encoding="utf-8"))
    files = {f.file for f in findings}
    assert "src/orphan.ts" in files
    kinds = {f.rule_id for f in findings}
    assert "unused-file" in kinds
    assert "knip-exports" in kinds
    assert "knip-types" in kinds
    export = next(f for f in findings if f.rule_id == "knip-exports")
    assert export.line == 12
    assert "unusedExport" in export.message


# --------------------------------------------------------------- integration (live)

@pytest.mark.skipif(shutil.which("vulture") is None, reason="vulture не установлен")
def test_vulture_live(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "import os\n\n\ndef used():\n    return 1\n\n\ndef unused_helper():\n    return 2\n\n\nprint(used())\n",
        encoding="utf-8",
    )
    findings = VultureAdapter().run(tmp_path, Config())
    messages = " ".join(f.message for f in findings)
    assert "unused_helper" in messages
    assert "os" in messages


@pytest.mark.skipif(shutil.which("deptry") is None, reason="deptry не установлен")
def test_deptry_live(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["requests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    findings = DeptryAdapter().run(tmp_path, Config())
    assert any("requests" in f.message for f in findings)


def test_vulture_ignores_registered_decorated_functions(tmp_path: Path) -> None:
    """Функция, зарегистрированная декоратором фреймворка, не мёртвая."""
    (tmp_path / "cli.py").write_text(
        "import typer\n\napp = typer.Typer()\n\n\n"
        "@app.command()\ndef version() -> None:\n    print(1)\n\n\n"
        "def orphan() -> None:\n    print(2)\n",
        encoding="utf-8",
    )
    messages = " ".join(f.message for f in VultureAdapter().run(tmp_path, Config()))
    assert "orphan" in messages
    assert "version" not in messages


def test_vulture_ignore_names_from_config(tmp_path: Path) -> None:
    """Имена из dead_code_ignore_names vulture не считает мёртвыми."""
    (tmp_path / "mod.py").write_text(
        "def orphan() -> None:\n    pass\n\n\ndef other() -> None:\n    pass\n",
        encoding="utf-8",
    )
    config = Config(dead_code_ignore_names=["orphan"])
    messages = " ".join(f.message for f in VultureAdapter().run(tmp_path, config))
    assert "orphan" not in messages
    assert "other" in messages


def test_deptry_skipped_without_manifest(tmp_path: Path) -> None:
    """Репозиторий без объявленных зависимостей — не сбой, а «нечего проверять»."""
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    assert DeptryAdapter().run(tmp_path, Config()) == []


def test_has_dependency_manifest_detects_sources(tmp_path: Path) -> None:
    """Манифестом считаем requirements*.txt и pyproject с секцией зависимостей."""
    from slopcheck.adapters.deadcode import has_dependency_manifest

    assert not has_dependency_manifest(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    assert not has_dependency_manifest(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    assert has_dependency_manifest(tmp_path)

    other = tmp_path / "req"
    other.mkdir()
    (other / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert has_dependency_manifest(other)
