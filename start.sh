#!/bin/bash
set -euo pipefail

: "${REPORTERV2_DATA:?REPORTERV2_DATA must be set}"
: "${REPORTERV2_HOST:?REPORTERV2_HOST must be set}"

mkdir -p "$REPORTERV2_DATA"
rm -f "$REPORTERV2_DATA/index.db"

echo "[reporterv2] starting background reindex loop"
uv run python -c "from reporterv2.index import reindex_loop; reindex_loop()" &

exec uv run gunicorn reporterv2.web:app \
  --bind 0.0.0.0:${PORT:-8802} \
  --workers 4 \
  --worker-class gevent \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
