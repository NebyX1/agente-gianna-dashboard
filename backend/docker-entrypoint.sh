#!/bin/sh
set -eu
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    flask --app wsgi db upgrade
fi
exec gunicorn --config gunicorn.conf.py wsgi:app
