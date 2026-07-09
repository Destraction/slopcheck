# slopcheck — образ со всеми детекторами.
#
# Собирать в окружении с открытой сетью (npm-registry, GitHub releases):
#   docker build -t slopcheck .
#   docker run --rm -v "$PWD":/src slopcheck run /src
#
# Node — для jscpd/knip; Python-детекторы — из extra [detectors];
# aislop (бинарник) ставится best-effort и при недоступности просто пропускается
# адаптером (graceful skip).

FROM node:20-bookworm-slim

# Версия aislop для загрузки бинарника (переопределяется --build-arg).
ARG AISLOP_VERSION=latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node-детекторы глобально.
RUN npm install -g jscpd@4 knip@5

# aislop: best-effort загрузка релизного бинарника (сборку не валит).
RUN set -eux; \
    arch="$(uname -m)"; \
    url="https://github.com/scanaislop/aislop/releases/download/${AISLOP_VERSION}/aislop-${arch}-unknown-linux-gnu"; \
    (curl -fsSL "$url" -o /usr/local/bin/aislop && chmod +x /usr/local/bin/aislop) \
        || echo "aislop не установлен — адаптер будет пропущен";

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
