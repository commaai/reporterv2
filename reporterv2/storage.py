import os
from fsspec.core import url_to_fs
from fsspec.spec import AbstractFileSystem


def _required_env(name: str) -> str:
  value = os.getenv(name)
  if not value:
    raise RuntimeError(f"{name} must be set")
  return value


def store_root() -> str:
  return _required_env("REPORTERV2_HOST")


def _store(timeout: float = 30.0) -> tuple[AbstractFileSystem, str]:
  root = store_root().rstrip("/") or "/"
  if "://" not in root:
    root = os.path.abspath(root)
  return url_to_fs(root, timeout=timeout)


def _store_path(key: str, root: str) -> str:
  return os.path.join(root, key.lstrip("/"))


def _store_key(path: str, root: str) -> str:
  return os.path.relpath(path, root or "/")


def store_get(key: str) -> bytes | None:
  fs, root = _store()
  try:
    return fs.cat_file(_store_path(key, root))
  except FileNotFoundError:
    return None


def store_put(key: str, data: bytes | str, timeout: float = 30.0) -> None:
  if isinstance(data, str):
    data = data.encode()
  fs, root = _store(timeout=timeout)
  if fs.protocol == "mkv" and not data:
    data = b"\x00"
  path = _store_path(key, root)
  fs.makedirs(os.path.dirname(path), exist_ok=True)
  fs.pipe_file(path, data)


def store_delete(key: str, recursive: bool = False) -> None:
  fs, root = _store()
  try:
    fs.rm(_store_path(key, root), recursive=recursive)
  except FileNotFoundError:
    pass


def store_list(prefix: str) -> list[str]:
  fs, root = _store()
  try:
    keys = fs.find(_store_path(prefix, root))
  except FileNotFoundError:
    return []
  return [_store_key(key, root) for key in keys]


def store_size(key: str) -> int | None:
  fs, root = _store()
  try:
    return fs.size(_store_path(key, root))
  except FileNotFoundError:
    return None
