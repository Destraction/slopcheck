# slopcheck — образ со всеми детекторами.
#
# Собирать в окружении с открытой сетью (npm-registry, GitHub releases):
#   docker build -t slopcheck .
#   docker run --rm -v "$PWD":/src slopcheck run /src
#
# Node — для jscpd/knip/aislop/eslint; Go — для golangci-lint;
# Python-детекторы — из extra [detectors].

# Go-тулчейн и golangci-lint берём из официальных образов: golangci-lint
# грузит пакеты через `go`, поэтому без тулчейна он бесполезен.
FROM golang:1.27-bookworm AS go
FROM golangci/golangci-lint:v2.15.0 AS golangci

FROM node:20-bookworm-slim

# Версия aislop (переопределяется --build-arg для пина).
ARG AISLOP_VERSION=latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node-детекторы глобально. aislop распространяется npm-пакетом (не релизным
# бинарником) и на постинсталле дотягивает свои бинарники сам.
RUN npm install -g jscpd@4 knip@5 "aislop@${AISLOP_VERSION}"

# ESLint с плагинами для пакетного конфига (rules/eslint.config.cjs):
# React-хуки, ключи списков, any, JSDoc экспортов.
RUN npm install -g eslint@9 typescript@5 typescript-eslint@8 \
        eslint-plugin-react@7 eslint-plugin-react-hooks@7 eslint-plugin-jsdoc@65 \
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
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[detectors]"

WORKDIR /src
ENTRYPOINT ["slopcheck"]
CMD ["run", "/src"]
