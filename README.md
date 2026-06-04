# reporterv2

The incredible comma model reporter!

## Install

```bash
uv pip install .
```

## Storage

`REPORTERV2_HOST` must point at an fsspec-compatible store.
`REPORTERV2_DATA` stores the local SQLite index cache.

```bash
export REPORTERV2_HOST=/tmp/reporterv2-store
export REPORTERV2_DATA=/tmp/reporterv2-index
```

## Client

```python
from reporterv2 import ReporterV2

reporter = ReporterV2({"training_id": "run-id"})
```

## Server

```bash
uv run reporterv2-server
```

Open `http://localhost:8802`.

## Docker

```bash
docker compose -f docker-compose.local.yaml up --build
```
