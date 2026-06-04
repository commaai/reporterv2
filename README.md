# reporterv2

`reporterv2` contains both the Python client used by training jobs and the web UI/API used to browse runs.

## Install

From this repo:

```bash
uv pip install .
python -c "from reporterv2 import ReporterV2; print(ReporterV2)"
```

## Python usage

```python
from reporterv2 import ReporterV2
```

Set `REPORTERV2_HOST` before using the client. Any fsspec-compatible path will work.
For standalone local use, a normal filesystem path is enough:

```bash
export REPORTERV2_HOST=/tmp/reporterv2-store
```

`mkv://` storage works when the `mkv` package is installed in the same environment.

## Docker

For a normal local run:

```bash
docker compose -f docker-compose.local.yaml up --build
```

For a temporary local run with an explicit host path:

```bash
docker compose -f docker-compose.local.yaml run --rm --service-ports -v /reporterv2:/reporterv2 -e REPORTERV2_HOST=/reporterv2 reporterv2
```
