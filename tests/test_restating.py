"""Комментарии-пересказы: позитивные и негативные примеры эвристики."""

from __future__ import annotations

from pathlib import Path

import pytest

from slopcheck.adapters.restating import RestatingCommentAdapter, code_words, find_restating, restates
from slopcheck.config import Config


@pytest.mark.parametrize(
    ("comment", "code"),
    [
        ("Fetch the data", "  fetchData().then(setData)"),
        ("fetch user data", "  const user = await fetchUserData(id)"),
        ("Close the file", "\tf.Close()"),
        ("increment counter", "  counter++"),
        ("Return the result", "  return result"),
        ("set loading to true", "  setLoading(true)"),
        ("parse the config", "\tcfg, err := parse_config(path)"),
    ],
)
def test_restating_detected(comment: str, code: str) -> None:
    assert restates(comment, code)


@pytest.mark.parametrize(
    ("comment", "code"),
    [
        ("retry: API отдаёт 502 при холодном старте", "  await retry(fetchData)"),
        ("API returns 502 on cold start, so retry", "  await retry(fetchData)"),
        ("Fetch the data before hydration to avoid flicker", "  fetchData()"),
        ("ensure deterministic order for golden tests", "\tsort.Strings(keys)"),
        ("nil map would panic on write", "\tm = make(map[string]int)"),
    ],
)
def test_explaining_comments_kept(comment: str, code: str) -> None:
    assert not restates(comment, code)


def test_code_words_split_identifiers() -> None:
    assert {"fetch", "user", "data", "id"} <= code_words("fetchUserData(user_id)")
    assert {"http", "server"} <= code_words("NewHTTPServer()")


def test_find_skips_doc_comments_directives_and_blocks() -> None:
    text = (
        "// Start starts the server\n"
        "func (s *Server) Start() error {\n"
        "\t//nolint:errcheck\n"
        "\tf.Close()\n"
        "\t// The cache is warmed lazily: first request pays\n"
        "\t// close the file\n"
        "\tf.Close()\n"
        "\t// close the file\n"
        "\n"
        "\t// close the file\n"
        "\tf.Close()\n"
        "}\n"
    )
    assert find_restating(text) == [(10, "close the file")]


def test_adapter_runs_only_go_and_js(tmp_path: Path) -> None:
    (tmp_path / "a.ts").write_text("function f() {\n  // save the user\n  saveUser(u)\n}\n")
    (tmp_path / "b.py").write_text("# save the user\nsave_user(u)\n")
    findings = RestatingCommentAdapter().run(tmp_path, Config())
    assert [(f.file, f.line, f.rule_id) for f in findings] == [("a.ts", 2, "trivial-comment")]


@pytest.mark.parametrize(
    ("comment", "code"),
    [
        ("apptoken", '\ts.assertQueryRequest("token", "apptoken", handler)'),
        ("Act", "\tgot := stringInSlice(tt.a, tt.list)"),
    ],
)
def test_strings_and_initials_do_not_match(comment: str, code: str) -> None:
    assert not restates(comment, code)


def test_go_field_docs_and_labels_skipped() -> None:
    text = (
        "type Command struct {\n"
        "\t// flags is full set of flags.\n"
        "\tflags *flag.FlagSet\n"
        "}\n"
        "func run() {\n"
        "\t// update discussion:\n"
        "\tupdateDiscussion()\n"
        "\t// parent is a parent command\n"
        "\tparent = c.parent\n"
        "}\n"
    )
    assert find_restating(text) == []
