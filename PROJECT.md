# PROJECT — slopcheck

Детектор «AI slop» без ИИ: оркестратор поверх зрелых open-source статических анализаторов. Находит дубли, мёртвый код, лишние комментарии, недостаток документации, сложность и смеллы; сводит в единый отчёт со slop-score; в CI валит PR, только если тот **добавил** slop.

---

## 1. Резюме

**Что строим.** CLI-инструмент `slopcheck` (Python-оркестратор), который запускает набор внешних детекторов, нормализует их вывод в единую модель findings, считает slop-score по категориям и выдаёт отчёт (console / JSON / SARIF / Markdown). Плюс Docker-образ со всеми тулами и GitHub Action, которая гейтит PR по дельте к базовой ветке.

**Для кого.** Личное использование по своим репозиториям (Plendo, «Практика», парсеры и пр.), мультиязычным. Бесплатно, офлайн, воспроизводимо.

**Роль ИИ.** Ядро — 100% детерминированное, без LLM. Есть один опциональный шаг `--llm-review` (off по умолчанию, отдельная волна, тонкий seam) для субъективного ревью — используется только по явному флагу.

**Критерии готовности (v1).**
1. `slopcheck run ./repo` на мультиязычном репо выдаёт корректный console-отчёт со slop-score и разбивкой по 4 категориям.
2. Поддержаны детекторы всех 4 категорий; отсутствие тула не роняет запуск (skip с пометкой в отчёте).
3. `--format json|sarif|md` дают валидный машинный вывод; SARIF открывается во вкладке Code Scanning GitHub.
4. Docker-образ собирается и содержит все детекторы; `docker run … slopcheck run /src` работает.
5. GitHub Action на тестовом PR: зелёная, если slop не добавлен; красная — если добавлен (delta-гейт).
6. Конфиг `.slopcheck.yml` управляет: набором детекторов, порогами, игнор-путями, языками.

**Явно НЕ входит в v1 (→ v2).** Кастомные semgrep-правила (нарративные комментарии, смеллы); eslint-plugin-jsdoc (покрытие доками JS/TS); автофикс/переписывание кода; HTML-дашборд; реализация LLM-ревью (только seam); поддержка языков вне списка детекторов; веб-сервис/GUI.

---

## 2. Структура проекта

```
slopcheck/
├── PROJECT.md                     # этот файл
├── README.md                      # использование, установка
├── pyproject.toml                 # пакет, зависимости (click/typer, rich, pydantic, pyyaml), entrypoint slopcheck
├── .slopcheck.yml                 # пример/дефолтный конфиг
├── Dockerfile                     # образ со всеми детекторами
├── action.yml                     # composite GitHub Action
├── .github/workflows/example.yml  # пример использования Action
├── src/slopcheck/
│   ├── __init__.py
│   ├── cli.py                     # entrypoint: run / version / init-config
│   ├── config.py                  # загрузка/валидация .slopcheck.yml, дефолты
│   ├── languages.py               # детект языков репо (по расширениям/файлам-маркерам)
│   ├── models.py                  # Finding, CategoryResult, Report (pydantic)
│   ├── runner.py                  # оркестратор: выбор адаптеров, запуск, сбор findings
│   ├── subprocess_util.py         # безопасный запуск внешних тулов, таймауты, «тул отсутствует»
│   ├── registry.py                # реестр адаптеров: категория → адаптеры
│   ├── adapters/
│   │   ├── base.py                # ABC Adapter: is_available(), run(paths) -> list[Finding]
│   │   ├── duplication.py         # jscpd
│   │   ├── deadcode.py            # knip (JS/TS), vulture + deptry (Python)
│   │   ├── comments.py            # aislop + semgrep (нарративные комментарии), interrogate + jsdoc (покрытие)
│   │   └── complexity.py          # lizard + semgrep (смеллы)
│   ├── scoring.py                 # метрики по категориям + агрегатный slop-score
│   ├── baseline.py                # прогон на base ref, diff findings, delta-гейт
│   ├── reporters/
│   │   ├── console.py             # rich-таблицы
│   │   ├── json_report.py
│   │   ├── sarif.py
│   │   └── markdown.py
│   └── llm/
│       └── review.py              # опциональный seam (off по умолчанию), stub-интерфейс в v1
│   # semgrep-rules/ — v2 (кастомные правила: нарративные комментарии, смеллы)
└── tests/
    ├── fixtures/                  # мини-репо с намеренным slop на разных языках
    └── test_*.py                  # по адаптеру/репортеру/скорингу/дельте
```

---

## 3. Архитектура и реализация

**Стек.** Python 3.11+, `typer`(CLI) + `rich`(console), `pydantic`(модели/конфиг), `pyyaml`. Внешние детекторы вызываются как subprocess и живут в Docker-образе (разные рантаймы: Node — jscpd/knip/aislop; Python — vulture/deptry/interrogate/semgrep/lizard).

**Нормализованная модель (ядро всей системы).**
```
Finding: category, tool, file, line, end_line?, severity(info|warn|error),
         message, rule_id?, metric?(число, напр. сложность/%покрытия)
CategoryResult: category, findings[], metrics(dict), score(0..100)
Report: repo, languages[], categories[CategoryResult], total_score, generated_at
```
Каждый адаптер парсит родной вывод тула (обычно JSON) в `list[Finding]`. Всё дальше (скоринг, репортеры, дельта) работает только с нормализованной моделью — тулы взаимозаменяемы.

**Поток данных.**
```
config + пути → languages.detect → runner выбирает адаптеры (по языкам+конфигу)
  → adapters.run (subprocess → parse) → list[Finding]
  → scoring → Report → reporters(console/json/sarif/md)
                    ↘ baseline.delta (в CI) → exit code
```

**Адаптеры (registry, категория → тулы):**
| Категория | Тулы | Языки |
|---|---|---|
| Дубли | jscpd | мультиязык (223 формата) |
| Мёртвый код + зависимости | knip; vulture; deptry | JS/TS; Python |
| Комментарии + доки | aislop; interrogate | мультиязык; Python (v2: semgrep, eslint-jsdoc) |
| Сложность | lizard | мультиязык (v2: semgrep-смеллы) |

Адаптер объявляет, для каких языков применим, и `is_available()` (тул установлен?). Отсутствует → skip + пометка в отчёте (грациозная деградация внутри Docker не нужна, но CLI без Docker так переживёт нехватку тула).

**Скоринг.** Каждая категория даёт метрики (напр. % дублей, число мёртвых символов, docstring-coverage, доля функций с высокой цикломатикой) → нормируется в 0..100. `total_score` — взвешенное среднее (веса в конфиге). Score — для человека/тренда, гейт — по дельте.

**Delta-гейт (baseline).** В CI: `slopcheck` прогоняется на `base ref` (checkout+run) и на PR; findings сравниваются (по стабильному ключу category+rule+нормализованный путь, устойчиво к сдвигу строк). Гейт красный, если появились новые findings выше severity-порога / выросли метрики сверх допуска. Конфиг задаёт, что считать регрессом.

**Конфиг `.slopcheck.yml`.** enabled-детекторы, пороги/веса по категориям, `ignore:` пути (vendor, миграции, генерённое), явный список языков (override автодетекта), severity-порог гейта.

**Docker.** База node-slim + python-venv с pip-тулами; aislop ставится из npm, и сборка падает, если он не встал (молча пропущенный детектор AI-slop обесценивает гейт); в финале — `slopcheck` как entrypoint. `docker run -v $PWD:/src slopcheck run /src`.

**GitHub Action.** `action.yml` (composite): checkout base+head, запуск docker-образа, upload SARIF (`github/codeql-action/upload-sarif`), Markdown в `$GITHUB_STEP_SUMMARY`, exit code от delta-гейта.

---

## 4. Список фич (каждая ≈ один /dev)

**F1. Каркас пакета + модели данных.** pyproject, `slopcheck` entrypoint (typer, `run`/`version`), `models.py` (Finding/CategoryResult/Report на pydantic). Проверка: `slopcheck version` работает, модели импортируются, тест на сериализацию Report.
*Файлы:* pyproject.toml, src/slopcheck/{__init__,cli,models}.py, tests/test_models.py

**F2. Загрузка конфига + детект языков.** `.slopcheck.yml` парс+валидация+дефолты; `languages.detect(path)` по расширениям/маркерам. Проверка: `slopcheck init-config` пишет дефолт; на fixture-репо детект языков верный.
*Файлы:* src/slopcheck/{config,languages}.py, .slopcheck.yml, tests/test_config.py, tests/test_languages.py

**F3. Интерфейс адаптеров + Runner.** `adapters/base.py` (ABC), `subprocess_util.py`, `registry.py`, `runner.py` (выбор адаптеров по языкам+конфигу, запуск, сбор Findings). Один тривиальный фейковый адаптер для теста конвейера. Проверка: runner на фейк-адаптере возвращает агрегированный список findings.
*Файлы:* src/slopcheck/{runner,registry,subprocess_util}.py, src/slopcheck/adapters/base.py, tests/test_runner.py

**F4. Адаптер дублей (jscpd).** invoke jscpd `--reporters json`, парс в Findings (категория duplication). Проверка: на fixture с копипастой findings появляются с верными файлами/строками.
*Файлы:* src/slopcheck/adapters/duplication.py, tests/fixtures/dup/*, tests/test_dup.py

**F5. Адаптер мёртвого кода (knip + vulture + deptry).** три тула → одна категория. Проверка: на JS-fixture (неисп. экспорт) и Python-fixture (неисп. функция + лишняя зависимость) findings корректны.
*Файлы:* src/slopcheck/adapters/deadcode.py, tests/fixtures/dead/*, tests/test_deadcode.py

**F6. Адаптер комментариев + доков (aislop + interrogate).** нарративные комментарии (aislop, мультиязык) + покрытие докстрингами (interrogate, Python). Проверка: fixture с `// increment i` и функцией без докстринга → findings. (v2: semgrep-правила нарративных комментариев, eslint-plugin-jsdoc для JS/TS.)
*Файлы:* src/slopcheck/adapters/comments.py, tests/fixtures/comments/*, tests/test_comments.py

**F7. Адаптер сложности (lizard).** цикломатика/раздутые функции с метрикой. Проверка: fixture с функцией высокой сложности → finding с метрикой. (v2: semgrep-правила смеллов.)
*Файлы:* src/slopcheck/adapters/complexity.py, tests/fixtures/complexity/*, tests/test_complexity.py

**F8. Скоринг.** метрики по категориям → нормировка 0..100 → взвешенный total_score (веса из конфига). Проверка: детерминированный score на фиксированном наборе findings.
*Файлы:* src/slopcheck/scoring.py, tests/test_scoring.py

**F9. Репортеры console + JSON.** rich-таблицы (категории, топ-findings, score) + JSON-дамп Report. Проверка: `slopcheck run --format console|json` на fixture даёт ожидаемый вывод.
*Файлы:* src/slopcheck/reporters/{console,json_report}.py, tests/test_reporters_basic.py

**F10. Репортер SARIF.** Report → валидный SARIF 2.1.0. Проверка: вывод проходит валидацию схемы SARIF.
*Файлы:* src/slopcheck/reporters/sarif.py, tests/test_sarif.py

**F11. Репортер Markdown-саммари.** компактный MD для GitHub Step Summary/PR-комментария. Проверка: содержит score, таблицу категорий, топ-findings.
*Файлы:* src/slopcheck/reporters/markdown.py, tests/test_markdown.py

**F12. Baseline + delta-гейт.** прогон на base ref, diff findings по стабильному ключу, exit code по регрессу. Проверка: два прогона (base без slop, head со slop) → ненулевой exit; наоборот → 0.
*Файлы:* src/slopcheck/baseline.py, tests/test_baseline.py

**F13. Dockerfile.** multi-stage образ со всеми детекторами, entrypoint slopcheck. Проверка: образ собирается, `docker run … run /src` на fixture даёт отчёт.
*Файлы:* Dockerfile, .dockerignore

**F14. GitHub Action + пример workflow.** composite action.yml (docker, upload SARIF, MD summary, delta exit) + example.yml. Проверка: на тест-PR зелёная без нового slop, красная с ним.
*Файлы:* action.yml, .github/workflows/example.yml, README-секция

**F15 (опциональная). Seam LLM-ревью.** `llm/review.py` — интерфейс + флаг `--llm-review` (off по умолчанию), в v1 stub без реального вызова (документированный шов). Проверка: без флага поведение неизменно; с флагом вызывается заглушка.
*Файлы:* src/slopcheck/llm/review.py, tests/test_llm_seam.py

---

## 5. Карта файлов (пересечения → последовательность)

- F1/F2/F3 трогают общее ядро (models, cli, runner) → строго последовательно, первыми.
- F4–F7 — каждый свой файл в `adapters/` + свои fixtures → **независимы между собой**, зависят от F3.
- F8 (scoring) зависит от модели Finding (F1), не от адаптеров → можно рано, но осмысленно после появления реальных findings.
- F9–F11 (репортеры) — свои файлы, зависят от F8 (score в выводе) → параллелятся между собой.
- F12 (delta) зависит от runner (F3) + findings → после волны адаптеров.
- F13 (docker) зависит от знания всех тулов → после F4–F7.
- F14 (action) зависит от F13 + SARIF/MD (F10/F11).
- F15 опциональна, последней.

---

## 6. Волны

**Волна 1 — каркас (последовательно):** F1 → F2 → F3. Общая земля, параллелить нельзя.

**Волна 2 — адаптеры детекторов (можно параллельно, ≤3 агента):** F4, F5, F6, F7. Независимы, каждый свой файл/fixtures.

**Волна 3 — скоринг + отчёты:** F8 → затем F9, F10, F11 (эти три параллельно).

**Волна 4 — CI-контур (последовательно):** F12 → F13 → F14.

**Волна 5 — опция (по желанию):** F15.

---

> Личный проект → git-хостинг GitHub (`github.com/Destraction`), в коммитах без Co-Authored-By. Репозиторий инициализируется в первой фиче.
