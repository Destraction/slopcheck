"""JSON-репортер: машинный дамп отчёта."""

from __future__ import annotations

import json

from slopcheck.runner import RunResult


def to_dict(result: RunResult) -> dict:
    """Собрать сериализуемый словарь из результата прогона."""
    data = result.report.model_dump(mode="json")
    data["skipped"] = result.skipped
    return data


def render(result: RunResult) -> str:
    """Вернуть pretty-printed JSON отчёта."""
    return json.dumps(to_dict(result), ensure_ascii=False, indent=2)
