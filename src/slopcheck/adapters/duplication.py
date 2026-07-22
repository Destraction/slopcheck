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
from slopcheck.registry import default_registry
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


def parse_report(report_json: str, root: Path | None = None) -> list[Finding]:
    """Разобрать jscpd JSON-отчёт в список находок дублей.

    `root` — корень репозитория для приведения путей обоих файлов клона к
    относительным (тот же relativize, что в runner). Идентичность находки —
    отсортированная пара нормализованных путей, без числа строк и позиций:
    иначе сдвиг второго блока делал бы находку «новой» для delta-гейта.
    """
    data = json.loads(report_json)
    findings: list[Finding] = []
    for dup in data.get("duplicates", []):
        first = dup.get("firstFile", {})
        second = dup.get("secondFile", {})
        lines = dup.get("lines")
        name = first.get("name")
        if not name:
            continue
        second_name = second.get("name", "?")
        second_start = second.get("start", "?")
        if root is not None:
            name = relativize(name, root)
            if second_name != "?":
                second_name = relativize(second_name, root)
        findings.append(
            Finding(
                category=Category.DUPLICATION,
                tool="jscpd",
                file=name,
                line=int(first.get("start", 0) or 0),
                end_line=first.get("end"),
                message=(
                    f"Дублирующийся блок ({lines} строк) — "
                    f"также в {second_name}:{second_start}"
                ),
                severity=Severity.WARN,
                rule_id="duplicate-block",
                metric=float(lines) if lines is not None else None,
                identity="|".join(sorted([name, second_name])),
            )
        )
    return findings


class JscpdAdapter(Adapter):
    """Детект копипасты через jscpd (мультиязычно)."""

    name = "jscpd"
    category = Category.DUPLICATION
    languages = frozenset()  # jscpd покрывает множество форматов

    def is_available(self) -> bool:
        return tool_available("jscpd")

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
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
            return parse_report(report.read_text(encoding="utf-8"), root=root)


default_registry.register(JscpdAdapter())
