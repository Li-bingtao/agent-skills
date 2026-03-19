from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


YOUTUBE_HOSTS = {
    "youtu.be",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}

DEFAULT_LANGUAGES = ["en", "zh-Hans", "zh-Hant", "zh"]
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


@dataclass
class Segment:
    start: float
    duration: float
    text: str


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare chat-friendly JSON for summarizing a single YouTube video "
            "without paid APIs."
        )
    )
    parser.add_argument("url", help="YouTube video URL or bare video id")
    parser.add_argument(
        "--languages",
        nargs="+",
        default=DEFAULT_LANGUAGES,
        help="Preferred transcript/subtitle languages in priority order.",
    )
    parser.add_argument(
        "--force-method",
        choices=["api", "subs", "transcribe"],
        help="Run only one extraction method for debugging.",
    )
    parser.add_argument(
        "--transcribe-model",
        default=os.environ.get("YOUTUBE_SUMMARY_TRANSCRIBE_MODEL", "base"),
        help="faster-whisper model for the transcription fallback.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=8000,
        help="Approximate max characters per transcript chunk.",
    )
    parser.add_argument(
        "--include-frames",
        action="store_true",
        help="Download the video temporarily and extract representative frames.",
    )
    parser.add_argument(
        "--frame-count",
        type=int,
        default=6,
        help="Representative frame count when --include-frames is used.",
    )
    parser.add_argument(
        "--vision-model",
        default=os.environ.get("YOUTUBE_SUMMARY_VISION_MODEL"),
        help="Optional local Ollama vision model name for frame descriptions.",
    )
    parser.add_argument(
        "--ollama-host",
        default=os.environ.get("YOUTUBE_SUMMARY_OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        help="Ollama host for frame description requests.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep temp files instead of cleaning them up before exit.",
    )
    parser.add_argument(
        "--work-dir",
        help="Explicit work directory. Useful together with --keep-artifacts.",
    )
    return parser.parse_args()


def require_module(module_name: str, package_name: str) -> Any:
    try:
        module = __import__(module_name, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency '{package_name}'. Install it with "
            f"'uv sync' in the project root, or "
            f"'python -m pip install {package_name}'."
        ) from exc
    return module


def extract_video_id(url_or_id: str) -> str:
    raw = url_or_id.strip()
    if re.fullmatch(r"[\w-]{11}", raw):
        return raw

    parsed = urlparse(raw)
    if parsed.netloc.lower() not in YOUTUBE_HOSTS:
        raise ValueError("Input is not a recognized YouTube URL or video id.")

    if parsed.netloc.lower() == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        if re.fullmatch(r"[\w-]{11}", candidate):
            return candidate

    query = parse_qs(parsed.query)
    if "v" in query:
        candidate = query["v"][0]
        if re.fullmatch(r"[\w-]{11}", candidate):
            return candidate

    parts = [part for part in parsed.path.split("/") if part]
    for idx, part in enumerate(parts):
        if part in {"shorts", "embed", "live"} and idx + 1 < len(parts):
            candidate = parts[idx + 1]
            if re.fullmatch(r"[\w-]{11}", candidate):
                return candidate

    raise ValueError("Could not extract a YouTube video id from the input.")


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\u200b", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minute:02d}:{sec:02d}"
    return f"{minute:02d}:{sec:02d}"


def normalize_segments(raw_segments: list[dict[str, Any]]) -> list[Segment]:
    normalized: list[Segment] = []
    for raw in raw_segments:
        text = clean_text(str(raw.get("text", "")))
        if not text:
            continue
        start = float(raw.get("start", 0.0))
        duration = float(raw.get("duration", 0.0))
        if normalized:
            previous = normalized[-1]
            gap = start - (previous.start + previous.duration)
            if previous.text == text and gap <= 1.0:
                previous.duration = max(previous.duration, start + duration - previous.start)
                continue
        normalized.append(Segment(start=start, duration=duration, text=text))
    return normalized


def segments_to_plain_text(segments: list[Segment]) -> str:
    return "\n".join(segment.text for segment in segments)


def chunk_segments(segments: list[Segment], max_chars: int) -> list[dict[str, Any]]:
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    current_chars = 0

    for segment in segments:
        line = f"{segment.text}\n"
        if current and current_chars + len(line) > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += len(line)

    if current:
        chunks.append(current)

    payload: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        start = chunk[0].start
        end = chunk[-1].start + chunk[-1].duration
        text = "\n".join(
            f"[{format_timestamp(segment.start)}] {segment.text}" for segment in chunk
        )
        payload.append(
            {
                "index": index,
                "start_seconds": start,
                "end_seconds": end,
                "start": format_timestamp(start),
                "end": format_timestamp(end),
                "char_count": len(text),
                "text": text,
            }
        )
    return payload


def parse_subtitle_timestamp(value: str) -> float:
    value = value.replace(",", ".")
    pieces = value.split(":")
    if len(pieces) == 2:
        hours = 0
        minutes = int(pieces[0])
        seconds = float(pieces[1])
    elif len(pieces) == 3:
        hours = int(pieces[0])
        minutes = int(pieces[1])
        seconds = float(pieces[2])
    else:
        raise ValueError(f"Unsupported subtitle timestamp: {value}")
    return hours * 3600 + minutes * 60 + seconds


def parse_timestamp_pair(line: str) -> tuple[float, float] | None:
    match = re.search(
        r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})",
        line,
    )
    if not match:
        return None
    return parse_subtitle_timestamp(match.group("start")), parse_subtitle_timestamp(
        match.group("end")
    )


def parse_subtitle_file(path: Path) -> list[Segment]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    raw_segments: list[dict[str, Any]] = []
    start: float | None = None
    end: float | None = None
    text_lines: list[str] = []

    def flush() -> None:
        nonlocal start, end, text_lines
        if start is None or end is None:
            text_lines = []
            return
        text = clean_text(" ".join(text_lines))
        if text:
            raw_segments.append(
                {
                    "start": start,
                    "duration": max(0.0, end - start),
                    "text": text,
                }
            )
        start = None
        end = None
        text_lines = []

    for line in lines:
        stripped = line.strip().lstrip("\ufeff")
        timestamp_pair = parse_timestamp_pair(stripped)
        if timestamp_pair:
            flush()
            start, end = timestamp_pair
            continue
        if not stripped:
            flush()
            continue
        if stripped == "WEBVTT" or stripped.startswith("NOTE"):
            continue
        if stripped.startswith("Kind:") or stripped.startswith("Language:"):
            continue
        if stripped.isdigit():
            continue
        text_lines.append(stripped)

    flush()
    return normalize_segments(raw_segments)


class QuietLogger:
    def debug(self, _message: str) -> None:
        return

    def warning(self, _message: str) -> None:
        return

    def error(self, _message: str) -> None:
        return


def build_ydl_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "logger": QuietLogger(),
        "compat_opts": {"no-youtube-unavailable-videos"},
    }


def collect_metadata(url: str) -> dict[str, Any]:
    yt_dlp = require_module("yt_dlp", "yt-dlp")
    with yt_dlp.YoutubeDL({**build_ydl_opts(), "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "duration": info.get("duration"),
        "description": info.get("description"),
        "webpage_url": info.get("webpage_url") or url,
        "upload_date": info.get("upload_date"),
        "chapters": info.get("chapters") or [],
        "thumbnail": info.get("thumbnail"),
        "tags": info.get("tags") or [],
    }


def fetch_with_transcript_api(
    video_id: str, languages: list[str]
) -> tuple[list[Segment], dict[str, Any]]:
    transcript_api = require_module(
        "youtube_transcript_api",
        "youtube-transcript-api",
    )
    api = transcript_api.YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=languages)
    segments = normalize_segments(
        [
            {
                "start": snippet.start,
                "duration": snippet.duration,
                "text": snippet.text,
            }
            for snippet in fetched
        ]
    )
    return segments, {
        "language": fetched.language,
        "language_code": fetched.language_code,
        "is_generated": fetched.is_generated,
    }


def expand_subtitle_languages(languages: list[str]) -> list[str]:
    expanded: list[str] = []
    for language in languages:
        expanded.append(language)
        if language == "en":
            expanded.append("en.*")
        if language.startswith("zh"):
            expanded.append("zh.*")
    return list(dict.fromkeys(expanded))


def choose_subtitle_file(directory: Path, preferred_languages: list[str]) -> Path:
    candidates = sorted(
        [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".vtt", ".srt"}
        ]
    )
    if not candidates:
        raise FileNotFoundError("yt-dlp did not produce a subtitle file.")

    def score(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        language_rank = 999
        for index, language in enumerate(preferred_languages):
            needle = language.lower().replace("*", "")
            if needle and needle in name:
                language_rank = index
                break
        format_rank = 0 if path.suffix.lower() == ".vtt" else 1
        return language_rank, format_rank, name

    return min(candidates, key=score)


def fetch_with_ytdlp_subtitles(
    url: str,
    subtitles_dir: Path,
    languages: list[str],
) -> tuple[list[Segment], dict[str, Any]]:
    yt_dlp = require_module("yt_dlp", "yt-dlp")
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    for language in languages:
        for path in subtitles_dir.glob("*"):
            if path.is_file():
                path.unlink()

        opts = {
            **build_ydl_opts(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": expand_subtitle_languages([language]),
            "subtitlesformat": "vtt/srt/best",
            "outtmpl": str(subtitles_dir / "source.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            subtitle_path = choose_subtitle_file(subtitles_dir, [language])
            segments = parse_subtitle_file(subtitle_path)
            if not segments:
                raise RuntimeError(f"Subtitle file was empty: {subtitle_path.name}")
            return segments, {
                "subtitle_file": str(subtitle_path),
                "subtitle_language_attempt": language,
            }
        except Exception as exc:
            errors.append(f"{language}: {exc}")

    raise RuntimeError("No subtitle download succeeded. " + " | ".join(errors))


def find_downloaded_media(directory: Path, stem_prefix: str) -> Path:
    candidates = sorted(
        [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.name.startswith(stem_prefix)
            and path.suffix.lower() not in {".part", ".tmp", ".temp"}
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No downloaded media found for prefix '{stem_prefix}'.")
    return candidates[0]


def download_audio(url: str, media_dir: Path) -> Path:
    yt_dlp = require_module("yt_dlp", "yt-dlp")
    media_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **build_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": str(media_dir / "audio.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return find_downloaded_media(media_dir, "audio.")


def transcribe_audio(
    audio_path: Path,
    model_name: str,
    language_hint: str | None,
) -> tuple[list[Segment], dict[str, Any]]:
    faster_whisper = require_module("faster_whisper", "faster-whisper")
    model = faster_whisper.WhisperModel(model_name, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language_hint,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    segments = normalize_segments(
        [
            {
                "start": segment.start,
                "duration": segment.end - segment.start,
                "text": segment.text,
            }
            for segment in segments_iter
        ]
    )
    if not segments:
        raise RuntimeError("Local transcription finished but returned no segments.")
    return segments, {
        "model": model_name,
        "detected_language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
    }


def download_video(url: str, media_dir: Path) -> Path:
    yt_dlp = require_module("yt_dlp", "yt-dlp")
    media_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        **build_ydl_opts(),
        "format": "best[ext=mp4][height<=720]/best[height<=720]/best[ext=mp4]/best",
        "outtmpl": str(media_dir / "video.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    return find_downloaded_media(media_dir, "video.")


def choose_frame_targets(duration: float | None, frame_count: int) -> list[int]:
    if not duration or duration <= 0:
        return [15, 45, 90, 135, 180, 225][:frame_count]
    if frame_count <= 1:
        return [max(1, int(duration * 0.5))]
    start = duration * 0.08
    end = duration * 0.92
    if end <= start:
        end = duration
    step = (end - start) / max(1, frame_count - 1)
    return sorted({max(0, int(start + index * step)) for index in range(frame_count)})


def extract_representative_frames(
    video_path: Path,
    frames_dir: Path,
    target_seconds: list[int],
) -> list[dict[str, Any]]:
    av = require_module("av", "av")
    frames_dir.mkdir(parents=True, exist_ok=True)
    remaining = sorted(target_seconds)
    captured: list[dict[str, Any]] = []

    container = av.open(str(video_path))
    stream = container.streams.video[0]
    for frame in container.decode(stream):
        if frame.time is None:
            continue
        current_time = float(frame.time)
        while remaining and current_time >= remaining[0]:
            target = remaining.pop(0)
            frame_index = len(captured) + 1
            image_path = frames_dir / f"frame-{frame_index:02d}-{target:04d}.jpg"
            frame.to_image().save(image_path, quality=90)
            captured.append(
                {
                    "index": frame_index,
                    "timestamp_seconds": target,
                    "timestamp": format_timestamp(target),
                    "path": str(image_path),
                }
            )
        if not remaining:
            break
    container.close()

    if remaining:
        raise RuntimeError(
            "Could not extract all requested frames. "
            f"Missing timestamps: {', '.join(str(item) for item in remaining)}"
        )

    return captured


def describe_frame_with_ollama(
    image_path: Path,
    model: str,
    ollama_host: str,
    timestamp: str,
) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    prompt = (
        f"This frame comes from a YouTube video at {timestamp}. "
        "Describe only the visual content that matters for understanding the video. "
        "Mention visible text, slides, UI, diagrams, people, actions, or scene changes. "
        "Keep it to at most two concise sentences."
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [encoded],
            }
        ],
    }
    request = Request(
        url=f"{ollama_host.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    message = body.get("message") or {}
    content = clean_text(str(message.get("content", "")))
    if not content:
        raise RuntimeError(f"Ollama returned an empty description for {image_path.name}.")
    return content


def build_heuristics(metadata: dict[str, Any], transcript_text: str) -> dict[str, Any]:
    duration = metadata.get("duration")
    word_count = len(transcript_text.split())
    words_per_minute = None
    visual_recommended = False
    reasons: list[str] = []

    if duration and duration > 0:
        words_per_minute = round(word_count / (duration / 60), 2)
        if words_per_minute < 55:
            visual_recommended = True
            reasons.append("Transcript density is low for the video duration.")

    title = (metadata.get("title") or "").lower()
    if any(token in title for token in ["short film", "trailer", "mv", "music video"]):
        visual_recommended = True
        reasons.append("Title suggests a visual-first video.")

    return {
        "words_per_minute": words_per_minute,
        "visual_pass_recommended": visual_recommended,
        "reasons": reasons,
    }


def language_hint_from_preferences(languages: list[str]) -> str | None:
    if not languages:
        return None
    language_hint = languages[0]
    if language_hint.startswith("zh"):
        return "zh"
    if language_hint in {"en", "zh"}:
        return language_hint
    return None


def build_output_payload(
    *,
    metadata: dict[str, Any],
    method_used: str,
    method_details: dict[str, Any],
    attempts: list[dict[str, str]],
    segments: list[Segment],
    chunk_chars: int,
    heuristics: dict[str, Any],
    visual_frames: list[dict[str, Any]],
    warnings: list[str],
    kept_work_dir: str | None,
) -> dict[str, Any]:
    transcript_text = segments_to_plain_text(segments)
    return {
        "ok": True,
        "video": metadata,
        "extraction": {
            "method_used": method_used,
            "method_details": method_details,
            "attempts": attempts,
        },
        "heuristics": heuristics,
        "transcript": {
            "segment_count": len(segments),
            "word_count": len(transcript_text.split()),
            "text": transcript_text,
            "chunks": chunk_segments(segments, chunk_chars),
        },
        "visual": {
            "enabled": bool(visual_frames),
            "vision_model": next(
                (
                    frame.get("vision_model")
                    for frame in visual_frames
                    if frame.get("vision_model")
                ),
                None,
            ),
            "frames": visual_frames,
        },
        "warnings": warnings,
        "artifacts": {
            "kept": bool(kept_work_dir),
            "work_dir": kept_work_dir,
        },
    }


def main() -> int:
    configure_stdio()
    args = parse_args()
    warnings: list[str] = []
    work_dir: Path | None = None

    try:
        video_id = extract_video_id(args.url)
        try:
            metadata = collect_metadata(args.url)
        except Exception:
            metadata = {
                "id": video_id,
                "title": video_id,
                "webpage_url": args.url,
                "duration": None,
                "description": None,
                "chapters": [],
                "tags": [],
            }

        if args.work_dir:
            work_dir = Path(args.work_dir).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)
        else:
            work_dir = Path(tempfile.mkdtemp(prefix="youtube-summary-"))

        subtitles_dir = work_dir / "subtitles"
        media_dir = work_dir / "media"
        frames_dir = work_dir / "frames"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)

        methods = [args.force_method] if args.force_method else ["api", "subs", "transcribe"]
        segments: list[Segment] = []
        method_used = ""
        method_details: dict[str, Any] = {}
        attempts: list[dict[str, str]] = []

        for method in methods:
            try:
                if method == "api":
                    segments, method_details = fetch_with_transcript_api(video_id, args.languages)
                elif method == "subs":
                    segments, method_details = fetch_with_ytdlp_subtitles(
                        args.url,
                        subtitles_dir,
                        args.languages,
                    )
                elif method == "transcribe":
                    audio_path = download_audio(args.url, media_dir)
                    segments, method_details = transcribe_audio(
                        audio_path,
                        args.transcribe_model,
                        language_hint_from_preferences(args.languages),
                    )
                    method_details["audio_file"] = str(audio_path)
                else:
                    raise RuntimeError(f"Unsupported method: {method}")
                if segments:
                    method_used = method
                    break
            except Exception as exc:
                attempts.append({"method": method, "error": str(exc)})

        if not method_used or not segments:
            raise RuntimeError(
                "All transcript extraction methods failed. "
                + " | ".join(f"{item['method']}: {item['error']}" for item in attempts)
            )

        transcript_text = segments_to_plain_text(segments)
        heuristics = build_heuristics(metadata, transcript_text)

        visual_frames: list[dict[str, Any]] = []
        if args.include_frames:
            if not args.vision_model and not args.keep_artifacts:
                warnings.append(
                    "Frames were requested without a vision model. "
                    "Temporary files would be deleted, so no frame descriptions were generated. "
                    "Use --vision-model or --keep-artifacts."
                )
            try:
                video_path = download_video(args.url, media_dir)
                frame_targets = choose_frame_targets(
                    metadata.get("duration"),
                    max(1, args.frame_count),
                )
                visual_frames = extract_representative_frames(video_path, frames_dir, frame_targets)
                if args.vision_model:
                    for frame in visual_frames:
                        description = describe_frame_with_ollama(
                            Path(frame["path"]),
                            args.vision_model,
                            args.ollama_host,
                            frame["timestamp"],
                        )
                        frame["description"] = description
                        frame["vision_model"] = args.vision_model
                elif not args.keep_artifacts:
                    visual_frames = []
            except Exception as exc:
                warnings.append(f"Visual pass failed: {exc}")
                visual_frames = []

        if not args.keep_artifacts:
            for frame in visual_frames:
                frame["path"] = None

        payload = build_output_payload(
            metadata=metadata,
            method_used=method_used,
            method_details=method_details,
            attempts=attempts,
            segments=segments,
            chunk_chars=args.chunk_chars,
            heuristics=heuristics,
            visual_frames=visual_frames,
            warnings=warnings,
            kept_work_dir=str(work_dir) if args.keep_artifacts else None,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        error_payload = {
            "ok": False,
            "error": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        return 1
    finally:
        if work_dir and not args.keep_artifacts:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
