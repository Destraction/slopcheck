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

# Вендоренный UI-кит (shadcn/ui и подобные): компоненты копируются в проект
# целиком, со всем API примитива — неиспользуемые экспорты и похожие обёртки
# Dialog/Sheet/Drawer там норма, а не slop. Кит узнаём по каталогу
# `components/ui/`, в котором хоть один файл импортирует radix или cva.
_UI_KIT_RULES = frozenset({
    "knip:knip-exports",
    "knip:knip-types",
    "jscpd:duplicate-block",
    "aislop:code-quality/duplicate-block",
})
_UI_KIT_DIR = re.compile(r"^(.*?(?:^|/)components/ui)/")
_UI_KIT_IMPORT = re.compile(r"""from\s+["'](?:@radix-ui/|class-variance-authority)""")
_UI_KIT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
_HALLUCINATED = re.compile(r'Imports "([^"]+)"')
_PANIC_LITERAL = re.compile(r'panic\(\s*("|`|fmt\.Sprint|errors\.New)')
_CATCH_COMMENT = re.compile(r"catch\b[^{]*\{\s*(//|/\*)")
_CALL = re.compile(r"^\s*(\w+)\(")
_MOUNTED = re.compile(r"set(Is)?Mounted\(\s*true\s*\)")
_ASYNC_WORK = re.compile(r"\.then\(|\bawait\b|\bfetch\(")
_LATEST_REF = re.compile(r"^\s*\w+\.current\s*=\s*[\w.]+;?\s*$")


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


@lru_cache(maxsize=64)
def _is_ui_kit_dir(directory: Path) -> bool:
    """Каталог `components/ui` — вендоренный кит: в нём импортируют radix или cva."""
    for path in directory.rglob("*"):
        if path.suffix in _UI_KIT_SUFFIXES and _UI_KIT_IMPORT.search("\n".join(_read_lines(path))):
            return True
    return False


def _in_ui_kit(root: Path, finding: Finding) -> bool:
    """Находка лежит в вендоренном UI-ките."""
    match = _UI_KIT_DIR.match(finding.file)
    return bool(match) and _is_ui_kit_dir(root / match.group(1))


def _framework_param(root: Path, finding: Finding) -> bool:
    """Параметр сигнатуры фреймворка и параметр catch — не мёртвый код."""
    return finding.message.startswith(("Parameter", "Catch parameter"))


def _panic_on_programmer_error(root: Path, finding: Finding) -> bool:
    """panic("…") на ошибке программиста — идиома Go (regexp.MustCompile);
    плохо — panic(err) на ошибке окружения."""
    return bool(_PANIC_LITERAL.search(_span(root, finding)))


def _sanitized(root: Path, finding: Finding) -> bool:
    """HTML уже прошёл через sanitize (DOMPurify)."""
    return "sanitize" in _span(root, finding, extra=3)


def _act_wrapper(root: Path, finding: Finding) -> bool:
    """Вызов локальной обёртки над act() (`const flush = () => act(...)`):
    act React 19 возвращает thenable даже для синхронного колбэка."""
    call = _CALL.match(_span(root, finding))
    if not call:
        return False
    name = re.escape(call.group(1))
    wrapper = re.compile(rf"\b{name}\s*=\s*(async\s*)?\([^)]*\)\s*=>\s*act\(")
    return bool(wrapper.search("\n".join(_read_lines(root / finding.file))))


def _effect_idiom(root: Path, finding: Finding) -> bool:
    """setState в эффекте как идиома: флаг mounted для гидрации или сброс
    loading/error перед асинхронной загрузкой в том же эффекте."""
    after = _span(root, finding, extra=8)
    return bool(_MOUNTED.search(after) or _ASYNC_WORK.search(after))


def _latest_ref(root: Path, finding: Finding) -> bool:
    """`fnRef.current = fn` при рендере — паттерн «последнее значение в ref»."""
    return bool(_LATEST_REF.match(_span(root, finding)))


# Поправки, которые зависят от кода вокруг находки: правило → признак «не slop».
_DEMOTE_IF = {
    "aislop:eslint/no-unused-vars": _framework_param,
    "aislop:ai-slop/go-library-panic": _panic_on_programmer_error,
    "aislop:security/dangerously-set-innerhtml": _sanitized,
    "eslint:react/no-danger": _sanitized,
    "eslint:@typescript-eslint/no-floating-promises": _act_wrapper,
    "eslint:react-hooks/set-state-in-effect": _effect_idiom,
    "aislop:react/set-state-in-effect": _effect_idiom,
    "aislop:react/refs": _latest_ref,
}


def _demote(root: Path, finding: Finding, key: str) -> bool:
    """Находка верна по форме, но в этом контексте не slop."""
    if key.startswith(_ALWAYS_INFO):
        return True
    if key in _RELAXED_IN_TESTS and is_test_file(finding.file):
        return True
    if key in _UI_KIT_RULES and _in_ui_kit(root, finding):
        return True
    check = _DEMOTE_IF.get(key)
    return bool(check and check(root, finding))


def _covered_separators(findings: list[Finding]) -> set[tuple[str, int | None]]:
    """Строки, где разделитель уже нашёл встроенный `separator-comment`."""
    return {(f.file, f.line) for f in findings if f.rule_id == "separator-comment"}


def _aislop_separator(finding: Finding) -> bool:
    """aislop отдаёт комментарий-разделитель как narrative-comment; отличает только сообщение."""
    return rule_key(finding) == "aislop:ai-slop/narrative-comment" and "decorative separator" in finding.message


def calibrate(findings: list[Finding], root: Path) -> list[Finding]:
    """Применить поправки корпуса: отбросить ложные, понизить шумные до info."""
    _read_lines.cache_clear()
    _is_ui_kit_dir.cache_clear()
    # Один разделитель — одна находка. Копия от aislop штрафовала бы счёт
    # дважды, а агенту несла подсказку про рассказ о правках вместо линейки
    # (cobra completions.go:86, хук на gotify-server).
    separators = _covered_separators(findings)
    result: list[Finding] = []
    for finding in findings:
        key = rule_key(finding)
        if _drop(root, finding, key) or (_aislop_separator(finding) and (finding.file, finding.line) in separators):
            continue
        if finding.severity != Severity.INFO and _demote(root, finding, key):
            finding = finding.model_copy(update={"severity": Severity.INFO})
        result.append(finding)
    return result
