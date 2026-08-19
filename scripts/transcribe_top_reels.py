#!/usr/bin/env python3
"""Collect comment-ranked Instagram Reels, retain audio, and transcribe it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import instaloader
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = DATA_ROOT / "processed"
AUDIO_ROOT = RAW_ROOT / "audio"

MODEL = "gpt-transcribe"
LANGUAGES = ["ko"]
MAX_OPENAI_FILE_BYTES = 25_000_000
COLLECTOR_ID = f"instaloader/instaloader@{version('instaloader')}"
PROMPT_PREFIX = (
    "한국어 인스타그램 릴스 음성입니다. 주제는 집꾸미기, 인테리어, 살림, "
    "생활용품이며 영어 브랜드명이나 제품명이 섞일 수 있습니다."
)
CSV_FIELDS = [
    "rank",
    "source_url",
    "shortcode",
    "published_at",
    "caption",
    "transcript",
    "detected_languages",
    "comments",
    "likes",
    "views",
    "plays",
    "duration_seconds",
    "audio_path",
    "audio_sha256",
    "audio_size_bytes",
    "transcription_status",
    "error",
    "model",
    "collector_id",
    "actor_id",
    "collected_at",
    "transcribed_at",
]


class CollectionIncompleteError(RuntimeError):
    """Raised when a complete, rankable profile snapshot cannot be produced."""


class ExistingAudioInvalidError(RuntimeError):
    """Raised instead of overwriting an existing invalid audio artifact."""


class NoAudioError(RuntimeError):
    """Raised when a Reel media URL does not expose an audio stream."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def validate_username(username: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._]+", username):
        raise argparse.ArgumentTypeError("username contains unsupported characters")
    return username


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    atomic_write_json(path, payload)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return payload


def nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def node_count(node: dict[str, Any], *field_names: str) -> int | None:
    for field_name in field_names:
        field = node.get(field_name)
        if isinstance(field, dict) and field.get("count") is not None:
            return nullable_int(field["count"])
    return None


def normalize_post(post: instaloader.Post, collected_at: str) -> dict[str, Any] | None:
    node = getattr(post, "_node", {})
    product_type = node.get("product_type")
    typename = post.typename

    if typename == "GraphVideo" and product_type is None:
        raise CollectionIncompleteError(
            f"video post {post.shortcode} has no product_type; Reel classification is unknown"
        )
    if product_type != "clips":
        return None

    audio_attribution = node.get("clips_music_attribution_info") or {}
    return {
        "shortcode": post.shortcode,
        "source_url": f"https://www.instagram.com/reel/{post.shortcode}/",
        "published_at": post.date_utc.replace(tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "caption": post.caption,
        "comments_count": node_count(
            node, "edge_media_to_comment", "edge_media_to_parent_comment"
        ),
        "likes_count": node_count(node, "edge_media_preview_like", "edge_liked_by"),
        "views_count": nullable_int(node.get("video_view_count")),
        "plays_count": nullable_int(node.get("video_play_count")),
        "shares_count": None,
        "duration_seconds": (
            float(node["video_duration"])
            if node.get("video_duration") is not None
            else None
        ),
        "media_product_type": product_type,
        "typename": typename,
        "audio_attribution": {
            "artist_name": audio_attribution.get("artist_name"),
            "song_name": audio_attribution.get("song_name"),
            "uses_original_audio": audio_attribution.get("uses_original_audio"),
        },
        "media_url_obtained": bool(node.get("video_url")),
        "collector_id": COLLECTOR_ID,
        "actor_id": None,
        "collected_at": collected_at,
    }


def rank_reels(reels: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    missing = [
        item["shortcode"] for item in reels if item.get("comments_count") is None
    ]
    if missing:
        joined = ", ".join(missing[:5])
        raise CollectionIncompleteError(
            f"cannot rank Reels with missing comment counts: {joined}"
        )

    def sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
        published = datetime.fromisoformat(item["published_at"])
        return (-int(item["comments_count"]), -published.timestamp(), item["shortcode"])

    ranked: list[dict[str, Any]] = []
    for rank, item in enumerate(sorted(reels, key=sort_key), start=1):
        ranked.append({**item, "rank": rank})
    return ranked


def create_loader() -> instaloader.Instaloader:
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        max_connection_attempts=3,
    )


def preflight() -> None:
    missing = [
        command for command in ("ffmpeg", "ffprobe") if shutil.which(command) is None
    ]
    if missing:
        raise RuntimeError(
            f"missing required executable(s): {', '.join(missing)}; install ffmpeg before collection"
        )


def scan_paths(username: str, run_id: str) -> tuple[Path, Path]:
    final_path = RAW_ROOT / f"{username}-reels-{run_id}.json"
    checkpoint_path = RAW_ROOT / f"{username}-reels-{run_id}.checkpoint.json"
    return final_path, checkpoint_path


def collect_profile(
    username: str,
    run_id: str,
    top: int,
    loader: instaloader.Instaloader | None = None,
) -> dict[str, Any]:
    final_path, checkpoint_path = scan_paths(username, run_id)
    if final_path.exists():
        payload = load_json(final_path)
        if payload.get("username") != username or payload.get("run_id") != run_id:
            raise ValueError("saved scan does not match username and run ID")
        if not payload.get("scan_complete") or not payload.get("ranking_complete"):
            raise CollectionIncompleteError("saved profile scan is incomplete")
        return payload

    checkpoint = load_json(checkpoint_path) if checkpoint_path.exists() else None
    if checkpoint and (
        checkpoint.get("username") != username or checkpoint.get("run_id") != run_id
    ):
        raise ValueError("scan checkpoint does not match username and run ID")

    loader = loader or create_loader()
    profile = instaloader.Profile.from_username(loader.context, username)
    if profile.is_private:
        raise CollectionIncompleteError("profile is private")

    started_at = checkpoint.get("collection_started_at") if checkpoint else utc_now()
    collected_reels = {
        item["shortcode"]: item
        for item in (checkpoint.get("reels", []) if checkpoint else [])
    }
    posts_scanned = int(checkpoint.get("posts_scanned", 0)) if checkpoint else 0
    last_shortcode = checkpoint.get("last_shortcode") if checkpoint else None
    seeking_resume_point = bool(last_shortcode)
    profile_snapshot = (
        checkpoint.get("profile_snapshot")
        if checkpoint
        else {
            "userid": profile.userid,
            "is_private": profile.is_private,
            "mediacount": profile.mediacount,
            "followers": profile.followers,
            "followees": profile.followees,
        }
    )

    iterator = profile.get_posts()
    try:
        for post in iterator:
            if seeking_resume_point:
                if post.shortcode == last_shortcode:
                    seeking_resume_point = False
                continue

            item_collected_at = utc_now()
            normalized = normalize_post(post, item_collected_at)
            posts_scanned += 1
            if normalized is not None:
                collected_reels[normalized["shortcode"]] = normalized
            last_shortcode = post.shortcode

            atomic_write_json(
                checkpoint_path,
                {
                    "schema_version": 1,
                    "username": username,
                    "run_id": run_id,
                    "collection_started_at": started_at,
                    "profile_snapshot": profile_snapshot,
                    "posts_scanned": posts_scanned,
                    "last_shortcode": last_shortcode,
                    "reels": list(collected_reels.values()),
                    "scan_complete": False,
                },
            )
    except Exception:
        if not checkpoint_path.exists():
            atomic_write_json(
                checkpoint_path,
                {
                    "schema_version": 1,
                    "username": username,
                    "run_id": run_id,
                    "collection_started_at": started_at,
                    "profile_snapshot": profile_snapshot,
                    "posts_scanned": posts_scanned,
                    "last_shortcode": last_shortcode,
                    "reels": list(collected_reels.values()),
                    "scan_complete": False,
                },
            )
        raise

    if seeking_resume_point:
        raise CollectionIncompleteError(
            "saved resume shortcode was not found; the profile timeline changed"
        )

    ranked = rank_reels(list(collected_reels.values()))
    if len(ranked) < top:
        raise CollectionIncompleteError(
            f"profile has only {len(ranked)} rankable Reels; requested Top {top}"
        )

    completed_at = utc_now()
    payload = {
        "schema_version": 1,
        "username": username,
        "run_id": run_id,
        "collector": {
            "id": COLLECTOR_ID,
            "actor_id": None,
        },
        "collection_started_at": started_at,
        "collection_completed_at": completed_at,
        "profile_snapshot": profile_snapshot,
        "posts_scanned": posts_scanned,
        "reels_found": len(ranked),
        "scan_complete": True,
        "ranking_complete": True,
        "ranking": {
            "metric": "comments_count",
            "order": "descending",
            "tie_breakers": ["published_at descending", "shortcode ascending"],
            "requested_top": top,
        },
        "reels": ranked,
    }
    write_json_once(final_path, payload)
    checkpoint_path.unlink(missing_ok=True)
    return payload


def sanitize_prompt_text(text: str | None, limit: int = 800) -> str:
    if not text:
        return ""
    normalized = " ".join(text.replace("<", " ").replace(">", " ").split())
    return normalized[:limit]


def build_prompt(caption: str | None) -> str:
    cleaned = sanitize_prompt_text(caption)
    if not cleaned:
        return PROMPT_PREFIX
    return f"{PROMPT_PREFIX} 연관 게시물 캡션: {cleaned}"


def sanitize_error(error: BaseException | str) -> str:
    text = str(error)
    text = re.sub(r"https?://\S+", "<media-url>", text)
    return text[:2000]


def run_command(
    command: Sequence[str], timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_audio(path: Path) -> dict[str, Any]:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size:stream=index,codec_type,codec_name,sample_rate,channels,channel_layout,duration",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise ExistingAudioInvalidError(
            sanitize_error(result.stderr or "ffprobe failed")
        )

    payload = json.loads(result.stdout)
    audio_streams = [
        stream
        for stream in payload.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise NoAudioError("media contains no audio stream")

    stream = audio_streams[0]
    format_data = payload.get("format", {})
    duration_value = stream.get("duration") or format_data.get("duration")
    return {
        "codec_name": stream.get("codec_name"),
        "sample_rate": nullable_int(stream.get("sample_rate")),
        "channels": nullable_int(stream.get("channels")),
        "channel_layout": stream.get("channel_layout"),
        "duration_seconds": float(duration_value)
        if duration_value is not None
        else None,
        "format_name": format_data.get("format_name"),
        "size_bytes": path.stat().st_size,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_no_audio_ffmpeg_error(stderr: str) -> bool:
    lowered = stderr.lower()
    markers = (
        "matches no streams",
        "does not contain any stream",
        "stream map '0:a:0' matches no streams",
    )
    return any(marker in lowered for marker in markers)


def extract_audio(media_url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        metadata = probe_audio(destination)
        return {
            **metadata,
            "sha256": sha256_file(destination),
            "reused": True,
            "derived_for_openai": False,
        }

    temporary = destination.with_name(
        f".{destination.stem}.{os.getpid()}.tmp{destination.suffix}"
    )
    temporary.unlink(missing_ok=True)
    result = run_command(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            media_url,
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "copy",
            str(temporary),
        ]
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        if is_no_audio_ffmpeg_error(result.stderr):
            raise NoAudioError("Reel media contains no audio stream")
        raise RuntimeError(
            sanitize_error(result.stderr or "ffmpeg audio extraction failed")
        )

    metadata = probe_audio(temporary)
    if destination.exists():
        temporary.unlink(missing_ok=True)
        raise FileExistsError(f"audio appeared during extraction: {destination}")
    os.replace(temporary, destination)
    return {
        **metadata,
        "sha256": sha256_file(destination),
        "reused": False,
        "derived_for_openai": False,
    }


def create_openai_derivative(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        metadata = probe_audio(destination)
        if metadata["size_bytes"] > MAX_OPENAI_FILE_BYTES:
            raise ExistingAudioInvalidError("existing OpenAI derivative exceeds 25 MB")
        return {
            **metadata,
            "sha256": sha256_file(destination),
            "reused": True,
            "derived_for_openai": True,
        }

    temporary = destination.with_name(
        f".{destination.stem}.{os.getpid()}.tmp{destination.suffix}"
    )
    temporary.unlink(missing_ok=True)
    result = run_command(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(temporary),
        ]
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(sanitize_error(result.stderr or "ffmpeg derivative failed"))

    metadata = probe_audio(temporary)
    if metadata["size_bytes"] > MAX_OPENAI_FILE_BYTES:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("OpenAI derivative still exceeds 25 MB")
    if destination.exists():
        temporary.unlink(missing_ok=True)
        raise FileExistsError(
            f"audio derivative appeared during extraction: {destination}"
        )
    os.replace(temporary, destination)
    return {
        **metadata,
        "sha256": sha256_file(destination),
        "reused": False,
        "derived_for_openai": True,
    }


def ensure_audio(
    loader: instaloader.Instaloader,
    username: str,
    reel: dict[str, Any],
) -> tuple[Path, dict[str, Any], Path, dict[str, Any] | None]:
    shortcode = reel["shortcode"]
    audio_directory = AUDIO_ROOT / username
    audio_path = audio_directory / f"{shortcode}.m4a"

    if audio_path.exists():
        audio_metadata = extract_audio("", audio_path)
    else:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        product_type = getattr(post, "_node", {}).get("product_type")
        if product_type != "clips":
            raise CollectionIncompleteError(
                f"post {shortcode} is no longer identified as a Reel"
            )
        media_url = post.video_url
        if not media_url:
            raise RuntimeError(f"post {shortcode} has no video URL")
        audio_metadata = extract_audio(media_url, audio_path)

    upload_path = audio_path
    derivative_metadata = None
    if audio_metadata["size_bytes"] > MAX_OPENAI_FILE_BYTES:
        upload_path = audio_directory / f"{shortcode}.openai.m4a"
        derivative_metadata = create_openai_derivative(audio_path, upload_path)

    return audio_path, audio_metadata, upload_path, derivative_metadata


def relative_project_path(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))


def call_transcription(
    client: OpenAI,
    upload_path: Path,
    prompt: str,
    attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        try:
            with upload_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=MODEL,
                    file=audio_file,
                    prompt=prompt,
                    languages=LANGUAGES,
                    stream=False,
                )
            if hasattr(response, "model_dump"):
                payload = response.model_dump(mode="json")
            else:
                payload = json.loads(response.json())
            return payload
        except OpenAIError:
            if attempt == attempts:
                raise
            sleeper(float(2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def transcription_paths(
    username: str, run_id: str, limit: int, top: int
) -> tuple[Path, Path, Path]:
    checkpoint = RAW_ROOT / f"{username}-transcriptions-{run_id}.checkpoint.json"
    snapshot = RAW_ROOT / f"{username}-transcriptions-{run_id}-limit{limit}.json"
    csv_path = (
        PROCESSED_ROOT / f"{username}-top{top}-comments-{run_id}-limit{limit}.csv"
    )
    return checkpoint, snapshot, csv_path


def next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    attempt = 2
    while True:
        candidate = path.with_name(f"{path.stem}-attempt{attempt}{path.suffix}")
        if not candidate.exists():
            return candidate
        attempt += 1


def initialize_transcriptions(
    scan: dict[str, Any],
    top: int,
    checkpoint_path: Path,
) -> dict[str, Any]:
    if checkpoint_path.exists():
        payload = load_json(checkpoint_path)
        if (
            payload.get("run_id") != scan["run_id"]
            or payload.get("username") != scan["username"]
        ):
            raise ValueError("transcription checkpoint does not match the profile scan")
        if payload.get("model") != MODEL:
            raise ValueError("transcription checkpoint uses a different model")
        existing_shortcodes = {item["shortcode"] for item in payload["items"]}
        for item in scan["reels"]:
            if int(item["rank"]) > top or item["shortcode"] in existing_shortcodes:
                continue
            payload["items"].append(
                {
                    "rank": item["rank"],
                    "shortcode": item["shortcode"],
                    "source_url": item["source_url"],
                    "status": "pending",
                    "transcript": None,
                    "detected_languages": [],
                    "request": None,
                    "response": None,
                    "audio": None,
                    "openai_derivative": None,
                    "error": None,
                    "transcribed_at": None,
                }
            )
        payload["items"].sort(key=lambda item: int(item["rank"]))
        payload["updated_at"] = utc_now()
        atomic_write_json(checkpoint_path, payload)
        return payload

    ranked = [item for item in scan["reels"] if int(item["rank"]) <= top]
    payload = {
        "schema_version": 1,
        "username": scan["username"],
        "run_id": scan["run_id"],
        "model": MODEL,
        "languages": LANGUAGES,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "items": [
            {
                "rank": item["rank"],
                "shortcode": item["shortcode"],
                "source_url": item["source_url"],
                "status": "pending",
                "transcript": None,
                "detected_languages": [],
                "request": None,
                "response": None,
                "audio": None,
                "openai_derivative": None,
                "error": None,
                "transcribed_at": None,
            }
            for item in ranked
        ],
    }
    atomic_write_json(checkpoint_path, payload)
    return payload


def detected_language_codes(response: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for language in response.get("languages") or []:
        if isinstance(language, dict) and language.get("code"):
            codes.append(str(language["code"]))
        elif isinstance(language, str):
            codes.append(language)
    return codes


def find_reel(scan: dict[str, Any], shortcode: str) -> dict[str, Any]:
    for reel in scan["reels"]:
        if reel["shortcode"] == shortcode:
            return reel
    raise KeyError(shortcode)


def write_processed_csv(
    path: Path,
    scan: dict[str, Any],
    transcription: dict[str, Any],
    top: int,
) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    results_by_shortcode = {item["shortcode"]: item for item in transcription["items"]}
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for reel in scan["reels"]:
            if int(reel["rank"]) > top:
                continue
            result = results_by_shortcode[reel["shortcode"]]
            audio = result.get("audio") or {}
            writer.writerow(
                {
                    "rank": reel["rank"],
                    "source_url": reel["source_url"],
                    "shortcode": reel["shortcode"],
                    "published_at": reel["published_at"],
                    "caption": reel.get("caption"),
                    "transcript": result.get("transcript"),
                    "detected_languages": json.dumps(
                        result.get("detected_languages") or [], ensure_ascii=False
                    ),
                    "comments": reel.get("comments_count"),
                    "likes": reel.get("likes_count"),
                    "views": reel.get("views_count"),
                    "plays": reel.get("plays_count"),
                    "duration_seconds": audio.get("duration_seconds")
                    or reel.get("duration_seconds"),
                    "audio_path": audio.get("path"),
                    "audio_sha256": audio.get("sha256"),
                    "audio_size_bytes": audio.get("size_bytes"),
                    "transcription_status": result.get("status"),
                    "error": result.get("error"),
                    "model": transcription["model"],
                    "collector_id": reel.get("collector_id"),
                    "actor_id": reel.get("actor_id"),
                    "collected_at": reel.get("collected_at"),
                    "transcribed_at": result.get("transcribed_at"),
                }
            )


def process_transcriptions(
    scan: dict[str, Any],
    top: int,
    limit: int,
    loader: instaloader.Instaloader | None = None,
    client: OpenAI | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    checkpoint_path, snapshot_path, csv_path = transcription_paths(
        scan["username"], scan["run_id"], limit, top
    )
    snapshot_path = next_available_path(snapshot_path)
    csv_path = next_available_path(csv_path)

    transcription = initialize_transcriptions(scan, top, checkpoint_path)
    if limit == 0:
        transcription["updated_at"] = utc_now()
        write_json_once(snapshot_path, transcription)
        write_processed_csv(csv_path, scan, transcription, top)
        return transcription, snapshot_path, csv_path

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    loader = loader or create_loader()
    client = client or OpenAI()
    attempted = 0
    for result in transcription["items"]:
        if int(result["rank"]) > limit:
            continue
        if result.get("status") == "success":
            audio = result.get("audio") or {}
            stored_path = audio.get("path")
            if not stored_path:
                result.update(
                    {
                        "status": "error",
                        "error": "successful checkpoint item has no stored audio path",
                    }
                )
                transcription["updated_at"] = utc_now()
                atomic_write_json(checkpoint_path, transcription)
                continue
            try:
                probe_audio(PROJECT_ROOT / stored_path)
            except Exception as error:  # noqa: BLE001 - preserve the invalid artifact.
                result.update({"status": "error", "error": sanitize_error(error)})
                transcription["updated_at"] = utc_now()
                atomic_write_json(checkpoint_path, transcription)
                continue
            print(f"[{result['rank']}/{limit}] reuse {result['source_url']}")
            continue
        if result.get("status") == "no_audio":
            print(f"[{result['rank']}/{limit}] reuse no_audio {result['source_url']}")
            continue

        attempted += 1
        reel = find_reel(scan, result["shortcode"])
        result.update(
            {
                "status": "processing",
                "error": None,
                "request": {
                    "model": MODEL,
                    "languages": LANGUAGES,
                    "prompt": build_prompt(reel.get("caption")),
                },
            }
        )
        transcription["updated_at"] = utc_now()
        atomic_write_json(checkpoint_path, transcription)
        print(f"[{result['rank']}/{limit}] process {result['source_url']}")

        try:
            audio_path, audio_metadata, upload_path, derivative_metadata = ensure_audio(
                loader, scan["username"], reel
            )
            result["audio"] = {
                **audio_metadata,
                "path": relative_project_path(audio_path),
                "extracted_at": utc_now(),
                "source_url": reel["source_url"],
            }
            if derivative_metadata is not None:
                result["openai_derivative"] = {
                    **derivative_metadata,
                    "path": relative_project_path(upload_path),
                    "created_at": utc_now(),
                }

            response = call_transcription(
                client,
                upload_path,
                result["request"]["prompt"],
            )
            result.update(
                {
                    "status": "success",
                    "transcript": response.get("text"),
                    "detected_languages": detected_language_codes(response),
                    "response": response,
                    "error": None,
                    "transcribed_at": utc_now(),
                }
            )
        except NoAudioError as error:
            result.update(
                {
                    "status": "no_audio",
                    "error": sanitize_error(error),
                    "transcribed_at": utc_now(),
                }
            )
        except Exception as error:  # noqa: BLE001 - record one Reel failure and continue.
            result.update(
                {
                    "status": "error",
                    "error": sanitize_error(error),
                    "transcribed_at": utc_now(),
                }
            )
        transcription["updated_at"] = utc_now()
        atomic_write_json(checkpoint_path, transcription)

    transcription["last_execution"] = {
        "limit": limit,
        "attempted": attempted,
        "completed_at": utc_now(),
    }
    transcription["updated_at"] = utc_now()
    atomic_write_json(checkpoint_path, transcription)
    write_json_once(snapshot_path, transcription)
    write_processed_csv(csv_path, scan, transcription, top)
    return transcription, snapshot_path, csv_path


def status_counts(transcription: dict[str, Any], limit: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in transcription["items"]:
        if int(item["rank"]) > limit:
            continue
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank public Instagram Reels by comments, retain audio, and transcribe Korean speech."
    )
    parser.add_argument("--username", required=True, type=validate_username)
    parser.add_argument("--top", type=positive_int, default=100)
    parser.add_argument("--transcribe-limit", type=nonnegative_int, default=5)
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="resume a previous run ID, for example 20260819T120000Z",
    )
    parser.add_argument(
        "--confirm-owned-profile",
        action="store_true",
        help="confirm that the profile is owned or controlled by you before retaining its audio",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.transcribe_limit > args.top:
        print("--transcribe-limit cannot exceed --top", file=sys.stderr)
        return 2
    if args.transcribe_limit > 0 and not args.confirm_owned_profile:
        print(
            "--confirm-owned-profile is required before retaining Reel audio",
            file=sys.stderr,
        )
        return 2

    load_dotenv(PROJECT_ROOT / ".env")
    run_id = args.resume or new_run_id()
    print(f"run_id={run_id}")
    print(f"collector={COLLECTOR_ID}")
    try:
        preflight()
        scan = collect_profile(args.username, run_id, args.top)
        print(
            f"scan_complete posts={scan['posts_scanned']} reels={scan['reels_found']} "
            f"top={args.top}"
        )
        transcription, snapshot_path, csv_path = process_transcriptions(
            scan,
            args.top,
            args.transcribe_limit,
        )
    except Exception as error:  # noqa: BLE001 - convert the CLI boundary to an exit code.
        print(f"error: {sanitize_error(error)}", file=sys.stderr)
        return 1

    counts = status_counts(transcription, args.transcribe_limit)
    print(f"statuses={json.dumps(counts, ensure_ascii=False, sort_keys=True)}")
    print(f"raw_transcriptions={snapshot_path.relative_to(PROJECT_ROOT)}")
    print(f"processed_csv={csv_path.relative_to(PROJECT_ROOT)}")
    return 0 if not counts.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
