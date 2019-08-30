#!/bin/sh

# Start celery
celery -A adserver worker -l INFO
