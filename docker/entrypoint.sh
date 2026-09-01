#!/bin/sh
set -e
echo "Running alembic upgrade head..."
alembic -c backend/alembic.ini upgrade head || echo "no revisions yet, skipping"
exec "$@"
