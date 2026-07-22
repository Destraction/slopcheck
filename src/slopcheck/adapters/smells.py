"""Адаптер смеллов на semgrep (v2): антипаттерны по кастомным правилам.

Правила лежат в пакете (`slopcheck/rules/smells.yml`), потребляется SARIF-вывод
semgrep. Находки относятся к категории COMPLEXITY (смеллы = раздутость/риск).
"""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.adapters.comments import parse_sarif
from slopcheck.config import Config
from slopcheck.models import Category, Finding
from slopcheck.registry import default_registry
from slopcheck.subprocess_util import ToolExecutionError, crashed, run_tool, tool_available

_RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "smells.yml"


def _clean_rule_id(rule_id: str | None) -> str | None:
    """semgrep префиксует id полным путём (`a.b.smells.eq-none`) — берём хвост."""
    if not rule_id:
        return rule_id
    return rule_id.split(".")[-1]


class SemgrepSmellsAdapter(Adapter):
    """Код-смеллы через semgrep по правилам пакета."""

    name = "semgrep-smells"
    category = Category.COMPLEXITY
    languages = frozenset({"python", "javascript", "typescript", "go"})

    def is_available(self) -> bool:
        return tool_available("semgrep") and _RULES_FILE.exists()

    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        if files is None:
            targets = [str(root)]
        else:
            targets = self.select_files(files)
            if not targets:
                return []
        cmd = [
            "semgrep",
            "--config",
            str(_RULES_FILE),
            "--sarif",
            "--quiet",
            "--metrics=off",  # без телеметрии/сети — детерминизм и приватность
        ]
        for pattern in config.ignore:
            cmd += ["--exclude", pattern]
        cmd += targets

        result = run_tool(cmd, cwd=root)
        if crashed(result) or not result.stdout.strip():
            if crashed(result):
                raise ToolExecutionError(f"semgrep упал: {result.stderr.strip()[:200]}")
            return []

        findings = parse_sarif(result.stdout, tool="semgrep", category=Category.COMPLEXITY)
        for f in findings:
            f.rule_id = _clean_rule_id(f.rule_id)
        return findings


default_registry.register(SemgrepSmellsAdapter())
