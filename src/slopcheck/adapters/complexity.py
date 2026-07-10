"""Адаптер сложности на базе lizard (мультиязычно, через Python-API).

Функции с цикломатической сложностью выше порога попадают в находки
категории COMPLEXITY; метрика находки = значение сложности.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Iterable, Protocol

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.registry import default_registry

# Порог цикломатической сложности, выше которого функция считается раздутой.
DEFAULT_CCN_THRESHOLD = 10
# Порог, выше которого находка повышается до ERROR.
ERROR_CCN_THRESHOLD = 20


class _FunctionInfo(Protocol):
    name: str
    cyclomatic_complexity: int
    start_line: int


class _FileInfo(Protocol):
    filename: str
    function_list: list[_FunctionInfo]


def findings_from_analysis(
    file_infos: Iterable[_FileInfo], threshold: int = DEFAULT_CCN_THRESHOLD
) -> list[Finding]:
    """Построить находки из результатов анализа lizard."""
    findings: list[Finding] = []
    for info in file_infos:
        for func in info.function_list:
            ccn = func.cyclomatic_complexity
            if ccn <= threshold:
                continue
            severity = Severity.ERROR if ccn > ERROR_CCN_THRESHOLD else Severity.WARN
            findings.append(
                Finding(
                    category=Category.COMPLEXITY,
                    tool="lizard",
                    file=info.filename,
                    line=int(func.start_line),
                    message=f"Высокая цикломатическая сложность ({ccn}): {func.name}",
                    severity=severity,
                    rule_id="high-complexity",
                    metric=float(ccn),
                    # Идентичность — имя функции (файл уже входит в ключ):
                    # рост CCN 15→16 не должен делать находку «новой» для гейта.
                    identity=func.name,
                )
            )
    return findings


def exclude_globs(ignore: list[str]) -> list[str]:
    """Glob'ы для lizard `exclude_pattern` из паттернов конфига.

    Паттерн может означать и каталог (`build`), и файл (`*.min.js`) — даём обе
    формы: обёртка только в `*/{pat}/*` ломала файловые паттерны (получалось
    `*/*.min.js/*`, которое не матчит ни один файл).
    """
    globs: list[str] = []
    for pattern in ignore:
        globs += [f"*/{pattern}/*", f"*/{pattern}", pattern]
    return globs


class LizardAdapter(Adapter):
    """Раздутые функции по цикломатической сложности."""

    name = "lizard"
    category = Category.COMPLEXITY
    languages = frozenset()  # lizard покрывает множество языков

    def is_available(self) -> bool:
        return importlib.util.find_spec("lizard") is not None

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        import lizard

        if files is None:
            targets = [str(root)]
        else:
            # lizard принимает явные пути; select_files не сузит (languages
            # пуст), но отсечёт нечего — просто передаём список как есть.
            targets = [str(root / f) for f in files]
            if not targets:
                return []
        analysis = lizard.analyze(targets, exclude_pattern=exclude_globs(config.ignore))
        return findings_from_analysis(analysis)


default_registry.register(LizardAdapter())
