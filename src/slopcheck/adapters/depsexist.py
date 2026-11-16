"""Несуществующие пакеты: импорт или зависимость, которой нет в реестре.

ИИ уверенно пишет `import { x } from "react-use-smart-form"` на пакет,
которого не существует. Злоумышленники регистрируют такие имена
(slopsquatting), и `npm install` ставит их код. Детектор сверяет с реестрами:
  - npm: зависимости package.json и импорты JS/TS-файлов;
  - Go: модули go.mod и импорты, не покрытые go.mod;
  - PyPI: только зависимости манифестов (имя импорта ≠ имя дистрибутива:
    `yaml` ставится как PyYAML — сверка импортов дала бы ложные находки).

Ходит в сеть, поэтому включается только `check_deps` / `--check-deps`.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import is_ignored, lang_for_path
from slopcheck.models import Category, Finding, Severity
from slopcheck.registries import RegistryClient, RegistryUnavailable
from slopcheck.subprocess_util import ToolExecutionError

_REGISTRY_NAMES = {"npm": "npm", "go": "Go module proxy", "pypi": "PyPI"}

# Встроенные модули Node (`fs`, `node:fs`, `fs/promises`).
_NODE_BUILTINS = frozenset(
    "assert async_hooks buffer child_process cluster console constants crypto dgram "
    "diagnostics_channel dns domain events fs http http2 https inspector module net os "
    "path perf_hooks process punycode querystring readline repl stream string_decoder "
    "sys test timers tls trace_events tty url util v8 vm wasi worker_threads zlib".split()
)
_JS_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)["']([^"'\n]+)["']""",
    re.MULTILINE,
)
# Валидное имя npm-пакета: строчные, опциональный scope. Всё прочее — алиасы
# сборщика (`@/components`, `~/lib`), виртуальные модули (`virtual:x`).
_NPM_NAME = re.compile(r"^(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*$")
_GO_IMPORT_BLOCK = re.compile(r"^import\s*\((.*?)^\)", re.MULTILINE | re.DOTALL)
_GO_IMPORT_LINE = re.compile(r'^import\s+(?:[\w.]+\s+)?"([^"]+)"', re.MULTILINE)
_GO_QUOTED = re.compile(r'"([^"]+)"')
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass(frozen=True)
class Usage:
    """Где встретился пакет: экосистема, имя, файл, строка."""

    ecosystem: str
    name: str
    file: str
    line: int


def _line_of(text: str, offset: int) -> int:
    """Номер строки (с 1) для смещения в тексте."""
    return text.count("\n", 0, offset) + 1


def _first_line_with(text: str, needle: str) -> int:
    """Строка первого вхождения `"needle"` в манифесте (1, если не нашлось)."""
    index = text.find(f'"{needle}"')
    return _line_of(text, index) if index >= 0 else 1


# ------------------------------------------------------------------- npm


def npm_package_name(specifier: str) -> str | None:
    """Имя пакета из спецификатора импорта; None — не пакет из реестра."""
    # `~/` — повсеместный алиас корня проекта, а не пакет.
    if specifier.startswith((".", "/", "#", "~", "node:")) or ":" in specifier:
        return None
    parts = specifier.split("/")
    name = "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
    if name in _NODE_BUILTINS or not _NPM_NAME.match(name):
        return None
    return name


def _strip_jsonc(text: str) -> str:
    """tsconfig — JSON с комментариями и висячими запятыми."""
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def tsconfig_aliases(project: Path) -> tuple[list[str], set[str]]:
    """Префиксы алиасов `paths` и имена верхнего уровня под `baseUrl`."""
    path = project / "tsconfig.json"
    try:
        options = json.loads(_strip_jsonc(path.read_text(encoding="utf-8"))).get("compilerOptions", {})
    except (OSError, ValueError, AttributeError):
        return [], set()
    prefixes = [key.rstrip("*") for key in (options.get("paths") or {})]
    base_names: set[str] = set()
    if options.get("baseUrl"):
        base = (project / options["baseUrl"]).resolve()
        if base.is_dir():
            base_names = {p.stem if p.is_file() else p.name for p in base.iterdir()}
    return prefixes, base_names


_LOCAL_SPECS = ("workspace:", "file:", "link:", "git", "http")
_NPM_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def _manifest_deps(data: dict) -> list[str]:
    """Имена из реестра в разделах зависимостей package.json (без локальных ссылок)."""
    names: list[str] = []
    for section in _NPM_SECTIONS:
        for name, spec in (data.get(section) or {}).items():
            spec = spec if isinstance(spec, str) else ""
            if spec.startswith(_LOCAL_SPECS):
                continue
            # `"alias": "npm:real-name@^1"` — в реестре ищется real-name.
            names.append(spec[4:].rsplit("@", 1)[0] or name if spec.startswith("npm:") else name)
    return names


def _npm_manifest_usages(root: Path, manifests: list[Path]) -> tuple[list[Usage], set[str]]:
    """Зависимости всех package.json и имена пакетов самого workspace."""
    usages: list[Usage] = []
    workspace: set[str] = set()
    for manifest in manifests:
        text = manifest.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(text)
        except ValueError:
            continue
        workspace.add(data.get("name", ""))
        rel = manifest.relative_to(root).as_posix()
        usages += [Usage("npm", n, rel, _first_line_with(text, n)) for n in _manifest_deps(data)]
    return usages, workspace


def _import_package(specifier: str, prefixes: list[str], skip: set[str]) -> str | None:
    """Пакет из реестра для спецификатора; None — алиас, свой пакет или не пакет."""
    if any(p and specifier.startswith(p) for p in prefixes):
        return None
    name = npm_package_name(specifier)
    if not name or name in skip or name.split("/")[0] in skip:
        return None
    return name


def npm_usages(root: Path, manifests: list[Path], sources: list[Path]) -> list[Usage]:
    """Пакеты npm из package.json и импортов JS/TS-файлов."""
    usages, workspace = _npm_manifest_usages(root, manifests)
    aliases: dict[Path, tuple[list[str], set[str]]] = {}
    for source in sources:
        project = next((m.parent for m in manifests if m.parent in source.parents), root)
        prefixes, base_names = aliases.setdefault(project, tsconfig_aliases(project))
        text = source.read_text(encoding="utf-8", errors="replace")
        rel = source.relative_to(root).as_posix()
        for match in _JS_IMPORT.finditer(text):
            name = _import_package(match.group(1), prefixes, workspace | base_names)
            if name:
                usages.append(Usage("npm", name, rel, _line_of(text, match.start())))
    return usages


# ------------------------------------------------------------------- Go


def _go_mod(path: Path) -> tuple[str, dict[str, int], str]:
    """Путь модуля, require (модуль → строка) и текст go.mod."""
    text = path.read_text(encoding="utf-8", errors="replace")
    module = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    requires: dict[str, int] = {}
    in_block = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("//")[0].strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            line = line[len("require "):]
        elif not in_block:
            continue
        parts = line.split()
        if len(parts) >= 2:
            requires[parts[0]] = number
    return (module.group(1) if module else ""), requires, text


def go_imports(text: str) -> list[tuple[str, int]]:
    """Импорты Go-файла: путь и строка."""
    found: list[tuple[str, int]] = []
    for block in _GO_IMPORT_BLOCK.finditer(text):
        for quoted in _GO_QUOTED.finditer(block.group(1)):
            found.append((quoted.group(1), _line_of(text, block.start(1) + quoted.start())))
    for single in _GO_IMPORT_LINE.finditer(text):
        found.append((single.group(1), _line_of(text, single.start())))
    return found


def _is_go_std(path: str) -> bool:
    """Стандартная библиотека: в первом элементе пути нет точки."""
    return "." not in path.split("/")[0]


def go_module_candidates(import_path: str) -> list[str]:
    """Префиксы пути импорта, которые могут быть модулем (от длинного к короткому)."""
    parts = import_path.split("/")
    return ["/".join(parts[:n]) for n in range(len(parts), 1, -1)]


def _covered(path: str, prefixes: set[str]) -> bool:
    """Путь — один из модулей `prefixes` или пакет внутри него."""
    return any(path == m or path.startswith(m + "/") for m in prefixes)


def go_usages(root: Path, go_mods: list[Path], sources: list[Path]) -> tuple[list[Usage], list[Usage]]:
    """(модули go.mod, импорты вне go.mod) — вторые проверяются по префиксам."""
    required: list[Usage] = []
    modules: list[tuple[Path, set[str]]] = []
    for go_mod in go_mods:
        module, requires, _text = _go_mod(go_mod)
        rel = go_mod.relative_to(root).as_posix()
        required += [Usage("go", name, rel, line) for name, line in requires.items()]
        # Свой модуль и его зависимости — «покрытые» пути для импортов.
        modules.append((go_mod.parent, set(requires) | ({module} if module else set())))
    uncovered: list[Usage] = []
    for source in sources:
        known = next((m[1] for m in modules if m[0] in source.parents), set())
        text = source.read_text(encoding="utf-8", errors="replace")
        rel = source.relative_to(root).as_posix()
        uncovered += [
            Usage("go", path, rel, line)
            for path, line in go_imports(text)
            if not _is_go_std(path) and not _covered(path, known)
        ]
    return required, uncovered


# ------------------------------------------------------------------- PyPI


def pypi_usages(root: Path, manifests: list[Path]) -> list[Usage]:
    """Зависимости requirements*.txt и pyproject.toml."""
    usages: list[Usage] = []
    for manifest in manifests:
        text = manifest.read_text(encoding="utf-8", errors="replace")
        rel = manifest.relative_to(root).as_posix()
        if manifest.name == "pyproject.toml":
            usages += _pyproject_usages(text, rel)
            continue
        for number, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#")[0].strip()
            if not line or line.startswith(("-", "git+", "http")) or "://" in line:
                continue
            match = _REQ_NAME.match(line)
            if match:
                usages.append(Usage("pypi", match.group(1).lower(), rel, number))
    return usages


def _table(data: dict, *keys: str) -> dict:
    """Вложенная таблица TOML по пути ключей; отсутствующая — пустая."""
    for key in keys:
        value = data.get(key)
        data = value if isinstance(value, dict) else {}
    return data


def _pyproject_usages(text: str, rel: str) -> list[Usage]:
    """Зависимости [project] (включая optional) и [tool.poetry.dependencies]."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    project = _table(data, "project")
    specs = list(project.get("dependencies", []))
    for group in _table(project, "optional-dependencies").values():
        specs += group
    names = [m.group(1) for spec in specs if (m := _REQ_NAME.match(spec))]
    names += [n for n in _table(data, "tool", "poetry", "dependencies") if n.lower() != "python"]
    return [Usage("pypi", n.lower(), rel, _first_line_with(text, n)) for n in names]


# ------------------------------------------------------------------- адаптер


def _private(name: str, patterns: list[str]) -> bool:
    """Свой пакет: совпал с `private_packages` или GOPRIVATE."""
    goprivate = [p for p in os.environ.get("GOPRIVATE", "").split(",") if p]
    return any(fnmatch(name, p) or fnmatch(name, p + "/*") for p in [*patterns, *goprivate])


def _walk(root: Path, ignore: list[str]):
    """Файлы под `root` без игнорируемых каталогов (в node_modules не спускаемся)."""
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel = base.relative_to(root).parts
        dirnames[:] = [d for d in dirnames if not is_ignored((*rel, d), ignore)]
        for name in filenames:
            if not is_ignored((*rel, name), ignore):
                yield base / name


_REQUIREMENTS = re.compile(r"requirements.*\.(txt|in)$")


def _role(path: Path) -> str | None:
    """Роль файла для проверки: манифест экосистемы или исходник; None — не нужен."""
    name = path.name
    if name in ("package.json", "go.mod"):
        return name
    if name == "pyproject.toml" or _REQUIREMENTS.match(name):
        return "python"
    lang = lang_for_path(path)
    if lang in ("javascript", "typescript"):
        return "js"
    return "go" if lang == "go" else None


def _collect(root: Path, config: Config, files: list[str] | None) -> dict[str, list[Path]]:
    """Файлы по ролям: манифесты экосистем и исходники JS/TS и Go."""
    if files is None:
        candidates = list(_walk(root, config.ignore))
    else:
        candidates = [root / f for f in files if (root / f).is_file()]
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in candidates:
        role = _role(path)
        if role:
            groups[role].append(path)
    return groups


def _finding(usage: Usage) -> Finding:
    """Находка «пакет не найден в реестре»."""
    registry = _REGISTRY_NAMES[usage.ecosystem]
    return Finding(
        category=Category.DEAD_CODE,
        tool="deps-exist",
        file=usage.file,
        line=usage.line,
        message=(
            f"Пакет «{usage.name}» не найден в {registry} — вероятно, выдуман; "
            "установка такого имени может поставить чужой код (slopsquatting)"
        ),
        severity=Severity.ERROR,
        rule_id="missing-package",
        identity=f"{usage.ecosystem}:{usage.name}",
    )


class DepsExistAdapter(Adapter):
    """Импорты и зависимости, которых нет в публичных реестрах."""

    name = "deps-exist"
    category = Category.DEAD_CODE
    languages = frozenset({"javascript", "typescript", "go", "python"})

    def __init__(self, client: RegistryClient | None = None) -> None:
        """`client` подменяется в тестах; по умолчанию — реальные реестры с кэшем."""
        self._client = client

    def enabled(self, config: Config) -> bool:
        """Только по `check_deps`: проверка ходит в сеть."""
        return config.check_deps

    def is_available(self) -> bool:
        """Внешних тулов нет — только HTTP."""
        return True

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Сверить пакеты с реестрами и вернуть ненайденные."""
        client = self._client or RegistryClient()
        groups = _collect(root, config, files)
        required_go, uncovered_go = go_usages(root, groups["go.mod"], groups["go"])
        direct = [
            u for u in [
                *npm_usages(root, groups["package.json"], groups["js"]),
                *required_go,
                *pypi_usages(root, groups["python"]),
            ]
            if not _private(u.name, config.private_packages)
        ]
        uncovered_go = [u for u in uncovered_go if not _private(u.name, config.private_packages)]
        try:
            missing = self._missing_direct(client, direct)
            missing += self._missing_go_imports(client, uncovered_go)
        except RegistryUnavailable as exc:
            raise ToolExecutionError(f"реестр недоступен — {exc}") from exc
        return [_finding(u) for u in missing]

    @staticmethod
    def _missing_direct(client: RegistryClient, usages: list[Usage]) -> list[Usage]:
        """Упоминания пакетов, которых нет в реестре своей экосистемы."""
        by_eco: dict[str, set[str]] = defaultdict(set)
        for u in usages:
            by_eco[u.ecosystem].add(u.name)
        exists = {eco: client.exists_many(eco, names) for eco, names in by_eco.items()}
        return [u for u in usages if not exists[u.ecosystem][u.name]]

    @staticmethod
    def _missing_go_imports(client: RegistryClient, usages: list[Usage]) -> list[Usage]:
        """Импорт вне go.mod существует, если модулем является хоть один его префикс."""
        candidates = {c for u in usages for c in go_module_candidates(u.name)}
        if not candidates:
            return []
        exists = client.exists_many("go", candidates)
        return [u for u in usages if not any(exists[c] for c in go_module_candidates(u.name))]


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (DepsExistAdapter(),)
