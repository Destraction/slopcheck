"""Markdown-репортер: компактная сводка для GitHub Step Summary / PR-комментария."""

from __future__ import annotations

from slopcheck.models import Report, Severity
from slopcheck.runner import RunResult

# Сколько находок показывать в топе.
_TOP_FINDINGS = 20

_SEVERITY_EMOJI = {
    Severity.ERROR: "🔴",
    Severity.WARN: "🟡",
    Severity.INFO: "⚪",
}

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}


def _score_emoji(score: float) -> str:
    if score >= 90:
        return "✅"
    if score >= 70:
        return "⚠️"
    return "❌"


def _summary_section(report: Report) -> list[str]:
    lines = [
        f"## slopcheck — `{report.repo}`",
        "",
        f"**Итоговый slop-score: {_score_emoji(report.total_score)} {report.total_score:.1f} / 100**",
        "",
        "| Категория | Score | Находок | 🔴/🟡/⚪ |",
        "| --- | ---: | ---: | ---: |",
    ]
    for cat in report.categories:
        m = cat.metrics
        ewi = f"{int(m.get('error', 0))}/{int(m.get('warn', 0))}/{int(m.get('info', 0))}"
        lines.append(
            f"| {cat.category.value} | {_score_emoji(cat.score)} {cat.score:.1f} "
            f"| {len(cat.findings)} | {ewi} |"
        )
    return lines


def _findings_section(report: Report) -> list[str]:
    findings = sorted(report.findings, key=lambda f: _SEVERITY_ORDER[f.severity])
    if not findings:
        return ["", "_Находок нет._"]

    lines = ["", "### Топ находок", "", "| | Категория | Место | Сообщение |", "| --- | --- | --- | --- |"]
    for f in findings[:_TOP_FINDINGS]:
        msg = f.message.replace("|", "\\|")
        lines.append(
            f"| {_SEVERITY_EMOJI[f.severity]} | {f.category.value} "
            f"| `{f.file}:{f.line}` | {msg} |"
        )
    if len(findings) > _TOP_FINDINGS:
        lines.append("")
        lines.append(f"_…и ещё {len(findings) - _TOP_FINDINGS} находок._")
    return lines


def render(result: RunResult) -> str:
    """Вернуть Markdown-сводку отчёта."""
    lines = _summary_section(result.report)
    lines += _findings_section(result.report)
    if result.skipped:
        lines += ["", "### Пропущенные детекторы", ""]
        lines += [f"- {note}" for note in result.skipped]
    return "\n".join(lines) + "\n"
