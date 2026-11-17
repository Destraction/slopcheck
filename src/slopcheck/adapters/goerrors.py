"""Go: ошибка в ветке `if err != nil` заменена новой без исходной.

    u, err := url.Parse(raw)
    if err != nil {
        return nil, fmt.Errorf("invalid webhook url")   // причина потеряна
    }

ИИ часто «оформляет» ошибку своим текстом и забывает `%w`: вызывающий код
больше не видит причину, `errors.Is`/`errors.As` не работают. Эвристика без
анализа типов:
  - условие `if` проверяет переменную ошибки (`err`, `rerr`, `fooErr`, `errX`) на `!= nil`,
    в том числе в составном условии и после `;` (`if _, err := f(); err != nil`);
  - в теле ветки есть `return …errors.New(…)` или `return …fmt.Errorf(…)`;
  - сама переменная в теле не упоминается (нет `%w`, логирования, `errors.Is`).

Не трогаем:
  - вызовы вне `return` (`ctx.AbortWithError(404, errors.New(…))`) — ответ
    клиенту, а не проброс ошибки;
  - ветки с комментарием: поясняющий комментарий — признак, что причину
    скрыли осознанно;
  - ошибку разбора `strconv` (`Atoi`, `ParseInt`…): кроме «invalid syntax» в ней
    ничего нет, а своё сообщение («limit must be an integer») для клиента лучше.
"""

from __future__ import annotations

import re
from pathlib import Path

from slopcheck.adapters.base import BuiltinAdapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity

# Строки и комментарии Go. Строки затираются пробелами, комментарии — `#`
# (в коде Go этого символа нет): так сохраняются смещения и видно, был ли
# в ветке комментарий.
_LITERAL = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`[^`]*`', re.DOTALL)
_IF_ERR = re.compile(r"\bif\b[^{\n]*?\b(\w*err|\w+Err|err[A-Z]\w*)\s*!=\s*nil[^{\n]*\{")
# Ошибку присвоил разбор числа: в ней только «invalid syntax» / «out of range».
_STRCONV = re.compile(r"\bstrconv\.(Atoi|Parse\w+)\(")
_RETURN_NEW = re.compile(r"\breturn\b[^\n]*?\b(errors\.New|fmt\.Errorf)\(")


def _mask(match: re.Match) -> str:
    """Литерал той же длины: комментарий → `#`, строка → пробелы (переводы строк сохраняются)."""
    fill = "#" if match.group(0).startswith("/") else " "
    return re.sub(r"[^\n]", fill, match.group(0))


def _block_end(code: str, open_at: int) -> int:
    """Позиция `}`, закрывающей блок с `{` в `open_at`."""
    depth = 0
    for pos in range(open_at, len(code)):
        if code[pos] == "{":
            depth += 1
        elif code[pos] == "}":
            depth -= 1
            if depth == 0:
                return pos
    return len(code)


def _origin(code: str, if_at: int, body_at: int) -> str:
    """Откуда ошибка: строка над `if` и сам `if` с init-частью."""
    if_line = code.rfind("\n", 0, if_at)
    previous_line = code.rfind("\n", 0, max(if_line, 0)) + 1
    return code[previous_line:body_at]


def find_unwrapped(text: str) -> list[tuple[int, str, str]]:
    """(строка, переменная ошибки, код строки) для `return` с новой ошибкой без исходной."""
    code = _LITERAL.sub(_mask, text)
    lines = text.splitlines()
    found = []
    for match in _IF_ERR.finditer(code):
        var = match.group(1)
        start = match.end()
        body = code[start:_block_end(code, start - 1)]
        if "#" in body or re.search(rf"\b{re.escape(var)}\b", body):
            continue
        if _STRCONV.search(_origin(code, match.start(), start)):
            continue
        ret = _RETURN_NEW.search(body)
        if ret:
            line = code.count("\n", 0, start + ret.start()) + 1
            found.append((line, var, lines[line - 1].strip()))
    return found


class GoErrorWrapAdapter(BuiltinAdapter):
    """Новая ошибка вместо исходной в ветке `if err != nil` (Go)."""

    name = "go-error-wrap"
    category = Category.COMPLEXITY
    languages = frozenset({"go"})

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Найти ветки `if err != nil`, теряющие исходную ошибку."""
        findings: list[Finding] = []
        for rel, text in self.sources(root, config, files):
            for line, var, source in find_unwrapped(text):
                findings.append(Finding(
                    category=Category.COMPLEXITY,
                    tool="go-error-wrap",
                    file=rel,
                    line=line,
                    message=(
                        f"Ошибка {var} заменена новой без исходной — причина теряется, "
                        f"errors.Is/As не сработают. Оберните: fmt.Errorf(\"…: %w\", {var}); "
                        "если причину скрываете намеренно, поясните это комментарием в ветке"
                    ),
                    severity=Severity.WARN,
                    rule_id="error-no-wrap",
                    identity=source,
                ))
        return findings


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (GoErrorWrapAdapter(),)
