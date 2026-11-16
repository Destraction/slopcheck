"""Go-интерфейс с единственной реализацией — абстракция «на вырост».

ИИ охотно заводит `type userRepository interface {...}` ровно под один
`*userRepo`. Второй реализации нет, моков в тестах нет: интерфейс только
удлиняет путь от вызова к коду. Эвристика без анализа типов:
  - интерфейсы и методы типов собираются регулярками по всем .go модуля,
    включая `_test.go`: мок в тестах — вторая реализация, и тогда
    интерфейс оправдан;
  - реализация — тип, у которого есть все методы интерфейса (по именам);
  - интерфейсы со встраиванием и ограничения дженериков (`~int | ~float64`)
    пропускаются: их методы регулярками не посчитать;
  - экспортируемый интерфейс библиотечного пакета не трогаем — его
    реализуют снаружи модуля; проверяем неэкспортируемые и пакеты main/internal.
Уровень info: это повод присмотреться, а не дефект.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from slopcheck.adapters.base import Adapter
from slopcheck.config import Config
from slopcheck.languages import walk_files
from slopcheck.models import Category, Finding, Severity

_INTERFACE = re.compile(r"^type\s+(\w+)(?:\[[^\]]*\])?\s+interface\s*\{(.*?)^\}", re.MULTILINE | re.DOTALL)
_METHOD = re.compile(r"^\s*(\w+)\s*\(", re.MULTILINE)
_RECEIVER = re.compile(r"^func\s*\(\s*\w*\s*\*?\s*(\w+)(?:\[[^\]]*\])?\s*\)\s*(\w+)\s*\(", re.MULTILINE)
_PACKAGE = re.compile(r"^package\s+(\w+)", re.MULTILINE)


@dataclass
class Interface:
    """Интерфейс: имя, методы, где объявлен, пакет."""

    name: str
    methods: frozenset[str]
    file: str
    line: int
    package: str
    directory: str


def _body_is_plain(body: str) -> bool:
    """В теле только методы: нет встраивания, ограничений типов и пустых тел."""
    for raw in body.splitlines():
        line = raw.split("//")[0].strip()
        if not line:
            continue
        if "|" in line or "~" in line or not _METHOD.match(line):
            return False
    return True


def parse_file(text: str, rel: str) -> tuple[list[Interface], list[tuple[str, str, str]]]:
    """Интерфейсы файла и методы типов: (каталог, тип, метод)."""
    package_match = _PACKAGE.search(text)
    package = package_match.group(1) if package_match else ""
    directory = str(Path(rel).parent)
    interfaces = []
    for match in _INTERFACE.finditer(text):
        body = match.group(2)
        methods = frozenset(_METHOD.findall(body))
        if methods and _body_is_plain(body):
            line = text.count("\n", 0, match.start()) + 1
            interfaces.append(Interface(match.group(1), methods, rel, line, package, directory))
    methods = [(directory, m.group(1), m.group(2)) for m in _RECEIVER.finditer(text)]
    return interfaces, methods


def _in_scope(iface: Interface) -> bool:
    """Проверяем неэкспортируемые интерфейсы и любые в main/internal."""
    if not iface.name[0].isupper():
        return True
    return iface.package == "main" or "internal" in Path(iface.directory).parts


def single_impl_interfaces(files: dict[str, str]) -> list[tuple[Interface, str]]:
    """(интерфейс, единственная реализация) по текстам файлов {путь: текст}."""
    interfaces: list[Interface] = []
    method_sets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rel, text in files.items():
        found, methods = parse_file(text, rel)
        interfaces += found
        for directory, type_name, method in methods:
            method_sets[(directory, type_name)].add(method)
    result = []
    for iface in interfaces:
        if not _in_scope(iface):
            continue
        impls = [t for (_d, t), ms in method_sets.items() if iface.methods <= ms]
        if len(impls) == 1:
            result.append((iface, impls[0]))
    return result


class GoSingleImplAdapter(Adapter):
    """Go-интерфейсы, у которых в модуле ровно одна реализация и нет моков."""

    name = "go-single-impl"
    category = Category.COMPLEXITY
    languages = frozenset({"go"})
    # Реализации ищутся по всему модулю: на срезе файлов вторая не видна.
    file_scoped = False

    def is_available(self) -> bool:
        """Встроенная эвристика: внешних тулов нет."""
        return True

    def run(self, root: Path, config: Config, files: list[str] | None = None) -> list[Finding]:
        """Найти интерфейсы с единственной реализацией."""
        sources = {
            p.relative_to(root).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in walk_files(root, config.ignore)
            if p.suffix == ".go"
        }
        return [
            Finding(
                category=Category.COMPLEXITY,
                tool="go-single-impl",
                file=iface.file,
                line=iface.line,
                message=(
                    f"Интерфейс {iface.name} реализует только {impl} (и нет моков в тестах) — "
                    "абстракция без второй реализации; можно использовать тип напрямую"
                ),
                severity=Severity.INFO,
                rule_id="single-impl-interface",
                identity=iface.name,
            )
            for iface, impl in single_impl_interfaces(sources)
        ]


# Адаптеры модуля; регистрирует их `slopcheck.adapters.register_all`.
ADAPTERS = (GoSingleImplAdapter(),)
