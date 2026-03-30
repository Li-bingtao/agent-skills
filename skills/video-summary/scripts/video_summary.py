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
from datetime import datetime, timezone
from functools import lru_cache
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
CHINESE_FIRST_LANGUAGES = ["zh", "zh-Hans", "zh-Hant", "en"]
CHINESE_FIRST_PLATFORMS = {"bilibili", "xiaohongshu", "douyin"}
SCRIPT_DIR = Path(__file__).resolve().parent
DOUYIN_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; Mobile) "
    "AppleWebKit/537.36 Chrome/122.0.0.0 Mobile Safari/537.36"
)


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
            "Prepare chat-friendly JSON for summarizing a supported online video "
            "without paid APIs."
        )
    )
    parser.add_argument("url", help="Supported video URL or bare video id")
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
        default=(
            os.environ.get("VIDEO_SUMMARY_TRANSCRIBE_MODEL")
            or os.environ.get("YOUTUBE_SUMMARY_TRANSCRIBE_MODEL")
            or "base"
        ),
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
        default=(
            os.environ.get("VIDEO_SUMMARY_VISION_MODEL")
            or os.environ.get("YOUTUBE_SUMMARY_VISION_MODEL")
        ),
        help="Optional vision-capable model identifier for automatic frame descriptions.",
    )
    parser.add_argument(
        "--vision-base-url",
        dest="vision_base_url",
        default=(
            os.environ.get("VIDEO_SUMMARY_VISION_BASE_URL")
            or os.environ.get("YOUTUBE_SUMMARY_VISION_BASE_URL")
            or os.environ.get("VIDEO_SUMMARY_VISION_HOST")
            or os.environ.get("YOUTUBE_SUMMARY_VISION_HOST")
        ),
        help=(
            "Base URL for an OpenAI-compatible vision API, for example "
            "http://127.0.0.1:1234/v1 or https://api.openai.com/v1."
        ),
    )
    parser.add_argument(
        "--vision-api-key",
        default=(
            os.environ.get("VIDEO_SUMMARY_VISION_API_KEY")
            or os.environ.get("YOUTUBE_SUMMARY_VISION_API_KEY")
        ),
        help=(
            "Optional API key for the vision API. "
            "Leave unset for local endpoints that do not require authentication."
        ),
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
        bootstrap_cmd = f'"{sys.executable}" "{SCRIPT_DIR / "bootstrap.py"}"'
        install_cmd = f'"{sys.executable}" "{SCRIPT_DIR / "install_deps.py"}"'
        raise RuntimeError(
            f"Missing dependency '{package_name}'. Run {bootstrap_cmd} for guided setup, "
            f"or {install_cmd} to install dependencies directly."
        ) from exc
    return module


def detect_platform(url_or_id: str) -> str:
    raw = url_or_id.strip()
    if re.fullmatch(r"[\w-]{11}", raw):
        return "youtube"

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if not host:
        raise ValueError("Input is not a recognized video URL or supported bare video id.")

    if host in YOUTUBE_HOSTS:
        return "youtube"

    if host.endswith("bilibili.com") or host == "b23.tv":
        return "bilibili"

    if host.endswith("xiaohongshu.com") or host == "xhslink.com":
        return "xiaohongshu"

    if host.endswith("douyin.com") or host.endswith("iesdouyin.com"):
        return "douyin"

    if host.endswith("x.com") or host.endswith("twitter.com") or host == "t.co":
        return "x"

    return "generic"


def effective_languages(selected: list[str], platform: str) -> list[str]:
    if selected != DEFAULT_LANGUAGES:
        return selected
    if platform in CHINESE_FIRST_PLATFORMS:
        return CHINESE_FIRST_LANGUAGES
    return selected


def extract_youtube_video_id(url_or_id: str) -> str:
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


def fetch_webpage_text(
    url: str,
    *,
    referer: str | None = None,
    user_agent: str | None = None,
) -> str:
    headers = {"User-Agent": user_agent or "Mozilla/5.0"}
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def decode_escaped_json_string(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace("\\/", "/")


def extract_xiaohongshu_note_id(url: str) -> str | None:
    match = re.search(r"/explore/([0-9a-zA-Z]+)", urlparse(url).path)
    if match:
        return match.group(1)
    return None


def build_xiaohongshu_context(page_html: str, note_id: str | None) -> str:
    if note_id:
        anchor = page_html.find(f'"noteId":"{note_id}"')
        if anchor != -1:
            start = max(0, anchor - 6000)
            end = min(len(page_html), anchor + 60000)
            return page_html[start:end]
    return page_html


def extract_douyin_aweme_id(url: str) -> str | None:
    path = urlparse(url).path
    match = re.search(r"/(?:share/)?video/(\d+)", path)
    if match:
        return match.group(1)
    return None


def build_douyin_context(page_html: str, aweme_id: str | None) -> str:
    if aweme_id:
        anchor = page_html.find(f'"aweme_id":"{aweme_id}"')
        if anchor == -1:
            anchor = page_html.find(f'"itemId":"{aweme_id}"')
        if anchor != -1:
            start = max(0, anchor - 6000)
            end = min(len(page_html), anchor + 60000)
            return page_html[start:end]
    return page_html


def extract_first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    return decode_escaped_json_string(match.group(1))


@lru_cache(maxsize=16)
def fetch_xiaohongshu_note_data(url: str) -> dict[str, Any]:
    page_html = fetch_webpage_text(url)
    note_id = extract_xiaohongshu_note_id(url)
    context = build_xiaohongshu_context(page_html, note_id)

    title = extract_first_match(context, r'"displayTitle":"((?:[^"\\]|\\.)*)"')
    uploader = extract_first_match(context, r'"nickname":"((?:[^"\\]|\\.)*)"')
    description = clean_text(extract_first_match(context, r'"desc":"((?:[^"\\]|\\.)*)"') or "")
    thumbnail = extract_first_match(
        context,
        r'"cover":\{.*?"urlDefault":"((?:[^"\\]|\\.)*)"',
    ) or extract_first_match(
        context,
        r'"imageList":\[\{.*?"urlDefault":"((?:[^"\\]|\\.)*)"',
    )
    stream_url = extract_first_match(context, r'"masterUrl":"((?:[^"\\]|\\.)*)"')
    duration_raw = extract_first_match(context, r'"capa":\{"duration":(\d+)\}')
    if duration_raw is None:
        duration_raw = extract_first_match(context, r'"video":\{.*?"duration":(\d+)')
    duration = float(duration_raw) if duration_raw else None
    time_raw = extract_first_match(context, r'"time":(\d{13})')
    upload_date = None
    if time_raw:
        upload_date = datetime.fromtimestamp(
            int(time_raw) / 1000,
            tz=timezone.utc,
        ).strftime("%Y%m%d")
    tags = [
        clean_text(tag)
        for tag in re.findall(r'"name":"((?:[^"\\]|\\.)*)","type":"topic"', context)
    ]
    tags = [tag for tag in tags if tag]

    if not note_id and not stream_url and not title:
        raise RuntimeError("Could not extract Xiaohongshu note metadata from the share page.")

    return {
        "id": note_id,
        "title": title or note_id or url,
        "uploader": uploader,
        "channel": None,
        "duration": duration,
        "description": description or None,
        "webpage_url": url,
        "upload_date": upload_date,
        "chapters": [],
        "thumbnail": thumbnail,
        "tags": tags,
        "stream_url": stream_url,
    }


@lru_cache(maxsize=16)
def fetch_douyin_note_data(url: str) -> dict[str, Any]:
    page_html = fetch_webpage_text(url, user_agent=DOUYIN_MOBILE_USER_AGENT)
    aweme_id = extract_douyin_aweme_id(url)
    context = build_douyin_context(page_html, aweme_id)
    if not aweme_id:
        aweme_id = extract_first_match(context, r'"aweme_id":"(\d+)"') or extract_first_match(
            context,
            r'"itemId":"(\d+)"',
        )

    description = clean_text(extract_first_match(context, r'"desc":"((?:[^"\\]|\\.)*)"') or "")
    uploader = extract_first_match(context, r'"nickname":"((?:[^"\\]|\\.)*)"')
    title = description or extract_first_match(
        page_html,
        r'<meta[^>]+name="description"[^>]+content="((?:[^"\\]|\\.)*)"',
    )
    cover = extract_first_match(
        context,
        r'"cover":\{.*?"url_list":\["((?:[^"\\]|\\.)*)"',
    )
    stream_url = extract_first_match(
        context,
        r'"play_addr":\{.*?"url_list":\["((?:[^"\\]|\\.)*)"',
    )
    create_time = extract_first_match(context, r'"create_time":(\d{10})')
    duration_raw = extract_first_match(context, r'"duration":(\d{2,6})')
    duration = None
    if duration_raw:
        duration = float(duration_raw)
        if duration > 1000:
            duration /= 1000.0
    upload_date = None
    if create_time:
        upload_date = datetime.fromtimestamp(
            int(create_time),
            tz=timezone.utc,
        ).strftime("%Y%m%d")
    tags = [clean_text(tag) for tag in re.findall(r"#([^\s#]+)", description)]
    tags = [tag for tag in tags if tag]

    if not aweme_id and not stream_url and not title:
        raise RuntimeError("Could not extract Douyin metadata from the share page.")

    return {
        "id": aweme_id,
        "title": title or aweme_id or url,
        "uploader": uploader,
        "channel": None,
        "duration": duration,
        "description": description or None,
        "webpage_url": url,
        "upload_date": upload_date,
        "chapters": [],
        "thumbnail": cover,
        "tags": tags,
        "stream_url": stream_url,
    }


def download_direct_media(
    url: str,
    destination: Path,
    *,
    referer: str | None = None,
    user_agent: str | None = None,
) -> Path:
    headers = {"User-Agent": user_agent or "Mozilla/5.0"}
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def collect_metadata(url: str) -> dict[str, Any]:
    yt_dlp = require_module("yt_dlp", "yt-dlp")
    try:
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
    except Exception:
        platform = detect_platform(url)
        if platform == "xiaohongshu":
            note = fetch_xiaohongshu_note_data(url)
            return {
                key: note.get(key)
                for key in [
                    "id",
                    "title",
                    "uploader",
                    "channel",
                    "duration",
                    "description",
                    "webpage_url",
                    "upload_date",
                    "chapters",
                    "thumbnail",
                    "tags",
                ]
            }
        if platform == "douyin":
            note = fetch_douyin_note_data(url)
            return {
                key: note.get(key)
                for key in [
                    "id",
                    "title",
                    "uploader",
                    "channel",
                    "duration",
                    "description",
                    "webpage_url",
                    "upload_date",
                    "chapters",
                    "thumbnail",
                    "tags",
                ]
            }
        raise


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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return find_downloaded_media(media_dir, "audio.")
    except Exception:
        platform = detect_platform(url)
        if platform == "xiaohongshu":
            note = fetch_xiaohongshu_note_data(url)
            stream_url = note.get("stream_url")
            if not stream_url:
                raise RuntimeError("Xiaohongshu fallback could not find a direct media URL.")
            return download_direct_media(stream_url, media_dir / "audio.mp4", referer=url)
        if platform != "douyin":
            raise
        note = fetch_douyin_note_data(url)
        stream_url = note.get("stream_url")
        if not stream_url:
            raise RuntimeError("Douyin fallback could not find a direct media URL.")
        return download_direct_media(
            stream_url,
            media_dir / "audio.mp4",
            referer=url,
            user_agent=DOUYIN_MOBILE_USER_AGENT,
        )


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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return find_downloaded_media(media_dir, "video.")
    except Exception:
        platform = detect_platform(url)
        if platform == "xiaohongshu":
            note = fetch_xiaohongshu_note_data(url)
            stream_url = note.get("stream_url")
            if not stream_url:
                raise RuntimeError("Xiaohongshu fallback could not find a direct video URL.")
            return download_direct_media(stream_url, media_dir / "video.mp4", referer=url)
        if platform != "douyin":
            raise
        note = fetch_douyin_note_data(url)
        stream_url = note.get("stream_url")
        if not stream_url:
            raise RuntimeError("Douyin fallback could not find a direct video URL.")
        return download_direct_media(
            stream_url,
            media_dir / "video.mp4",
            referer=url,
            user_agent=DOUYIN_MOBILE_USER_AGENT,
        )


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


def extract_vision_text(content: Any) -> str:
    if isinstance(content, str):
        return clean_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("type") == "output_text" and item.get("text"):
                    parts.append(str(item["text"]))
        return clean_text(" ".join(parts))
    return ""


def build_vision_api_url(vision_base_url: str) -> str:
    base = vision_base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def describe_frame_with_vision_api(
    image_path: Path,
    model: str,
    vision_base_url: str,
    vision_api_key: str | None,
    timestamp: str,
) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    prompt = (
        f"This frame comes from a video at {timestamp}. "
        "Describe only the visual content that matters for understanding the video. "
        "Mention visible text, slides, UI, diagrams, people, actions, or scene changes. "
        "Keep it to at most two concise sentences."
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ],
            }
        ],
        "max_tokens": 180,
    }
    headers = {"Content-Type": "application/json"}
    if vision_api_key:
        headers["Authorization"] = f"Bearer {vision_api_key}"
    request = Request(
        url=build_vision_api_url(vision_base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    choices = body.get("choices") or []
    first_choice = choices[0] if choices else {}
    message = first_choice.get("message") or {}
    content = extract_vision_text(message.get("content"))
    if not content:
        raise RuntimeError(f"Vision endpoint returned an empty description for {image_path.name}.")
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
        platform = detect_platform(args.url)
        languages = effective_languages(args.languages, platform)
        video_id = extract_youtube_video_id(args.url) if platform == "youtube" else None
        try:
            metadata = collect_metadata(args.url)
        except Exception:
            metadata = {
                "id": video_id or args.url,
                "title": video_id or args.url,
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
            work_dir = Path(tempfile.mkdtemp(prefix="video-summary-"))

        subtitles_dir = work_dir / "subtitles"
        media_dir = work_dir / "media"
        frames_dir = work_dir / "frames"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)

        default_methods = ["api", "subs", "transcribe"] if platform == "youtube" else ["subs", "transcribe"]
        methods = [args.force_method] if args.force_method else default_methods
        segments: list[Segment] = []
        method_used = ""
        method_details: dict[str, Any] = {}
        attempts: list[dict[str, str]] = []

        for method in methods:
            try:
                if method == "api":
                    if platform != "youtube" or not video_id:
                        raise RuntimeError("Transcript API fallback is only implemented for YouTube.")
                    segments, method_details = fetch_with_transcript_api(video_id, languages)
                elif method == "subs":
                    segments, method_details = fetch_with_ytdlp_subtitles(
                        args.url,
                        subtitles_dir,
                        languages,
                    )
                elif method == "transcribe":
                    audio_path = download_audio(args.url, media_dir)
                    segments, method_details = transcribe_audio(
                        audio_path,
                        args.transcribe_model,
                        language_hint_from_preferences(languages),
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
                    if not args.vision_base_url:
                        raise RuntimeError(
                            "A vision base URL is required for automatic frame descriptions. "
                            "Set --vision-base-url or VIDEO_SUMMARY_VISION_BASE_URL."
                        )
                    for frame in visual_frames:
                        description = describe_frame_with_vision_api(
                            Path(frame["path"]),
                            args.vision_model,
                            args.vision_base_url,
                            args.vision_api_key,
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
            method_details={"platform": platform, **method_details},
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
