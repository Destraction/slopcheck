"""Console-репортер на rich: сводная таблица и топ находок."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from slopcheck.models import Report, Severity
from slopcheck.runner import RunResult

# Сколько находок показывать в топе.
_TOP_FINDINGS = 15

_SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARN: "yellow",
    Severity.INFO: "dim",
}


def _score_style(score: float) -> str:
    if score >= 90:
        return "bold green"
    if score >= 70:
        return "yellow"
    return "bold red"


def _summary_table(report: Report) -> Table:
    table = Table(title=f"slopcheck: {report.repo}")
    table.add_column("Категория")
    table.add_column("Score", justify="right")
    table.add_column("Находок", justify="right")
    table.add_column("E/W/I", justify="right")
    for cat in report.categories:
        m = cat.metrics
        ewi = f"{int(m.get('error', 0))}/{int(m.get('warn', 0))}/{int(m.get('info', 0))}"
        table.add_row(
            cat.category.value,
            f"[{_score_style(cat.score)}]{cat.score:.1f}[/]",
            str(len(cat.findings)),
            ewi,
        )
    return table


def _findings_table(report: Report) -> Table:
    table = Table(title="Топ находок")
    table.add_column("Sev")
    table.add_column("Категория")
    table.add_column("Файл:строка")
    table.add_column("Сообщение")
    ordered = sorted(
        report.findings,
        key=lambda f: {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}[f.severity],
    )
    for f in ordered[:_TOP_FINDINGS]:
        style = _SEVERITY_STYLE[f.severity]
        table.add_row(
            f"[{style}]{f.severity.value}[/]",
            f.category.value,
            f"{f.file}:{f.line}",
            f.message,
        )
    return table


def render(result: RunResult, console: Console | None = None) -> None:
    """Напечатать отчёт в stdout."""
    console = console or Console()
    report = result.report

    console.print(_summary_table(report))
    console.print(
        f"Итоговый slop-score: "
        f"[{_score_style(report.total_score)}]{report.total_score:.1f}[/] / 100"
    )
    if report.languages:
        console.print(f"Языки: {', '.join(report.languages)}", style="dim")

    if report.findings:
        console.print(_findings_table(report))

    for note in result.skipped:
        console.print(f"⚠ пропущено — {note}", style="dim")
