#!/bin/sh
#runs when the container starts; applies migrations and then serve the app
set -e

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Checking for a first admin account..."
python manage.py ensure_admin || echo "ensure_admin failed; continuing without creating an admin. See the message above."

PORT="${PORT:-10000}"
echo "Starting gunicorn on port ${PORT}"
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile -
