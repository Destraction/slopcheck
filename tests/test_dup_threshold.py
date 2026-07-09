"""Тест проброса порога дублей в команду jscpd (без запуска jscpd)."""

from __future__ import annotations

from pathlib import Path

import slopcheck.adapters.duplication as dup
from slopcheck.adapters.duplication import JscpdAdapter
from slopcheck.config import Config
from slopcheck.subprocess_util import ToolResult


def test_config_default_thresholds() -> None:
    cfg = Config()
    assert cfg.dup_min_tokens == 50
    assert cfg.dup_min_lines == 5


def test_jscpd_command_includes_thresholds(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    def fake_run_tool(cmd, cwd=None, timeout=300.0):
        captured["cmd"] = cmd
        # эмулируем отсутствие отчёта → адаптер бросит ToolExecutionError,
        # но нам важна только собранная команда, поэтому пишем пустой отчёт
        (Path(cmd[cmd.index("--output") + 1]) / "jscpd-report.json").write_text(
            '{"duplicates": []}', encoding="utf-8"
        )
        return ToolResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dup, "run_tool", fake_run_tool)
    monkeypatch.setattr(dup, "tool_available", lambda name: True)

    cfg = Config()
    cfg.dup_min_tokens = 17
    cfg.dup_min_lines = 2
    JscpdAdapter().run(tmp_path, cfg)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--min-tokens") + 1] == "17"
    assert cmd[cmd.index("--min-lines") + 1] == "2"
