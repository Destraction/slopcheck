# slopcheck — образ со всеми детекторами.
#
# Собирать в окружении с открытой сетью (npm-registry, GitHub releases):
#   docker build -t slopcheck .
#   docker run --rm -v "$PWD":/src slopcheck run /src
#
# Node — для jscpd/knip/aislop; Python-детекторы — из extra [detectors].

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
