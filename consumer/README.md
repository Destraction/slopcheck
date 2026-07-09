# slopcheck в любом репозитории

`workflows/slopcheck.yml` — привратник качества, который тянет готовый образ
`ghcr.io/destraction/slopcheck` и гоняет delta-гейт (валит PR/push только за
**добавленный** slop). Локальная сборка не нужна.

## Как поставить в репозиторий

**Автоматически при создании нового репо:**
```bash
ghnew my-project          # создаёт репо + кладёт workflow + первый коммит
```

**В существующий репозиторий:**
```bash
cd path/to/repo
slopcheck-init            # копирует workflow в .github/workflows/
git add .github && git commit -m "ci: add slopcheck gate"
```

`ghnew` и `slopcheck-init` — функции из `~/.zshrc` (устанавливаются один раз).

**Через веб (GitHub):** создать репозиторий из шаблона `Destraction/slopcheck-ci-template`
кнопкой «Use this template».

## Предпосылки

- Образ опубликован в GHCR (workflow `publish-image` в репозитории slopcheck).
- Пакет `slopcheck` в GHCR доступен репозиторию: проще всего сделать его
  **public** один раз (Packages → slopcheck → Package settings → Change visibility),
  иначе для приватных потребителей нужно выдать доступ в настройках пакета.
