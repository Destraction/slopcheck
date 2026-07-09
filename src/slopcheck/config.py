"""Загрузка и валидация `.slopcheck.yml`.

Конфиг управляет: набором включённых категорий-детекторов, весами и порогами
для скоринга, игнор-путями, override списка языков и порогом severity для гейта.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from slopcheck.models import Category, Severity

CONFIG_FILENAME = ".slopcheck.yml"


class CategoryConfig(BaseModel):
    """Настройки одной категории-детектора."""

    enabled: bool = True
    # Вес категории в агрегатном total_score (нормируется при расчёте).
    weight: float = Field(default=1.0, ge=0.0)


class Config(BaseModel):
    """Полная конфигурация прогона."""

    # Пути (glob-фрагменты), которые исключаются из анализа.
    ignore: list[str] = Field(
        default_factory=lambda: [
            "node_modules",
            ".git",
            "dist",
            "build",
            "vendor",
            ".venv",
            "venv",
            "migrations",
        ]
    )
    # Явный список языков; пустой → автодетект (languages.detect).
    languages: list[str] = Field(default_factory=list)
    # Находки этого severity и выше учитываются delta-гейтом как регресс.
    gate_severity: Severity = Severity.WARN
    # Порог дублей для jscpd: минимум токенов/строк в клоне. Дефолт jscpd — 50
    # токенов; ниже поднимает чувствительность к мелким копипастам.
    dup_min_tokens: int = Field(default=50, ge=1)
    dup_min_lines: int = Field(default=5, ge=1)
    # Настройки по каждой категории.
    categories: dict[Category, CategoryConfig] = Field(
        default_factory=lambda: {cat: CategoryConfig() for cat in Category}
    )

    def enabled_categories(self) -> list[Category]:
        """Категории, включённые в конфиге (в стабильном порядке enum)."""
        return [cat for cat in Category if self.categories.get(cat, CategoryConfig()).enabled]


def default_config() -> Config:
    """Дефолтная конфигурация (все категории включены)."""
    return Config()


def load_config(path: Path) -> Config:
    """Загрузить конфиг из `path`.

    `path` может указывать на сам файл конфига или на каталог, в котором он лежит.
    Если файла нет — возвращаются дефолты.
    """
    config_file = path / CONFIG_FILENAME if path.is_dir() else path
    if not config_file.exists():
        return default_config()

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_file}: ожидался YAML-словарь на верхнем уровне")
    return Config.model_validate(raw)


def dump_default_config() -> str:
    """Сериализовать дефолтный конфиг в YAML для команды `init-config`."""
    data = default_config().model_dump(mode="json")
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
