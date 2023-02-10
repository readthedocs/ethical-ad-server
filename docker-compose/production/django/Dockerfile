# Production Docker setup
#
# This Dockerfile is not currently used or maintained
# but may be useful in setting up your own adserver instance.

FROM ubuntu:20.04
MAINTAINER Read the Docs, Inc. <support@readthedocs.org>

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

# Install Node v14
RUN curl -sL https://deb.nodesource.com/setup_14.x | bash -
RUN apt-get -y install nodejs

RUN addgroup django && useradd -g django django

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
# Uncomment this if you need the page/topic analyzer
# RUN pip install --no-cache-dir -r /requirements/analyzer.txt
RUN pip install --no-cache-dir -r /requirements/production.txt \
    && rm -rf /requirements

# Install node dependencies
RUN npm install

COPY ./docker-compose/production/django/start /start
RUN chmod +x /start
RUN chown django /start

COPY ./docker-compose/production/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker
RUN chown django /start-celeryworker

COPY ./docker-compose/production/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat
RUN chown django /start-celerybeat

# Explicitly copy files/directories so no configuration/data/secrets get copied
COPY ./adserver /app/adserver
COPY ./assets /app/assets
COPY ./config /app/config
COPY ./geoip /app/geoip
COPY ./templates /app/templates
COPY ./manage.py /app
COPY ./newrelic.ini /app
COPY ./package.json /app
COPY ./package-lock.json /app
COPY ./webpack.config.js /app

# Uncomment if you require Azure's container SSH setup
# Allow Azure to SSH into the running container
# Although the root password is known, port 2222 is inaccessible from the internet
# https://docs.microsoft.com/en-us/azure/app-service/containers/configure-custom-container#enable-ssh
# RUN apk add openssh && echo "root:Docker!" | chpasswd
# COPY ./docker-compose/production/django/sshd_config /etc/ssh/

RUN chown -R django:django /app
USER django

WORKDIR /app

EXPOSE 2222 5000

CMD ["/start"]
