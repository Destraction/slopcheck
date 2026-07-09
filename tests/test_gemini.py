"""Тесты Gemini-ревьюера. Живой gemini не зовём — мокаем run_tool."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import slopcheck.llm.gemini as gem
from slopcheck.cli import app
from slopcheck.config import Config
from slopcheck.llm.gemini import (
    GeminiNotAuthenticated,
    GeminiReviewer,
    _collect_code,
    _extract_json_array,
    parse_review,
)
from slopcheck.llm.review import LLMReviewer
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity
from slopcheck.runner import RunResult
from slopcheck.subprocess_util import ToolResult


# --------------------------------------------------------------- парсинг

def test_extract_json_array() -> None:
    assert _extract_json_array('```json\n[{"a":1}]\n```') == '[{"a":1}]'
    assert _extract_json_array("prefix [1,2] suffix") == "[1,2]"
    assert _extract_json_array("нет массива") == "[]"


def test_parse_review_valid() -> None:
    text = '[{"file":"a.py","line":5,"message":"Плохое имя x"}]'
    findings = parse_review(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "gemini"
    assert f.severity is Severity.INFO
    assert f.rule_id == "llm-design"
    assert f.category is Category.COMPLEXITY
    assert f.line == 5


def test_parse_review_tolerates_junk() -> None:
    assert parse_review("не json") == []
    assert parse_review("[]") == []
    assert parse_review('[{"no_file":1}]') == []  # без file — пропуск


def test_reviewer_satisfies_protocol() -> None:
    assert isinstance(GeminiReviewer(), LLMReviewer)


# --------------------------------------------------------------- сбор кода

def test_collect_code_reads_finding_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    report = Report(
        repo="d",
        categories=[
            CategoryResult(
                category=Category.DEAD_CODE,
                findings=[Finding(category=Category.DEAD_CODE, tool="t", file="a.py",
                                  line=1, message="m")],
            )
        ],
    )
    blob = _collect_code(RunResult(report=report, root=tmp_path))
    assert "a.py" in blob
    assert "x = 1" in blob


# --------------------------------------------------------------- review (мок subprocess)

def _patch_gemini(monkeypatch, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
    """Подменить run_tool в gemini-модуле фиксированным результатом."""
    result = ToolResult(returncode=returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(gem, "run_tool", lambda *_a, **_k: result)
    monkeypatch.setattr(gem, "tool_available", lambda *_a, **_k: True)


def _repo(tmp_path: Path, name: str = "a.py") -> RunResult:
    (tmp_path / name).write_text("def foo():\n    return 1\n", encoding="utf-8")
    report = Report(
        repo="d",
        categories=[
            CategoryResult(
                category=Category.DEAD_CODE,
                findings=[Finding(category=Category.DEAD_CODE, tool="t", file=name,
                                  line=1, message="m")],
            )
        ],
    )
    return RunResult(report=report, root=tmp_path)


def test_review_maps_gemini_json(monkeypatch, tmp_path: Path) -> None:
    _patch_gemini(monkeypatch, stdout='[{"file":"a.py","line":1,"message":"Имя foo неинформативно"}]')
    findings = GeminiReviewer().review(_repo(tmp_path), Config())
    assert len(findings) == 1
    assert findings[0].tool == "gemini"
    assert "неинформативно" in findings[0].message


def test_review_raises_when_unauthenticated(monkeypatch, tmp_path: Path) -> None:
    import pytest

    _patch_gemini(monkeypatch, returncode=1, stderr="Please set an Auth method in settings.json")
    with pytest.raises(GeminiNotAuthenticated):
        GeminiReviewer().review(_repo(tmp_path), Config())


def test_review_empty_when_no_files() -> None:
    # Нет находок → нечего читать → пустой результат без вызова gemini.
    assert GeminiReviewer().review(RunResult(report=Report(repo="d")), Config()) == []


# --------------------------------------------------------------- CLI-интеграция

def _cli_llm(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import os\n\n\ndef dead():\n    return 1\n", encoding="utf-8")


def test_cli_llm_review_injects_findings(monkeypatch, tmp_path: Path) -> None:
    _cli_llm(tmp_path)
    _patch_gemini(monkeypatch, stdout='[{"file":"app.py","line":4,"message":"dead — плохое имя"}]')
    res = CliRunner().invoke(app, ["run", str(tmp_path), "--format", "json", "--llm-review"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    gemini_findings = [f for c in data["categories"] for f in c["findings"] if f["tool"] == "gemini"]
    assert len(gemini_findings) == 1
    assert gemini_findings[0]["rule_id"] == "llm-design"


def test_cli_llm_review_graceful_when_unauthed(monkeypatch, tmp_path: Path) -> None:
    _cli_llm(tmp_path)
    _patch_gemini(monkeypatch, returncode=1, stderr="Please set an Auth method")
    res = CliRunner().invoke(app, ["run", str(tmp_path), "--format", "json", "--llm-review"])
    # Не падаем — отчёт всё равно выводится, ревью пропущено с пометкой.
    assert res.exit_code == 0
    assert "залогинен" in res.stderr
    json.loads(res.stdout)  # stdout остаётся валидным JSON-отчётом
