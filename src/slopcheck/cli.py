"""CLI-энтрипоинт slopcheck."""

from __future__ import annotations

from pathlib import Path

import typer

from slopcheck import __version__

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
) -> None:
    """Прогнать детекторы по репозиторию и выдать отчёт.

    Заглушка F1 — оркестрация появится в следующих фичах (F3+).
    """
    typer.echo(f"slopcheck run: {path} (format={fmt}) — оркестрация ещё не реализована (F3+)")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
