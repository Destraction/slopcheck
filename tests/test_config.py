"""Тесты загрузки конфига и команды init-config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from slopcheck.config import (
    CONFIG_FILENAME,
    Config,
    default_config,
    dump_default_config,
    load_config,
)
from slopcheck.models import Category, Severity


def test_load_missing_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    assert cfg == default_config()
    assert set(cfg.enabled_categories()) == set(Category)


def test_load_from_directory_and_file(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(
        yaml.safe_dump({"gate_severity": "error", "languages": ["python"]}),
        encoding="utf-8",
    )
    from_dir = load_config(tmp_path)
    from_file = load_config(tmp_path / CONFIG_FILENAME)
    assert from_dir == from_file
    assert from_dir.gate_severity is Severity.ERROR
    assert from_dir.languages == ["python"]


def test_disabled_category_excluded(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(
        yaml.safe_dump({"categories": {"complexity": {"enabled": False}}}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert Category.COMPLEXITY not in cfg.enabled_categories()
    assert Category.DUPLICATION in cfg.enabled_categories()


def test_non_mapping_config_rejected(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(tmp_path)


def test_dump_default_is_reloadable() -> None:
    text = dump_default_config()
    reloaded = Config.model_validate(yaml.safe_load(text))
    assert reloaded == default_config()


def test_rule_ignored_exact_glob_and_legacy_alias() -> None:
    from slopcheck.config import Config

    cfg = Config(ignore_rules=["jsdoc/*", "React/No-Array-Index-Key"])
    assert cfg.rule_ignored("jsdoc/require-jsdoc")
    assert cfg.rule_ignored("react/no-array-index-key")
    assert not cfg.rule_ignored("react/jsx-key")
    assert not cfg.rule_ignored(None)
    # Дефолт устаревшего aislop_ignore_rules продолжает работать.
    assert cfg.rule_ignored("python-formatting")
    assert not Config(aislop_ignore_rules=[]).rule_ignored("python-formatting")


def test_hook_severity_default_warn() -> None:
    from slopcheck.config import Config
    from slopcheck.models import Severity

    assert Config().hook_severity is Severity.WARN
