#!/bin/bash
set -euo pipefail

: "${REPORTERV2_DATA:?REPORTERV2_DATA must be set}"
: "${REPORTERV2_HOST:?REPORTERV2_HOST must be set}"

mkdir -p "$REPORTERV2_DATA"
rm -f "$REPORTERV2_DATA/index.db"

PYTHON="${REPORTERV2_PYTHON:-python}"

echo "[reporterv2] starting background reindex loop"
"$PYTHON" -c "from reporterv2.index import reindex_loop; reindex_loop()" &

exec "$PYTHON" -m gunicorn.app.wsgiapp reporterv2.web:app \
  --bind 0.0.0.0:${PORT:-8802} \
  --workers 4 \
  --worker-class gevent \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
