FROM ubuntu:20.04

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
        libmysqlclient-dev \
        libfreetype6 \
        libjpeg-dev \
        sqlite \
        netcat \
        telnet \
        lsb-release

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install --upgrade pip
RUN pip install -r /requirements/development.txt
RUN pip install -r /requirements/production.txt
# Uncomment this if you need the page/topic analyzer
# RUN pip install -r /requirements/analyzer.txt

# COPY ./docker-compose/local/django/entrypoint /entrypoint
# RUN chmod +x /entrypoint

COPY ./docker-compose/local/django/start /start
RUN chmod +x /start

COPY ./docker-compose/local/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./docker-compose/local/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat

# Ensure that ``python`` is in the PATH so that ``./manage.py`` works
RUN ln -s /usr/bin/python3 /usr/bin/python

# Setup the locale
RUN locale-gen en_US.UTF-8
RUN dpkg-reconfigure locales

WORKDIR /app

# ENTRYPOINT ["/entrypoint"]
