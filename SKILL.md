---
name: youtube-summary
description: Summarize a YouTube video locally without paid APIs. Pull an existing transcript first, fall back to yt-dlp subtitles, then local faster-whisper transcription. Optionally use a local Ollama vision model on extracted frames for visual-heavy videos.
user-invocable: true
metadata: {"openclaw":{"requires":{"anyBins":["uv","python","python3","py"]}}}
---

# YouTube Summary

Use this skill when the user gives a YouTube URL or video id and wants a summary, notes, transcript digest, chapter outline, or study guide.

This skill is chat-first:

- final output belongs in the conversation
- temporary files are internal and auto-cleaned by default
- do not create Obsidian notes or other persistent documents unless the user explicitly asks

## Preferred runner

If `uv` exists, prefer:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/youtube_summary.py" "<youtube-url>"
```

If `uv` is unavailable but Python is installed and dependencies are already present, use:

```bash
python "{baseDir}/scripts/youtube_summary.py" "<youtube-url>"
```

## Workflow

1. Decide whether transcript-only is enough.
2. If the video is lecture-heavy, interview-heavy, podcast-like, or otherwise speech-dominant, start with text-only.
3. Run the helper script and read the JSON it prints to stdout.
4. Summarize from `transcript.text` or `transcript.chunks`.
5. Mention which extraction path succeeded: `api`, `subs`, or `transcribe`.
6. If the script reports `heuristics.visual_pass_recommended = true`, use that as a signal that the transcript is sparse and visuals may matter.

## Human-in-the-Loop rules

- For lecture, tutorial, interview, and talk-head videos:
  default to text-only unless the user explicitly wants visuals included.
- For short films, gameplay, reaction videos, slide-heavy demos, whiteboard videos, or videos with sparse transcripts:
  ask whether to include a visual pass.
- A visual pass downloads a temporary local video file.
- Before running a visual pass, tell the user it will temporarily download the video.
- If a local vision model is not configured:
  say that transcript-only is available now, and visual understanding needs `YOUTUBE_SUMMARY_VISION_MODEL` or `--vision-model`.
- Do not ask whether to delete the video cache when `--keep-artifacts` is not used:
  the script auto-cleans temp files.
- Only ask about cleanup if you intentionally run with `--keep-artifacts`.

## Visual pass commands

If the user approves image-aware understanding and a local Ollama vision model is configured:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/youtube_summary.py" "<youtube-url>" --include-frames
```

If you need to override the vision model explicitly:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/youtube_summary.py" "<youtube-url>" --include-frames --vision-model gemma3
```

## Output fields

The helper prints a JSON object with these important fields:

- `video`
- `extraction`
- `heuristics`
- `transcript.text`
- `transcript.chunks`
- `visual.frames`
- `warnings`

Use those fields directly in your response. Do not dump the raw JSON back to the user.

## Response rules

- Give the user a direct answer in chat.
- Keep the answer in the user's requested language.
- If the user asked for a summary, summarize rather than paraphrasing the full transcript.
- If the transcript is long, synthesize from the chunk list instead of copying large passages.
- If a visual pass was used, clearly say that the result combines transcript and frame descriptions.
- If only transcript extraction succeeded, clearly say the result is transcript-based.

Read [references/troubleshooting.md](references/troubleshooting.md) only when extraction or vision steps fail.
