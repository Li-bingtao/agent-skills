# Agent Skills

A repository of reusable local skills for OpenClaw, Codex, and other shell-capable agents.

Each skill lives in its own folder under `skills/` and is meant to stay self-contained:

- `SKILL.md` for the skill contract
- `agents/openai.yaml` for UI metadata when relevant
- `scripts/` for deterministic helpers
- `references/` for focused secondary guidance

## Repository layout

```text
agent-skills/
  skills/
    video-summary/
```

## Current skills

- `video-summary`
  Local, no-paid-API video summarization with a transcript-first pipeline, optional visual pass, platform fallback logic, self-extension guidance, and final response review rules.

Main files:

- [`skills/video-summary/SKILL.md`](./skills/video-summary/SKILL.md)
- [`skills/video-summary/agents/openai.yaml`](./skills/video-summary/agents/openai.yaml)
- [`skills/video-summary/scripts/video_summary.py`](./skills/video-summary/scripts/video_summary.py)

## Installing a skill

Clone this repository anywhere:

```bash
git clone <your-repo-url> agent-skills
cd agent-skills
```

Then copy or symlink the specific skill folder you want.

### OpenClaw

Install `video-summary` by placing this folder into an OpenClaw skills directory:

```bash
./skills/video-summary
```

Typical targets:

- `~/.openclaw/skills/video-summary`
- `<workspace>/skills/video-summary`

### Codex

Install `video-summary` by placing this folder into the Codex skills directory:

```bash
./skills/video-summary
```

Typical target:

- `$CODEX_HOME/skills/video-summary`

### Standalone use

Skills that include scripts can also be run directly from this repository.

Example:

```bash
uv run --project ./skills/video-summary ./skills/video-summary/scripts/video_summary.py "<video-url>"
```

## Notes

- OpenClaw is not required unless a specific skill says so.
- Vision capability is not required unless a specific workflow says so.
- Paid APIs are not assumed unless a specific skill says so.
- If a skill supports self-extension, that contract should live inside the skill itself rather than in the repository root.
