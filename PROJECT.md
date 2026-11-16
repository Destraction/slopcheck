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
| Мёртвый код + зависимости | knip; vulture; deptry; golangci-lint; eslint | JS/TS; Python; Go; JS/TS |
| Комментарии + доки | aislop; interrogate; golangci-lint (revive exported); eslint (jsdoc) | мультиязык; Python; Go; JS/TS |
| Сложность | lizard; semgrep-смеллы; golangci-lint; eslint (React-хуки, any) | мультиязык; Python/JS/TS/Go; Go; JS/TS |

golangci-lint и eslint — мультикатегорийные: один прогон даёт находки трёх
категорий (атрибут адаптера `measures`), раскладка — по линтеру/правилу.
Наборы правил лежат в пакете (`rules/golangci.yml`, `rules/eslint.config.cjs`).

**Решения по Go/React (16.11.2026, мои):**
- Go — golangci-lint v2, а не отдельные staticcheck/revive/errcheck: один бинарник,
  один JSON. Код не компилируется → находка typecheck → сбой детектора
  (категории непроверены), а не «чисто».
- golangci-lint и knip запускаются в каждом модуле/проекте (`go.mod`,
  верхнеуровневый `package.json`): раскладка «Go в корне + фронт в `web/`».
  Нет `package.json` → knip проверять нечего (как deptry); нет `go.mod` → сбой.
- ESLint с пакетным конфигом, конфиг проекта не читается. Плагины — глобальный
  npm (путь через `SLOPCHECK_NODE_MODULES`/`npm root -g`), `basePath` — корень
  репозитория, иначе ESLint 9 пропускает файлы вне каталога конфига.
  `eslint-disable` чужих правил и ошибки парсинга — не находки.

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

---

# v3 — калибровка, хук агента, слепые зоны ИИ-кода (эпик от 16.11.2026)

## Журнал решений

- 16.11.2026, пользователь: корпус для калибровки — живые OSS-репозитории (Go, React), подбирает Claude; закреплены на коммите, клонируются скриптом, в репо slopcheck не кладутся.
- 16.11.2026, пользователь: хук Claude Code — глобально (`~/.claude/settings.json`), срабатывает только в репозиториях с `.slopcheck.yml`.
- 16.11.2026, пользователь: хук возвращает новые находки (warn+, относительно HEAD) агенту на починку в том же ходе; без зацикливания.
- 16.11.2026, пользователь: проверка несуществующих пакетов ходит в сеть только по флагу `--check-deps` / полю конфига; в шаблоне CI флаг включён; нет сети — проверка помечается пропущенной.
- 16.11.2026, пользователь: план v3 (G1–G10, 5 волн) утверждён.

## Резюме

Три направления, одна цель: доверять отчёту slopcheck на Go/React и ловить slop в момент написания, а не в CI.

1. **Калибровка.** Корпус OSS-репозиториев, разметка находок «польза/шум», чистка шумных правил, регрессионные тесты на шум.
2. **Хук агента.** После хода Claude Code slopcheck проверяет изменённые файлы. Новые находки относительно HEAD возвращаются агенту на починку. Плюс pre-commit.
3. **Слепые зоны ИИ-кода.** Несуществующие пакеты, правила TS с типами, пересказывающие комментарии в Go/TSX, лишняя защитность и абстракции.

**Критерии готовности (DoD):**
- `uv run python bench/run.py` прогоняет корпус и печатает долю шума по правилам. На корпусе шум среди находок уровня warn и выше не больше 20%. Каждое правило с шумом выше 50% выключено или переписано.
- Каждый подтверждённый тип ложного срабатывания закреплён тестом в `tests/noise/`.
- В репозитории с `.slopcheck.yml`: агент добавил пустой `catch` → Stop-хук возвращает находку, агент её чинит. Старый долг в тех же файлах хук не трогает. Повторного блока нет (`stop_hook_active`). Без `.slopcheck.yml` хук молчит.
- `pre-commit` с `.pre-commit-hooks.yaml` slopcheck валит коммит, добавивший slop.
- `--check-deps`: импорт несуществующего npm-, Go- или PyPI-пакета даёт ERROR. Без флага сетевых запросов нет. Нет сети → проверка пропущена с пометкой.
- Новые детекторы (TS с типами, комментарии, защитность) откалиброваны на корпусе по тому же порогу.
- Тесты зелёные, гейт slopcheck на себе зелёный, CI зелёный.

**Не входит:** HTML-дашборд, автофикс в CI, inline-комментарии в PR (отдельный эпик), LLM-детекторы.

## Структура (новое и меняемое)

```
bench/                      # dev-инструмент калибровки, в пакет не входит
  corpus.yml                # репо: url, commit, языки, подкаталог
  run.py                    # клон в ~/.cache/slopcheck-bench → прогон → findings/*.json → таблица шума
  labels/<repo>.yml         # разметка: ключ находки → useful|noise + причина
  README.md                 # как пополнять корпус и размечать
tests/noise/                # фикстуры подтверждённых ложных срабатываний + тесты «находки нет»
src/slopcheck/
  agent_check.py            # дельта рабочего дерева против HEAD (для хука и pre-commit)
  hooks/claude_stop.py      # Stop-хук: stdin JSON → проверка → exit 2 + находки в stderr
  adapters/depsexist.py     # несуществующие пакеты (npm, Go proxy, PyPI), кэш ответов
  adapters/comments_heur.py # пересказывающие комментарии Go/TSX (детерминированная эвристика)
  adapters/goiface.py       # Go-интерфейс с единственной реализацией в модуле
  rules/eslint.typed.cjs    # правила TS с типами (при tsconfig + node_modules)
  rules/smells.yml          # + useMemo/useCallback на тривиальном, except-raise в Python
  cli.py                    # check-changed, hook claude, install-hook, --check-deps
  config.py                 # check_deps, ignore_rules (общий), hook_severity
.pre-commit-hooks.yaml
```

## Архитектура и решения

- **Дельта для хука (`agent_check`).** Изменённые файлы = staged + unstaged + untracked относительно HEAD. Базой служит временный `git worktree` на HEAD, прогон по тому же списку файлов. Новые находки ищет существующий `diff_findings`. В отчёт идут находки не ниже `hook_severity` (по умолчанию warn). Детекторы по всему проекту (knip, deptry) в хуке пропускаются, как в `--changed`. На первом коммите (HEAD нет) база пустая.
- **Stop-хук.** Команда `slopcheck hook claude` читает JSON хука. Нет `.slopcheck.yml` в git-корне `cwd` или `stop_hook_active=true` → exit 0. Есть новые находки → exit 2, в stderr компактный список `файл:строка правило — сообщение` с указанием починить. Таймаут 120 с; по таймауту хук не блокирует ход и пишет об этом. Установка: `slopcheck install-hook claude` добавляет запись в `~/.claude/settings.json` идемпотентно, с бэкапом. Сделать это на вашей машине — отдельный шаг с подтверждением.
- **pre-commit.** `.pre-commit-hooks.yaml` (id `slopcheck`, `slopcheck check-changed --staged`) и `slopcheck install-hook git` для тех, у кого нет фреймворка pre-commit.
- **Несуществующие пакеты.** Собираются заявленные в манифестах (package.json, go.mod, requirements/pyproject) и импортируемые не-относительные модули. Для каждого — запрос `registry.npmjs.org/<name>`, `proxy.golang.org/<module>/@v/list`, `pypi.org/pypi/<name>/json`. 404 → ERROR (категория dead_code, как у deptry). Пропускаются: workspace-пакеты, алиасы путей из tsconfig, stdlib Go/Node/Python, приватные скоупы из конфига. Ответы кэшируются в `~/.cache/slopcheck/registry.json` (TTL 7 дней). Сетевые ошибки → детектор пропущен, а не «пакет не найден».
- **TS с типами.** Второй прогон ESLint с `parserOptions.projectService` и правилами `no-floating-promises`, `no-misused-promises`, `await-thenable`, `no-unnecessary-type-assertion`. Включается только при `tsconfig.json` и установленном `node_modules`: без них типы превращаются в `any`, и правила врут. Иначе пометка «пропущено: нет node_modules», категория остаётся измеренной базовым ESLint.
- **Пересказывающие комментарии.** Однострочный комментарий над строкой кода считается находкой (WARN, категория comments), если после нормализации (camelCase → слова, стоп-слова, стемминг by-suffix) не меньше 70% его слов есть в идентификаторах следующей строки. Пример: `// Fetch the data` над `fetchData()`. Doc-комментарии экспортов и директивы (`//go:`, `// eslint-`, `@ts-`) не трогаем.
- **Защитность и абстракции:**
  - Go-интерфейс, у которого в модуле ровно одна реализация и который не экспортируется из библиотечного пакета. Эвристика по множествам методов через парсинг Go-исходников регулярками. Уровень info, выживает только если пройдёт калибровку.
  - `useMemo`/`useCallback` вокруг литерала или простого чтения поля (semgrep), уровень info.
  - `except ...: raise` без изменений (semgrep, Python). JS-аналог уже покрыт `no-useless-catch`.
- **Общий `ignore_rules`** в конфиге вместо одного `aislop_ignore_rules` (старое поле остаётся алиасом). Нужен калибровке, чтобы выключать шумные правила без правки кода.
- **Корпус.** 6 репозиториев: 3 Go (сервис, CLI, библиотека) и 3 React (Vite SPA, Next.js, библиотека компонентов). Средний размер, активная поддержка, разные стили. Конкретные репо и коммиты выбираются в G1 и фиксируются в `corpus.yml`. Разметка: до 15 находок на правило в каждом репо, причина — одной строкой.

## Список фич

- [x] **G1. Бенч-каркас.** `bench/corpus.yml`, `bench/run.py`, формат разметки, отчёт «правило → находок / размечено / доля шума». Проверка: прогон на корпусе печатает таблицу; повторный прогон по кэшу клонов работает без сети. Файлы: `bench/*`. Зависит: —.
- [x] **G2. Общий `ignore_rules` + `hook_severity` в конфиге.** Проверка: правило из `ignore_rules` исчезает из находок любого адаптера; старое `aislop_ignore_rules` работает. Файлы: `config.py`, `runner.py`, README. Зависит: —.
- [x] **G3. Дельта рабочего дерева против HEAD.** `agent_check.py` и `slopcheck check-changed [--staged]`. Проверка: репо с долгом в файле плюс новая находка в том же файле → выводится только новая; untracked-файл учитывается; без HEAD база пустая. Файлы: `agent_check.py`, `gitchanged.py`, `cli.py`. Зависит: G2.
- [x] **G4. Stop-хук Claude Code и pre-commit.** `slopcheck hook claude`, `install-hook claude|git`, `.pre-commit-hooks.yaml`. Проверка: тесты на JSON хука (нет конфига, `stop_hook_active`, есть находки → exit 2), идемпотентность установки, живой прогон pre-commit. Файлы: `hooks/`, `cli.py`, README, GUIDE. Зависит: G3.
- [ ] **G5. Несуществующие пакеты (`--check-deps`).** Проверка: фикстуры манифестов и импортов, сеть замокана (404 → ERROR, 200 → чисто, сетевая ошибка → skip); живой тест под маркером `network`; без флага ни одного запроса. Файлы: `adapters/depsexist.py`, `cli.py`, `config.py`, consumer-workflow. Зависит: G2.
- [ ] **G6. ESLint-правила TS с типами.** Проверка: фикстура с `node_modules` и промисом без `await` → находка; без `node_modules` → пометка о пропуске. Файлы: `adapters/eslint.py`, `rules/eslint.typed.cjs`, Dockerfile (не нужен). Зависит: —.
- [ ] **G7. Пересказывающие комментарии Go/TSX.** Проверка: таблица позитивных и негативных примеров (`// Fetch the data` над `fetchData()` → находка; `// retry: API отдаёт 502 при холодном старте` → нет). Файлы: `adapters/comments_heur.py`. Зависит: —.
- [ ] **G8. Защитность и абстракции.** Go-интерфейс с одной реализацией, тривиальные `useMemo`/`useCallback`, `except: raise`. Проверка: позитивные и негативные фикстуры на каждое. Файлы: `adapters/goiface.py`, `rules/smells.yml`. Зависит: —.
- [ ] **G9. Калибровка и чистка шума.** Прогон корпуса, разметка, правки правил и дефолтов, `tests/noise/`. Достижение порога из DoD. Таблица «до → после» в `bench/README.md`. Файлы: правила, конфиги, `config.py` (дефолты), `tests/noise/`, `bench/labels/`. Зависит: G1, G2, G5–G8.
- [ ] **G10. Установка хука у вас.** `slopcheck install-hook claude` в `~/.claude/settings.json`, проверка на реальном ходе агента. Только после вашего подтверждения. Зависит: G4, G9.

## Карта файлов

- `config.py`: G2, G5, G9 → последовательно (G2 первым).
- `cli.py`: G3, G4, G5 → последовательно.
- `adapters/eslint.py`: только G6. `rules/smells.yml`: только G8. `bench/`: G1, G9.
- G6, G7, G8 не пересекаются друг с другом и с G3–G5 (кроме `adapters/__init__.py`, где одна строка регистрации — конфликт тривиальный).

## Волны

1. **Волна 1:** G1 и G2 (независимы, можно параллельно).
2. **Волна 2:** G3 → G4 (хук, последовательно).
3. **Волна 3:** G5, G6, G7, G8 (независимы, можно параллельно, не больше 3 агентов одновременно).
4. **Волна 4:** G9 (калибровка всего, включая новые детекторы).
5. **Волна 5:** G10 (установка хука у вас, с подтверждением).
