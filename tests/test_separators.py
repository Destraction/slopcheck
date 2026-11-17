"""Комментарии-разделители в Go и JS/TS (separator-comments)."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.separators import SeparatorCommentAdapter, find_separators
from slopcheck.config import Config


def test_separator_forms_found() -> None:
    src = (
        "// =====\n"
        "// --- расширенные тесты HTTP-слоя ---\n"
        "/* ***** helpers ***** */\n"
        "{/* ----- форма ----- */}\n"
        "// ===== helpers\n"
    )
    assert [line for line, _ in find_separators(src)] == [1, 2, 3, 4, 5]


def test_not_separators() -> None:
    src = (
        "// ---\n"            # YAML-разделитель в swagger-аннотации
        "//\t---\n"
        "// ---- not closed\n"
        "// - a - b\n"
        "// a --- b ---\n"
        "//go:build linux\n"
        "const a = 1 // -----\n"  # хвостовой комментарий — не раздел файла
    )
    assert find_separators(src) == []


def test_adapter_go_and_tsx_only(tmp_path: Path) -> None:
    (tmp_path / "a_test.go").write_text("package a\n\n// --- LoginHandler ---\n")
    (tmp_path / "App.tsx").write_text("export const A = 1;\n// ==========\n")
    (tmp_path / "x.py").write_text("# ----------\n")
    found = SeparatorCommentAdapter().run(tmp_path, Config())
    assert sorted((f.file, f.line, f.rule_id, f.severity.value) for f in found) == [
        ("App.tsx", 2, "separator-comment", "warn"),
        ("a_test.go", 3, "separator-comment", "warn"),
    ]
