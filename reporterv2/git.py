import json
import subprocess
from pathlib import Path


def _candidate_roots() -> list[Path]:
  candidates = (
    candidate
    for base in (Path.cwd(), Path(__file__).resolve().parent)
    for candidate in (base, *base.parents)
  )
  return list(dict.fromkeys(candidates))


def _repo_root() -> Path | None:
  for candidate in _candidate_roots():
    if (candidate / "git-info.json").is_file() or (candidate / ".git").exists():
      return candidate
  return None


def _run_git(args: list[str], cwd: Path) -> str:
  return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.PIPE).decode("utf-8").strip()


def get_git_info() -> tuple[str, str, str]:
  repo_root = _repo_root()
  if repo_root is None:
    return "", "", ""

  git_info_cache = repo_root / "git-info.json"
  if git_info_cache.is_file():
    try:
      with git_info_cache.open("r", encoding="utf-8") as handle:
        info = json.load(handle)
      return info.get("branch", ""), info.get("commit", ""), info.get("diff", "")
    except (OSError, json.JSONDecodeError):
      pass

  try:
    commit = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    diff = _run_git(["diff", "HEAD"], cwd=repo_root)
    local_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    if local_branch == "HEAD":
      return "HEAD detached", commit, diff

    try:
      upstream_branch = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=repo_root)
    except subprocess.CalledProcessError as error:
      if b"no upstream" in error.stderr.lower():
        return local_branch, commit, diff
      raise

    return upstream_branch, commit, diff
  except (OSError, subprocess.CalledProcessError):
    return "", "", ""
