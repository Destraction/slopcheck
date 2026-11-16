"""Бенч калибровки: ключ находки совпадает с Finding.key, статистика считает шум."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from slopcheck.models import Category, Finding, Severity

_SPEC = importlib.util.spec_from_file_location(
    "bench_run", Path(__file__).resolve().parent.parent / "bench" / "run.py"
)
bench = importlib.util.module_from_spec(_SPEC)
# dataclass ищет модуль в sys.modules — без регистрации загрузка падает.
sys.modules["bench_run"] = bench
_SPEC.loader.exec_module(bench)


def _finding(rule: str, file: str, severity: Severity = Severity.WARN) -> Finding:
    return Finding(
        category=Category.COMPLEXITY, tool="eslint", file=file, line=3,
        message="m", rule_id=rule, severity=severity,
    )


def test_finding_key_matches_model_key() -> None:
    f = _finding("react/jsx-key", "a.tsx")
    assert bench.finding_key(f.model_dump(mode="json")) == "|".join(f.key())


def test_collect_stats_counts_noise_among_warn_plus(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bench, "OUT", tmp_path / "out")
    monkeypatch.setattr(bench, "LABELS", tmp_path / "labels")
    (tmp_path / "out").mkdir()
    found = [
        _finding("r1", "a.ts").model_dump(mode="json"),
        _finding("r1", "b.ts").model_dump(mode="json"),
        _finding("r2", "c.ts", Severity.INFO).model_dump(mode="json"),
    ]
    (tmp_path / "out" / "x.json").write_text(json.dumps(found))
    labels = {
        bench.finding_key(found[0]): {"key": "k1", "rule": "eslint:r1", "verdict": "noise"},
        bench.finding_key(found[1]): {"key": "k2", "rule": "eslint:r1", "verdict": "useful"},
        bench.finding_key(found[2]): {"key": "k3", "rule": "eslint:r2", "verdict": "noise"},
    }
    monkeypatch.setattr(bench, "load_labels", lambda _name: labels)

    stats, totals = bench.collect_stats([bench.Repo(name="x", url="u", commit="c")])
    assert stats["eslint:r1"].noise_share == 0.5
    # info-находка в итог warn+ не входит.
    assert totals == {"labeled": 2, "noise": 1}


# Корпус ИИ-кода: сопоставление находки со случаем из разметки.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench" / "ai"))
import recall  # noqa: E402


def _raw(rule: str, file: str, line: int, tool: str = "knip") -> dict:
    return {"tool": tool, "rule_id": rule, "file": file, "line": line, "severity": "warn",
            "message": "m", "category": "dead_code"}


def test_case_covers_by_file_line_and_kind() -> None:
    case = recall.Case(file="src/a.ts", line=10, kind="unused-code")
    assert case.covers(_raw("knip-exports", "src/a.ts", 12))
    assert not case.covers(_raw("knip-exports", "src/a.ts", 13))  # дальше ±2
    assert not case.covers(_raw("knip-exports", "src/b.ts", 10))  # другой файл
    assert not case.covers(_raw("trivial-comment", "src/a.ts", 10, tool="aislop"))  # правило не про этот тип


def test_summary_recall_and_precision() -> None:
    summary = recall.Summary()
    cases = [recall.Case(file="a.ts", line=1, kind="unused-code"),
             recall.Case(file="a.ts", line=20, kind="over-defensive")]
    summary.account("m/t", cases, [_raw("knip-exports", "a.ts", 1), _raw("knip-types", "b.ts", 5)], verbose=False)
    assert (summary.overall.total, summary.overall.warn_plus) == (2, 1)
    assert (summary.warn_matched, summary.warn_new) == (1, 2)
