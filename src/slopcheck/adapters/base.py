"""Базовый интерфейс адаптера детектора."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from slopcheck.config import Config
from slopcheck.languages import lang_for_path, walk_files
from slopcheck.models import Category, Finding


class Adapter(ABC):
    """Обёртка над одним детектором.

    Наследник объявляет:
      - `name` — идентификатор адаптера (для отчёта о skip);
      - `category` — категория, в которую попадают его находки;
      - `languages` — языки, к которым применим (пустой набор = любой язык);
      - `measures` — дополнительные категории, которые адаптер проверяет
        (golangci-lint и eslint дают и мёртвый код, и доки, и смеллы);
      - `file_scoped` — умеет ли работать по списку файлов. False — детектор
        анализирует проект целиком (deptry, knip); в инкрементальном режиме
        такой пропускается с пометкой.
    и реализует `is_available()` и `run()`.
    """

    name: str = "adapter"
    category: Category
    languages: frozenset[str] = frozenset()
    measures: frozenset[Category] = frozenset()
    file_scoped: bool = True

    def categories(self) -> frozenset[Category]:
        """Все категории, которые адаптер проверяет: домашняя плюс `measures`."""
        return self.measures | {self.category}

    def enabled(self, config: Config) -> bool:
        """Включён ли адаптер конфигом. Выключенный runner обходит молча.

        Это не пропуск: проверку не просили (напр. сетевую `check_deps`),
        и помечать её «слепой зоной» в каждом отчёте было бы шумом.
        """
        return True

    def applies_to(self, languages: list[str]) -> bool:
        """Актуален ли адаптер для набора языков репозитория."""
        if not self.languages:
            return True
        return bool(self.languages.intersection(languages))

    def select_files(self, files: list[str]) -> list[str]:
        """Файлы из списка, релевантные языкам адаптера.

        Инкрементальный список содержит файлы всех языков вперемешку;
        передать vulture .ts-файл — получить сбой, поэтому каждый адаптер
        сужает список до своих расширений.
        """
        if not self.languages:
            return list(files)
        return [f for f in files if lang_for_path(f) in self.languages]

    def sources(self, root: Path, config: Config, files: list[str] | None) -> Iterator[tuple[str, str]]:
        """(путь от root, текст) файлов языков адаптера — для встроенных эвристик.

        Полный прогон — весь `root` без игнорируемых путей; инкрементальный —
        только релевантные файлы из `files`.
        """
        if files is None:
            paths = (p for p in walk_files(root, config.ignore) if lang_for_path(p) in self.languages)
        else:
            paths = (root / f for f in self.select_files(files))
        for path in paths:
            yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="replace")

    def resolve_targets(
        self, root: Path, files: list[str] | None, *, absolute: bool = False
    ) -> list[str] | None:
        """Что передать тулу: весь `root` либо релевантный срез файлов.

        None означает «работы нет» — в инкрементальном режиме ни один
        изменённый файл не относится к языкам адаптера, и запускать тул
        не на чем (пустой список аргументов заставил бы его сканировать cwd).

        `absolute` — для тулов, которые зовутся Python-API и не знают про cwd.
        """
        if files is None:
            return [str(root)]
        selected = self.select_files(files)
        if not selected:
            return None
        return [str(root / f) for f in selected] if absolute else selected

    @abstractmethod
    def is_available(self) -> bool:
        """Установлен ли требуемый внешний тул."""
        raise NotImplementedError

    @abstractmethod
    def run(
        self, root: Path, config: Config, files: list[str] | None = None
    ) -> list[Finding]:
        """Прогнать детектор по `root` и вернуть нормализованные находки.

        `files` — инкрементальный режим: относительные (от root) пути
        изменённых файлов. None — полный прогон. Адаптер, который не может
        сузить анализ (jscpd: дубль может быть с неизменённым файлом),
        вправе игнорировать список — runner отфильтрует находки сам.
        """
        raise NotImplementedError


class BuiltinAdapter(Adapter):
    """Встроенная эвристика slopcheck: внешних тулов нет, доступна всегда."""

    def is_available(self) -> bool:
        """Внешних тулов нет — доступна всегда."""
        return True
