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
