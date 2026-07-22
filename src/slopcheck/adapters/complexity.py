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

# Порог цикломатической сложности, выше которого функция считается раздутой.
DEFAULT_CCN_THRESHOLD = 10
# Порог, выше которого находка повышается до ERROR.
ERROR_CCN_THRESHOLD = 20


class _FunctionInfo(Protocol):
    """Функция в разборе lizard: только нужные нам поля."""

    name: str
    cyclomatic_complexity: int
    start_line: int


class _FileInfo(Protocol):
    """Файл в разборе lizard: имя и список функций."""

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
        """lizard — Python-библиотека, отдельной установки не требует."""
        return importlib.util.find_spec("lizard") is not None

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Посчитать цикломатику через lizard и вернуть раздутые функции."""
        import lizard

        # lizard принимает явные пути; select_files не сузит (languages пуст).
        targets = self.resolve_targets(root, files, absolute=True)
        if targets is None:
            return []
        analysis = lizard.analyze(targets, exclude_pattern=exclude_globs(config.ignore))
        return findings_from_analysis(analysis)


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (LizardAdapter(),)
