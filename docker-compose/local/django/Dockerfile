FROM python:3.6-alpine

ENV PYTHONUNBUFFERED 1

RUN apk update \
  # psycopg2 dependencies
  && apk add --virtual build-deps gcc python3-dev musl-dev \
  && apk add postgresql-dev \
  # Pillow dependencies
  && apk add jpeg-dev zlib-dev freetype-dev lcms2-dev openjpeg-dev tiff-dev tk-dev tcl-dev \
  # CFFI dependencies
  && apk add libffi-dev py-cffi \
  # Translations dependencies
  && apk add gettext \
  # https://docs.djangoproject.com/en/dev/ref/django-admin/#dbshell
  && apk add postgresql-client

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install -r /requirements/development.txt
RUN pip install -r /requirements/production.txt

COPY ./docker-compose/production/django/entrypoint /entrypoint
RUN chmod +x /entrypoint

COPY ./docker-compose/local/django/start /start
RUN chmod +x /start

COPY ./docker-compose/local/django/celery/worker/start /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./docker-compose/local/django/celery/beat/start /start-celerybeat
RUN chmod +x /start-celerybeat

WORKDIR /app

ENTRYPOINT ["/entrypoint"]
