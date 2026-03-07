# Production Dockerfile for EthicalAds (AWS ECS Fargate deployment)
#
# Build:
#   docker build -t ethicalads .
#
# Run locally:
#   docker run -p 5000:5000 --env-file .envs/local/django ethicalads

FROM ubuntu:24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV PYTHONUNBUFFERED=1

# uv environment variables
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/.venv

RUN apt-get -y update && apt-get -y install --no-install-recommends \
        curl \
        g++ \
        git-core \
        libevent-dev \
        libpq-dev \
        libxml2-dev \
        libxslt1-dev \
        locales \
        build-essential \
        libfreetype6 \
        libjpeg-dev \
        netcat-openbsd \
        lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Setup the locale
RUN locale-gen en_US.UTF-8 && dpkg-reconfigure locales

# Install uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

# ---------------------------------------------------------------------------
# Dependencies layer (cached unless pyproject.toml or uv.lock change)
# ---------------------------------------------------------------------------
FROM base AS deps

WORKDIR /build
COPY pyproject.toml uv.lock ./

RUN uv python install

# Install production + analyzer dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra production --extra analyzer

# ---------------------------------------------------------------------------
# Application layer
# ---------------------------------------------------------------------------
FROM base AS app

# Copy the virtual environment from deps stage
COPY --from=deps /.venv /.venv
COPY --from=deps /root/.local /root/.local

# Copy the application code
WORKDIR /app
COPY . .

# Collect static files (whitenoise serves them)
RUN DJANGO_SETTINGS_MODULE=config.settings.testing \
    DJANGO_SETTINGS_SKIP_LOCAL=True \
    /.venv/bin/python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 5000

# Default command: run Django via Gunicorn with New Relic
CMD ["/.venv/bin/newrelic-admin", "run-program", \
     "/.venv/bin/gunicorn", "config.wsgi", \
     "--bind", "0.0.0.0:5000", \
     "--max-requests=10000", \
     "--log-file", "-"]
