import re


META_SCHEMA = """CREATE TABLE IF NOT EXISTS meta (
  run_id TEXT PRIMARY KEY,
  created_at REAL,
  display_name TEXT,
  trainer TEXT DEFAULT '',
  branch TEXT DEFAULT '',
  commit_hash TEXT DEFAULT '',
  dirty INTEGER DEFAULT 0,
  command TEXT DEFAULT '',
  slurm_job_id TEXT DEFAULT '',
  slurm_job_name TEXT DEFAULT '',
  hostname TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  status TEXT DEFAULT '',
  config TEXT DEFAULT '{}',
  last_step INTEGER DEFAULT 0,
  last_epoch INTEGER DEFAULT 0,
  last_timestamp INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0,
  last_change_timestamp INTEGER DEFAULT 0
)"""

META_COLUMNS = re.findall(r"(\w+)\s+(?:TEXT|REAL|INTEGER)", META_SCHEMA)
