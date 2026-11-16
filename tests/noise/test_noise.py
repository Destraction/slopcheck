"""Подтверждённые на корпусе (bench/, G9) ложные срабатывания: находки быть не должно.

Каждый тест — признак из разметки `bench/labels/`, закреплённый так, чтобы
поправка калибровки не потерялась при правке правил.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slopcheck.adapters.depsexist import tsconfig_aliases
from slopcheck.calibrate import calibrate
from slopcheck.config import Config
from slopcheck.models import Category, Finding, Severity


def _f(tool: str, rule: str, file: str, line: int = 1, message: str = "m", **kw) -> Finding:
    return Finding(category=Category.COMPLEXITY, tool=tool, rule_id=rule, file=file, line=line,
                   message=message, severity=kw.pop("severity", Severity.WARN), **kw)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ отбрасываются

@pytest.mark.parametrize("file", ["pnpm-lock.yaml", "docs/guide.md", ".github/workflows/ci.yml", "go.sum"])
def test_duplicates_in_lockfiles_docs_ci_dropped(tmp_path: Path, file: str) -> None:
    assert calibrate([_f("jscpd", "duplicate-block", file)], tmp_path) == []


def test_baseurl_directory_is_not_hallucinated_package(tmp_path: Path) -> None:
    # taxonomy: `import { X } from "types"` — каталог types/ под baseUrl ".";
    # paths со звёздочками раньше ломали разбор tsconfig.
    _write(tmp_path, "tsconfig.json",
           '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}, "include": ["**/*.ts"]}')
    _write(tmp_path, "types/index.d.ts", "export type X = 1\n")
    _write(tmp_path, "config/site.ts", 'import { X } from "types"\n')
    local = _f("aislop", "ai-slop/hallucinated-import", "config/site.ts",
               message='Imports "types" but it\'s not declared in package.json')
    ghost = local.model_copy(update={"message": 'Imports "left-padx" but it\'s not declared in package.json'})
    assert calibrate([local, ghost], tmp_path) == [ghost]


def test_tsconfig_glob_strings_are_not_comments(tmp_path: Path) -> None:
    _write(tmp_path, "tsconfig.json",
           '{\n  // алиасы\n  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}},\n'
           '  "include": ["**/*.ts", "**/*.tsx"], /* хвост */\n}')
    _write(tmp_path, "lib/x.ts", "")
    prefixes, names = tsconfig_aliases(tmp_path)
    assert prefixes == ["@/"] and "lib" in names


def test_empty_catch_with_reason_comment_dropped(tmp_path: Path) -> None:
    _write(tmp_path, "a.ts", "try {\n  load()\n} catch {\n  // file is optional\n}\n"
                             "try {\n  load()\n} catch {}\n")
    commented = _f("semgrep", "empty-catch", "a.ts", line=1, end_line=5)
    silent = _f("semgrep", "empty-catch", "a.ts", line=6, end_line=8)
    assert calibrate([commented, silent], tmp_path) == [silent]


# ------------------------------------------------------------------ понижаются до info

def _severity(findings: list[Finding]) -> list[Severity]:
    return [f.severity for f in findings]


def test_test_files_relaxed(tmp_path: Path) -> None:
    found = calibrate([
        _f("eslint", "@typescript-eslint/no-explicit-any", "tests/devtools.test.tsx"),
        _f("jscpd", "duplicate-block", "api/message_test.go"),
        _f("eslint", "@typescript-eslint/no-explicit-any", "src/store.ts"),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.INFO, Severity.WARN]


def test_a11y_and_service_urls_info(tmp_path: Path) -> None:
    found = calibrate([
        _f("aislop", "jsx-a11y/heading-has-content", "mdx.tsx"),
        _f("aislop", "ai-slop/hardcoded-url", "config/site.ts"),
        _f("knip", "knip-devDependencies", "package.json"),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO] * 3


def test_framework_params_info_but_unused_local_kept(tmp_path: Path) -> None:
    found = calibrate([
        _f("aislop", "eslint/no-unused-vars", "route.ts", message="Parameter 'req' is declared but never used."),
        _f("aislop", "eslint/no-unused-vars", "route.ts", message="Catch parameter 'error' is caught but never used."),
        _f("aislop", "eslint/no-unused-vars", "route.ts", message="'x' is assigned a value but never used."),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.INFO, Severity.WARN]


def test_panic_on_programmer_error_info_on_env_error_warn(tmp_path: Path) -> None:
    _write(tmp_path, "cobra.go", 'panic("Eq called on unsupported type")\npanic(err)\n')
    found = calibrate([
        _f("aislop", "ai-slop/go-library-panic", "cobra.go", line=1),
        _f("aislop", "ai-slop/go-library-panic", "cobra.go", line=2),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.WARN]


def test_sanitized_inner_html_info(tmp_path: Path) -> None:
    _write(tmp_path, "md.tsx", "<div\n  dangerouslySetInnerHTML={{\n    __html: DOMPurify.sanitize(html),\n  }}\n/>\n"
                               "<div dangerouslySetInnerHTML={{ __html: html }} />\n")
    found = calibrate([
        _f("eslint", "react/no-danger", "md.tsx", line=2),
        _f("eslint", "react/no-danger", "md.tsx", line=6),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.WARN]


# ------------------------------------------------------------------ правила детекторов

@pytest.mark.skipif(not (shutil.which("golangci-lint") and shutil.which("go")), reason="golangci-lint/go не установлены")
def test_errcheck_skips_idiomatic_calls(tmp_path: Path) -> None:
    from slopcheck.adapters.golangci import GolangciLintAdapter

    _write(tmp_path, "go.mod", "module example.com/x\n\ngo 1.22\n")
    _write(tmp_path, "x.go",
           'package x\n\nimport (\n\t"fmt"\n\t"io"\n\t"os"\n)\n\n'
           '// Dump пишет в w.\nfunc Dump(w io.Writer, f *os.File) {\n'
           '\tfmt.Fprintln(w, "x")\n\tf.Close()\n\tos.Setenv("A", "1")\n\tos.Chdir("/")\n}\n')
    lines = sorted(f.line for f in GolangciLintAdapter().run(tmp_path, Config()) if f.rule_id == "errcheck")
    assert lines == [14]


def test_render_prop_is_not_nested_component(tmp_path: Path) -> None:
    from slopcheck.adapters.eslint import EslintAdapter

    if not EslintAdapter().is_available():
        pytest.skip("eslint с плагинами не установлен")
    _write(tmp_path, "src/List.tsx",
           "/** Список. */\nexport function List() {\n"
           "  return <Table columns={[{ Cell({ v }: { v: string }) { return <b>{v}</b>; } }]} />;\n}\n")
    found = EslintAdapter().run(tmp_path, Config())
    assert "react/no-unstable-nested-components" not in {f.rule_id for f in found}


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep не установлен")
def test_explicit_blank_assignment_is_info(tmp_path: Path) -> None:
    from slopcheck.adapters.smells import SemgrepSmellsAdapter

    _write(tmp_path, "main.go", 'package main\n\nfunc main() {\n\t_ = viper.BindPFlag("tui", nil)\n}\n')
    found = [f for f in SemgrepSmellsAdapter().run(tmp_path, Config()) if f.rule_id == "swallowed-error-go"]
    assert found and all(f.severity is Severity.INFO for f in found)


# ------------------------------------------------------------------ ИИ-корпус (bench/ai, H3)

def test_act_wrapper_call_is_info(tmp_path: Path) -> None:
    # `flush()` — обёртка над act(): act React 19 всегда возвращает thenable.
    _write(tmp_path, "src/List.test.tsx",
           "const flush = () => act(() => vi.advanceTimersByTime(300));\n"
           "flush();\n"
           "save();\n")
    found = calibrate([
        _f("eslint", "@typescript-eslint/no-floating-promises", "src/List.test.tsx", line=2),
        _f("eslint", "@typescript-eslint/no-floating-promises", "src/List.test.tsx", line=3),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.WARN]


def test_set_state_before_async_load_is_info(tmp_path: Path) -> None:
    _write(tmp_path, "src/useFetch.ts",
           "useEffect(() => {\n  setLoading(true);\n  fetcher().then(setData);\n}, [attempt]);\n"
           "useEffect(() => {\n  setFiltered(items.filter(Boolean));\n}, [items]);\n")
    found = calibrate([
        _f("eslint", "react-hooks/set-state-in-effect", "src/useFetch.ts", line=2),
        _f("aislop", "react/set-state-in-effect", "src/useFetch.ts", line=2),
        _f("eslint", "react-hooks/set-state-in-effect", "src/useFetch.ts", line=6),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.INFO, Severity.WARN]


def test_latest_value_ref_is_info(tmp_path: Path) -> None:
    _write(tmp_path, "src/useFetch.ts", "fetcherRef.current = fetcher;\nconst n = countRef.current + 1;\n")
    found = calibrate([
        _f("aislop", "react/refs", "src/useFetch.ts", line=1),
        _f("aislop", "react/refs", "src/useFetch.ts", line=2),
    ], tmp_path)
    assert _severity(found) == [Severity.INFO, Severity.WARN]


def test_non_english_comment_is_not_restating() -> None:
    from slopcheck.adapters.restating import find_restating

    russian = "  // Храним последний fetcher в ref, чтобы новая ссылка не вызывала загрузку.\n  const fetcherRef = useRef(fetcher);\n"
    assert find_restating(russian) == []
    assert find_restating("  // fetch the data\n  fetchData()\n") == [(1, "fetch the data")]
