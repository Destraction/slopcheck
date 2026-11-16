"""Существует ли пакет в публичном реестре: npm, Go module proxy, PyPI.

Единственное место slopcheck, которое ходит в сеть, и только по `check_deps`.
Ответы кэшируются на диске: существующий пакет не исчезает — 7 дней,
отсутствующий могут опубликовать — 1 день.

Сетевая ошибка — не «пакета нет»: она поднимается наверх, и детектор
помечается пропущенным, а не выдаёт ложную находку.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_log = logging.getLogger(__name__)
_TTL_EXISTS = 7 * 24 * 3600
_TTL_MISSING = 24 * 3600
_TIMEOUT = 10.0
# Нейтральный User-Agent: без данных пользователя и проекта.
_HEADERS = {"User-Agent": "slopcheck-deps-check"}


class RegistryUnavailable(Exception):
    """Реестр не ответил определённо (сеть, 5xx, лимиты)."""


def _go_escape(path: str) -> str:
    """Экранирование пути модуля для Go proxy: заглавная буква → `!` + строчная."""
    return "".join(f"!{ch.lower()}" if ch.isupper() else ch for ch in path)


def url_for(ecosystem: str, name: str) -> str:
    """URL проверки существования пакета `name` в реестре `ecosystem`."""
    if ecosystem == "npm":
        return "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@/")
    if ecosystem == "go":
        return f"https://proxy.golang.org/{_go_escape(name)}/@v/list"
    if ecosystem == "pypi":
        return f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json"
    raise ValueError(f"неизвестная экосистема: {ecosystem}")


def fetch_status(url: str) -> int:
    """HTTP-статус GET-запроса (тело не читаем). Сбой сети — RegistryUnavailable."""
    request = urllib.request.Request(url, headers=_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 — https-URL из url_for
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RegistryUnavailable(f"{url}: {exc}") from exc


def _cache_path() -> Path:
    """Файл кэша: SLOPCHECK_CACHE_DIR или ~/.cache/slopcheck."""
    base = os.environ.get("SLOPCHECK_CACHE_DIR") or Path.home() / ".cache" / "slopcheck"
    return Path(base) / "registry.json"


class RegistryClient:
    """Проверка существования пакетов с дисковым кэшем."""

    def __init__(self, fetch=fetch_status, cache_file: Path | None = None) -> None:
        """`fetch` подменяется в тестах; `cache_file` — по умолчанию в ~/.cache."""
        self._fetch = fetch
        self._cache_file = cache_file or _cache_path()
        self._cache: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        """Прочитать кэш; битый или отсутствующий — пустой."""
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        """Записать кэш на диск."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError as exc:
            # Кэш — ускорение, а не условие работы: проверка продолжается,
            # но о потере кэша сообщаем, иначе каждый прогон молча ходит в сеть.
            _log.warning("кэш реестров не сохранён: %s", exc)

    def _cached(self, key: str) -> bool | None:
        """Ответ из кэша, если он не устарел; None — спрашивать реестр."""
        entry = self._cache.get(key)
        if not entry:
            return None
        ttl = _TTL_EXISTS if entry["exists"] else _TTL_MISSING
        return entry["exists"] if time.time() - entry["ts"] < ttl else None

    def _ask(self, ecosystem: str, name: str) -> bool:
        """Спросить реестр: 200 — есть, 404/410 — нет, прочее — исключение."""
        status = self._fetch(url_for(ecosystem, name))
        if status == 200:
            return True
        # Go proxy отвечает 410 Gone на несуществующий модуль.
        if status in (404, 410):
            return False
        raise RegistryUnavailable(f"{ecosystem}:{name}: HTTP {status}")

    def exists_many(self, ecosystem: str, names: set[str]) -> dict[str, bool]:
        """Существование каждого пакета; хоть один неопределённый ответ — исключение."""
        result: dict[str, bool] = {}
        todo: list[str] = []
        for name in sorted(names):
            cached = self._cached(f"{ecosystem}:{name}")
            if cached is None:
                todo.append(name)
            else:
                result[name] = cached
        if todo:
            with ThreadPoolExecutor(max_workers=8) as pool:
                answers = list(pool.map(lambda n: self._ask(ecosystem, n), todo))
            now = time.time()
            for name, exists in zip(todo, answers):
                result[name] = exists
                self._cache[f"{ecosystem}:{name}"] = {"exists": exists, "ts": now}
            self._save()
        return result
