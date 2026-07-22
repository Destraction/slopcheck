"""Тест парсинга jscpd-отчёта в находки дублей."""

from __future__ import annotations

from pathlib import Path

from slopcheck.adapters.duplication import JscpdAdapter, parse_report
from slopcheck.models import Category, Severity

FIXTURE = Path(__file__).parent / "fixtures" / "jscpd-report.json"


def test_parse_report_extracts_duplicate() -> None:
    findings = parse_report(FIXTURE.read_text(encoding="utf-8"))
    assert len(findings) == 1
    f = findings[0]
    assert f.category is Category.DUPLICATION
    assert f.tool == "jscpd"
    assert f.file == "src/a.js"
    assert f.line == 1
    assert f.end_line == 6
    assert f.metric == 5.0
    assert f.severity is Severity.WARN
    assert "src/b.js" in f.message


def test_parse_report_empty() -> None:
    assert parse_report('{"duplicates": []}') == []


def test_parse_report_skips_entry_without_name() -> None:
    bad = '{"duplicates": [{"lines": 3, "firstFile": {}, "secondFile": {}}]}'
    assert parse_report(bad) == []


def test_adapter_metadata() -> None:
    adapter = JscpdAdapter()
    assert adapter.name == "jscpd"
    assert adapter.category is Category.DUPLICATION
    assert adapter.applies_to(["python"])  # мультиязычен → применим к любому


def test_identity_stable_without_lines_and_positions() -> None:
    # Идентичность дубля — пара путей: рост числа строк и сдвиг второго
    # блока не должны делать находку «новой» для delta-гейта.
    findings = parse_report(FIXTURE.read_text(encoding="utf-8"))
    f = findings[0]
    assert f.identity == "|".join(sorted(["src/a.js", "src/b.js"]))
    # message содержит изменчивое (строки/позиции) — ключ его игнорирует
    import json as _json

    data = _json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["duplicates"][0]["lines"] += 7
    data["duplicates"][0]["secondFile"]["start"] = 999
    shifted = parse_report(_json.dumps(data))[0]
    assert shifted.key() == f.key()
    assert shifted.message != f.message


def test_parse_report_relativizes_both_paths(tmp_path: Path) -> None:
    # second_name нормализуется той же логикой, что и f.file.
    import json as _json

    report = {
        "duplicates": [
            {
                "lines": 5,
                "firstFile": {"name": str(tmp_path / "src" / "a.js"), "start": 1, "end": 6},
                "secondFile": {"name": str(tmp_path / "src" / "b.js"), "start": 10},
            }
        ]
    }
    f = parse_report(_json.dumps(report), root=tmp_path)[0]
    assert f.file == "src/a.js"
    assert "src/b.js" in f.message
    assert str(tmp_path) not in (f.identity or "")
    assert f.identity == "src/a.js|src/b.js"


def test_parse_report_drops_ignored_format() -> None:
    """Дубли в игнорируемом формате (проза) не попадают в находки."""
    report = """
    {"duplicates": [{"format": "markdown", "lines": 8,
      "firstFile": {"name": "docs/G.md:markdown", "start": 1, "end": 8},
      "secondFile": {"name": "docs/G.md:markdown", "start": 20, "end": 27}}]}
    """
    assert parse_report(report, ignore_formats=["markdown"]) == []
    assert len(parse_report(report, ignore_formats=[])) == 1


def test_parse_report_strips_format_suffix() -> None:
    """Хвост `:<format>` у фрагментов срезается — путь должен быть настоящим."""
    report = """
    {"duplicates": [{"format": "markdown", "lines": 8,
      "firstFile": {"name": "docs/G.md:markdown", "start": 1, "end": 8},
      "secondFile": {"name": "docs/H.md:markdown", "start": 20, "end": 27}}]}
    """
    (f,) = parse_report(report, ignore_formats=[])
    assert f.file == "docs/G.md"
    assert "docs/H.md:20" in f.message
    assert f.identity == "docs/G.md|docs/H.md"


def test_parse_report_drops_self_overlap() -> None:
    """Клон файла с самим собой на тех же строках — шум jscpd, отбрасываем."""
    report = """
    {"duplicates": [{"format": "javascript", "lines": 8,
      "firstFile": {"name": "src/a.js", "start": 201, "end": 208},
      "secondFile": {"name": "src/a.js", "start": 201, "end": 208}}]}
    """
    assert parse_report(report) == []


def test_parse_report_keeps_same_file_distinct_blocks() -> None:
    """Два разных блока одного файла — настоящий дубль, с понятным текстом."""
    report = """
    {"duplicates": [{"format": "javascript", "lines": 16,
      "firstFile": {"name": "src/a.js", "start": 1, "end": 16},
      "secondFile": {"name": "src/a.js", "start": 40, "end": 55}}]}
    """
    (f,) = parse_report(report)
    assert f.file == "src/a.js"
    assert "в этом же файле, строка 40" in f.message
