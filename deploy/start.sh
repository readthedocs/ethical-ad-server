#!/bin/sh

# Collect static files using appropriate Django settings
python3 /app/manage.py collectstatic --no-input

# Run any outstanding migrations
python3 /app/manage.py migrate

# Start the app listening on port 5000
/usr/local/bin/gunicorn config.wsgi --bind 0.0.0.0:5000 --chdir=/app
