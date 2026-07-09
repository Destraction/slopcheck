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
) -> None:
    """Прогнать детекторы по репозиторию и выдать отчёт."""
    from slopcheck import reporters
    from slopcheck.config import load_config
    from slopcheck.runner import run as run_analysis

    if fmt not in reporters.available_formats():
        typer.echo(
            f"неизвестный формат: {fmt} (доступно: {', '.join(reporters.available_formats())})",
            err=True,
        )
        raise typer.Exit(code=2)

    result = run_analysis(path)

    if llm_review:
        from slopcheck.llm.review import run_review

        extra = run_review(result, load_config(path))
        if extra:
            result.report.categories[0].findings.extend(extra)  # упрощённо: до реальной интеграции
        else:
            typer.echo("LLM-ревью: заглушка v1 — доп. находок нет.", err=True)

    reporters.emit(result, fmt)


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
) -> None:
    """Delta-гейт: провалить (exit 1), если PR добавил slop выше порога severity.

    Base-отчёт готовится заранее: на базовой ветке `slopcheck run --format json`.
    """
    from slopcheck.baseline import evaluate_gate, load_baseline
    from slopcheck.config import load_config
    from slopcheck.runner import run as run_analysis

    head = run_analysis(path)
    base_report = load_baseline(baseline)
    outcome = evaluate_gate(head.report, base_report, load_config(path))

    if outcome.passed:
        typer.echo(
            f"✅ slopcheck gate: новых блокирующих находок нет "
            f"(всего новых: {len(outcome.new_findings)})"
        )
        raise typer.Exit(code=0)

    typer.echo(f"❌ slopcheck gate: PR добавил slop — {len(outcome.blocking)} блокирующих находок:")
    for f in outcome.blocking:
        typer.echo(f"  [{f.severity.value}] {f.category.value} {f.file}:{f.line} — {f.message}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
