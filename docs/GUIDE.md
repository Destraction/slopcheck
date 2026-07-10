# slopcheck — подробный гайд

Гайд в двух частях: **для новичка** (что это и как этим пользоваться, не зная деталей)
и **для владельца** (как всё устроено внутри, как чинить и развивать).

---

## Часть 1. Для новичка

### Что это такое

slopcheck — «привратник качества» кода. Это конвейер на GitHub:

1. Ты пушишь код или открываешь Pull Request.
2. GitHub Actions автоматически запускает проверку slopcheck.
3. Инструмент ищет в коде **slop** — халтуру: дублирование, мёртвый код,
   переусложнённые функции, закомментированный код, типовые «запахи».
4. Если ты **добавил новый** slop относительно базовой версии — проверка падает
   (красный крест ✗ на коммите/PR). Если нового slop нет — зелёная галочка ✓.

Ключевое слово — **новый**. Это delta-гейт: старые грехи репозитория тебя не валят,
валит только то, что ты сам только что внёс. Поэтому slopcheck можно ставить
в любой, даже очень запущенный репозиторий — он не потребует «сначала почини всё».

### Что проверяется (детекторы)

| Детектор      | Что ловит                                                        |
|---------------|------------------------------------------------------------------|
| `duplication` | скопипащенные блоки кода (одинаковые фрагменты в разных местах)  |
| `deadcode`    | мёртвый код: неиспользуемые функции, переменные, импорты         |
| `complexity`  | переусложнённые функции (слишком длинные/ветвистые)              |
| `comments`    | закомментированный код, мусорные комментарии                     |
| `smells`      | типовые «запахи» по правилам из `src/slopcheck/rules/smells.yml` |

Плюс опционально **LLM-ревью** (`--llm-review`) — код смотрит Gemini и находит то,
что регулярками не поймать. Если ключа/квоты нет, LLM-часть тихо пропускается,
детекторы работают без неё.

### Как поставить slopcheck в репозиторий

**Новый репозиторий — одна команда:**

```bash
ghnew my-project
```

Она создаст приватный репо на GitHub, склонирует его, положит workflow,
поставит секрет и сделает первый коммит. Всё, гейт работает.

**Существующий репозиторий:**

```bash
cd path/to/repo
slopcheck-init
git add .github/workflows/slopcheck.yml
git commit -m "ci: add slopcheck quality gate"
git push
```

**Через веб-интерфейс GitHub:** создать репозиторий из шаблона
`Destraction/slopcheck-ci-template` кнопкой «Use this template»
(секрет `GHCR_PULL_TOKEN` потом всё равно поставить: `gh secret set GHCR_PULL_TOKEN`).

`ghnew` и `slopcheck-init` — shell-функции из `~/.zshrc` (блок `slopcheck scaffold`).

### Что делать, когда проверка красная

Красный крест — это не «CI сломался», это найден конкретный новый slop. Порядок:

1. **Прочитай, что именно нашлось.** Три способа:
   - Страница запуска Actions → **Summary** — там markdown-отчёт со всеми находками.
   - Лог шага **Delta gate**: `gh run view <run-id> --log`, формат строк —
     `детектор файл:строка — описание`.
   - Артефакт `slopcheck-sarif` — машиночитаемый отчёт (скачивается со страницы запуска).
2. **Почини именно указанное место** (вынеси дубль в функцию, удали мёртвый код и т.д.).
3. Закоммить, запушь, дождись зелёной галочки.
4. Мержить можно **только зелёное**. Красный крест физически мерж не блокирует
   (см. ограничения ниже), поэтому это вопрос дисциплины.

### Как прогнать проверку локально, до пуша

```bash
# через докер-образ (так же, как в CI):
docker run --rm -v "$PWD:/src" ghcr.io/destraction/slopcheck:latest run /src

# из репозитория slopcheck (нужен Python + зависимости):
python -m slopcheck run путь/к/репо

# с LLM-ревью (нужен gemini cli / ключ):
python -m slopcheck run путь/к/репо --llm-review

# полный гейт против базовой версии, как в CI:
docker run --rm -v "$PWD:/src" ghcr.io/destraction/slopcheck:latest run /src --format json > base.json   # на базовом коммите
docker run --rm -v "$PWD/base.json:/base/base.json:ro" -v "$PWD:/src" ghcr.io/destraction/slopcheck:latest gate /src --baseline /base/base.json
```

---

## Часть 2. Для владельца — как всё устроено

### Общая архитектура

```
Destraction/slopcheck  (этот репозиторий)
├── src/slopcheck/            # сам инструмент (Python)
├── Dockerfile                # образ с инструментом
├── .github/workflows/
│   └── publish-image.yml     # пуш в master → сборка → ghcr.io/destraction/slopcheck
├── consumer/
│   ├── README.md             # инструкция для потребителей
│   └── workflows/slopcheck.yml   # ЭТАЛОННЫЙ consumer-workflow (его тянет slopcheck-init)
└── docs/GUIDE.md             # этот файл

Destraction/slopcheck-ci-template   # template-репо для создания через веб
Любой consumer-репо                 # получает копию consumer/workflows/slopcheck.yml
```

Потребители **не собирают** образ — тянут готовый `ghcr.io/destraction/slopcheck:latest`.
Образ пересобирается workflow'ом `publish-image` при пуше в master, если менялись
`src/**`, `Dockerfile`, `pyproject.toml` или сам workflow. Теги: `:latest` + `:<sha>`.
Concurrency без cancel — параллельные пуши собираются по очереди, каждый sha-тег публикуется.

### Устройство инструмента (src/slopcheck)

- `cli.py` — команды: `run` (отчёт), `gate` (delta-гейт против baseline),
  `init-config` и пр.
- `adapters/` — детекторы: `duplication`, `deadcode`, `complexity`, `comments`, `smells`.
- `rules/smells.yml` — декларативные правила «запахов».
- `reporters/` — форматы вывода: `console`, `json`, `md` (markdown), `sarif`.
- `baseline.py` + `gate` — сравнение находок с baseline: падаем только на новых.
- `scoring.py` — веса/скоринг находок.
- `llm/` — LLM-ревью: `gemini.py` (класс `GeminiReviewer`, через gemini cli),
  `review.py`. Нет ключа/квоты → ревью молча пропускается.
- `tests/` — pytest.

### Consumer-workflow: как работает гейт в чужом репо

Файл `consumer/workflows/slopcheck.yml`, шаги:

1. **Checkout** с `fetch-depth: 0` (нужна история для baseline).
2. **Log in to GHCR** — `secrets.GHCR_PULL_TOKEN || secrets.GITHUB_TOKEN`
   (пакет приватный, чужой `GITHUB_TOKEN` его не тянет — см. ниже).
3. **Pull slopcheck image**.
4. **Resolve baseline**: для PR — `github.event.pull_request.base.sha`,
   для push — `github.event.before`. Если базы нет (новая ветка, первый пуш,
   нулевой SHA `0000…`) — гейт пропускается, только отчёт.
5. **Baseline report**: `git worktree add ../base <sha>` → `run /src --format json`.
6. **Report**: SARIF в артефакт + markdown в `$GITHUB_STEP_SUMMARY`.
7. **Upload SARIF to Code Scanning** — с `continue-on-error: true` (см. ограничения).
8. **Delta gate**: `gate /src --baseline /base/base.json` — красный, если есть новые находки.

Триггеры: `pull_request` и `push` в `master`/`main`. Concurrency с
`cancel-in-progress: true` — новый пуш в ветку отменяет старый прогон.

### Раскатка: ghnew / slopcheck-init / секрет

Функции в `~/.zshrc` (блок между `>>> slopcheck scaffold >>>` и `<<< slopcheck scaffold <<<`):

- `slopcheck-init` — качает свежий workflow прямо из
  `Destraction/slopcheck/consumer/workflows/slopcheck.yml` через
  `gh api … -H "Accept: application/vnd.github.raw"`, кладёт в `.github/workflows/`,
  затем ставит секрет `GHCR_PULL_TOKEN` из macOS Keychain.
- `ghnew <имя> [флаги]` — `gh repo create --private --clone` + `slopcheck-init`
  + коммит `ci: add slopcheck quality gate` + пуш в `master`.

**Секрет `GHCR_PULL_TOKEN`:** пакет `slopcheck` в GHCR приватный; `GITHUB_TOKEN`
consumer-репозитория к нему доступа не имеет. Поэтому используется PAT (classic)
со scope `read:packages`, который хранится в macOS Keychain:

```bash
# положить/обновить PAT в Keychain:
security add-generic-password -s slopcheck-ghcr-pull -a ghcr -w <PAT>
# прочитать:
security find-generic-password -s slopcheck-ghcr-pull -w
# поставить в конкретный репо вручную:
gh secret set GHCR_PULL_TOKEN --body "$(security find-generic-password -s slopcheck-ghcr-pull -w)"
```

Если пакет когда-нибудь станет public — секрет не нужен, workflow сам
откатится на `GITHUB_TOKEN` (fallback уже зашит).

### Известные ограничения и грабли

- **Мерж не блокируется физически.** Аккаунт `Destraction` — User на Free-плане:
  rulesets / branch protection на **приватных** репо дают 403 «Upgrade to GitHub Pro».
  Осознанное решение — живём без ruleset, гейт информационный (красный крест),
  дисциплина «не мержить красное» — ручная. Если появится Pro или репо станет
  публичным: обязательный чек — контекст `slopcheck` (имя job).
- **Code Scanning (инлайн-аннотации SARIF в диффе PR)** требует Advanced Security
  на приватных репо. Шаг upload-sarif стоит с `continue-on-error` — его warning
  в логах не ошибка, отчёт всё равно есть в Summary и артефакте.
- **Первый пуш в новую ветку** не гейтится (нет базы) — это by design, гейт
  сработает на PR.
- **CodeQL upload deprecation warnings** в логах consumer-репо — от
  `github/codeql-action/upload-sarif@v3`, на работу гейта не влияют.

### Проверка боем (проведена)

Демо на `Destraction/praktika`: в ветке `demo/sloppy-code` был создан файл
`apps/web/src/lib/discount-utils.ts` с намеренно скопипащенными функциями скидок.
PR #1 → slopcheck красный, **3 находки duplication** с точными файл:строка.
Гейт отработал верно; PR закрыт, ветка удалена, `main` чист.

### Типовые операции владельца

```bash
# пересобрать/опубликовать образ вручную:
gh workflow run publish-image -R Destraction/slopcheck

# тесты инструмента:
cd ~/Projects/slopcheck && python -m pytest -q

# посмотреть последний прогон гейта в consumer-репо:
gh run list -R Destraction/<repo> --workflow slopcheck -L 5
gh run view <run-id> -R Destraction/<repo> --log

# обновить workflow во всех consumer-репо после правки эталона:
# (в каждом клоне) slopcheck-init && git add .github && git commit -m "ci: update slopcheck" && git push
```
