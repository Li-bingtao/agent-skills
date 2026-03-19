# Troubleshooting

## Transcript extraction

- `youtube-transcript-api` fails:
  try `--force-method subs` or `--force-method transcribe`.
- `yt-dlp` cannot find subtitles:
  try `--force-method transcribe`.
- Restricted or age-gated videos:
  this project targets public videos and does not implement a browser-cookie workflow.

## Local transcription

- First transcription can be slow:
  `faster-whisper` may download the selected model on first use.
- CPU-only machines:
  prefer `--transcribe-model tiny` or `--transcribe-model base` first.

## Visual pass

- `--include-frames` downloads the video temporarily.
- If you want auto-cleanup and still need visual understanding, provide a local Ollama vision model with `--vision-model` or `YOUTUBE_SUMMARY_VISION_MODEL`.
- If Ollama is not reachable, verify `YOUTUBE_SUMMARY_OLLAMA_HOST` or start Ollama on `http://127.0.0.1:11434`.

## Temp files

- By default the script cleans up temporary downloads before exiting.
- Use `--keep-artifacts` only for debugging or manual inspection.
