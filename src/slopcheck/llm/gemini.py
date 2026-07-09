"""LLM-ревьюер на локальном Gemini CLI (бесплатный OAuth, без API-ключа).

Опциональный шаг (`--llm-review`, off по умолчанию). Даёт субъективные находки,
которые статика не берёт: плохие имена, лишние/протекающие абстракции, неясные
границы модулей. Advisory — severity INFO, гейт по умолчанию не валит.

Выбор Gemini (а не Claude): бесплатный локальный CLI, не тратит лимит Claude,
уже используется в /second-opinion. Требует разового Google-логина (`gemini`).
"""

from __future__ import annotations

import json
from pathlib import Path

from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity
from slopcheck.runner import RunResult
from slopcheck.subprocess_util import ToolExecutionError, run_tool, tool_available

# Границы, чтобы не раздувать промпт: сколько файлов и сколько байт с файла.
_MAX_FILES = 8
_MAX_BYTES_PER_FILE = 12_000
_TIMEOUT = 120.0

_PROMPT = (
    "Ты строгий сеньор-ревьюер. Ниже — исходные файлы. Найди СУБЪЕКТИВНЫЕ проблемы, "
    "которые статический анализ не ловит: плохие/неясные имена, лишние или протекающие "
    "абстракции, неудачные границы модулей, усложнённую логику. Игнорируй стиль и форматирование. "
    "Верни ТОЛЬКО JSON-массив объектов с полями file, line, message. "
    "Если проблем нет — верни []. Без markdown-обёртки, без пояснений вне JSON."
)


class GeminiNotAuthenticated(ToolExecutionError):
    """Gemini CLI установлен, но не пройден вход (нет OAuth/ключа)."""


def _extract_json_array(text: str) -> str:
    """Вырезать JSON-массив из ответа (модель иногда добавляет обёртку/фенсы)."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return "[]"
    return text[start : end + 1]


def parse_review(text: str, category: Category = Category.COMPLEXITY) -> list[Finding]:
    """Разобрать JSON-ответ Gemini в находки (advisory, severity INFO)."""
    try:
        data = json.loads(_extract_json_array(text))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    findings: list[Finding] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        findings.append(
            Finding(
                category=category,
                tool="gemini",
                file=str(item["file"]),
                line=int(item.get("line") or 0),
                message=str(item.get("message", "")).strip() or "субъективное замечание",
                severity=Severity.INFO,
                rule_id="llm-design",
            )
        )
    return findings


def _collect_code(result: RunResult) -> str:
    """Собрать содержимое файлов с находками (ограниченно) для ревью."""
    seen: list[str] = []
    for f in result.report.findings:
        if f.file not in seen:
            seen.append(f.file)
    blobs: list[str] = []
    for rel in seen[:_MAX_FILES]:
        path = result.root / rel
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:_MAX_BYTES_PER_FILE]
        except OSError:
            continue
        blobs.append(f"# ===== {rel} =====\n{content}")
    return "\n\n".join(blobs)


class GeminiReviewer:
    """Реализация LLMReviewer поверх локального Gemini CLI."""

    def is_available(self) -> bool:
        return tool_available("gemini")

    def review(self, result: RunResult, config: Config) -> list[Finding]:
        code = _collect_code(result)
        if not code.strip():
            return []

        run = run_tool(["gemini", "-p", _PROMPT], cwd=result.root, timeout=_TIMEOUT, input_text=code)
        if "Auth method" in run.stderr or "GEMINI_API_KEY" in run.stderr:
            raise GeminiNotAuthenticated(
                "gemini не залогинен — выполни `gemini` в терминале и пройди Google-логин"
            )
        if run.returncode != 0 and not run.stdout.strip():
            raise ToolExecutionError(f"gemini упал: {run.stderr.strip()[:200]}")
        return parse_review(run.stdout)
