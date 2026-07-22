"""Нормализованная модель данных slopcheck.

Каждый адаптер парсит родной вывод своего тула в список `Finding`.
Всё дальше (скоринг, репортеры, delta-гейт) работает только с этими моделями,
поэтому конкретные детекторы взаимозаменяемы.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    """Категории slop, по которым группируются находки."""

    DUPLICATION = "duplication"
    DEAD_CODE = "dead_code"
    COMMENTS = "comments"
    COMPLEXITY = "complexity"


class Severity(str, Enum):
    """Уровень находки. Гейт настраивается на пороговый severity."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


# Ранг severity: чем выше, тем серьёзнее. Единая шкала для гейта и --fail-on.
SEVERITY_RANK = {Severity.INFO: 0, Severity.WARN: 1, Severity.ERROR: 2}


class Finding(BaseModel):
    """Одна нормализованная находка от любого детектора."""

    category: Category
    tool: str
    file: str
    line: int = Field(ge=0)
    message: str
    severity: Severity = Severity.WARN
    end_line: int | None = Field(default=None, ge=0)
    rule_id: str | None = None
    metric: float | None = None
    # Стабильная идентичность для delta-гейта. Задаётся адаптером, когда
    # message содержит изменчивые данные (число строк, CCN, номер строки):
    # без неё косметический сдвиг превращал бы старую находку в «новую».
    identity: str | None = None

    def key(self) -> tuple[str, str, str, str]:
        """Стабильный ключ для delta-сравнения, устойчивый к сдвигу строк.

        Строку намеренно не включаем — вставка кода выше не должна
        превращать старую находку в «новую». Если адаптер задал `identity`,
        она используется вместо изменчивого message.
        """
        return (
            self.category.value,
            self.rule_id or self.tool,
            self.file,
            self.identity or self.message,
        )


class CategoryResult(BaseModel):
    """Агрегат находок и метрик по одной категории."""

    category: Category
    findings: list[Finding] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    score: float = Field(default=100.0, ge=0.0, le=100.0)
    # Отработал ли хоть один детектор категории. False означает «не проверяли»,
    # и это НЕ то же самое, что «чисто»: пустой список находок у непроведённой
    # проверки выглядел бы как безупречный код. Такие категории не идут в
    # total_score и помечаются в отчётах отдельно.
    measured: bool = True


class Report(BaseModel):
    """Полный результат прогона по репозиторию."""

    repo: str
    languages: list[str] = Field(default_factory=list)
    categories: list[CategoryResult] = Field(default_factory=list)
    total_score: float = Field(default=100.0, ge=0.0, le=100.0)
    # Категории, по которым не отработал ни один детектор. Итоговый счёт
    # посчитан БЕЗ них — иначе он завышен на непроверенное.
    unmeasured: list[Category] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def findings(self) -> list[Finding]:
        """Все находки из всех категорий одним списком."""
        return [f for cat in self.categories for f in cat.findings]
