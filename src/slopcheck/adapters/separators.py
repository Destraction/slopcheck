"""Комментарии-разделители (Go, JS/TS).

    // --- расширенные тесты HTTP-слоя ---
    // =========================================
    /* ***** helpers ***** */

Линейки делят файл на «разделы» вместо того, чтобы разнести код по
функциям и файлам; ИИ ставит их охотно, люди в Go/TS — редко (на корпусе
калибровки — 5 строк в 2 репозиториях из 6). Разделитель — комментарий, весь
текст которого:
  - линейка из одного символа `- = * # ~ _` длиной от 5;
  - или заголовок между линейками от 3 символов: `--- тесты ---`;
  - или линейка от 5 и заголовок после неё: `// ===== helpers`.

Голый `---` не трогаем: это разделитель YAML-документов (swagger-аннотации
в doc-комментариях Go, front matter).
"""

from __future__ import annotations

import re
from pathlib import Path

from slopcheck.adapters.base import BuiltinAdapter
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity

# Текст комментария: `//`, `/* … */`, JSX `{/* … */}`.
_COMMENT = re.compile(r"^\s*(?://|\{?/\*)\s*(.*?)\s*(?:\*/\}?)?\s*$")
_SEPARATOR = re.compile(
    r"^(?:"
    r"([-=*#~_])\1{4,}"                   # линейка от 5
    r"|([-=*#~_])\2{2,}\s+\S.*?\s+\2{3,}"  # --- заголовок ---
    r"|([-=*#~_])\3{4,}\s+\S.*"           # ===== заголовок
    r")$"
)


def find_separators(text: str) -> list[tuple[int, str]]:
    """(строка, текст) комментариев-разделителей файла."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        match = _COMMENT.match(line)
        if match and _SEPARATOR.match(match.group(1)):
            found.append((number, match.group(1)))
    return found


class SeparatorCommentAdapter(BuiltinAdapter):
    """Комментарии-линейки, делящие файл на разделы (Go, JS/TS)."""

    name = "separator-comments"
    category = Category.COMMENTS
    languages = frozenset({"go", "javascript", "typescript"})

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Найти комментарии-разделители в файлах Go и JS/TS."""
        return [
            Finding(
                category=Category.COMMENTS,
                tool="separator-comments",
                file=rel,
                line=line,
                message=(
                    f"Комментарий-разделитель «{comment[:60]}»: разделы файла задают функции "
                    "и файлы, а не линейки — удалите или вынесите раздел в отдельный файл"
                ),
                severity=Severity.WARN,
                rule_id="separator-comment",
                identity=comment,
            )
            for rel, text in self.sources(root, config, files)
            for line, comment in find_separators(text)
        ]


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (SeparatorCommentAdapter(),)
