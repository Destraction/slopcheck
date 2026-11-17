"""История счёта: запись полного прогона, trend, строка base → head для гейта."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slopcheck import history
from slopcheck.cli import app
from slopcheck.config import Config
from slopcheck.models import Category, CategoryResult, Finding, Report, Severity


@pytest.fixture(autouse=True)
def _local_env(monkeypatch) -> None:
    # Тесты сами бегут в CI — там история выключена; здесь проверяем локальный режим.
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SLOPCHECK_HISTORY", raising=False)


def _report(score: float, cats=(Category.DEAD_CODE,), warn: int = 0) -> Report:
    findings = [Finding(category=cats[0], tool="t", file="a.py", line=i, message=str(i), severity=Severity.WARN)
                for i in range(warn)]
    categories = [CategoryResult(category=c, findings=findings if c == cats[0] else [], score=score) for c in cats]
    return Report(repo="r", categories=categories, total_score=score)


def test_record_appends_and_self_ignores(tmp_path: Path) -> None:
    history.record(tmp_path, _report(90.0, warn=2), Config())
    history.record(tmp_path, _report(92.5), Config())
    entries = history.load(tmp_path)
    assert [e["score"] for e in entries] == [90.0, 92.5]
    assert entries[0]["counts"] == {"error": 0, "warn": 2, "info": 0}
    assert entries[0]["commit"] is None  # не git-репозиторий
    assert (tmp_path / ".slopcheck" / ".gitignore").read_text().splitlines()[-1] == "*"


@pytest.mark.parametrize(("env", "config"), [({"CI": "true"}, Config()), ({"SLOPCHECK_HISTORY": "0"}, Config()),
                                             ({}, Config(history=False))])
def test_record_disabled(tmp_path: Path, monkeypatch, env: dict, config: Config) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert history.record(tmp_path, _report(90.0), config) is None
    assert not (tmp_path / ".slopcheck").exists()


def test_git_state_dirty_ignores_history_dir(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-b", "main"], ["commit", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, env=env)
    history.record(tmp_path, _report(90.0), Config())  # создаёт .slopcheck/ — это не «правки»
    entry = history.load(tmp_path)[0]
    assert entry["commit"] and entry["dirty"] is False


def test_trend_table_delta_and_incomparable() -> None:
    entries = [history.entry_of(_report(80.0), "aaa1111", False),
               history.entry_of(_report(85.5), "bbb2222", True),
               history.entry_of(_report(70.0, cats=(Category.DEAD_CODE, Category.COMMENTS)), "ccc3333", False)]
    text = history.render_trend(entries)
    rows = text.splitlines()[1:4]
    assert [row.split()[4] for row in rows] == ["—", "+5.5", "≠"]
    assert "bbb2222*" in rows[1]
    assert "за 3 прогонов: 80.0 → 70.0 (-10.0)" in text


def test_trend_empty_history_hint() -> None:
    assert "История пуста" in history.render_trend([])


def test_score_line() -> None:
    assert history.score_line(_report(90.0), _report(87.5)) == "slop-score: base 90.0 → head 87.5 (-2.5)"
    assert "несравним" in history.score_line(_report(90.0), _report(90.0, cats=(Category.COMMENTS,)))


def test_cli_run_records_full_not_changed_and_trend(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\n")
    runner = CliRunner()
    assert runner.invoke(app, ["run", str(tmp_path), "--format", "json"]).exit_code == 0
    assert len(history.load(tmp_path)) == 1
    result = runner.invoke(app, ["trend", str(tmp_path)])
    assert result.exit_code == 0 and "за 1 прогонов" in result.output
    json.loads(runner.invoke(app, ["run", str(tmp_path), "--format", "json"]).output)  # вывод json не испорчен
