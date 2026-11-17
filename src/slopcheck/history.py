"""История slop-score: строка на каждый полный прогон, `slopcheck trend`.

Один счёт ничего не говорит о направлении: 85 после чистки и 85 после
недели правок агента — разные истории. `slopcheck run` по всему репозиторию
дописывает строку в `<repo>/.slopcheck/history.jsonl`. Каталог сам себя
исключает из git (`.slopcheck/.gitignore` со `*`), `.gitignore` проекта не
трогается.

Не пишется:
  - инкрементальный прогон (`--changed`) — его счёт по части файлов
    несравним с полным;
  - в CI (переменная `CI`) и в Docker-образе (`SLOPCHECK_HISTORY=0`):
    история между прогонами CI не хранится, а контейнер оставил бы в
    смонтированном репо файлы владельца root;
  - если в конфиге `history: false`.

Строки с разным набором проверенных категорий несравнимы: `trend` их
помечает, иначе установка нового детектора выглядела бы как регресс.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from slopcheck.config import Config
from slopcheck.models import Report

_log = logging.getLogger(__name__)
HISTORY_DIR = ".slopcheck"
HISTORY_FILE = "history.jsonl"


def enabled(config: Config) -> bool:
    """Писать ли историю: конфиг, не CI и не выключено переменной окружения."""
    if not config.history or os.environ.get("CI"):
        return False
    return os.environ.get("SLOPCHECK_HISTORY", "1").lower() not in ("0", "off", "false", "no")


def _git_state(root: Path) -> tuple[str | None, bool]:
    """Короткий sha HEAD и есть ли незакоммиченные правки (вне git — None, False)."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)

    head = git("rev-parse", "--short", "HEAD")
    if head.returncode != 0:
        return None, False
    status = git("status", "--porcelain", "--", ".", f":!{HISTORY_DIR}")
    return head.stdout.strip(), bool(status.stdout.strip())


def entry_of(report: Report, commit: str | None, dirty: bool) -> dict:
    """Строка истории по отчёту."""
    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in report.findings:
        counts[finding.severity.value] += 1
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "dirty": dirty,
        "score": round(report.total_score, 1),
        "categories": {c.category.value: round(c.score, 1) for c in report.categories if c.measured},
        "counts": counts,
    }


def record(root: Path, report: Report, config: Config) -> Path | None:
    """Дописать прогон в историю; сбой записи не роняет прогон (None)."""
    if not enabled(config):
        return None
    directory = root / HISTORY_DIR
    try:
        directory.mkdir(exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# История slopcheck — локальная, в git не идёт.\n*\n", encoding="utf-8")
        path = directory / HISTORY_FILE
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry_of(report, *_git_state(root)), ensure_ascii=False) + "\n")
    except OSError as exc:
        _log.warning("история slopcheck не записана: %s", exc)
        return None
    return path


def load(root: Path) -> list[dict]:
    """Строки истории в порядке записи; битые строки пропускаются."""
    path = root / HISTORY_DIR / HISTORY_FILE
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def _delta(current: float, previous: float | None) -> str:
    """Изменение счёта со знаком; у первой строки — прочерк."""
    return "—" if previous is None else f"{current - previous:+.1f}"


def render_trend(entries: list[dict], last: int = 20) -> str:
    """Таблица последних `last` прогонов и итог за них."""
    if not entries:
        return "История пуста: она пишется полным `slopcheck run` (не в CI и не в Docker)."
    shown = entries[-last:]
    lines = [f"{'дата':16} {'коммит':9} {'счёт':>6} {'Δ':>6}  🔴/🟡/⚪"]
    previous: dict | None = None
    for entry in shown:
        commit = (entry.get("commit") or "—") + ("*" if entry.get("dirty") else "")
        counts = entry.get("counts", {})
        comparable = previous is None or set(previous.get("categories", {})) == set(entry.get("categories", {}))
        delta = _delta(entry["score"], previous["score"] if previous else None) if comparable else "≠"
        lines.append(
            f"{entry['ts'][:16].replace('T', ' '):16} {commit:9} {entry['score']:6.1f} {delta:>6}  "
            f"{counts.get('error', 0)}/{counts.get('warn', 0)}/{counts.get('info', 0)}"
        )
        previous = entry
    first, final = shown[0], shown[-1]
    lines += [
        "",
        f"за {len(shown)} прогонов: {first['score']:.1f} → {final['score']:.1f} "
        f"({final['score'] - first['score']:+.1f})",
        "* — незакоммиченные правки; ≠ — другой набор проверенных категорий, счёт несравним",
    ]
    return "\n".join(lines)


def score_line(base: Report, head: Report) -> str:
    """Счёт base → head для гейта и сводки CI."""
    base_cats = {c.category for c in base.categories if c.measured}
    head_cats = {c.category for c in head.categories if c.measured}
    line = f"slop-score: base {base.total_score:.1f} → head {head.total_score:.1f} ({head.total_score - base.total_score:+.1f})"
    if base_cats != head_cats:
        line += " — наборы проверенных категорий различаются, счёт несравним"
    return line
