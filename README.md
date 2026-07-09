# slopcheck

Детектор «AI slop» без ИИ: оркестратор поверх зрелых open-source статических анализаторов. Находит дубли, мёртвый код, лишние комментарии, недостаток документации и сложность; сводит в единый отчёт со slop-score. В CI валит PR, только если тот **добавил** slop (delta к baseline).

Ядро 100% детерминированное, офлайн, без LLM. Опциональный `--llm-review` (off по умолчанию) — на будущее.

Подробный план и архитектура — в [PROJECT.md](./PROJECT.md).

## Статус

v1 в разработке по волнам (см. PROJECT.md, раздел 6). Сейчас готов каркас: модель данных и CLI-скелет.

## Установка (dev)

```bash
pip install -e ".[dev]"
slopcheck version
```

## Использование

```bash
slopcheck run ./path/to/repo --format console   # json | sarif | md
slopcheck gate ./repo --baseline base.json      # delta-гейт для CI (exit 1 при регрессе)
```

## Docker (все детекторы в одном образе)

Собирать в окружении с открытой сетью (npm-registry, GitHub releases):

```bash
docker build -t slopcheck .
docker run --rm -v "$PWD":/src slopcheck run /src --format console
```

Образ несёт node-детекторы (jscpd, knip), Python-детекторы (vulture, deptry,
interrogate, lizard) и best-effort бинарник aislop. Недоступный детектор
пропускается с пометкой в отчёте.

## CI (GitHub Actions)

Готовый composite-action — `action.yml`; полный пример PR-workflow с delta-гейтом
и загрузкой SARIF в Code Scanning — [.github/workflows/example.yml](.github/workflows/example.yml).
Гейт красит PR красным, только если он **добавил** slop уровня не ниже
`gate_severity` (см. `.slopcheck.yml`); старый долг сборку не валит.
