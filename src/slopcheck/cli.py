"""CLI-энтрипоинт slopcheck."""

from __future__ import annotations

from pathlib import Path

import typer

from slopcheck import __version__
from slopcheck.config import CONFIG_FILENAME, dump_default_config

app = typer.Typer(
    name="slopcheck",
    help="Детектор AI slop без ИИ: оркестратор поверх статических анализаторов.",
    no_args_is_help=True,
    add_completion=False,
)


def _load(path: Path, check_deps: bool):
    """Конфиг репозитория; `--check-deps` включает сетевую проверку пакетов поверх него."""
    from slopcheck.config import load_config

    config = load_config(path)
    return config.model_copy(update={"check_deps": True}) if check_deps else config


@app.command()
def version() -> None:
    """Показать версию slopcheck."""
    typer.echo(f"slopcheck {__version__}")


@app.command(name="init-config")
def init_config(
    path: Path = typer.Argument(
        Path("."),
        file_okay=False,
        dir_okay=True,
        help="Каталог, в котором создать .slopcheck.yml.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Перезаписать существующий конфиг."
    ),
) -> None:
    """Записать дефолтный .slopcheck.yml."""
    target = path / CONFIG_FILENAME
    if target.exists() and not force:
        typer.echo(f"{target} уже существует (--force для перезаписи)", err=True)
        raise typer.Exit(code=1)
    path.mkdir(parents=True, exist_ok=True)
    target.write_text(dump_default_config(), encoding="utf-8")
    typer.echo(f"Записан {target}")


@app.command()
def run(
    path: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Путь к репозиторию для анализа.",
    ),
    fmt: str = typer.Option(
        "console",
        "--format",
        "-f",
        help="Формат отчёта: console | json | sarif | md.",
    ),
    llm_review: bool = typer.Option(
        False,
        "--llm-review",
        help="Опциональный LLM-ревью (off по умолчанию; в v1 — заглушка без вызовов).",
    ),
    changed: str | None = typer.Option(
        None,
        "--changed",
        help=(
            "Инкрементальный режим: анализировать только изменённые файлы. "
            "Значение — ref для diff (merge-base ref...HEAD) или 'staged' "
            "(индекс, сценарий pre-commit)."
        ),
    ),
    check_deps: bool = typer.Option(
        False,
        "--check-deps",
        help="Сверить пакеты с реестрами npm / Go proxy / PyPI (ходит в сеть).",
    ),
) -> None:
    """Прогнать детекторы по репозиторию и выдать отчёт."""
    from slopcheck import reporters
    from slopcheck.runner import run as run_analysis
    from slopcheck.subprocess_util import ToolExecutionError

    if fmt not in reporters.available_formats():
        typer.echo(
            f"неизвестный формат: {fmt} (доступно: {', '.join(reporters.available_formats())})",
            err=True,
        )
        raise typer.Exit(code=2)

    files: list[str] | None = None
    if changed is not None:
        from slopcheck.gitchanged import changed_files

        try:
            files = changed_files(path, changed)
        except ToolExecutionError as exc:
            # Битый ref / не git-репо — это ошибка вызова, а не «нет изменений»:
            # молчаливый полный прогон в pre-commit хуже честного отказа.
            typer.echo(f"--changed: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    config = _load(path, check_deps)
    result = run_analysis(path, config=config, files=files)

    if llm_review:
        _apply_llm_review(result, config)

    reporters.emit(result, fmt)


def _apply_llm_review(result, config) -> None:
    """Прогнать опциональный Gemini-ревью и влить его находки в отчёт."""
    from slopcheck.llm.gemini import GeminiReviewer
    from slopcheck.llm.review import run_review
    from slopcheck.models import CategoryResult
    from slopcheck.scoring import score_report
    from slopcheck.subprocess_util import ToolExecutionError

    reviewer = GeminiReviewer()
    if not reviewer.is_available():
        typer.echo("LLM-ревью: gemini не установлен — пропущено.", err=True)
        return

    try:
        extra = run_review(result, config, reviewer)
    except ToolExecutionError as exc:
        # Не авторизован / упал / таймаут — advisory-ревью не валит основной прогон.
        typer.echo(f"LLM-ревью пропущено: {exc}", err=True)
        return

    if not extra:
        typer.echo("LLM-ревью: субъективных замечаний нет.", err=True)
        return

    # Влить находки в их категорию (создать, если отключена/отсутствует).
    by_cat = {c.category: c for c in result.report.categories}
    for finding in extra:
        target = by_cat.get(finding.category)
        if target is None:
            target = CategoryResult(category=finding.category)
            by_cat[finding.category] = target
            result.report.categories.append(target)
        target.findings.append(finding)

    # Пересчитать score/total_score: они были посчитаны ДО влития LLM-находок.
    result.report = score_report(result.report, config)
    typer.echo(f"LLM-ревью: добавлено замечаний — {len(extra)}.", err=True)


@app.command()
def gate(
    path: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Путь к репозиторию (текущее состояние / PR).",
    ),
    baseline: Path = typer.Option(
        ...,
        "--baseline",
        "-b",
        exists=True,
        dir_okay=False,
        help="JSON-отчёт базовой ветки (вывод `slopcheck run --format json`).",
    ),
    check_deps: bool = typer.Option(
        False,
        "--check-deps",
        help="Сверить пакеты с реестрами npm / Go proxy / PyPI (ходит в сеть).",
    ),
) -> None:
    """Delta-гейт: провалить (exit 1), если PR добавил slop выше порога severity.

    Base-отчёт готовится заранее: на базовой ветке `slopcheck run --format json`.
    """
    from slopcheck.baseline import evaluate_gate, load_baseline
    from slopcheck.runner import run as run_analysis

    config = _load(path, check_deps)
    head = run_analysis(path, config=config)
    base = load_baseline(baseline)
    outcome = evaluate_gate(
        head.report,
        base.report,
        config,
        head_skipped=head.skipped,
        base_skipped=base.skipped,
    )

    # Слепые зоны показываем всегда: молчание о skipped — прямой путь
    # к ложному зелёному.
    if base.skipped:
        typer.echo("Пропущенные детекторы baseline:", err=True)
        for entry in base.skipped:
            typer.echo(f"  - {entry}", err=True)
    if head.skipped:
        typer.echo("Пропущенные детекторы head:", err=True)
        for entry in head.skipped:
            typer.echo(f"  - {entry}", err=True)
    for warning in outcome.warnings:
        typer.echo(f"⚠️  {warning}", err=True)

    if outcome.passed:
        typer.echo(
            f"✅ slopcheck gate: новых блокирующих находок нет "
            f"(всего новых: {len(outcome.new_findings)})"
        )
        raise typer.Exit(code=0)

    for error in outcome.errors:
        typer.echo(f"❌ slopcheck gate: {error}", err=True)
    if outcome.blocking:
        typer.echo(
            f"❌ slopcheck gate: PR добавил slop — {len(outcome.blocking)} блокирующих находок:"
        )
        for f in outcome.blocking:
            typer.echo(
                f"  [{f.severity.value}] {f.category.value} {f.file}:{f.line} — {f.message}"
            )
    raise typer.Exit(code=1)


@app.command(name="check-changed")
def check_changed(
    path: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Путь к git-репозиторию (или его подкаталогу).",
    ),
    staged: bool = typer.Option(
        False, "--staged", help="Только файлы из индекса (сценарий pre-commit)."
    ),
    check_deps: bool = typer.Option(
        False,
        "--check-deps",
        help="Сверить пакеты с реестрами npm / Go proxy / PyPI (ходит в сеть).",
    ),
) -> None:
    """Новые относительно HEAD находки в незакоммиченных правках (exit 1, если есть).

    Старый долг изменённых файлов не показывается — только то, что внесли
    правки. Порог — `hook_severity` из `.slopcheck.yml`.
    """
    from slopcheck.agent_check import FINDINGS_HEADER, check, format_text
    from slopcheck.subprocess_util import ToolExecutionError

    try:
        result = check(path, staged=staged, config=_load(path, check_deps))
    except ToolExecutionError as exc:
        typer.echo(f"check-changed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    for entry in result.skipped:
        typer.echo(f"  пропущено — {entry}", err=True)
    if not result.new:
        typer.echo(f"✅ slopcheck: новых находок нет (файлов проверено: {len(result.files)})")
        raise typer.Exit(code=0)
    typer.echo(f"{FINDINGS_HEADER} — {len(result.new)}:")
    typer.echo(format_text(result))
    raise typer.Exit(code=1)


hook_app = typer.Typer(help="Хуки, которые вызывают внешние инструменты (не для ручного запуска).")
app.add_typer(hook_app, name="hook")


@hook_app.command(name="claude")
def hook_claude() -> None:
    """Stop-хук Claude Code: JSON на stdin, новые находки → exit 2 и текст агенту."""
    import json
    import sys

    from slopcheck.hooks import claude_stop

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    decision = claude_stop(payload)
    if decision.message:
        typer.echo(decision.message, err=True)
    raise typer.Exit(code=decision.exit_code)


@app.command(name="install-hook")
def install_hook(
    target: str = typer.Argument(..., help="claude — Stop-хук Claude Code; git — pre-commit."),
    path: Path = typer.Option(
        Path("."), "--repo", help="Репозиторий для git pre-commit."
    ),
    settings: Path = typer.Option(
        Path.home() / ".claude" / "settings.json",
        "--settings",
        help="settings.json Claude Code (по умолчанию — глобальный).",
    ),
    force: bool = typer.Option(False, "--force", help="Перезаписать чужой pre-commit хук."),
) -> None:
    """Установить хук: Stop-хук Claude Code или git pre-commit."""
    from slopcheck.hooks import install_claude, install_git

    if target == "claude":
        typer.echo(install_claude(settings))
        return
    if target == "git":
        try:
            typer.echo(install_git(path, force=force))
        except (FileExistsError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        return
    typer.echo(f"неизвестная цель: {target} (claude | git)", err=True)
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
