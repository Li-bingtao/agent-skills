# Troubleshooting

## First-time setup

- Preferred guided setup:
  `python scripts/bootstrap.py`
- Environment check only:
  `python scripts/check_env.py`
- Dependency installation only:
  `python scripts/install_deps.py`
- Minimal local verification:
  `python scripts/video_summary.py --help`

If `uv` is installed, the bootstrap flow uses `uv sync --project <skill-dir>`.
If `uv` is unavailable, it falls back to `python -m pip install ...`.

## Environment and dependencies

- Python too old:
  the skill expects Python 3.10 or newer.
- Missing dependency error from `video_summary.py`:
  run `python scripts/bootstrap.py` and then retry.
- `av` import fails during frame extraction:
  rerun the installer and verify that the current Python environment can import `av`.
- `faster-whisper` import fails:
  rerun `python scripts/install_deps.py` in the same interpreter environment that will run the skill.

## Transcript extraction

- `youtube-transcript-api` fails:
  try `--force-method subs` or `--force-method transcribe`.
- `yt-dlp` cannot find subtitles:
  try `--force-method transcribe`.
- Restricted or age-gated videos:
  this project targets public videos and does not implement a browser-cookie workflow.
- Xiaohongshu:
  some posts fail in `yt-dlp` subtitle or media extraction; the current script includes an HTML fallback for share pages.
- Douyin:
  subtitles often require fresh cookies, but the current script can still fall back to share-page parsing and local transcription for many public posts.
- X:
  subtitle availability is uncommon; expect the transcription fallback to be used more often.

## Local transcription

- First transcription can be slow:
  `faster-whisper` may download the selected model on first use.
- CPU-only machines:
  prefer `--transcribe-model tiny` or `--transcribe-model base` first.
- If transcription fails immediately after installation:
  run `python scripts/check_env.py` to confirm the package imports succeeded in the current interpreter.

## Visual pass

- `--include-frames` downloads the video temporarily.
- A vision-capable model is optional:
  transcript-first summaries do not require one.
- If you want auto-cleanup and still need visual understanding, configure `--vision-model` or `VIDEO_SUMMARY_VISION_MODEL`.
- If the automatic frame-description endpoint is not reachable, verify `--vision-host` or `VIDEO_SUMMARY_VISION_HOST`.
- The bundled client currently expects an Ollama-compatible `/api/chat` endpoint.
- The vision model can be different from your main chat model.
- For a quick local check before a visual run:
  use `python scripts/check_env.py`, then verify your vision model and host settings separately.

## Temp files

- By default the script cleans up temporary downloads before exiting.
- Use `--keep-artifacts` only for debugging or manual inspection.
