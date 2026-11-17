"""Калибровка slopcheck на корпусе OSS-репозиториев.

    uv run python bench/run.py run [--only NAME] [--docker IMAGE]
        клонировать корпус (кэш ~/.cache/slopcheck-bench), прогнать slopcheck,
        сохранить находки в bench/out/<name>.json и напечатать таблицу шума;
    uv run python bench/run.py report
        только таблица по уже сохранённым находкам и разметке;
    uv run python bench/run.py label NAME [--per-rule 15]
        дописать в bench/labels/<name>.yml неразмеченные находки (verdict: "?")
        — до N на правило, для ручной разметки useful|noise;
    uv run python bench/run.py recall [--rerun] [--unmatched]
        полнота на корпусе ИИ-кода (bench/ai): --rerun заново прогоняет
        slopcheck по патчам агентов, --unmatched печатает новые находки
        без пары в разметке.

Ключ находки — `Finding.key()` (категория|правило|файл|identity-или-сообщение):
он не содержит номера строки, поэтому разметка переживает сдвиги кода.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

BENCH = Path(__file__).resolve().parent
CACHE = Path.home() / ".cache" / "slopcheck-bench"
OUT = BENCH / "out"
LABELS = BENCH / "labels"
VERDICTS = ("useful", "noise")
# Порог из DoD v3: доля шума среди размеченных находок warn+.
NOISE_LIMIT = 0.20


@dataclass
class Repo:
    """Репозиторий корпуса."""

    name: str
    url: str
    commit: str
    path: str = "."

    @property
    def checkout(self) -> Path:
        """Каталог клона в кэше."""
        return CACHE / self.name

    @property
    def target(self) -> Path:
        """Что анализировать: корень клона или подкаталог."""
        return self.checkout / self.path


def load_corpus() -> list[Repo]:
    """Прочитать bench/corpus.yml."""
    data = yaml.safe_load((BENCH / "corpus.yml").read_text(encoding="utf-8"))
    return [Repo(**item) for item in data["repos"]]


def _git(*args: str, cwd: Path | None = None) -> None:
    """git с проверкой кода возврата (сбой клона — исключение, а не пустой корпус)."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def ensure_checkout(repo: Repo) -> None:
    """Клон на нужном коммите; уже готовый клон не трогаем (работает без сети)."""
    head = repo.checkout / ".git"
    if head.exists():
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo.checkout, capture_output=True, text=True
        ).stdout.strip()
        if current == repo.commit:
            return
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--filter=blob:none", repo.url, str(repo.checkout))
    _git("fetch", "--quiet", "origin", repo.commit, cwd=repo.checkout)
    _git("checkout", "--quiet", "--detach", repo.commit, cwd=repo.checkout)


def run_slopcheck(repo: Repo, image: str | None) -> dict:
    """Прогнать slopcheck по репозиторию, вернуть JSON-отчёт."""
    if image:
        cmd = ["docker", "run", "--rm", "-v", f"{repo.target}:/src", image, "run", "/src", "--format", "json"]
    else:
        cmd = [str(Path(sys.executable).parent / "slopcheck"), "run", str(repo.target), "--format", "json"]
    # Замер, а не работа над проектом: историю счёта в клонах корпуса не пишем.
    env = {**os.environ, "SLOPCHECK_HISTORY": "0"}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"{repo.name}: slopcheck упал: {proc.stderr.strip()[-500:]}")
    return json.loads(proc.stdout)


def findings_of(report: dict) -> list[dict]:
    """Находки из JSON-отчёта slopcheck."""
    body = report.get("report", report)
    return [f for cat in body.get("categories", []) for f in cat.get("findings", [])]


def finding_key(f: dict) -> str:
    """Тот же ключ, что `Finding.key()`, одной строкой."""
    return "|".join(
        [f["category"], f.get("rule_id") or f["tool"], f["file"], f.get("identity") or f["message"]]
    )


def rule_of(f: dict) -> str:
    """Правило в таблице: инструмент + rule_id."""
    return f"{f['tool']}:{f.get('rule_id') or '-'}"


def load_labels(name: str) -> dict[str, dict]:
    """Разметка репозитория: ключ → {verdict, why, rule, where}."""
    path = LABELS / f"{name}.yml"
    if not path.exists():
        return {}
    items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {item["key"]: item for item in items}


def save_labels(name: str, labels: dict[str, dict]) -> None:
    """Записать разметку, отсортированную по правилу и ключу."""
    LABELS.mkdir(exist_ok=True)
    items = sorted(labels.values(), key=lambda i: (i["rule"], i["key"]))
    text = yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=120)
    (LABELS / f"{name}.yml").write_text(text, encoding="utf-8")


def load_findings(name: str) -> list[dict]:
    """Сохранённые находки репозитория (пусто, если прогона не было)."""
    path = OUT / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@dataclass
class RuleStats:
    """Счётчики одного правила по корпусу."""

    total: int = 0
    warn_plus: int = 0
    useful: int = 0
    noise: int = 0

    @property
    def noise_share(self) -> float | None:
        """Доля шума среди размеченных; None — не размечено."""
        labeled = self.useful + self.noise
        return self.noise / labeled if labeled else None


def collect_stats(repos: list[Repo]) -> tuple[dict[str, RuleStats], dict[str, int]]:
    """Статистика по правилам и итог по warn+ (размечено/шум/без разметки)."""
    stats: dict[str, RuleStats] = defaultdict(RuleStats)
    totals = {"labeled": 0, "noise": 0, "unlabeled": 0}
    for repo in repos:
        labels = load_labels(repo.name)
        for f in load_findings(repo.name):
            s = stats[rule_of(f)]
            s.total += 1
            warn_plus = f["severity"] in ("warn", "error")
            s.warn_plus += warn_plus
            verdict = labels.get(finding_key(f), {}).get("verdict")
            if verdict not in VERDICTS:
                totals["unlabeled"] += warn_plus
                continue
            setattr(s, verdict, getattr(s, verdict) + 1)
            if warn_plus:
                totals["labeled"] += 1
                totals["noise"] += verdict == "noise"
    return stats, totals


def print_report(repos: list[Repo]) -> bool:
    """Таблица шума по правилам и итог против порога DoD; False — выше порога."""
    stats, totals = collect_stats(repos)
    print(f"{'правило':60} {'всего':>6} {'warn+':>6} {'польза':>7} {'шум':>5} {'шум%':>6}")
    for rule, s in sorted(stats.items(), key=lambda kv: -kv[1].total):
        share = s.noise_share
        pct = f"{share:.0%}" if share is not None else "—"
        print(f"{rule[:60]:60} {s.total:6} {s.warn_plus:6} {s.useful:7} {s.noise:5} {pct:>6}")
    if totals["unlabeled"]:
        # Новое правило или сдвиг находок после обновления тула: в долю шума
        # не входят, пока не размечены.
        print(f"\nwarn+ без разметки: {totals['unlabeled']} — разметить: bench/run.py label <репо>")
    labeled = totals["labeled"]
    if not labeled:
        print("\nwarn+: разметки нет")
        return True
    share = totals["noise"] / labeled
    ok = share <= NOISE_LIMIT
    print(f"\nwarn+: размечено {labeled}, шум {totals['noise']} ({share:.0%}), "
          f"порог {NOISE_LIMIT:.0%} — {'OK' if ok else 'ВЫШЕ ПОРОГА'}")
    return ok


def add_label_stubs(repo: Repo, per_rule: int) -> int:
    """Дописать в разметку до `per_rule` неразмеченных находок на правило."""
    labels = load_labels(repo.name)
    per: dict[str, int] = defaultdict(int)
    for item in labels.values():
        per[item["rule"]] += 1
    added = 0
    for f in load_findings(repo.name):
        key, rule = finding_key(f), rule_of(f)
        if key in labels or per[rule] >= per_rule:
            continue
        labels[key] = {
            "key": key,
            "rule": rule,
            "where": f"{f['file']}:{f['line']}",
            "verdict": "?",
            "why": "",
        }
        per[rule] += 1
        added += 1
    save_labels(repo.name, labels)
    return added


def main() -> None:
    """Точка входа CLI бенча."""
    parser = argparse.ArgumentParser(description="Калибровка slopcheck на корпусе")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--only")
    run_p.add_argument("--docker", metavar="IMAGE")
    sub.add_parser("report")
    label_p = sub.add_parser("label")
    label_p.add_argument("name")
    label_p.add_argument("--per-rule", type=int, default=15)
    recall_p = sub.add_parser("recall")
    recall_p.add_argument("--rerun", action="store_true")
    recall_p.add_argument("--unmatched", action="store_true")
    args = parser.parse_args()
    {"recall": _cmd_recall, "run": _cmd_run, "report": _cmd_report, "label": _cmd_label}[args.cmd](args)


def _cmd_recall(args: argparse.Namespace) -> None:
    """Полнота на корпусе ИИ-кода (bench/ai)."""
    sys.path.insert(0, str(BENCH / "ai"))
    import recall

    if args.rerun:
        recall.rerun()
    recall.report(args.unmatched)


def _cmd_run(args: argparse.Namespace) -> None:
    """Клон → slopcheck → находки в out/ → таблица шума."""
    repos = load_corpus()
    OUT.mkdir(exist_ok=True)
    for repo in repos:
        if args.only and repo.name != args.only:
            continue
        ensure_checkout(repo)
        report = run_slopcheck(repo, args.docker)
        (OUT / f"{repo.name}.json").write_text(
            json.dumps(findings_of(report), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{repo.name}: {len(findings_of(report))} находок; пропущено: {report.get('skipped') or '—'}")
    _exit_on_noise(print_report(repos))


def _cmd_report(_args: argparse.Namespace) -> None:
    """Таблица шума по сохранённым находкам."""
    _exit_on_noise(print_report(load_corpus()))


def _exit_on_noise(ok: bool) -> None:
    """Код выхода 1, если шум выше порога (для еженедельного прогона в CI)."""
    if not ok:
        sys.exit(1)


def _cmd_label(args: argparse.Namespace) -> None:
    """Заготовки разметки для одного репозитория."""
    repo = next(r for r in load_corpus() if r.name == args.name)
    print(f"{repo.name}: добавлено заготовок {add_label_stubs(repo, args.per_rule)}")

if __name__ == "__main__":
    main()
