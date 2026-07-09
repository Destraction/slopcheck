"""Тесты опционального LLM-шва: по умолчанию нейтрален, включается флагом."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slopcheck.cli import app
from slopcheck.config import Config
from slopcheck.llm.review import LLMReviewer, StubReviewer, run_review
from slopcheck.models import Category, Finding
from slopcheck.runner import RunResult
from slopcheck.models import Report


def _empty_result() -> RunResult:
    return RunResult(report=Report(repo="d"))


def test_stub_reviewer_adds_nothing() -> None:
    assert run_review(_empty_result(), Config()) == []


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubReviewer(), LLMReviewer)


def test_custom_reviewer_is_used() -> None:
    class _Fake:
        def review(self, result: RunResult, config: Config) -> list[Finding]:
            return [Finding(category=Category.COMMENTS, tool="llm", file="a.py",
                            line=1, message="subjective note")]

    extra = run_review(_empty_result(), Config(), reviewer=_Fake())
    assert len(extra) == 1
    assert extra[0].tool == "llm"


def _findings_json(stdout: str) -> list:
    import json

    data = json.loads(stdout)
    return [f for c in data["categories"] for f in c["findings"]]


def test_cli_without_flag_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    runner = CliRunner()
    a = runner.invoke(app, ["run", str(tmp_path), "--format", "json"])
    b = runner.invoke(app, ["run", str(tmp_path), "--format", "json"])
    assert a.exit_code == 0
    # Находки воспроизводимы (таймстемп generated_at намеренно не сравниваем).
    assert _findings_json(a.stdout) == _findings_json(b.stdout)


def test_cli_llm_flag_runs_stub(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    res = CliRunner().invoke(
        app, ["run", str(tmp_path), "--format", "json", "--llm-review"]
    )
    assert res.exit_code == 0
    assert "заглушка v1" in res.stderr
