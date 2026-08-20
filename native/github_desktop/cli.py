"""`github` CLI helper: open / clone (parity with Electron CLI)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


USAGE = """GitHub Desktop CLI usage:
  github                            Open the current directory
  github open [path]                Open the provided path
  github clone [-b branch] <url>    Clone the repository by url or name/owner
                                    (ex torvalds/linux), optionally checking out
                                    the branch
"""


def _launch(args: list[str]) -> int:
    exe = shutil.which("github-desktop")
    if exe:
        proc = subprocess.Popen([exe, *args], start_new_session=True)
        return 0 if proc.pid else 1
    # Running from a source tree
    env = os.environ.copy()
    native = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = native + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen([sys.executable, "-m", "github_desktop", *args], env=env, start_new_session=True)
    return 0 if proc.pid else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="github", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-b", "--branch")
    parser.add_argument("rest", nargs="*")
    args, unknown = parser.parse_known_args(argv)
    if args.help or (args.rest[:1] == ["help"]) or unknown[:1] == ["help"]:
        sys.stdout.write(USAGE)
        return 0
    rest = [a for a in [*args.rest, *unknown] if not a.startswith("-")]
    if rest and rest[0] == "clone":
        url_arg = rest[1] if len(rest) > 1 else None
        if not url_arg:
            sys.stderr.write(USAGE)
            return 1
        url = f"https://github.com/{url_arg}" if "/" in url_arg and "://" not in url_arg and url_arg.count("/") == 1 else url_arg
        launch = [f"--cli-clone={url}"]
        if args.branch:
            launch.append(f"--cli-branch={args.branch}")
        return _launch(launch)
    path_arg = rest[1] if rest and rest[0] == "open" else (rest[0] if rest else ".")
    path = str(Path(path_arg).resolve())
    return _launch([f"--cli-open={path}"])


if __name__ == "__main__":
    raise SystemExit(main())
