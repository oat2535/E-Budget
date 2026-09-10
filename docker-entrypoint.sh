#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn ebudget.wsgi:application --bind 0.0.0.0:8000 \
    --workers 3 --worker-class gthread --threads 4 \
    --timeout 60 --graceful-timeout 30
