"""Полнота slopcheck на корпусе ИИ-кода (v4, H2).

Разметка — `truth/<model>/<task>.yml`: случаи slop, найденные человеком в
патче агента, без оглядки на slopcheck:

    cases:
      - file: internal/notes/auth.go
        line: 12
        kind: restating-comment
        why: «// Check the API key» над сравнением ключа

Случай считается пойманным, если среди НОВЫХ находок (нет в прогоне по
заготовке) есть находка в том же файле, в пределах ±2 строк, и её правило
совместимо с `kind` (`KIND_RULES`). Новые находки без пары — список для
перепроверки: это либо шум, либо случай, пропущенный при разметке.

    uv run python bench/run.py recall [--rerun] [--unmatched]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from slopcheck.baseline import WARN_WHEN_NEW

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import AI, OUT, WORK, apply, load_tasks, _copy_seed  # noqa: E402 — bench/ai не пакет

TRUTH = AI / "truth"
RESULTS = AI / "results"
EVAL = WORK.parent / "ai-eval"
LINE_SLACK = 2

# Тип случая → подстроки правил slopcheck, которые его ловят.
# Пустой список — детектора нет.
KIND_RULES: dict[str, tuple[str, ...]] = {
    "restating-comment": ("trivial-comment", "narrative-comment", "meta-comment"),
    "separator-comment": ("separator-comment",),
    "edit-trace-comment": (),
    "swallowed-error": ("errcheck", "swallowed", "empty-catch", "empty-block", "no-empty"),
    "error-no-wrap": ("error-no-wrap",),
    "ctx-background": (),
    "unused-code": ("unused", "knip", "vulture", "ineffassign", "no-unused", "deadcode"),
    "duplicate": ("duplicate",),
    "complexity": ("complexity", "function-too-long", "file-too-large", "too-many-params"),
    "any-type": ("no-explicit-any", "type-assertion", "ban-ts-comment", "non-null-assertion"),
    "hallucinated-dep": ("missing-package", "hallucinated-import"),
    "fake-test": (),
    "reinvented-util": (),
    "needless-abstraction": ("single-impl-interface",),
    "needless-memo": ("trivial-usememo",),
    "over-defensive": ("useless-reraise", "redundant-try-catch", "no-useless-catch"),
    "effect-misuse": ("exhaustive-deps", "set-state-in-effect"),
    "console-leftover": ("console", "debugger"),
    "panic": ("panic",),
    "suppression": ("lint-suppression",),
    "todo-stub": ("todo",),
    "other": (),
}


@dataclass
class Case:
    """Случай slop из ручной разметки."""

    file: str
    line: int
    kind: str
    why: str = ""
    end_line: int | None = None

    def covers(self, finding: dict) -> bool:
        """Ловит ли находка этот случай: файл, строка ±2, совместимое правило."""
        if finding["file"] != self.file:
            return False
        end = self.end_line or self.line
        line = finding.get("line") or 0
        if not (self.line - LINE_SLACK <= line <= end + LINE_SLACK):
            return False
        rule = f"{finding['tool']}:{finding.get('rule_id') or ''}".lower()
        return any(part in rule for part in KIND_RULES[self.kind])


def load_truth(model: str, task: str) -> list[Case] | None:
    """Разметка патча; None — патч ещё не размечен."""
    path = TRUTH / model / f"{task}.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = [Case(**item) for item in data.get("cases") or []]
    unknown = {c.kind for c in cases} - KIND_RULES.keys()
    if unknown:
        raise SystemExit(f"{path}: неизвестные kind {sorted(unknown)}")
    return cases


def _install(work: Path) -> None:
    """Зависимости, как в живом проекте: без них knip и eslint-typed не работают."""
    if (work / "package.json").exists():
        subprocess.run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", "--silent"],
                       cwd=work, check=True, capture_output=True)
    if (work / "go.mod").exists():
        subprocess.run(["go", "mod", "download"], cwd=work, check=False, capture_output=True)


def _slopcheck(work: Path) -> list[dict]:
    """Находки slopcheck (с проверкой пакетов, как в шаблоне CI)."""
    exe = str(Path(sys.executable).parent / "slopcheck")
    proc = subprocess.run([exe, "run", str(work), "--check-deps", "--format", "json"],
                          capture_output=True, text=True, check=False,
                          env={**os.environ, "SLOPCHECK_HISTORY": "0"})
    if not proc.stdout.strip():
        raise RuntimeError(f"{work}: slopcheck упал: {proc.stderr[-500:]}")
    report = json.loads(proc.stdout)
    findings = [f for cat in report["categories"] for f in cat["findings"]]
    return [dict(f, skipped=report.get("skipped") or []) for f in findings] or [
        {"_skipped": report.get("skipped") or []}
    ]


def _key(f: dict) -> str:
    """Ключ находки без номера строки (как в delta-гейте)."""
    return "|".join([f["category"], f.get("rule_id") or f["tool"], f["file"], f.get("identity") or f["message"]])


def evaluate(model: str, task: str, seed_keys: set[str]) -> list[dict]:
    """Новые находки slopcheck на заготовке с патчем агента."""
    work = apply(task, model, EVAL / model / task)
    _install(work)
    new = [f for f in _slopcheck(work) if "file" in f and _key(f) not in seed_keys]
    # Как гейт и хук: новое подавление линтера без причины — warn.
    return [dict(f, severity="warn") if f.get("rule_id") in WARN_WHEN_NEW else f for f in new]


def seed_keys(seed: str) -> set[str]:
    """Ключи находок на чистой заготовке — их агент не вносил."""
    work = EVAL / "seed" / seed
    _copy_seed({"seed": seed}, work)
    _install(work)
    return {_key(f) for f in _slopcheck(work) if "file" in f}


def patches() -> list[tuple[str, str]]:
    """(модель, задача) всех собранных патчей."""
    return sorted((p.parent.name, p.stem) for p in OUT.glob("*/*.patch"))


def rerun() -> None:
    """Прогнать slopcheck по всем патчам и сохранить новые находки в results/."""
    tasks = load_tasks()
    seeds = {seed: seed_keys(seed) for seed in {t["seed"] for t in tasks.values()}}
    for model, task in patches():
        found = evaluate(model, task, seeds[tasks[task]["seed"]])
        dest = RESULTS / model / f"{task}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{model}/{task}: новых находок {len(found)}")
    if EVAL.exists():
        shutil.rmtree(EVAL / "seed", ignore_errors=True)


def _results(model: str, task: str) -> list[dict]:
    path = RESULTS / model / f"{task}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@dataclass
class Tally:
    """Счёт полноты: всего случаев, поймано любой находкой, поймано warn+."""

    total: int = 0
    any_level: int = 0
    warn_plus: int = 0

    def add(self, case: Case, findings: list[dict]) -> None:
        """Учесть случай."""
        hits = [f for f in findings if case.covers(f)]
        self.total += 1
        self.any_level += bool(hits)
        self.warn_plus += any(f["severity"] in ("warn", "error") for f in hits)


def _pct(part: int, whole: int) -> str:
    """Доля в процентах; при нуле — прочерк."""
    return f"{part / whole:.0%}" if whole else "—"


@dataclass
class Summary:
    """Итог по корпусу: полнота по типам, точность warn+, находки без пары."""

    by_kind: dict[str, Tally] = field(default_factory=dict)
    overall: Tally = field(default_factory=Tally)
    unmatched: Counter = field(default_factory=Counter)
    unlabeled: list[str] = field(default_factory=list)
    warn_new: int = 0
    warn_matched: int = 0

    def account(self, where: str, cases: list[Case], findings: list[dict], verbose: bool) -> None:
        """Учесть один размеченный патч."""
        for case in cases:
            self.by_kind.setdefault(case.kind, Tally()).add(case, findings)
            self.overall.add(case, findings)
            if verbose and not any(case.covers(f) for f in findings):
                print(f"  пропущено: {where} {case.file}:{case.line} [{case.kind}] {case.why}")
        for f in findings:
            matched = any(c.covers(f) for c in cases)
            if f["severity"] in ("warn", "error"):
                self.warn_new += 1
                self.warn_matched += matched
            if matched:
                continue
            self.unmatched[f"{f['tool']}:{f.get('rule_id')}"] += 1
            if verbose:
                print(f"  без пары: {where} {f['file']}:{f.get('line')} "
                      f"[{f['severity']}] {f['tool']}:{f.get('rule_id')} — {f['message'][:90]}")

    def print(self) -> None:
        """Таблица по типам случаев и итоговые строки."""
        print(f"{'тип случая':24} {'всего':>6} {'поймано':>8} {'warn+':>6} {'полнота':>8}")
        for kind, t in sorted(self.by_kind.items(), key=lambda kv: -kv[1].total):
            print(f"{kind:24} {t.total:6} {t.any_level:8} {t.warn_plus:6} {_pct(t.warn_plus, t.total):>8}")
        o = self.overall
        print(f"\nитог: случаев {o.total}, поймано {o.any_level} ({_pct(o.any_level, o.total)}), "
              f"warn+ {o.warn_plus} ({_pct(o.warn_plus, o.total)})")
        # Точность того, что хук вернёт агенту: доля новых warn+ находок,
        # попавших в размеченный случай slop.
        print(f"точность warn+: {self.warn_matched} из {self.warn_new} новых находок "
              f"({_pct(self.warn_matched, self.warn_new)})")
        if self.unmatched:
            print("новые находки без пары (шум или пропуск разметки):",
                  ", ".join(f"{r} ×{n}" for r, n in self.unmatched.most_common()))
        if self.unlabeled:
            print(f"не размечено: {len(self.unlabeled)} — {', '.join(self.unlabeled)}")


def report(verbose: bool = False) -> None:
    """Полнота и точность по размеченным патчам; --unmatched — подробности."""
    summary = Summary()
    for model, task in patches():
        cases = load_truth(model, task)
        if cases is None:
            summary.unlabeled.append(f"{model}/{task}")
        else:
            summary.account(f"{model}/{task}", cases, _results(model, task), verbose)
    summary.print()
