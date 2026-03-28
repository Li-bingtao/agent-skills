from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
REQUIRED_PYTHON = (3, 10)
REQUIRED_MODULES = {
    "av": "av",
    "faster_whisper": "faster-whisper",
    "PIL": "Pillow",
    "yt_dlp": "yt-dlp",
    "youtube_transcript_api": "youtube-transcript-api",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether the video-summary skill environment is ready."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a text report.",
    )
    return parser.parse_args()


def check_python() -> dict[str, object]:
    version_info = sys.version_info[:3]
    supported = version_info >= REQUIRED_PYTHON
    return {
        "executable": sys.executable,
        "version": ".".join(str(part) for part in version_info),
        "supported": supported,
        "required": ".".join(str(part) for part in REQUIRED_PYTHON),
    }


def check_installers() -> dict[str, object]:
    uv_path = shutil.which("uv")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pip_available = True
    except Exception:
        pip_available = False

    return {
        "uv": {"available": bool(uv_path), "path": uv_path},
        "pip": {"available": pip_available},
    }


def check_modules() -> tuple[dict[str, dict[str, str | bool]], list[str]]:
    results: dict[str, dict[str, str | bool]] = {}
    missing: list[str] = []

    for module_name, package_name in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module_name)
            results[package_name] = {"ok": True}
        except Exception as exc:
            results[package_name] = {"ok": False, "error": str(exc)}
            missing.append(package_name)

    return results, missing


def check_temp_writable() -> dict[str, object]:
    try:
        with tempfile.TemporaryDirectory(prefix="video-summary-check-") as temp_dir:
            probe = Path(temp_dir) / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            return {"ok": True, "path": temp_dir}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def build_report() -> dict[str, object]:
    python_info = check_python()
    installers = check_installers()
    modules, missing = check_modules()
    temp_dir = check_temp_writable()

    suggestions: list[str] = []
    if not python_info["supported"]:
        suggestions.append("Install Python 3.10 or newer and rerun this check.")
    if missing:
        suggestions.append(
            f'Run "{sys.executable}" "{PROJECT_DIR / "scripts" / "bootstrap.py"}" '
            "to install missing dependencies."
        )
    if not installers["uv"]["available"]:
        suggestions.append("uv is optional, but installing it makes setup simpler and more reproducible.")
    if not temp_dir["ok"]:
        suggestions.append("Fix temporary directory write access before running the skill.")

    ok = bool(python_info["supported"] and not missing and temp_dir["ok"])
    return {
        "ok": ok,
        "project_dir": str(PROJECT_DIR),
        "python": python_info,
        "installers": installers,
        "modules": modules,
        "temp_dir": temp_dir,
        "suggestions": suggestions,
    }


def print_text_report(report: dict[str, object]) -> None:
    python_info = report["python"]
    installers = report["installers"]
    modules = report["modules"]
    temp_dir = report["temp_dir"]

    print("Video Summary environment check")
    print(f"- Project: {report['project_dir']}")
    print(
        f"- Python: {python_info['version']} "
        f"({'ok' if python_info['supported'] else 'too old'}) "
        f"at {python_info['executable']}"
    )
    print(f"- uv available: {installers['uv']['available']}")
    print(f"- pip available: {installers['pip']['available']}")
    print(f"- Temp dir writable: {temp_dir['ok']}")
    print("- Module imports:")
    for package_name, status in modules.items():
        if status["ok"]:
            print(f"  - {package_name}: ok")
        else:
            print(f"  - {package_name}: missing ({status['error']})")

    if report["suggestions"]:
        print("- Suggestions:")
        for suggestion in report["suggestions"]:
            print(f"  - {suggestion}")

    print(f"- Overall: {'ready' if report['ok'] else 'not ready'}")


def main() -> int:
    args = parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
