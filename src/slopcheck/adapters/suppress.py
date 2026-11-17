"""Обходы линтера: директивы, отключающие проверку (Go, JS/TS, Python).

    // eslint-disable-next-line react-hooks/exhaustive-deps
    //nolint:errcheck
    // @ts-ignore
    import x  # noqa: F401

Агент, которому линтер мешает, часто глушит правило вместо того, чтобы
исправить причину. В чужом коде старые подавления — обычно осознанные
решения (на корпусе калибровки — 75 на 6 репозиториев), поэтому в полном
прогоне находка — info и счёт не штрафует. Новое подавление без причины
гейт и хук поднимают до warn (`baseline.WARN_WHEN_NEW`): агент видит его
сразу после правки.

Причина засчитывается только в формате самого тула, на той же строке:
`// eslint-disable-line x -- причина`, `//nolint:x // причина`,
`// @ts-expect-error причина`, `# noqa: E402  # причина`. Тогда rule_id —
`lint-suppression-justified`, и находка остаётся info.

Директивы ищутся только в комментариях: строки и docstring затираются,
поэтому примеры директив в тестах и документации не считаются.
"""

from __future__ import annotations

import re
from pathlib import Path

from slopcheck.adapters.base import BuiltinAdapter
from slopcheck.config import Config
from slopcheck.languages import lang_for_path
from slopcheck.models import Category, Finding, Severity

# Комментарий или строковый литерал; группа `c` — текст комментария.
_C_LIKE = re.compile(
    r"//(?P<c>[^\n]*)|/\*(?P<cb>.*?)\*/"
    r"|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)
_PYTHON = re.compile(
    r"#(?P<c>[^\n]*)"
    r"|[rRbBuUfF]{0,2}(?:\"\"\"(?:\\.|[^\\])*?\"\"\"|'''(?:\\.|[^\\])*?''')"
    r"|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'",
    re.DOTALL,
)
_TOKENS = {"go": _C_LIKE, "javascript": _C_LIKE, "typescript": _C_LIKE, "python": _PYTHON}

# Директива и её аргументы (список правил); всё после — кандидат в причину.
_RULES = r"[\w@/.-]+(?:\s*,\s*[\w@/.-]+)*"
_DIRECTIVES = {
    "go": re.compile(r"^\s*(?:nolint(?::[\w-]+(?:,[\w-]+)*)?|lint:ignore\s+[\w,]+)(?![\w-])"),
    "javascript": re.compile(
        rf"^\s*(?:eslint-disable(?:-next-line|-line)?(?:\s+(?!--){_RULES})?"
        r"|@ts-(?:ignore|expect-error|nocheck)"
        r"|biome-ignore(?:-all|-start|-end)?\s+[\w/]+(?:\([^)]*\))?)(?![\w-])"
    ),
    "python": re.compile(
        r"(?:^|#)\s*(?:noqa(?::?\s*[A-Z]+\d+(?:[,\s]+[A-Z]+\d+)*)?"
        r"|type:\s*ignore(?:\[[\w\-, ]+\])?"
        r"|pylint:\s*disable=[\w\-,]+"
        r"|pyright:\s*ignore(?:\[[\w, ]+\])?"
        r"|nosec(?:\s+[A-Z]\d+(?:[,\s]+[A-Z]\d+)*)?)(?![\w-])"
    ),
}
_DIRECTIVES["typescript"] = _DIRECTIVES["javascript"]
_REASON_LEAD = re.compile(r"^[\s:\-—–#/*]+")


def _reason(rest: str) -> str:
    """Причина после директивы: без разделителей `--`, `//`, `#`, `:` и хвоста `*/`."""
    return _REASON_LEAD.sub("", rest).rstrip(" */}")


def find_suppressions(text: str, lang: str) -> list[tuple[int, str, bool]]:
    """(строка, директива, указана ли причина) по всем комментариям файла."""
    directive = _DIRECTIVES[lang]
    found = []
    for token in _TOKENS[lang].finditer(text):
        comment = token.group("c") if token.group("c") is not None else token.groupdict().get("cb")
        if comment is None:
            continue
        match = directive.search(comment)
        if not match:
            continue
        reason = _reason(comment[match.end():])
        line = text.count("\n", 0, token.start()) + 1
        found.append((line, match.group(0).strip(" #"), len(re.findall(r"[^\W\d_]", reason)) >= 3))
    return found


class SuppressionAdapter(BuiltinAdapter):
    """Директивы подавления линтера (`eslint-disable`, `//nolint`, `# noqa`…)."""

    name = "lint-suppressions"
    category = Category.COMMENTS
    languages = frozenset(_TOKENS)

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Найти директивы подавления в комментариях."""
        findings: list[Finding] = []
        for rel, text in self.sources(root, config, files):
            for line, directive, justified in find_suppressions(text, lang_for_path(rel)):
                findings.append(Finding(
                    category=Category.COMMENTS,
                    tool="lint-suppressions",
                    file=rel,
                    line=line,
                    message=(
                        f"Подавление линтера «{directive}» с причиной" if justified else
                        f"Подавление линтера «{directive}» без причины — исправьте то, на что "
                        "жалуется правило; если подавление необходимо, укажите причину на той же "
                        "строке (`-- …` для eslint, `// …` после //nolint, `# …` после # noqa)"
                    ),
                    severity=Severity.INFO,
                    rule_id="lint-suppression-justified" if justified else "lint-suppression",
                    identity=directive,
                ))
        return findings


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (SuppressionAdapter(),)
