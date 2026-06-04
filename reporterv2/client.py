import json, math, os, signal, socket, sys, tarfile, time
from collections.abc import Mapping, Sequence
from multiprocessing import Process
from typing import Any

from .git import get_git_info
from .storage import store_delete, store_get, store_list, store_put

def flatten_dict(out: dict[str, Any], prefix: str, values: Mapping[str, Any], delim: str = ".") -> None:
  for key, value in values.items():
    flat_key = f"{prefix}{delim}{key}" if prefix else key
    if isinstance(value, Mapping):
      flatten_dict(out, flat_key, value, delim=delim)
    else:
      out[flat_key] = value.item() if hasattr(value, "item") else value


def read_meta(run_id: str) -> dict[str, Any]:
  raw = store_get(f"runs/{run_id}/metadata.json")
  if raw is None:
    return {}
  return json.loads(raw)


def write_ts(run_id: str, created_at: int, modified_at: int, override: bool = True) -> None:
  if override:
    for key in store_list(f"runs_timestamps/{run_id}/"):
      if key.endswith(".ts"):
        store_delete(key)
  store_put(f"runs_timestamps/{run_id}/{created_at}_{modified_at}.ts", b"0")


def write_meta(run_id: str, meta: Mapping[str, Any]) -> None:
  existing = read_meta(run_id)
  existing.update(meta)
  modified_at = int(time.time())
  existing["last_change_timestamp"] = modified_at
  store_put(f"runs/{run_id}/metadata.json", json.dumps(existing))
  write_ts(run_id, int(existing.get("created_at", modified_at)), modified_at)


def write_metrics(run_id: str, meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
  signal.signal(signal.SIGINT, signal.SIG_IGN)
  write_meta(run_id, meta)
  existing = store_get(f"runs/{run_id}/metrics.jsonl")
  content = existing.decode() if existing else ""
  for row in rows:
    clean = {
      key: (None if isinstance(value, float) and (math.isnan(value) or math.isinf(value)) else value)
      for key, value in row.items()
    }
    content += json.dumps(clean, default=str) + "\n"
  store_put(f"runs/{run_id}/metrics.jsonl", content)


def write_checkpoint(run_id: str, epoch: int, filename: str) -> None:
  signal.signal(signal.SIGINT, signal.SIG_IGN)
  with tarfile.open(filename, mode="r|") as archive:
    for member in archive:
      if not member.isfile():
        continue
      extracted = archive.extractfile(member)
      if extracted is None:
        continue
      store_put(f"checkpoint/{run_id}/{epoch}/{member.name}", extracted.read(), timeout=120.0)
  os.unlink(filename)


def write_report(training_id: str, data: Any, step: int, name: str, output_type: str) -> None:
  if output_type == "html":
    if isinstance(data, str):
      data = data.encode()
    store_put(f"runs/{training_id}/reports/{name}.{step}.html", data)
    return

  if output_type == "scalar":
    row = {"step": step, "ts": time.time()}
    flat: dict[str, Any] = {}
    flatten_dict(flat, "", {name: data}, delim="/")
    row.update(flat)
    write_metrics(training_id, {}, [row])
    return

  raise ValueError(f"Unsupported report output type: {output_type}")


class ReporterV2:
  def __init__(self, config: dict):
    if "training_id" not in config:
      raise ValueError("ReporterV2 config must define training_id")

    self.training_id = config["training_id"]
    self._pending: list[dict[str, Any]] = []
    self._processes: list[Process] = []
    self._last_step = -1
    self._last_epoch = -1

    branch, commit_hash, diff = get_git_info()
    slurm_job_id = (
      f'{os.getenv("SLURM_ARRAY_JOB_ID")}_{os.getenv("SLURM_ARRAY_TASK_ID")}'
      if os.getenv("SLURM_ARRAY_JOB_ID")
      else os.getenv("SLURM_JOB_ID", "")
    )
    command = os.getenv("TRAINING_COMMAND", " ".join(sys.argv))
    self._first_timestamp = round(time.time())
    self._meta = {
      "run_id": self.training_id,
      "trainer": config.get("trainer", ""),
      "created_at": self._first_timestamp,
      "display_name": config.get("display_name", ""),
      "branch": branch,
      "commit_hash": commit_hash,
      "dirty": 1 if diff else 0,
      "command": command,
      "slurm_job_id": slurm_job_id,
      "slurm_job_name": os.getenv("SLURM_JOB_NAME", ""),
      "hostname": socket.gethostname(),
      "notes": "",
      "deleted": 0,
      "last_step": self._last_step,
      "last_epoch": self._last_epoch,
    }

    write_ts(self.training_id, self._first_timestamp, self._first_timestamp)
    write_meta(self.training_id, self._meta)
    store_put(f"runs/{self.training_id}/hparams.json", json.dumps(config, default=str))
    store_put(f"runs/{self.training_id}/diff.patch", diff or "")
    print(f"training id is {self.training_id}")

  @property
  def processes(self) -> list[Process]:
    return self._processes

  def _compact_processes(self) -> None:
    self._processes = [process for process in self._processes if process.is_alive()]

  def set_layout(self, layout: list[dict[str, str]]) -> None:
    store_put(f"runs/{self.training_id}/layout.json", json.dumps(layout))

  def buffer_metrics(self, step: int, epoch: int, metrics: Mapping[str, Any]) -> None:
    row = {"step": step, "epoch": epoch, "ts": time.time()}
    self._last_epoch = epoch
    self._last_step = step
    flat: dict[str, Any] = {}
    flatten_dict(flat, "", metrics, delim="/")
    row.update(flat)
    self._pending.append(row)

  def save_metrics(self) -> None:
    if not self._pending:
      return
    self._compact_processes()
    rows = self._pending
    self._pending = []
    meta = {
      "last_timestamp": round(time.time()),
      "last_step": self._last_step,
      "last_epoch": self._last_epoch,
    }
    process = Process(target=write_metrics, args=(self.training_id, meta, rows))
    process.start()
    self._processes.append(process)

  def save_checkpoint(self, epoch: int, filename: str | None) -> None:
    if not filename:
      return
    self._compact_processes()
    process = Process(target=write_checkpoint, args=(self.training_id, epoch, filename))
    process.start()
    self._processes.append(process)

  def write_report(self, data: Any, step: int, name: str, output_type: str) -> None:
    write_report(self.training_id, data, step, name, output_type)

  def close(self) -> None:
    self.save_metrics()
    for process in self._processes:
      process.join()

  def __del__(self) -> None:
    try:
      self.close()
    except Exception:
      pass
