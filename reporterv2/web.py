import json, os, re, subprocess, traceback
import shutil
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_from_directory

from .client import read_meta, write_meta
from .index import INDEX_DB, close_index_db as close_index_db_connection, get_index_db, get_index_status, reindex_all, sync_to_index
from .storage import store_delete, store_get, store_list, store_size

STATUS_OK = "OK"
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

@app.teardown_appcontext
def close_index_db(exc: BaseException | None) -> None:
  del exc
  close_index_db_connection()


def get_active_job_ids() -> set[str]:
  try:
    if shutil.which("squeue") is None:
      return set()

    try:
      current_user = os.getlogin()
    except (FileNotFoundError, OSError):
      current_user = ""

    command = ["squeue", "--format=%i,%T", "--noheader"]
    if current_user != "batman":
      command = ["su", "batman", "-c", " ".join(command)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
    if result.returncode != 0:
      return set()

    job_ids = set()
    for line in result.stdout.strip().split("\n"):
      if not line.strip():
        continue
      parts = line.strip().split(",")
      if len(parts) >= 2 and parts[1] == "RUNNING":
        job_ids.add(parts[0])
    return job_ids
  except FileNotFoundError:
    return set()
  except Exception:
    traceback.print_exc()
    return set()


def get_slurm_status(slurm_job_id: str, active_job_ids: set[str] | None = None) -> str:
  if not slurm_job_id:
    return "?"
  if active_job_ids is None:
    active_job_ids = get_active_job_ids()
  base_id = slurm_job_id.split("_")[0]
  if slurm_job_id in active_job_ids or base_id in active_job_ids:
    return "running"
  return "completed"


def _apply_live_status(run: dict, active_job_ids: set[str]) -> dict:
  run = dict(run)
  run["status"] = "deleted" if int(run.get("deleted", 0)) else get_slurm_status(run.get("slurm_job_id", ""), active_job_ids)
  return run


def _decorate_runs_with_live_status(rows) -> list[dict]:
  active_job_ids = get_active_job_ids()
  return [_apply_live_status(dict(row), active_job_ids) for row in rows]


@app.route("/api/runs")
def list_runs() -> Response:
  db = get_index_db()
  query = "SELECT * FROM runs WHERE deleted = 0"
  params: list[str] = []
  search = request.args.get("search")
  if search:
    query += " AND (display_name LIKE ? OR run_id LIKE ? OR trainer LIKE ? OR branch LIKE ? OR command LIKE ? OR slurm_job_id LIKE ?)"
    search_like = f"%{search}%"
    params += [search_like, search_like, search_like, search_like, search_like, search_like]
  sort = request.args.get("sort", "created_at")
  order = request.args.get("order", "desc")
  if sort in ("created_at", "display_name", "last_step", "last_epoch"):
    query += f" ORDER BY {sort} {'DESC' if order == 'desc' else 'ASC'}"
  rows = db.execute(query, params).fetchall()
  runs = _decorate_runs_with_live_status(rows)

  status = request.args.get("status")
  if status:
    runs = [run for run in runs if run["status"] == status]

  if sort == "status":
    runs = sorted(runs, key=lambda run: str(run.get("status", "")), reverse=order == 'desc')

  return jsonify({"runs": runs, "total": len(runs)})


@app.route("/api/runs/<run_id>")
def get_run(run_id: str) -> Response:
  meta = read_meta(run_id)
  meta["run_id"] = run_id
  meta = _apply_live_status(meta, get_active_job_ids())
  return jsonify(meta)


@app.route("/api/runs/<run_id>", methods=["PATCH"])
def update_run(run_id: str) -> Response:
  if SAFE_RUN_ID_RE.fullmatch(run_id):
    updates = request.json or {}
    allowed = {"display_name", "notes"}
    filtered = {key: value for key, value in updates.items() if key in allowed}
    write_meta(run_id, filtered)
    sync_to_index(run_id)
    return jsonify({"ok": True})
  return jsonify({"ok": False, "error": "Invalid run_id"}), 400


@app.route("/api/runs/<run_id>", methods=["DELETE"])
def delete_run(run_id: str) -> Response:
  if SAFE_RUN_ID_RE.fullmatch(run_id):
    write_meta(run_id, {"deleted": 1})
    sync_to_index(run_id)
    store_delete(f"runs/{run_id}/", recursive=True)
    store_delete(f"checkpoint/{run_id}/", recursive=True)
    store_delete(f"runs_timestamps/{run_id}/", recursive=True)
    return jsonify({"ok": True})
  return jsonify({"ok": False, "error": "Invalid run_id"}), 400

@app.route("/rawexperiment/<run_id>")
@app.route("/api/runs/<run_id>/metrics")
def get_metrics(run_id: str) -> Response:
  raw = store_get(f"runs/{run_id}/metrics.jsonl")
  if not raw:
    return jsonify({"metrics": []})

  rows = []
  for line in raw.decode().strip().split("\n"):
    if not line:
      continue
    try:
      row = json.loads(line.replace("NaN", "null").replace("Infinity", "null").replace("-Infinity", "null"))
    except json.JSONDecodeError:
      continue
    rows.append(row)
  return jsonify({"metrics": rows})


@app.route("/api/runs/<run_id>/hparams")
def get_hparams(run_id: str) -> Response:
  raw = store_get(f"runs/{run_id}/hparams.json")
  if not raw:
    return jsonify({})
  return jsonify(json.loads(raw))


@app.route("/api/runs/<run_id>/layout")
def get_layout(run_id: str) -> Response:
  raw = store_get(f"runs/{run_id}/layout.json")
  if not raw:
    return jsonify([])
  return jsonify(json.loads(raw))


@app.route("/api/runs/<run_id>/diff")
def get_diff(run_id: str) -> Response:
  raw = store_get(f"runs/{run_id}/diff.patch")
  if not raw:
    return Response("", mimetype="text/plain")
  return Response(raw, mimetype="text/plain")


@app.route("/api/runs/<run_id>/reports")
def list_reports(run_id: str) -> Response:
  keys = store_list(f"runs/{run_id}/reports/")
  reports: dict[str, list[int]] = {}
  for key in keys:
    filename = key.rsplit("/", 1)[-1]
    match = re.match(r"^(.+)\.(\d+)\.html$", filename)
    if not match:
      continue
    name, step = match.group(1), int(match.group(2))
    reports.setdefault(name, []).append(step)
  for name in reports:
    reports[name].sort()
  return jsonify({"reports": reports})


@app.route("/api/runs/<run_id>/reports/<name>/<int:step>")
def get_report(run_id: str, name: str, step: int) -> Response:
  raw = store_get(f"runs/{run_id}/reports/{name}.{step}.html")
  if not raw:
    return Response("Not Found", status=404)
  return Response(raw, mimetype="text/html")


def _list_store_files(prefix: str) -> list[dict[str, str | int | None]]:
  return [{"path": key, "size": store_size(key)} for key in store_list(prefix)]


@app.route("/api/runs/<run_id>/ls")
def list_files(run_id: str) -> Response:
  return jsonify({"files": _list_store_files(f"runs/{run_id}/")})


@app.route("/api/checkpoint/<run_id>/ls")
def list_checkpoint_files(run_id: str) -> Response:
  return jsonify({"files": _list_store_files(f"checkpoint/{run_id}/")})


@app.route("/api/reindex", methods=["GET", "POST"])
def reindex() -> Response:
  count = reindex_all()
  return jsonify({"indexed": count})


@app.route("/")
@app.route("/<path:run_ids>")
def index(run_ids: str | None = None) -> Response:
  if run_ids and run_ids.startswith(("api/", "static/", "_/")):
    return Response("Not Found", status=404)
  return send_from_directory(app.static_folder, "index.html")


@app.route("/api/runs/<run_id>/metadata")
def get_metadata(run_id: str) -> Response:
  meta = read_meta(run_id)
  if not meta:
    return Response("Not Found", status=404)
  return jsonify(meta)


@app.route("/metaexperiment/<run_id>")
def get_metaexperiment(run_id: str) -> Response:
  meta = read_meta(run_id)
  if not meta:
    return Response("Not Found", status=404)
  raw = store_get(f"runs/{run_id}/hparams.json")
  meta["training_args"] = json.loads(raw) if raw else {}
  return jsonify(meta)


@app.route("/_/_/health")
def health() -> Response:
  return Response(STATUS_OK, mimetype="text/plain")


@app.route("/api/index_status")
def index_status() -> Response:
  return jsonify(get_index_status())


if __name__ == "__main__":
  if not INDEX_DB.exists():
    print("[reporterv2] index.db not found, building index...")
    reindex_all()
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8802)), debug=True)
