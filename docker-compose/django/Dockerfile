FROM ubuntu:24.04

ENV DEBIAN_FRONTEND noninteractive
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV PYTHONUNBUFFERED 1

# uv environment variables
# Copy (don't hardlink) files into /.venv. Avoid issues with Docker's FS
# https://docs.astral.sh/uv/reference/environment/
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_PROJECT_ENVIRONMENT=/.venv

# Pep668 prevents pip from modifying system packages
# https://peps.python.org/pep-0668/
ENV PIP_BREAK_SYSTEM_PACKAGES=1

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
        sqlite3 \
        netcat-openbsd \
        telnet \
        lsb-release

# Install uv for fast package management
# https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

# Copy project files for dependency resolution
# uv.lock ensures reproducible builds
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync
# This creates a virtual environment at /.venv (not in /app)
# This installs all dependencies from uv.lock, ensuring consistency
# --frozen: Don't update the lockfile
# --no-install-project: Don't install the project itself
# If you do not want the analyzer dependencies (which are LARGE), you can use:
#  RUN --mount=type=cache,target=/root/.cache/uv \
#      uv sync --frozen --no-install-project --extra dev --extra production
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-extras

COPY ./docker-compose/django/start /start
RUN chmod +x /start

# Launch a shell within the container with this script
COPY ./docker-compose/django/shell /shell
RUN chmod +x /shell

COPY ./docker-compose/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./docker-compose/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat

# Load model
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('multi-qa-MiniLM-L6-cos-v1', cache_folder='/tmp/sentence_transformers')"

# Setup the locale
RUN locale-gen en_US.UTF-8
RUN dpkg-reconfigure locales

WORKDIR /app
