# Contributing

This repository is a collection of reusable agent skills. Keep additions small, explicit, and self-contained.

## Adding a new skill

Create a new folder under `skills/<skill-name>/` with at least:

- `SKILL.md`
- `agents/openai.yaml`

Add `scripts/` and `references/` only when they materially improve reliability or keep `SKILL.md` concise.

## Skill requirements

Each public skill should:

- declare `name` and `description` in `SKILL.md` frontmatter
- include an explicit `license` in `SKILL.md` frontmatter
- keep the core workflow in `SKILL.md`
- move detailed reference material into `references/`
- use `agents/openai.yaml` for display metadata

## Validation

Run this before opening a pull request:

```bash
python ./scripts/validate_skills.py
```

If a skill includes Python helpers, make sure they compile cleanly and update documentation when behavior changes.

## Scope

- Repository-level policy belongs in the root.
- Skill-specific policy belongs inside that skill folder.
- Avoid adding unrelated docs or generated artifacts.
