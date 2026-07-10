"""Базовый интерфейс адаптера детектора."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from slopcheck.config import Config
from slopcheck.languages import lang_for_path
from slopcheck.models import Category, Finding


class Adapter(ABC):
    """Обёртка над одним детектором.

    Наследник объявляет:
      - `name` — идентификатор адаптера (для отчёта о skip);
      - `category` — категория, в которую попадают его находки;
      - `languages` — языки, к которым применим (пустой набор = любой язык);
      - `file_scoped` — умеет ли работать по списку файлов. False — детектор
        анализирует проект целиком (deptry, knip); в инкрементальном режиме
        такой пропускается с пометкой.
    и реализует `is_available()` и `run()`.
    """

    name: str = "adapter"
    category: Category
    languages: frozenset[str] = frozenset()
    file_scoped: bool = True

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
