import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


class ReindexTest(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = Path(temporary.name)
    self.store = self.root / "store"
    environment = patch.dict(os.environ, {
      "REPORTERV2_DATA": str(self.root / "index"),
      "REPORTERV2_HOST": str(self.store),
    })
    environment.start()
    self.addCleanup(environment.stop)

    from reporterv2 import index
    self.index = index
    executor = ThreadPoolExecutor(max_workers=4)
    self.addCleanup(executor.shutdown)
    for name, value in (("INDEX_DB", self.root / "index.db"), ("REINDEX_FETCH_WORKERS", 4), ("_reindex_executor", executor)):
      patched = patch.object(index, name, value)
      patched.start()
      self.addCleanup(patched.stop)

  def write_runs(self, step):
    for run_id in ("run-0", "run-1", "run-2", "run-3"):
      run_dir = self.store / "runs" / run_id
      run_dir.mkdir(parents=True, exist_ok=True)
      (run_dir / "metadata.json").write_text(json.dumps({"run_id": run_id, "last_step": step}))
      timestamp_dir = self.store / "runs_timestamps" / run_id
      timestamp_dir.mkdir(parents=True, exist_ok=True)
      for old_timestamp in timestamp_dir.iterdir():
        old_timestamp.unlink()
      (timestamp_dir / f"0_{step}.ts").touch()

  def indexed_steps(self):
    with sqlite3.connect(self.index.INDEX_DB) as db:
      return db.execute("SELECT last_step, last_change_timestamp FROM runs ORDER BY run_id").fetchall()

  def test_refreshes_reuse_workers_and_index_new_metadata(self):
    worker_ids = set()
    barrier = threading.Barrier(4, timeout=5)
    read_meta = self.index.read_meta

    def fetch(run_id):
      worker_ids.add(threading.get_native_id())
      barrier.wait()
      return read_meta(run_id)

    with patch.object(self.index, "read_meta", side_effect=fetch):
      for step in range(1, 11):
        self.write_runs(step)
        self.assertEqual(self.index.reindex_all(), 4)
        self.assertEqual(self.indexed_steps(), [(step, step)] * 4)
        self.assertEqual(len(worker_ids), 4, "refreshes must not accumulate new storage-client threads")
      self.assertEqual(self.index.reindex_all(), 0)

  def test_metadata_failure_rolls_back_and_next_refresh_succeeds(self):
    self.write_runs(1)
    self.assertEqual(self.index.reindex_all(), 4)
    self.write_runs(2)
    read_meta = self.index.read_meta
    failed = threading.Event()

    def fetch(run_id):
      if run_id == "run-0" and not failed.is_set():
        failed.set()
        raise OSError("storage unavailable")
      return read_meta(run_id)

    with patch.object(self.index, "read_meta", side_effect=fetch):
      with self.assertRaisesRegex(OSError, "storage unavailable"):
        self.index.reindex_all()
      self.assertEqual(self.indexed_steps(), [(1, 1)] * 4)
      self.assertEqual(self.index.reindex_all(), 4)
      self.assertEqual(self.indexed_steps(), [(2, 2)] * 4)


if __name__ == "__main__":
  unittest.main()
