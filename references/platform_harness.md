# Platform Harness

Use this guide only when a user gives a public video link that is outside the currently supported platform list, or when an existing platform needs a new fallback path.

## Goal

Extend the current `video-summary` skill with the smallest viable platform adapter while preserving the existing workflow:

1. existing transcript if available
2. subtitle download if available
3. local transcription fallback
4. optional visual pass
5. auto-clean temp files by default

## Adapter contract

For a new platform, answer these questions before editing code:

1. How is the platform detected from the URL or host?
2. Can public metadata be extracted with `yt-dlp` already?
3. If `yt-dlp` fails, does the share page HTML expose:
   title, author, description, cover, duration, media URLs, tags, or timestamps?
4. Does the platform prefer a specific language ordering?
5. Does it need a share-page fallback, cookies, or both?
6. Can the same direct media URL be reused for both transcription and frame extraction?

## Minimal implementation path

When adding support, prefer this order:

1. Add host detection in `detect_platform()`.
2. Add any platform-specific default language preference if needed.
3. Keep `yt-dlp` as the first metadata and media attempt.
4. Only if needed, add one HTML fallback helper that extracts:
   metadata and a direct media URL from the public share page.
5. Reuse `download_audio()`, `download_video()`, transcript chunking, heuristics, and cleanup logic.
6. Avoid adding platform-specific summary logic.

## Validation checklist

Before considering the platform supported:

1. Run the script on the triggering URL.
2. Confirm `video.title` and platform metadata are not empty placeholders.
3. Confirm at least one extraction path reaches transcript text or a justified visual-only recommendation.
4. Confirm temp files are auto-cleaned when `--keep-artifacts` is not used.
5. Update `SKILL.md`, `README.md`, and `agents/openai.yaml` if platform support changed.

## Constraints

- Prefer adapting the existing script over adding a second script.
- Keep changes local and composable.
- Do not silently switch to paid APIs.
- Do not require OpenClaw specifically.
- Do not make image recognition mandatory for the base transcript path.
