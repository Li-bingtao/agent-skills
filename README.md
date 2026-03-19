# OpenClaw YouTube Summary

Local, no-paid-API YouTube summarization for OpenClaw.

This project is an OpenClaw skill that:

- tries existing YouTube transcripts first
- falls back to `yt-dlp` subtitle download
- falls back again to local `faster-whisper` transcription
- can optionally run a local Ollama vision model on extracted frames for visual-heavy videos
- returns the result to the chat flow instead of writing final notes into Obsidian

## Install

Clone this repository into an OpenClaw skill directory:

```bash
git clone <your-repo-url> ~/.openclaw/skills/youtube-summary
```

OpenClaw also loads per-workspace skills from `<workspace>/skills`, so this also works:

```bash
git clone <your-repo-url> ./skills/youtube-summary
```

## Dependencies

Preferred:

```bash
uv run --project ~/.openclaw/skills/youtube-summary ~/.openclaw/skills/youtube-summary/scripts/youtube_summary.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

`uv run --project ...` will use the dependencies declared in `pyproject.toml`.

Fallback if you do not use `uv`:

```powershell
python -m pip install av faster-whisper Pillow yt-dlp youtube-transcript-api
```

## Optional vision support

If you want image-aware summaries for visual-heavy videos, run a local Ollama vision model and configure:

```bash
export YOUTUBE_SUMMARY_VISION_MODEL=gemma3
export YOUTUBE_SUMMARY_OLLAMA_HOST=http://127.0.0.1:11434
```

In OpenClaw you can inject those values per skill through `openclaw.json`:

```json5
{
  skills: {
    entries: {
      "youtube-summary": {
        env: {
          YOUTUBE_SUMMARY_VISION_MODEL: "gemma3",
          YOUTUBE_SUMMARY_OLLAMA_HOST: "http://127.0.0.1:11434"
        }
      }
    }
  }
}
```

## CLI examples

Text-only extraction:

```bash
uv run --project . ./scripts/youtube_summary.py "https://www.youtube.com/watch?v=Wo5dMEP_BbI"
```

Force a specific fallback:

```bash
uv run --project . ./scripts/youtube_summary.py "<url>" --force-method api
uv run --project . ./scripts/youtube_summary.py "<url>" --force-method subs
uv run --project . ./scripts/youtube_summary.py "<url>" --force-method transcribe
```

Visual pass with a local Ollama vision model:

```bash
uv run --project . ./scripts/youtube_summary.py "<url>" --include-frames --vision-model gemma3
```

Keep temporary artifacts for debugging:

```bash
uv run --project . ./scripts/youtube_summary.py "<url>" --keep-artifacts --work-dir ./artifacts/run-1
```

## Output contract

The script writes a single JSON object to stdout. The key fields are:

- `video`: basic metadata
- `extraction`: method used, details, and fallback attempts
- `heuristics`: transcript density and whether a visual pass is recommended
- `transcript.text`: full transcript text
- `transcript.chunks`: chunked transcript for long videos
- `visual.frames`: optional frame descriptions from a local Ollama vision model
- `artifacts`: preserved temp paths only when `--keep-artifacts` is used

The OpenClaw skill consumes this JSON and turns it into the final chat response.
