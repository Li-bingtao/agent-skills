---
name: video-summary
description: Summarize supported online videos locally without paid APIs. The current implementation supports YouTube, Bilibili, Xiaohongshu, Douyin, and X, with a transcript-first fallback chain and an optional vision-assisted pass.
license: MIT
user-invocable: true
metadata: {"openclaw":{"requires":{"anyBins":["uv","python","python3","py"]}}}
---

# Video Summary

Use this skill when the user gives a supported video URL and wants a summary, notes, transcript digest, chapter outline, or study guide.

Current scope:

- YouTube URLs and bare YouTube video ids
- Bilibili video URLs
- Xiaohongshu video note URLs
- Douyin share and video URLs
- X post URLs with playable video
- the skill name is intentionally broader because future adapters may add more platforms

This skill is chat-first:

- final output belongs in the conversation
- temporary files are internal and auto-cleaned by default
- do not create Obsidian notes or other persistent documents unless the user explicitly asks

## Preferred runner

If `uv` exists, prefer:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/video_summary.py" "<video-url>"
```

If `uv` is unavailable but Python is installed and dependencies are already present, use:

```bash
python "{baseDir}/scripts/video_summary.py" "<video-url>"
```

## Workflow

1. Decide whether transcript-only is enough.
2. If the video is lecture-heavy, interview-heavy, podcast-like, or otherwise speech-dominant, start with text-only.
3. Run the helper script and read the JSON it prints to stdout.
4. Summarize from `transcript.text` or `transcript.chunks`.
5. Mention which extraction path succeeded: `api`, `subs`, or `transcribe`.
6. If the script reports `heuristics.visual_pass_recommended = true`, use that as a signal that the transcript is sparse and visuals may matter.
7. Before replying, run a final text review for length, clarity, evidence, and policy compliance.

## Self-Extension

This skill is allowed to iteratively extend itself when the user provides a public video link from an unsupported or partially supported platform.

When a new platform fails current extraction:

1. Confirm whether the failure is due to platform support, temporary anti-bot behavior, or a bad link.
2. Inspect the share page or public HTML for recoverable metadata, text, cover images, or direct media URLs.
3. Reuse the existing transcript-first pipeline instead of inventing a new workflow.
4. Extend platform detection and add the smallest adapter or fallback needed.
5. Preserve the existing behavior:
   transcript first, visual pass optional, temp files auto-cleaned by default.
6. Validate the new path on the triggering URL before claiming support.
7. Update this skill's docs so the new support is explicit.

Read [references/platform_harness.md](references/platform_harness.md) when you need to extend support to a new platform.

## Human-in-the-Loop rules

- For lecture, tutorial, interview, and talk-head videos:
  default to text-only unless the user explicitly wants visuals included.
- For short films, gameplay, reaction videos, slide-heavy demos, whiteboard videos, or videos with sparse transcripts:
  ask whether to include a visual pass.
- A visual pass downloads a temporary local video file.
- Before running a visual pass, tell the user it will temporarily download the video.
- Unless the user explicitly asks to keep downloaded files for inspection or debugging:
  do not use `--keep-artifacts`.
- If a vision-capable model endpoint is not configured:
  say that transcript-only is available now, and visual understanding needs `VIDEO_SUMMARY_VISION_MODEL` or `--vision-model`.
- Do not ask whether to delete the video cache when `--keep-artifacts` is not used:
  the script auto-cleans temp files.
- Only ask about cleanup if you intentionally run with `--keep-artifacts`.
- If you temporarily keep artifacts for manual inspection:
  delete them before replying unless the user explicitly asked to retain them.

## Visual pass commands

If the user approves image-aware understanding and a vision-capable model endpoint is configured:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/video_summary.py" "<video-url>" --include-frames
```

If you need to override the vision settings explicitly:

```bash
uv run --project "{baseDir}" "{baseDir}/scripts/video_summary.py" "<video-url>" --include-frames --vision-model gemma3 --vision-host http://127.0.0.1:11434
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
- Default to a concise, high-signal version first unless the user explicitly asked for a detailed output.
- If the user asked for a summary, summarize rather than paraphrasing the full transcript.
- If the transcript is long, synthesize from the chunk list instead of copying large passages.
- If a visual pass was used, clearly say that the result combines transcript and frame descriptions.
- If only transcript extraction succeeded, clearly say the result is transcript-based.
- Unless the user already asked for a detailed version:
  end with one short follow-up asking whether they want a more detailed version.
- Run the final response through the checklist in [references/final_review.md](references/final_review.md) before sending it.

Read [references/troubleshooting.md](references/troubleshooting.md) only when extraction or vision steps fail.
Read [references/platform_harness.md](references/platform_harness.md) only when you need to extend support to a new platform.
Read [references/final_review.md](references/final_review.md) only when drafting the final user-facing answer.
