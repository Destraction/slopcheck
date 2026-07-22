"""Адаптер дублей на базе jscpd (copy/paste detector).

jscpd — Node-тул; здесь он вызывается как внешний бинарник, а его JSON-отчёт
нормализуется в Finding. Парсинг вынесен в чистую функцию `parse_report`,
чтобы тестировать без запуска jscpd.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.pathutil import relativize
from slopcheck.subprocess_util import ToolExecutionError, run_tool, tool_available

_REPORT_NAME = "jscpd-report.json"


def _ignore_globs(ignore: list[str]) -> list[str]:
    """Glob'ы для jscpd `--ignore` из паттернов конфига.

    Паттерн может означать и каталог (`build`), и файл (`*.min.js`) —
    даём обе формы, чтобы не гадать: лишний glob безвреден, а обёртка
    только в `**/{pat}/**` ломала файловые паттерны.
    """
    globs: list[str] = []
    for pattern in ignore:
        globs += [f"**/{pattern}/**", f"**/{pattern}", pattern]
    return globs


def _strip_format_suffix(name: str, fmt: str | None) -> str:
    """Убрать хвост `:<format>`, который jscpd вешает на фрагменты.

    Для встроенных фрагментов (код внутри markdown) jscpd отдаёт имя вида
    `docs/GUIDE.md:markdown` — такого пути на диске нет, он ломает и переход
    по ссылке, и ключ delta-гейта.
    """
    suffix = f":{fmt}" if fmt else None
    return name[: -len(suffix)] if suffix and name.endswith(suffix) else name


def _is_self_overlap(first: dict, second: dict, same_file: bool) -> bool:
    """Вырожденный клон: обе стороны — один файл с пересекающимися строками.

    jscpd изредка отдаёт такой «дубль сам с собой» (сдвиг на символ внутри
    того же блока). Полезной информации в нём нет, только шум.
    """
    if not same_file:
        return False
    start_a, end_a = int(first.get("start", 0) or 0), int(first.get("end", 0) or 0)
    start_b, end_b = int(second.get("start", 0) or 0), int(second.get("end", 0) or 0)
    return start_a <= end_b and start_b <= end_a


def _clone_name(side: dict, fmt: str | None, root: Path | None, default: str) -> str:
    """Имя файла одной стороны клона: без хвоста формата и относительно root."""
    name = side.get("name") or default
    name = _strip_format_suffix(name, fmt)
    return relativize(name, root) if root is not None else name


def _finding_from_clone(dup: dict, root: Path | None) -> Finding | None:
    """Собрать находку из одного клона jscpd; None — клон отбрасывается."""
    first = dup.get("firstFile", {})
    if not first.get("name"):
        return None
    second = dup.get("secondFile", {})
    fmt = dup.get("format")
    name = _clone_name(first, fmt, root, default="?")
    second_name = _clone_name(second, fmt, root, default="?")

    same_file = name == second_name
    if _is_self_overlap(first, second, same_file):
        return None

    second_start = second.get("start", "?")
    where = (
        f"в этом же файле, строка {second_start}"
        if same_file
        else f"в {second_name}:{second_start}"
    )
    lines = dup.get("lines")
    return Finding(
        category=Category.DUPLICATION,
        tool="jscpd",
        file=name,
        line=int(first.get("start", 0) or 0),
        end_line=first.get("end"),
        message=f"Дублирующийся блок ({lines} строк) — также {where}",
        severity=Severity.WARN,
        rule_id="duplicate-block",
        metric=float(lines) if lines is not None else None,
        identity="|".join(sorted([name, second_name])),
    )


def parse_report(
    report_json: str,
    root: Path | None = None,
    ignore_formats: list[str] | None = None,
) -> list[Finding]:
    """Разобрать jscpd JSON-отчёт в список находок дублей.

    `root` — корень репозитория для приведения путей обоих файлов клона к
    относительным (тот же relativize, что в runner). Идентичность находки —
    отсортированная пара нормализованных путей, без числа строк и позиций:
    иначе сдвиг второго блока делал бы находку «новой» для delta-гейта.

    `ignore_formats` — форматы jscpd, находки в которых отбрасываются
    (по умолчанию проза вроде markdown, см. `Config.dup_ignore_formats`).
    """
    data = json.loads(report_json)
    skip_formats = {f.lower() for f in (ignore_formats or [])}
    findings: list[Finding] = []
    for dup in data.get("duplicates", []):
        fmt = dup.get("format")
        if fmt and fmt.lower() in skip_formats:
            continue
        finding = _finding_from_clone(dup, root)
        if finding is not None:
            findings.append(finding)
    return findings


class JscpdAdapter(Adapter):
    """Детект копипасты через jscpd (мультиязычно)."""

    name = "jscpd"
    category = Category.DUPLICATION
    languages = frozenset()  # jscpd покрывает множество форматов

    def is_available(self) -> bool:
        """Есть ли в PATH бинарник jscpd."""
        return tool_available("jscpd")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Прогнать jscpd и вернуть находки-дубли."""
        # Дубли — парное свойство: изменённый файл может дублировать
        # неизменённый, поэтому сканируем весь root даже в инкрементальном
        # режиме; runner оставит только находки, задевшие изменённые файлы
        # (учитывая обе стороны пары через identity).
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            cmd = [
                "jscpd",
                str(root),
                "--reporters",
                "json",
                "--output",
                str(out_dir),
                "--silent",
                "--min-tokens",
                str(config.dup_min_tokens),
                "--min-lines",
                str(config.dup_min_lines),
            ]
            globs = _ignore_globs(config.ignore)
            if globs:
                # jscpd ждёт один comma-separated список глобов.
                cmd += ["--ignore", ",".join(globs)]
            run_tool(cmd, cwd=root)

            report = out_dir / _REPORT_NAME
            if not report.exists():
                # jscpd всегда пишет отчёт при успехе; его отсутствие = сбой,
                # а не «дублей нет» — не глотаем молча (иначе ложный зелёный гейт).
                raise ToolExecutionError("jscpd не создал JSON-отчёт")
            return parse_report(
                report.read_text(encoding="utf-8"),
                root=root,
                ignore_formats=config.dup_ignore_formats,
            )


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (JscpdAdapter(),)
