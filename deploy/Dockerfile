FROM ubuntu:18.04
MAINTAINER Read the Docs <support@readthedocs.org>

ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \
    python3-pip \
    postgresql-client

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip3 install --no-cache-dir -r /requirements/production.txt && rm -rf /requirements

# Copy explicitly rather than "."
# This protects private files from leaking into the build
COPY ./adserver /app/adserver
COPY ./config /app/config
COPY ./templates /app/templates
COPY ./assets /app/assets
COPY ./manage.py /app
COPY ./package.json /app

# Run the Ad Server as the user "adserver"
RUN addgroup --system adserver
RUN adduser --system --ingroup adserver adserver
RUN chown -R adserver /app

COPY ./deploy/start.sh /adserver
RUN chmod +x /adserver
RUN chown adserver /adserver

USER adserver
WORKDIR /app

EXPOSE 5000

CMD ["/adserver"]
