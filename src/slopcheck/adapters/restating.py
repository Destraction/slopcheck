"""Комментарии, пересказывающие следующую строку кода (Go, JS/TS).

    // Fetch the data
    fetchData()

Такой комментарий ничего не объясняет: он повторяет имена из кода словами.
Это типичный след ИИ. aislop ловит часть случаев; здесь — детерминированная
эвристика по словам:
  - одиночный `//`-комментарий (не часть многострочного пояснения), за
    которым идёт строка кода;
  - слова комментария без стоп-слов, с грубым стеммингом;
  - находка, если почти все слова есть среди идентификаторов следующей строки.

Не трогаем: doc-комментарии объявлений (в Go `// Start starts …` — конвенция),
директивы (`//go:`, `//nolint`, `// eslint-…`, `@ts-…`), TODO/FIXME
(их считает aislop), комментарии на других языках, кроме английского
(со словами кода они не совпадут).
"""

from __future__ import annotations

import re
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import lang_for_path, walk_files
from slopcheck.models import Category, Finding, Severity

_LANGS = frozenset({"go", "javascript", "typescript"})
_COMMENT = re.compile(r"^\s*//\s?(.*)$")
_DIRECTIVE = re.compile(r"^(go:|nolint|eslint|@ts-|prettier-|istanbul|c8 |#|/|todo|fixme|xxx|hack)", re.I)
# Объявление сразу под комментарием → это doc-комментарий, а не пересказ.
_DECLARATION = re.compile(
    r"^\s*(export\s+|func\s|type\s|var\s|const\s+[A-Z]|class\s|interface\s|"
    r"(async\s+)?function\s|public\s|private\s|protected\s|@)"
)
_WORD = re.compile(r"[A-Za-z]+")
# Строковые литералы: слова в них — данные, а не имена кода.
_STRING = re.compile(r"""'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`[^`]*`""")
# Поле структуры Go (`flags *flag.FlagSet`, `Name string \`json:"name"\``).
_GO_FIELD = re.compile(r"^\s*[A-Za-z_]\w*\s+[*\[\]A-Za-z_.{}]+(\s+`[^`]*`)?\s*$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STOP = frozenset(
    "a an the to of and or for in on at by with from into onto as is are be been was "
    "it its this that these those we our us you your i me my then now here there if "
    "else so just also all any some each every new current given".split()
)
# Операторы, которые пересказывают словами.
_OPERATOR_WORDS = {"++": "increment", "--": "decrement", "+=": "add", "-=": "subtract", "return": "return"}
# Общепринятые сокращения в именах: комментарий пишет слово целиком.
_ABBREVIATIONS = {
    "err": "error", "ctx": "context", "cfg": "config", "conf": "config", "req": "request",
    "res": "response", "resp": "response", "msg": "message", "btn": "button", "idx": "index",
    "num": "number", "str": "string", "val": "value", "tmp": "temporary", "db": "database",
    "conn": "connection", "args": "argument", "params": "parameter", "init": "initialize",
}
# Доля слов комментария из 3+ слов, которые должны найтись в коде
# (короткий комментарий из 1–2 слов должен совпасть целиком).
_MATCH_SHARE_LONG = 0.8


def _stem(word: str) -> str:
    """Грубый английский стемминг: fetching/fetched/fetches → fetch."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def comment_words(text: str) -> list[str]:
    """Значимые слова комментария (без стоп-слов), в стеммированном виде."""
    words = [w.lower() for w in _WORD.findall(text)]
    return [_stem(w) for w in words if w not in _STOP and len(w) > 1]


def code_words(line: str) -> set[str]:
    """Слова идентификаторов строки кода: fetchUserData → fetch, user, data."""
    words: set[str] = set()
    line = _STRING.sub(" ", line)
    for ident in _IDENT.findall(line):
        for chunk in filter(None, ident.split("_")):
            for part in _CAMEL.findall(chunk):
                part = part.lower()
                words.add(_stem(part))
                if part in _ABBREVIATIONS:
                    words.add(_stem(_ABBREVIATIONS[part]))
    for op, word in _OPERATOR_WORDS.items():
        if op in line:
            words.add(word)
    return words


def restates(comment: str, code: str) -> bool:
    """Пересказывает ли комментарий строку кода."""
    words = comment_words(comment)
    if not words:
        return False
    known = code_words(code)
    misses = [w for w in words if w not in known]
    # Однобуквенная переменная (`f.Close()` под «close the file») засчитывает
    # одно слово на ту же букву — и только в дополнение к прямым совпадениям.
    initials = {w for w in known if len(w) == 1}
    if len(words) >= 2 and len(misses) < len(words) and misses and misses[0][0] in initials:
        misses = misses[1:]
    return _matched_enough(len(words), len(misses))


def _matched_enough(total: int, misses: int) -> bool:
    """Короткий комментарий (1–2 слова) совпадает целиком, длинный — на 80%."""
    if total <= 2:
        return misses == 0
    return (total - misses) / total >= _MATCH_SHARE_LONG


def _is_lone_comment(lines: list[str], index: int) -> str | None:
    """Текст одиночного комментария строки `index`; None — не тот случай."""
    match = _COMMENT.match(lines[index])
    if not match:
        return None
    text = match.group(1).strip()
    # Метка раздела (`// update discussion:`) — навигация, а не пересказ.
    if not text or _DIRECTIVE.match(text) or text.endswith(":"):
        return None
    if index > 0 and _COMMENT.match(lines[index - 1]):
        return None  # продолжение многострочного пояснения
    return text


def _next_code(lines: list[str], index: int) -> str | None:
    """Строка кода сразу под комментарием; None — пусто, комментарий или объявление."""
    if index + 1 >= len(lines):
        return None
    code = lines[index + 1]
    if not code.strip() or _COMMENT.match(code) or _DECLARATION.match(code) or _GO_FIELD.match(code):
        return None
    return code


def _names_declared(comment: str, code: str) -> bool:
    """Doc-конвенция Go: комментарий начинается с имени, объявленного строкой ниже."""
    first_word = comment.split()[0] if comment.split() else ""
    first_ident = _IDENT.search(code)
    return bool(first_ident) and first_word == first_ident.group(0) and len(first_word) > 1


def find_restating(text: str) -> list[tuple[int, str]]:
    """(строка, текст) комментариев файла, пересказывающих следующую строку."""
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for index, _line in enumerate(lines):
        comment = _is_lone_comment(lines, index)
        if comment is None:
            continue
        code = _next_code(lines, index)
        if code is not None and not _names_declared(comment, code) and restates(comment, code):
            found.append((index + 1, comment))
    return found


class RestatingCommentAdapter(Adapter):
    """Комментарии-пересказы кода в Go и JS/TS."""

    name = "restating-comments"
    category = Category.COMMENTS
    languages = _LANGS

    def is_available(self) -> bool:
        """Встроенная эвристика: внешних тулов нет."""
        return True

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Найти комментарии-пересказы в файлах Go и JS/TS."""
        if files is None:
            paths = [p for p in walk_files(root, config.ignore) if lang_for_path(p) in _LANGS]
        else:
            paths = [root / f for f in self.select_files(files)]
        findings: list[Finding] = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(root).as_posix()
            findings += [
                Finding(
                    category=Category.COMMENTS,
                    tool="restating-comments",
                    file=rel,
                    line=line,
                    message=f"Комментарий пересказывает следующую строку кода: «{comment}»",
                    severity=Severity.WARN,
                    # Тот же класс и без identity, как у aislop: на одной строке
                    # находки обоих склеятся в одну.
                    rule_id="trivial-comment",
                )
                for line, comment in find_restating(text)
            ]
        return findings


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (RestatingCommentAdapter(),)
