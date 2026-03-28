# Agent Skills

Reusable local skills for OpenClaw, Codex, and other shell-capable agents.

This repository is organized as a multi-skill collection. Each skill lives under `skills/<skill-name>/` and stays self-contained:

- `SKILL.md` for the skill contract and workflow
- `agents/openai.yaml` for UI-facing metadata
- `scripts/` for deterministic helpers
- `references/` for secondary guidance loaded only when needed

## Repository layout

```text
agent-skills/
  skills/
    video-summary/
  scripts/
    validate_skills.py
```

## Current skills

| Skill | What it does | Status |
| --- | --- | --- |
| `video-summary` | Summarizes public videos locally with a transcript-first pipeline, optional visual pass, platform fallback logic, self-extension guidance, and a final response review step. | Active |

Skill entry points:

- [`skills/video-summary/SKILL.md`](./skills/video-summary/SKILL.md)
- [`skills/video-summary/agents/openai.yaml`](./skills/video-summary/agents/openai.yaml)
- [`skills/video-summary/scripts/video_summary.py`](./skills/video-summary/scripts/video_summary.py)

## Video Summary at a glance

`video-summary` currently supports:

- YouTube
- Bilibili
- Xiaohongshu
- Douyin
- X

The default extraction order is:

1. existing transcript
2. subtitle download
3. local speech-to-text
4. optional visual pass if the video is image-heavy

Key behavior:

- chat-first output
- no paid APIs required
- temporary artifacts auto-cleaned by default
- vision is optional, not required for transcript-based summaries
- unsupported platforms can be added incrementally through the platform harness

## Install from GitHub

Clone the repository:

```bash
git clone https://github.com/Li-bingtao/agent-skills.git
cd agent-skills
```

Then copy or symlink the specific skill folder you want.

### OpenClaw

Place [`skills/video-summary`](./skills/video-summary) in one of these locations:

- `~/.openclaw/skills/video-summary`
- `<workspace>/skills/video-summary`

### Codex

Place [`skills/video-summary`](./skills/video-summary) in:

- `$CODEX_HOME/skills/video-summary`

### Standalone use

For first-time setup:

```bash
python ./skills/video-summary/scripts/bootstrap.py
```

To inspect readiness without changing the environment:

```bash
python ./skills/video-summary/scripts/check_env.py
```

Then run the helper directly from this repository:

```bash
uv run --project ./skills/video-summary ./skills/video-summary/scripts/video_summary.py "<video-url>"
```

Transcript-only runs need Python plus the listed dependencies. A visual pass additionally needs a configured image-capable model endpoint that matches the skill's `--vision-model` and `--vision-host` settings.

## Development and validation

Before publishing or pushing changes, run:

```bash
python ./scripts/validate_skills.py
```

This validator checks:

- required skill files
- `SKILL.md` frontmatter fields
- `agents/openai.yaml` interface fields
- Python syntax for repository and skill scripts

GitHub Actions runs the same validation on push and pull request.

## Repository conventions

- Public-facing skills should include an explicit license.
- New skills belong under `skills/<skill-name>/`.
- Repository-level guidance goes in the root; skill-specific guidance stays inside the skill folder.
- If a skill supports self-extension, the extension contract should live inside that skill, not in the repository root.

Contribution guidance lives in [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

This repository is licensed under the MIT License. See [LICENSE](./LICENSE).
