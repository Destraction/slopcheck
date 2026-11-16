"""Несуществующие пакеты: сбор имён по экосистемам и сверка с реестрами (сеть подменена)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slopcheck.adapters.depsexist import (
    DepsExistAdapter,
    go_imports,
    go_module_candidates,
    npm_package_name,
)
from slopcheck.config import Config
from slopcheck.registries import RegistryClient, RegistryUnavailable, url_for
from slopcheck.runner import run
from slopcheck.registry import Registry
from slopcheck.subprocess_util import ToolExecutionError

# Что «существует» в подменённых реестрах.
_KNOWN = {
    "https://registry.npmjs.org/react",
    "https://registry.npmjs.org/@tanstack/react-query",
    "https://proxy.golang.org/github.com/go-chi/chi/v5/@v/list",
    "https://proxy.golang.org/github.com/!burnt!sushi/toml/@v/list",
    "https://pypi.org/pypi/requests/json",
}


class _FakeFetch:
    def __init__(self, fail: bool = False) -> None:
        self.urls: list[str] = []
        self.fail = fail

    def __call__(self, url: str) -> int:
        self.urls.append(url)
        if self.fail:
            raise RegistryUnavailable("нет сети")
        if "proxy.golang.org" in url:
            return 200 if url in _KNOWN else 410
        return 200 if url in _KNOWN else 404


def _adapter(tmp_path: Path, fetch: _FakeFetch) -> DepsExistAdapter:
    return DepsExistAdapter(RegistryClient(fetch=fetch, cache_file=tmp_path / "cache.json"))


def _cfg(**kw) -> Config:
    return Config(check_deps=True, **kw)


def test_npm_package_name() -> None:
    assert npm_package_name("react") == "react"
    assert npm_package_name("react-dom/client") == "react-dom"
    assert npm_package_name("@tanstack/react-query/devtools") == "@tanstack/react-query"
    for not_package in ("./a", "../b", "/abs", "node:fs", "fs", "fs/promises", "@/components/x",
                        "~/lib", "virtual:pwa", "#internal", "Components/Button"):
        assert npm_package_name(not_package) is None, not_package


def test_npm_hallucinated_import_and_dependency(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({
        "name": "app",
        "dependencies": {"react": "^19", "react-smart-form-hooks": "^1", "ui": "workspace:*"},
    }, indent=1))
    (repo / "tsconfig.json").write_text('{\n  // алиасы\n  "compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["src/*"]},},\n}')
    (repo / "src" / "lib").mkdir()
    (repo / "src" / "App.tsx").write_text(
        'import { useState } from "react";\n'
        'import { x } from "@/lib/x";\n'
        'import y from "lib/y";\n'
        'import { magic } from "react-smart-form-hooks";\n'
        'const z = await import("@tanstack/react-query");\n'
        'import fs from "node:fs";\n'
    )
    findings = _adapter(tmp_path, _FakeFetch()).run(repo, _cfg())
    where = sorted((f.file, f.line) for f in findings)
    assert where == [("package.json", 5), ("src/App.tsx", 4)]
    assert all(f.severity.value == "error" and "react-smart-form-hooks" in f.message for f in findings)


def test_go_requires_and_uncovered_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "go.mod").write_text(
        "module example.com/app\n\ngo 1.22\n\nrequire (\n"
        "\tgithub.com/go-chi/chi/v5 v5.0.0\n"
        "\tgithub.com/acme/fastjsonx v1.0.0 // indirect\n)\n"
        "require github.com/BurntSushi/toml v1.3.0\n"
    )
    (repo / "main.go").write_text(
        'package main\n\nimport (\n\t"fmt"\n\t"example.com/app/internal/db"\n'
        '\tchi "github.com/go-chi/chi/v5/middleware"\n\t"github.com/ghost/notreal/pkg"\n)\n'
    )
    findings = _adapter(tmp_path, _FakeFetch()).run(repo, _cfg())
    assert sorted((f.file, f.line, f.identity) for f in findings) == [
        ("go.mod", 7, "go:github.com/acme/fastjsonx"),
        ("main.go", 7, "go:github.com/ghost/notreal/pkg"),
    ]


def test_go_helpers() -> None:
    assert go_imports('package x\nimport "os"\nimport y "github.com/a/b"\n') == [
        ("os", 2), ("github.com/a/b", 3)
    ]
    assert go_module_candidates("github.com/a/b/c") == ["github.com/a/b/c", "github.com/a/b", "github.com/a"]
    assert url_for("go", "github.com/BurntSushi/toml").endswith("/github.com/!burnt!sushi/toml/@v/list")


def test_pypi_manifests_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("requests>=2\n# comment\n-r other.txt\nreqeusts-oauth==1.0\n")
    (repo / "app.py").write_text("import yaml\nimport notapackage_at_all\n")
    findings = _adapter(tmp_path, _FakeFetch()).run(repo, _cfg())
    assert [(f.file, f.line, f.identity) for f in findings] == [("requirements.txt", 4, "pypi:reqeusts-oauth")]


def test_private_packages_and_goprivate_skipped(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"dependencies": {"@mycorp/ui": "^1"}}))
    (repo / "go.mod").write_text("module m\n\nrequire git.corp.io/team/lib v1.0.0\n")
    monkeypatch.setenv("GOPRIVATE", "git.corp.io")
    fetch = _FakeFetch()
    findings = _adapter(tmp_path, fetch).run(repo, _cfg(private_packages=["@mycorp/*"]))
    assert findings == [] and fetch.urls == []


def test_cache_avoids_second_request(tmp_path: Path) -> None:
    fetch = _FakeFetch()
    client = RegistryClient(fetch=fetch, cache_file=tmp_path / "cache.json")
    assert client.exists_many("npm", {"react", "nope-xyz"}) == {"react": True, "nope-xyz": False}
    again = RegistryClient(fetch=fetch, cache_file=tmp_path / "cache.json")
    again.exists_many("npm", {"react", "nope-xyz"})
    assert len(fetch.urls) == 2


def test_network_failure_is_skip_not_findings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"dependencies": {"react": "^19"}}))
    with pytest.raises(ToolExecutionError, match="реестр недоступен"):
        _adapter(tmp_path, _FakeFetch(fail=True)).run(repo, _cfg())


def test_disabled_by_default_no_requests(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"dependencies": {"ghost-pkg-zzz": "1"}}))
    fetch = _FakeFetch()
    registry = Registry()
    registry.register(_adapter(tmp_path, fetch))
    result = run(repo, Config(), registry)
    assert result.report.findings == [] and fetch.urls == [] and result.skipped == []


@pytest.mark.skipif(not os.environ.get("SLOPCHECK_NETWORK_TESTS"), reason="сетевой тест: SLOPCHECK_NETWORK_TESTS=1")
def test_live_registries(tmp_path: Path) -> None:
    client = RegistryClient(cache_file=tmp_path / "cache.json")
    assert client.exists_many("npm", {"react", "slopcheck-surely-missing-pkg-0x1"}) == {
        "react": True, "slopcheck-surely-missing-pkg-0x1": False,
    }
    assert client.exists_many("go", {"github.com/go-chi/chi/v5", "github.com/slopcheck/surely-missing-0x1"}) == {
        "github.com/go-chi/chi/v5": True, "github.com/slopcheck/surely-missing-0x1": False,
    }
    assert client.exists_many("pypi", {"requests", "slopcheck-surely-missing-0x1"}) == {
        "requests": True, "slopcheck-surely-missing-0x1": False,
    }
