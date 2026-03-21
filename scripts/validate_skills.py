from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
REQUIRED_FRONTMATTER_KEYS = ("name", "description", "license")
REQUIRED_INTERFACE_KEYS = ("display_name", "short_description", "default_prompt")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter is not closed")

    block = parts[1]
    data: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def parse_openai_yaml(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    current_section = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            if stripped.endswith(":"):
                current_section = stripped[:-1]
            else:
                current_section = None
            continue
        if current_section != "interface":
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def validate_python_file(path: Path) -> list[str]:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error at line {exc.lineno}: {exc.msg}"]
    return []


def main() -> int:
    errors: list[str] = []

    if not SKILLS_DIR.exists():
        errors.append(f"Missing skills directory: {SKILLS_DIR}")
    else:
        skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
        if not skill_dirs:
            errors.append(f"No skill directories found under {SKILLS_DIR}")

        for skill_dir in skill_dirs:
            skill_md = skill_dir / "SKILL.md"
            openai_yaml = skill_dir / "agents" / "openai.yaml"

            if not skill_md.exists():
                errors.append(f"{skill_dir}: missing SKILL.md")
                continue
            if not openai_yaml.exists():
                errors.append(f"{skill_dir}: missing agents/openai.yaml")

            try:
                frontmatter = parse_frontmatter(skill_md)
            except ValueError as exc:
                errors.append(f"{skill_md}: {exc}")
                frontmatter = {}

            for key in REQUIRED_FRONTMATTER_KEYS:
                if not frontmatter.get(key):
                    errors.append(f"{skill_md}: missing frontmatter key '{key}'")

            if openai_yaml.exists():
                interface = parse_openai_yaml(openai_yaml)
                for key in REQUIRED_INTERFACE_KEYS:
                    if not interface.get(key):
                        errors.append(f"{openai_yaml}: missing interface key '{key}'")

            for py_file in sorted(skill_dir.rglob("*.py")):
                errors.extend(validate_python_file(py_file))

    for py_file in sorted(REPO_ROOT.glob("scripts/*.py")):
        errors.extend(validate_python_file(py_file))

    if errors:
        print("Skill validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Skill validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
