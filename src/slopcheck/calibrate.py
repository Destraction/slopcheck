"""Калибровка находок по корпусу реальных репозиториев (bench/, G9).

Детекторы тянут правила, написанные для других целей: линтер стиля,
a11y, полнота документации. На коде, написанном людьми, часть их находок —
не slop. Здесь собраны поправки, каждая выведена из просмотра находок
корпуса (`bench/labels/`) и сформулирована как признак, а не как список
файлов:

  - отбросить: находка заведомо ложная (не пакет, а каталог под baseUrl;
    catch с поясняющим комментарием; дубль в lock-файле);
  - понизить до info: правило полезно, но в этом контексте шумит выше
    порога (тесты, a11y, служебные dev-зависимости).

info видна в отчёте, но не штрафует счёт и не блокирует гейт.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from slopcheck.adapters.depsexist import tsconfig_aliases
from slopcheck.languages import is_test_file
from slopcheck.models import Finding, Severity

# Дубли там, где копия — норма формата: lock-файлы, примеры в доках, YAML CI.
_DUP_FREE_SUFFIXES = (".md", ".mdx", ".yml", ".yaml", ".lock", "-lock.json", "-lock.yaml", "go.sum")

# В тестах повтор подготовки, `any` для моков и длинные таблицы кейсов — норма.
_RELAXED_IN_TESTS = frozenset({
    "jscpd:duplicate-block",
    "aislop:code-quality/duplicate-block",
    "eslint:@typescript-eslint/no-explicit-any",
    "eslint:@typescript-eslint/no-non-null-assertion",
    "aislop:ai-slop/unsafe-type-assertion",
    "aislop:ai-slop/double-type-assertion",
    "lizard:high-complexity",
    "aislop:complexity/function-too-long",
    "aislop:complexity/file-too-large",
    "golangci-lint:errcheck",
})

# Шумят на любом коде, к slop отношения не имеют.
_ALWAYS_INFO = (
    "aislop:jsx-a11y/",                     # доступность — не задача slop-гейта
    "aislop:ai-slop/hardcoded-url",         # публичный URL сервиса в конфиге
    "aislop:unicorn/no-thenable",           # намеренный thenable в библиотеках
    "aislop:security/dependency-audit-skipped",  # служебное сообщение aislop
    "knip:knip-devDependencies",            # инструменты из конфигов не видны без node_modules
)

_HALLUCINATED = re.compile(r'Imports "([^"]+)"')
_PANIC_LITERAL = re.compile(r'panic\(\s*("|`|fmt\.Sprint|errors\.New)')
_CATCH_COMMENT = re.compile(r"catch\b[^{]*\{\s*(//|/\*)")


def rule_key(finding: Finding) -> str:
    """Ключ правила для калибровки: `tool:rule_id`."""
    return f"{finding.tool}:{finding.rule_id or '-'}"


@lru_cache(maxsize=4096)
def _read_lines(path: Path) -> tuple[str, ...]:
    """Строки файла (кэш на прогон: одни файлы встречаются в разных находках)."""
    try:
        return tuple(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()


def _span(root: Path, finding: Finding, extra: int = 0) -> str:
    """Текст строк находки (line..end_line + extra)."""
    if not finding.line:
        return ""
    end = max(finding.end_line or finding.line, finding.line) + extra
    return "\n".join(_read_lines(root / finding.file)[finding.line - 1 : end])


def _local_module(root: Path, finding: Finding) -> bool:
    """Импорт, который aislop счёл выдуманным пакетом, — каталог под baseUrl/paths."""
    match = _HALLUCINATED.search(finding.message)
    if not match:
        return False
    module = match.group(1)
    directory = (root / finding.file).parent
    while True:
        if (directory / "tsconfig.json").is_file():
            prefixes, base_names = tsconfig_aliases(directory)
            top = module.split("/")[0]
            return top in base_names or any(module.startswith(p) for p in prefixes if p)
        if directory == root or directory.parent == directory:
            return False
        directory = directory.parent


def _drop(root: Path, finding: Finding, key: str) -> bool:
    """Заведомо ложная находка."""
    if key in ("jscpd:duplicate-block", "aislop:code-quality/duplicate-block"):
        return finding.file.endswith(_DUP_FREE_SUFFIXES)
    if key == "aislop:ai-slop/hallucinated-import":
        return _local_module(root, finding)
    if key == "semgrep:empty-catch":
        # Пустой catch с комментарием «почему» — осознанное решение, а не проглатывание.
        return bool(_CATCH_COMMENT.search(_span(root, finding, extra=3)))
    return False


def _demote(root: Path, finding: Finding, key: str) -> bool:
    """Находка верна по форме, но в этом контексте не slop."""
    if key.startswith(_ALWAYS_INFO):
        return True
    if key in _RELAXED_IN_TESTS and is_test_file(finding.file):
        return True
    if key == "aislop:eslint/no-unused-vars":
        # Параметр сигнатуры фреймворка и параметр catch — не мёртвый код.
        return finding.message.startswith(("Parameter", "Catch parameter"))
    if key == "aislop:ai-slop/go-library-panic":
        # panic("…") на ошибке программиста — идиома Go (regexp.MustCompile);
        # плохо — panic(err) на ошибке окружения.
        return bool(_PANIC_LITERAL.search(_span(root, finding)))
    if key in ("aislop:security/dangerously-set-innerhtml", "eslint:react/no-danger"):
        return "sanitize" in _span(root, finding, extra=3)
    return False


def calibrate(findings: list[Finding], root: Path) -> list[Finding]:
    """Применить поправки корпуса: отбросить ложные, понизить шумные до info."""
    _read_lines.cache_clear()
    result: list[Finding] = []
    for finding in findings:
        key = rule_key(finding)
        if _drop(root, finding, key):
            continue
        if finding.severity != Severity.INFO and _demote(root, finding, key):
            finding = finding.model_copy(update={"severity": Severity.INFO})
        result.append(finding)
    return result
