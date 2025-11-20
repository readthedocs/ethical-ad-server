FROM ubuntu:24.04

ENV DEBIAN_FRONTEND noninteractive
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV PYTHONUNBUFFERED 1

RUN apt-get -y update
RUN apt-get -y install \
        curl \
        g++ \
        git-core \
        libevent-dev \
        libpq-dev \
        libxml2-dev \
        libxslt1-dev \
        locales \
        build-essential \
        python3-pip \
        python3-dev \
        postgresql-client \
        libmysqlclient-dev \
        libfreetype6 \
        libjpeg-dev \
        sqlite \
        netcat-openbsd \
        telnet \
        lsb-release

# Install uv for fast package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy project files for dependency resolution
# uv.lock ensures reproducible builds
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync
# This installs all dependencies from uv.lock, ensuring consistency
# --frozen: Don't update the lockfile
# --no-install-project: Don't install the project itself (we'll copy source later)
# By default, installs base dependencies + dev group (for development container)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

# For production builds, you can use:
# RUN --mount=type=cache,target=/root/.cache/uv \
#     uv sync --frozen --no-install-project --no-dev --extra production --extra analyzer

COPY ./docker-compose/django/start /start
RUN chmod +x /start

COPY ./docker-compose/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./docker-compose/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat

# Ensure that ``python`` is in the PATH so that ``./manage.py`` works
RUN ln -s /usr/bin/python3 /usr/bin/python

# Load model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('multi-qa-MiniLM-L6-cos-v1', cache_folder='/tmp/sentence_transformers')"

# Setup the locale
RUN locale-gen en_US.UTF-8
RUN dpkg-reconfigure locales

WORKDIR /app
