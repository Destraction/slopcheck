"""Go: новая ошибка вместо исходной в ветке `if err != nil` (go-error-wrap)."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.goerrors import GoErrorWrapAdapter, find_unwrapped
from slopcheck.config import Config


def _lines(src: str) -> list[int]:
    return [line for line, _var, _code in find_unwrapped(src)]


def test_lost_cause_found() -> None:
    src = (
        "u, err := url.Parse(raw)\n"
        "if err != nil || u.Host == \"\" {\n"
        "\treturn nil, fmt.Errorf(\"invalid webhook url\")\n"
        "}\n"
        "if _, rerr := os.Stat(p); rerr != nil {\n"
        "\treturn errors.New(\"no file\")\n"
        "}\n"
    )
    assert find_unwrapped(src) == [
        (3, "err", 'return nil, fmt.Errorf("invalid webhook url")'),
        (6, "rerr", 'return errors.New("no file")'),
    ]


def test_wrapped_or_used_error_ok() -> None:
    src = (
        "if err != nil {\n\treturn fmt.Errorf(\"load: %w\", err)\n}\n"
        "if err != nil {\n\tlog.Printf(\"load: %v\", err)\n\treturn errors.New(\"internal\")\n}\n"
        "if err != nil {\n\treturn ErrNotFound\n}\n"
    )
    assert _lines(src) == []


def test_deliberate_cases_skipped() -> None:
    src = (
        # Ответ клиенту, а не проброс ошибки.
        "if err != nil {\n\tctx.AbortWithError(404, errors.New(\"unknown plugin\"))\n\treturn\n}\n"
        # Комментарий объясняет, почему причина не нужна.
        "if err != nil {\n\t// не раскрываем внутреннюю ошибку клиенту\n\treturn errors.New(\"denied\")\n}\n"
        # Ошибка strconv — только «invalid syntax».
        "v, err := strconv.Atoi(raw)\nif err != nil {\n\treturn 0, fmt.Errorf(\"%s must be an integer\", name)\n}\n"
        # Скобки и `err` внутри строк не ломают разбор.
        "if err != nil {\n\treturn fmt.Errorf(\"bad {err} at http://x\")\n}\n"
    )
    assert _lines(src) == [14]


def test_adapter_reports_warn_with_identity(tmp_path: Path) -> None:
    (tmp_path / "a.go").write_text(
        "package a\n\nfunc f() error {\n\tif err := g(); err != nil {\n\t\treturn errors.New(\"x\")\n\t}\n\treturn nil\n}\n"
    )
    (tmp_path / "b.txt").write_text("if err != nil { return errors.New(\"x\") }\n")
    found = GoErrorWrapAdapter().run(tmp_path, Config())
    assert [(f.file, f.line, f.rule_id, f.severity.value, f.identity) for f in found] == [
        ("a.go", 5, "error-no-wrap", "warn", 'return errors.New("x")')
    ]
    assert GoErrorWrapAdapter().run(tmp_path, Config(), files=["b.txt"]) == []
