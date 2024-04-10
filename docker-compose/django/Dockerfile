FROM ubuntu:22.04

ARG SENTENCE_TRANSFORMERS_HOME
ARG SENTENCE_TRANSFORMERS_MODEL


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
        netcat \
        telnet \
        lsb-release

# Requirements are installed here to ensure they will be cached.
# https://docs.docker.com/build/cache/#use-the-dedicated-run-cache
COPY ./requirements /requirements
RUN pip install --upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /requirements/development.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /requirements/production.txt

# Comment this if you don't need the page/topic analyzer.
# The analyzer is used to target ads better based on page content.
# Its requirements are huge and include PyTorch and other ML tools.
# If not needed, make sure to set `ADSERVER_ANALYZER_BACKEND=` (empty string)
# in your environment file `./envs/local/django`.
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /requirements/st.txt

COPY ./docker-compose/django/start /start
RUN chmod +x /start

COPY ./docker-compose/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./docker-compose/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat

# Ensure that ``python`` is in the PATH so that ``./manage.py`` works
RUN ln -s /usr/bin/python3 /usr/bin/python

# Load model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('$SENTENCE_TRANSFORMERS_MODEL', cache_folder='$SENTENCE_TRANSFORMERS_HOME', trust_remote_code=True)"

# Setup the locale
RUN locale-gen en_US.UTF-8
RUN dpkg-reconfigure locales

WORKDIR /app
