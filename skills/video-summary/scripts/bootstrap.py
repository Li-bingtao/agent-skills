from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPTS_DIR.parents[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap the video-summary skill environment."
    )
    parser.add_argument(
        "--pip",
        action="store_true",
        help="Use pip for installation even if uv is available.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Pass --upgrade to pip installs.",
    )
    return parser.parse_args()


def run_check() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_env.py"), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if not completed.stdout.strip():
        raise RuntimeError(
            "Environment check did not produce JSON output. "
            + (completed.stderr.strip() or "No stderr output.")
        )
    return json.loads(completed.stdout)


def run_install(args: argparse.Namespace) -> int:
    command = [sys.executable, str(SCRIPTS_DIR / "install_deps.py")]
    if args.pip:
        command.append("--pip")
    if args.upgrade:
        command.append("--upgrade")
    completed = subprocess.run(command, check=False)
    return completed.returncode


def print_summary(report: dict[str, object]) -> None:
    print("Video Summary bootstrap")
    print(f"- Skill directory: {PROJECT_DIR}")
    print(f"- Python ready: {report['python']['supported']}")
    print(f"- Environment ready: {report['ok']}")


def print_next_steps() -> None:
    print("Verification commands:")
    print(f'  "{sys.executable}" "{SCRIPTS_DIR / "check_env.py"}"')
    print(f'  "{sys.executable}" "{SCRIPTS_DIR / "video_summary.py"}" --help')


def main() -> int:
    args = parse_args()
    initial_report = run_check()
    print_summary(initial_report)

    if initial_report["ok"]:
        print("No installation needed.")
        print_next_steps()
        return 0

    if not initial_report["python"]["supported"]:
        print("Python version is not supported. Install Python 3.10+ first.")
        return 1

    print("Installing missing dependencies...")
    install_code = run_install(args)
    if install_code != 0:
        print("Dependency installation failed.")
        return install_code

    final_report = run_check()
    print_summary(final_report)
    if final_report["ok"]:
        print("Environment is ready.")
        print_next_steps()
        return 0

    print("Environment is still not ready after installation.")
    for suggestion in final_report.get("suggestions", []):
        print(f"- {suggestion}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
