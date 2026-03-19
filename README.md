# OpenClaw Video Summary

Local, no-paid-API video summarization as a reusable skill plus a standalone helper script.

This repository packages the current `video-summary` workflow. It is transcript-first, falls back to local transcription, and can optionally add a visual pass for visual-heavy videos.

It is also designed to be self-extensible: when a user provides a public video link from an unsupported platform, the skill can iteratively add the smallest missing adapter or fallback path instead of forcing a separate new skill.

## Current support

- YouTube URLs and bare YouTube video ids
- Bilibili video URLs
- Xiaohongshu video note URLs
- Douyin share and video URLs
- X post URLs with playable video

For unsupported platforms, see [references/platform_harness.md](./references/platform_harness.md).

## What This Project Requires

Mandatory:

- Python `>= 3.10`
- the dependencies declared in [`pyproject.toml`](./pyproject.toml)
- network access to fetch public video pages or media streams

Not mandatory:

- OpenClaw is **not required**
- a vision-capable model is **not required** for transcript-first summaries
- paid APIs are **not used**

Optional:

- a vision-capable model endpoint if you want automatic image-aware summaries
- a host agent such as OpenClaw, Codex, or another shell-capable agent if you want polished chat responses instead of raw JSON
- browser cookies for some future edge cases on platforms with stronger anti-bot or login requirements

Important distinction:

- the helper script itself does **not** call an LLM to write the final answer
- it extracts metadata, transcript, and optional frames, then returns structured JSON
- the chat model in your agent stack turns that JSON into the final natural-language response

## Self-Extension Ability

This skill is intentionally written so an agent can extend it in place.

If a user provides a link from a platform that is not yet supported, the expected behavior is:

1. inspect the public page or share page
2. reuse the existing transcript-first pipeline
3. add the smallest new adapter or fallback path needed
4. validate on the triggering URL
5. update the documented support list

The detailed contract for this lives in [references/platform_harness.md](./references/platform_harness.md).

## Does It Require OpenClaw?

No.

OpenClaw is the smoothest way to use this as a chat skill, but it is not a hard requirement.

You can use this repository in three ways:

1. As an OpenClaw skill
2. As a Codex-style local skill
3. As a standalone CLI helper in any workflow that can run Python and parse JSON from stdout

## Does It Require a Vision Model?

No, not for normal text-first video understanding.

The default flow is:

1. Try an existing transcript
2. Try subtitle download
3. Fall back to local `faster-whisper` transcription

That path only needs normal local Python dependencies. It does **not** require a multimodal model.

You only need image-recognition capability when:

- the video is strongly visual
- transcript quality is poor or sparse
- you want automatic frame descriptions instead of transcript-only understanding

For automatic frame descriptions, configure:

- `VIDEO_SUMMARY_VISION_MODEL`
- `VIDEO_SUMMARY_VISION_HOST`
- or `--vision-model`

The vision model can be separate from your main chat model.

Implementation note:

- the bundled automatic frame-description client currently expects an Ollama-compatible `/api/chat` endpoint
- if your host agent can already inspect extracted frames directly, you can also skip automatic frame descriptions and still use the visual pass

## Install

### OpenClaw

Clone this repository into an OpenClaw skill directory:

```bash
git clone <your-repo-url> ~/.openclaw/skills/video-summary
```

OpenClaw also loads per-workspace skills from `<workspace>/skills`:

```bash
git clone <your-repo-url> ./skills/video-summary
```

### Codex

Clone this repository into the Codex skills directory:

```bash
git clone <your-repo-url> "$CODEX_HOME/skills/video-summary"
```

### Standalone / Other agents

Clone the repository anywhere and run the helper script directly:

```bash
git clone <your-repo-url>
cd openclaw-video-summary
uv run --project . ./scripts/video_summary.py "<video-url>"
```

Any agent or workflow that can execute this command and read JSON can integrate it.

## Dependencies

Preferred:

```bash
uv run --project . ./scripts/video_summary.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Fallback if you do not use `uv`:

```powershell
python -m pip install av faster-whisper Pillow yt-dlp youtube-transcript-api
```

## Optional vision support

If you want automatic image-aware summaries for visual-heavy videos, point the skill at a vision-capable endpoint:

```bash
export VIDEO_SUMMARY_VISION_MODEL=gemma3
export VIDEO_SUMMARY_VISION_HOST=http://127.0.0.1:11434
```

In OpenClaw you can inject those values per skill through `openclaw.json`:

```json5
{
  skills: {
    entries: {
      "video-summary": {
        env: {
          VIDEO_SUMMARY_VISION_MODEL: "gemma3",
          VIDEO_SUMMARY_VISION_HOST: "http://127.0.0.1:11434"
        }
      }
    }
  }
}
```

The bundled client currently expects an Ollama-compatible `/api/chat` endpoint. If no vision model is configured, the skill still works. It just stays transcript-based.

## CLI examples

Transcript-first extraction:

```bash
uv run --project . ./scripts/video_summary.py "https://www.youtube.com/watch?v=Wo5dMEP_BbI"
```

Other supported platforms:

```bash
uv run --project . ./scripts/video_summary.py "https://www.bilibili.com/video/BV18X1WBPEXF/"
uv run --project . ./scripts/video_summary.py "https://www.xiaohongshu.com/explore/<note-id>"
uv run --project . ./scripts/video_summary.py "https://v.douyin.com/<share-id>/"
uv run --project . ./scripts/video_summary.py "https://x.com/<user>/status/<id>"
```

Force a specific fallback:

```bash
uv run --project . ./scripts/video_summary.py "<url>" --force-method api
uv run --project . ./scripts/video_summary.py "<url>" --force-method subs
uv run --project . ./scripts/video_summary.py "<url>" --force-method transcribe
```

Visual pass with automatic frame descriptions:

```bash
uv run --project . ./scripts/video_summary.py "<url>" --include-frames --vision-model gemma3 --vision-host http://127.0.0.1:11434
```

Keep temporary artifacts for debugging:

```bash
uv run --project . ./scripts/video_summary.py "<url>" --keep-artifacts --work-dir ./artifacts/run-1
```

## Output contract

The helper script writes one JSON object to stdout. The key fields are:

- `video`: basic metadata
- `extraction`: method used, details, and fallback attempts
- `heuristics`: transcript density and whether a visual pass is recommended
- `transcript.text`: full transcript text
- `transcript.chunks`: chunked transcript for long videos
- `visual.frames`: optional frame descriptions from a configured vision-capable endpoint
- `warnings`: non-fatal extraction warnings
- `artifacts`: preserved temp paths only when `--keep-artifacts` is used

OpenClaw can consume this JSON and turn it into the final chat response, but any other agent can do the same.
