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
        help="Формат отчёта: console | json.",
    ),
) -> None:
    """Прогнать детекторы по репозиторию и выдать отчёт."""
    from slopcheck import reporters
    from slopcheck.runner import run as run_analysis

    if fmt not in reporters.available_formats():
        typer.echo(
            f"неизвестный формат: {fmt} (доступно: {', '.join(reporters.available_formats())})",
            err=True,
        )
        raise typer.Exit(code=2)

    result = run_analysis(path)
    reporters.emit(result, fmt)


if __name__ == "__main__":
    app()
