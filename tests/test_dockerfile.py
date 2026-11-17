"""Образ: версии всех детекторов закреплены точно (H10).

Плавающая версия (`latest`, `@4`, `>=`) меняла находки между сборками, и
гейт CI расходился с прошлым прогоном без правки кода.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
# Инструкции без переносов строк `\`: одна инструкция — одна строка.
_INSTRUCTIONS = re.sub(r"\\\n\s*", " ", _DOCKERFILE).splitlines()
_ARGS = dict(re.findall(r"^ARG (\w+)=(\S+)$", _DOCKERFILE, re.MULTILINE))


def test_version_args_are_exact() -> None:
    versions = {name: value for name, value in _ARGS.items() if name.endswith("_VERSION")}
    assert len(versions) >= 15
    loose = {name: value for name, value in versions.items() if not re.fullmatch(r"\d+(\.\d+)+", value)}
    assert loose == {}


def test_every_used_version_is_declared() -> None:
    used = set(re.findall(r"\$\{(\w+_VERSION)\}", _DOCKERFILE))
    assert used and used <= set(_ARGS)


def test_base_images_pinned_by_args() -> None:
    images = [line.split()[1] for line in _INSTRUCTIONS if line.startswith("FROM ")]
    assert images and all("${" in image for image in images), images


def test_npm_packages_pinned() -> None:
    specs = [
        spec.strip('"')
        for line in _INSTRUCTIONS if "npm install -g" in line
        for spec in line.split("npm install -g", 1)[1].split("&&")[0].split()
    ]
    assert specs and all(re.fullmatch(r"[\w@/.-]+@\$\{\w+_VERSION\}", spec) for spec in specs), specs


def test_python_detectors_pinned() -> None:
    extras = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    detectors = {re.split(r"[<>=!~ ]", dep)[0] for dep in extras["project"]["optional-dependencies"]["detectors"]}
    pip_line = next(line for line in _INSTRUCTIONS if "pip install" in line and ".[detectors]" in line)
    pinned = set(re.findall(r'"([\w-]+)==\$\{\w+_VERSION\}"', pip_line))
    assert detectors == pinned
