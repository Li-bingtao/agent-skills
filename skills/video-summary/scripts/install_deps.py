from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_DIR / "pyproject.toml"
REQUIRED_PYTHON = (3, 10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Python dependencies for the video-summary skill."
    )
    parser.add_argument(
        "--pip",
        action="store_true",
        help="Use pip even if uv is available.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Pass --upgrade when pip is used.",
    )
    return parser.parse_args()


def ensure_supported_python() -> None:
    if sys.version_info[:2] < REQUIRED_PYTHON:
        required = ".".join(str(part) for part in REQUIRED_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            f"Python {required}+ is required for this skill. Current version: {current}."
        )


def read_dependencies() -> list[str]:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, flags=re.S)
    if not match:
        raise RuntimeError(f"Could not read dependencies from {PYPROJECT_PATH}.")
    deps = ast.literal_eval("[" + match.group(1) + "]")
    if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
        raise RuntimeError(f"Dependency block in {PYPROJECT_PATH} is not a string list.")
    return deps


def run_command(command: list[str]) -> int:
    print("Running:")
    print("  " + " ".join(f'"{part}"' if " " in part else part for part in command))
    completed = subprocess.run(command, cwd=str(PROJECT_DIR))
    return completed.returncode


def install_with_uv() -> int:
    uv_path = shutil.which("uv")
    if not uv_path:
        return 127
    return run_command([uv_path, "sync", "--project", str(PROJECT_DIR)])


def install_with_pip(dependencies: list[str], upgrade: bool) -> int:
    command = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        command.append("--upgrade")
    command.extend(dependencies)
    return run_command(command)


def main() -> int:
    args = parse_args()
    ensure_supported_python()
    dependencies = read_dependencies()

    if not args.pip and shutil.which("uv"):
        code = install_with_uv()
        if code == 0:
            return 0
        print("uv install failed, falling back to pip.")

    return install_with_pip(dependencies, args.upgrade)


if __name__ == "__main__":
    raise SystemExit(main())
