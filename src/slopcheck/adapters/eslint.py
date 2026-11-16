"""Адаптер JS/TS и React на ESLint с пакетным конфигом.

Правила — в `slopcheck/rules/eslint.config.cjs`: хуки React (правила хуков,
зависимости эффектов), ключи списков, `any` и `@ts-ignore`, пустые catch,
неиспользуемые переменные, JSDoc у экспортов. Конфиг проекта не читается:
гейт мерит все репозитории одной линейкой.

Плагины ставятся глобально (`npm install -g`), путь к ним конфиг получает из
SLOPCHECK_NODE_MODULES — иначе require искал бы их рядом с пакетом slopcheck.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import is_test_file
from slopcheck.models import Category, Finding, Severity
from slopcheck.subprocess_util import ToolExecutionError, crashed, run_tool, tool_available

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "rules" / "eslint.config.cjs"

# Правило → (категория, severity). Неперечисленное — COMPLEXITY/WARN.
_RULES: dict[str, tuple[Category, Severity]] = {
    "no-unreachable": (Category.DEAD_CODE, Severity.WARN),
    "@typescript-eslint/no-unused-vars": (Category.DEAD_CODE, Severity.WARN),
    "jsdoc/require-jsdoc": (Category.COMMENTS, Severity.INFO),
    # Нарушение правил хуков и список без key ломают рендер — это баги.
    "react-hooks/rules-of-hooks": (Category.COMPLEXITY, Severity.ERROR),
    "react/jsx-key": (Category.COMPLEXITY, Severity.ERROR),
    "@typescript-eslint/no-non-null-assertion": (Category.COMPLEXITY, Severity.INFO),
}


def _is_noise(message: dict) -> bool:
    """Сообщение ESLint, которое не является находкой slop.

    - `Definition for rule ... was not found`: в коде отключено правило
      плагина, которого нет в нашем конфиге (`eslint-disable @next/...`);
    - fatal без ruleId: файл не парсится — это забота компилятора проекта.
    """
    if message.get("fatal") or not message.get("ruleId"):
        return True
    return str(message.get("message", "")).startswith("Definition for rule")


def parse_report(report_json: str, skip_test_docs: bool = True) -> list[Finding]:
    """Разобрать JSON-вывод ESLint (`--format json`)."""
    findings: list[Finding] = []
    for file_result in json.loads(report_json):
        file = file_result.get("filePath", "?")
        for message in file_result.get("messages") or []:
            if _is_noise(message):
                continue
            rule = message["ruleId"]
            category, severity = _RULES.get(rule, (Category.COMPLEXITY, Severity.WARN))
            if skip_test_docs and category is Category.COMMENTS and is_test_file(file):
                continue
            findings.append(
                Finding(
                    category=category,
                    tool="eslint",
                    file=file,
                    line=int(message.get("line", 0) or 0),
                    message=message.get("message", rule),
                    severity=severity,
                    rule_id=rule,
                )
            )
    return findings


@lru_cache(maxsize=1)
def node_modules_dir() -> str | None:
    """Где лежат глобальные npm-пакеты: env SLOPCHECK_NODE_MODULES или `npm root -g`."""
    explicit = os.environ.get("SLOPCHECK_NODE_MODULES")
    if explicit:
        return explicit
    if not tool_available("npm"):
        return None
    result = run_tool(["npm", "root", "-g"], timeout=30.0)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _ignore_patterns(ignore: list[str]) -> list[str]:
    """`--ignore-pattern` для каждого паттерна конфига: и каталог, и файл."""
    args: list[str] = []
    for pattern in ignore:
        args += ["--ignore-pattern", f"**/{pattern}/**", "--ignore-pattern", f"**/{pattern}"]
    return args


class EslintAdapter(Adapter):
    """JS/TS/React: хуки, ключи, any, пустые catch, мёртвые переменные, JSDoc."""

    name = "eslint"
    category = Category.COMPLEXITY
    measures = frozenset({Category.DEAD_CODE, Category.COMMENTS})
    languages = frozenset({"javascript", "typescript"})

    def is_available(self) -> bool:
        """Нужны eslint и каталог глобальных npm-пакетов с плагинами."""
        return tool_available("eslint") and node_modules_dir() is not None

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Прогнать ESLint с пакетным конфигом и вернуть находки."""
        targets = self.resolve_targets(root, files)
        if targets is None:
            return []
        cmd = [
            "eslint",
            "--config", str(_CONFIG_FILE),
            "--format", "json",
            "--no-warn-ignored",
            *_ignore_patterns(config.ignore),
            *targets,
        ]
        env = {"SLOPCHECK_NODE_MODULES": node_modules_dir() or "", "SLOPCHECK_ROOT": str(root)}
        result = run_tool(cmd, cwd=root, env=env, timeout=900.0)
        # Коды ESLint: 0 — чисто, 1 — есть ошибки уровня error; 2 — сбой
        # (не загрузился плагин, битый конфиг).
        if crashed(result, ok_returncodes=(0, 1)) or not result.stdout.strip():
            raise ToolExecutionError(f"eslint упал: {result.stderr.strip()[:300]}")
        return parse_report(result.stdout, config.docstrings_skip_tests)


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (EslintAdapter(),)
