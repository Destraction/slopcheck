# slopcheck — образ со всеми детекторами.
#
# Собирать в окружении с открытой сетью (npm-registry, GitHub releases):
#   docker build -t slopcheck .
#   docker run --rm -v "$PWD":/src slopcheck run /src
#
# Node — для jscpd/knip/aislop/eslint; Go — для golangci-lint;
# Python-детекторы — из extra [detectors].

# Версии всех детекторов закреплены точно (H10): плавающий `latest`/`@4`
# менял находки между сборками, и гейт CI расходился с прошлым прогоном
# без единой правки кода. Обновление тула — отдельный коммит с прогоном
# корпуса (bench/). Любую версию можно переопределить --build-arg.
ARG GO_VERSION=1.27.4
ARG GOLANGCI_VERSION=2.15.0
ARG NODE_VERSION=20.20.2

# Go-тулчейн и golangci-lint берём из официальных образов: golangci-lint
# грузит пакеты через `go`, поэтому без тулчейна он бесполезен.
FROM golang:${GO_VERSION}-bookworm AS go
FROM golangci/golangci-lint:v${GOLANGCI_VERSION} AS golangci

FROM node:${NODE_VERSION}-bookworm-slim

ARG JSCPD_VERSION=4.3.0
ARG KNIP_VERSION=5.88.1
ARG AISLOP_VERSION=0.22.1
ARG ESLINT_VERSION=9.39.5
ARG TYPESCRIPT_VERSION=5.9.3
ARG TYPESCRIPT_ESLINT_VERSION=8.72.2
ARG ESLINT_PLUGIN_REACT_VERSION=7.37.5
ARG ESLINT_PLUGIN_REACT_HOOKS_VERSION=7.1.1
ARG ESLINT_PLUGIN_JSDOC_VERSION=65.4.8
ARG VULTURE_VERSION=2.16
ARG DEPTRY_VERSION=0.25.1
ARG INTERROGATE_VERSION=1.7.0
ARG LIZARD_VERSION=1.26.1
ARG SEMGREP_VERSION=1.185.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node-детекторы глобально. aislop распространяется npm-пакетом (не релизным
# бинарником) и на постинсталле дотягивает свои бинарники сам.
RUN npm install -g "jscpd@${JSCPD_VERSION}" "knip@${KNIP_VERSION}" "aislop@${AISLOP_VERSION}"

# ESLint с плагинами для пакетного конфига (rules/eslint.config.cjs):
# React-хуки, ключи списков, any, JSDoc экспортов.
RUN npm install -g "eslint@${ESLINT_VERSION}" "typescript@${TYPESCRIPT_VERSION}" \
        "typescript-eslint@${TYPESCRIPT_ESLINT_VERSION}" \
        "eslint-plugin-react@${ESLINT_PLUGIN_REACT_VERSION}" \
        "eslint-plugin-react-hooks@${ESLINT_PLUGIN_REACT_HOOKS_VERSION}" \
        "eslint-plugin-jsdoc@${ESLINT_PLUGIN_JSDOC_VERSION}" \
    && eslint --version

COPY --from=go /usr/local/go /usr/local/go
COPY --from=golangci /usr/bin/golangci-lint /usr/local/bin/golangci-lint
ENV PATH="/usr/local/go/bin:$PATH" \
    # Смонтированный /src принадлежит другому uid: без этого go и git
    # отказываются работать с «чужим» репозиторием.
    GOFLAGS=-buildvcs=false
RUN git config --system --add safe.directory '*' && golangci-lint --version

# Детектор AI-slop — смысл всего инструмента: если он не встал, образ
# бесполезен и молча зеленел бы гейт. Валим сборку сразу.
RUN aislop --version

# Изолированный venv для slopcheck и Python-детекторов.
# История счёта (`slopcheck trend`) — локальная: контейнер оставил бы в
# смонтированном репозитории файлы владельца root.
ENV SLOPCHECK_HISTORY=0

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[detectors]" \
        "vulture==${VULTURE_VERSION}" "deptry==${DEPTRY_VERSION}" \
        "interrogate==${INTERROGATE_VERSION}" "lizard==${LIZARD_VERSION}" \
        "semgrep==${SEMGREP_VERSION}"

WORKDIR /src
ENTRYPOINT ["slopcheck"]
CMD ["run", "/src"]
