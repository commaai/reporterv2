import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import g

from .client import read_meta
from .schema import META_COLUMNS, META_SCHEMA
from .storage import store_list


REINDEX_INTERVAL = 300
REINDEX_FETCH_WORKERS = max(1, int(os.getenv("REPORTERV2_REINDEX_FETCH_WORKERS") or 16))
RUNS_SCHEMA = META_SCHEMA.replace("meta", "runs", 1)
_last_reindex_elapsed: float | None = None


def _index_db_path() -> Path:
  reporterv2_data = os.getenv("REPORTERV2_DATA")
  if not reporterv2_data:
    raise RuntimeError("REPORTERV2_DATA must be set")
  return Path(reporterv2_data) / "index.db"


INDEX_DB = _index_db_path()
INDEX_DB.parent.mkdir(parents=True, exist_ok=True)


def indexed_status(meta: dict) -> str:
  return "deleted" if int(meta.get("deleted", 0)) else "?"


def init_index_db(db: sqlite3.Connection) -> None:
  db.execute(RUNS_SCHEMA)
  db.commit()


def get_index_db() -> sqlite3.Connection:
  if "index_db" not in g:
    g.index_db = sqlite3.connect(str(INDEX_DB))
    g.index_db.row_factory = sqlite3.Row
    init_index_db(g.index_db)
  return g.index_db


def close_index_db() -> None:
  db = g.pop("index_db", None)
  if db is not None:
    db.close()


def _upsert_index_row(db: sqlite3.Connection, meta: dict, last_change_timestamp: int | None = None) -> None:
  if last_change_timestamp is not None:
    meta = {**meta, "last_change_timestamp": last_change_timestamp}
  columns = [column for column in META_COLUMNS if column in meta]
  placeholders = ",".join(["?"] * len(columns))
  db.execute(
    f"INSERT OR REPLACE INTO runs ({','.join(columns)}) VALUES ({placeholders})",
    [meta[column] for column in columns],
  )


def sync_to_index(run_id: str) -> None:
  meta = read_meta(run_id)
  if not meta:
    return

  meta["status"] = indexed_status(meta)
  db = get_index_db()
  _upsert_index_row(db, meta)
  db.commit()


def _parse_run_timestamp_key(key: str) -> tuple[str, int] | None:
  parts = key.strip("/").split("/")
  if len(parts) < 3:
    return None
  filename = parts[-1]
  if not filename.endswith(".ts"):
    return None
  try:
    last_timestamp = int(filename.removesuffix(".ts").split("_")[-1])
  except ValueError:
    return None
  return parts[-2], last_timestamp


def _collect_run_timestamps(timestamp_keys: list[str]) -> dict[str, int]:
  run_last_timestamp: dict[str, int] = {}
  for key in timestamp_keys:
    parsed = _parse_run_timestamp_key(key)
    if parsed is None:
      continue
    run_id, last_timestamp = parsed
    run_last_timestamp[run_id] = last_timestamp
  return run_last_timestamp


def _fetch_run_meta(run: tuple[str, int]) -> tuple[int, dict]:
  run_id, last_timestamp = run
  return last_timestamp, read_meta(run_id)


def _iter_changed_run_meta(changed_runs: list[tuple[str, int]], fetch_workers: int):
  if fetch_workers == 1:
    yield from (_fetch_run_meta(run) for run in changed_runs)
    return

  with ThreadPoolExecutor(max_workers=fetch_workers, thread_name_prefix="reporterv2-reindex") as executor:
    yield from executor.map(_fetch_run_meta, changed_runs)


def _load_changed_runs(changed_runs: list[tuple[str, int]]) -> tuple[list[tuple[dict, int]], int]:
  if not changed_runs:
    return [], 1

  fetch_workers = min(REINDEX_FETCH_WORKERS, len(changed_runs))
  rows: list[tuple[dict, int]] = []
  for last_timestamp, meta in _iter_changed_run_meta(changed_runs, fetch_workers):
    if not meta:
      continue
    meta["status"] = indexed_status(meta)
    rows.append((meta, last_timestamp))
  return rows, fetch_workers


def reindex_all() -> int:
  start_time = time.monotonic()
  db = sqlite3.connect(str(INDEX_DB))
  try:
    db.row_factory = sqlite3.Row
    db.execute(RUNS_SCHEMA)
    db.execute("BEGIN IMMEDIATE")

    indexed_timestamps = {
      row["run_id"]: row["last_change_timestamp"]
      for row in db.execute("SELECT run_id, last_change_timestamp FROM runs")
    }
    timestamp_keys = store_list("runs_timestamps/")
    run_last_timestamp = _collect_run_timestamps(timestamp_keys)

    deleted_runs = [run_id for run_id in indexed_timestamps if run_id not in run_last_timestamp]
    if deleted_runs:
      db.executemany("DELETE FROM runs WHERE run_id = ?", [(run_id,) for run_id in deleted_runs])

    changed_runs = [
      (run_id, last_timestamp)
      for run_id, last_timestamp in run_last_timestamp.items()
      if indexed_timestamps.get(run_id) != last_timestamp
    ]
    changed_rows, _ = _load_changed_runs(changed_runs)

    for meta, last_timestamp in changed_rows:
      _upsert_index_row(db, meta, last_change_timestamp=last_timestamp)

    db.execute(
      "UPDATE runs SET status = CASE WHEN deleted != 0 THEN 'deleted' ELSE '?' END "
      "WHERE status != CASE WHEN deleted != 0 THEN 'deleted' ELSE '?' END"
    )
    db.commit()
  finally:
    db.close()

  count = len(changed_rows)

  global _last_reindex_elapsed
  _last_reindex_elapsed = time.monotonic() - start_time
  print(f"[reindex] indexed {count} runs in {_last_reindex_elapsed:.2f}s")
  return count


def reindex_loop() -> None:
  while True:
    try:
      reindex_all()
    except Exception as error:
      print(f"[reindex] error: {error}")
    time.sleep(REINDEX_INTERVAL)


def get_index_status() -> dict[str, float | None]:
  return {
    "last_updated": INDEX_DB.stat().st_mtime if INDEX_DB.exists() else None,
    "elapsed": _last_reindex_elapsed,
  }
