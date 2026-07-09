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
- Пакет `slopcheck` в GHCR **приватный**. Доступ потребителям выдаётся через
  секрет `GHCR_PULL_TOKEN` — PAT (classic) со scope `read:packages`:
  1. Создать PAT один раз: https://github.com/settings/tokens/new?scopes=read:packages&description=slopcheck-ghcr-pull
  2. Положить в Keychain:
     `security add-generic-password -s slopcheck-ghcr-pull -a ghcr -w <PAT>`
  3. Дальше `slopcheck-init` / `ghnew` ставят секрет в каждый репозиторий сами.
- Workflow логинится как `secrets.GHCR_PULL_TOKEN || secrets.GITHUB_TOKEN`,
  поэтому если пакет когда-нибудь станет public — всё продолжит работать и без секрета.
- **Внимание:** при создании репо веб-кнопкой «Use this template» секреты не
  копируются — в таком репо нужно один раз выполнить:
  `gh secret set GHCR_PULL_TOKEN --body "$(security find-generic-password -s slopcheck-ghcr-pull -w)"`.
