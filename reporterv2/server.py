import os
import sys
from importlib.resources import as_file, files


def main() -> None:
  script = files("reporterv2").joinpath("start.sh")
  env = os.environ.copy()
  env.setdefault("REPORTERV2_PYTHON", sys.executable)
  with as_file(script) as path:
    os.execvpe("bash", ["bash", str(path)], env)
