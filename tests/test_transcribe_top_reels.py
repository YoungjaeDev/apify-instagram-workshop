import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import transcribe_top_reels as target


def reel(shortcode, comments, published_at, rank=None):
    item = {
        "shortcode": shortcode,
        "source_url": f"https://www.instagram.com/reel/{shortcode}/",
        "published_at": published_at,
        "caption": f"caption {shortcode}",
        "comments_count": comments,
        "likes_count": 10,
        "views_count": 20,
        "plays_count": 30,
        "duration_seconds": 12.5,
        "collector_id": target.COLLECTOR_ID,
        "actor_id": None,
        "collected_at": "2026-08-19T00:00:00Z",
    }
    if rank is not None:
        item["rank"] = rank
    return item


class FakeTranscriptionResponse:
    def model_dump(self, mode):
        assert mode == "json"
        return {
            "text": "안녕하세요",
            "languages": [{"code": "ko"}],
            "usage": {"seconds": 1},
        }


class FakeTranscriptions:
    def __init__(self):
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return FakeTranscriptionResponse()


class FakePost:
    def __init__(self, shortcode, comments, product_type="clips"):
        self.shortcode = shortcode
        self.typename = "GraphVideo"
        self.date_utc = datetime(2026, 8, 19, tzinfo=UTC)
        self.caption = f"caption {shortcode}"
        self._node = {
            "product_type": product_type,
            "is_video": True,
            "video_url": "https://cdn.example/video.mp4?secret=signed",
            "edge_media_to_comment": {"count": comments},
            "edge_media_preview_like": {"count": comments + 10},
            "video_view_count": comments + 20,
            "video_play_count": comments + 30,
        }


class FakeProfile:
    username = "user"
    userid = 123
    is_private = False
    mediacount = 3
    followers = 100
    followees = 10

    def __init__(self, posts):
        self.posts = posts

    def get_posts(self):
        return iter(self.posts)


class TopReelsTests(unittest.TestCase):
    def test_rank_reels_uses_comments_then_date_then_shortcode(self):
        items = [
            reel("CCC", 3, "2026-08-19T00:00:00Z"),
            reel("BBB", 5, "2026-08-18T00:00:00Z"),
            reel("AAA", 5, "2026-08-18T00:00:00Z"),
            reel("DDD", 5, "2026-08-19T00:00:00Z"),
        ]

        ranked = target.rank_reels(items)

        self.assertEqual(
            [item["shortcode"] for item in ranked], ["DDD", "AAA", "BBB", "CCC"]
        )
        self.assertEqual([item["rank"] for item in ranked], [1, 2, 3, 4])

    def test_rank_reels_rejects_missing_comment_counts(self):
        with self.assertRaises(target.CollectionIncompleteError):
            target.rank_reels([reel("AAA", None, "2026-08-19T00:00:00Z")])

    def test_normalize_post_uses_timeline_counts_without_storing_cdn_url(self):
        normalized = target.normalize_post(FakePost("AAA", 12), "2026-08-19T00:00:00Z")

        self.assertEqual(normalized["comments_count"], 12)
        self.assertEqual(normalized["likes_count"], 22)
        self.assertTrue(normalized["media_url_obtained"])
        self.assertNotIn("video_url", normalized)
        self.assertNotIn("cdn.example", json.dumps(normalized))

    def test_collect_profile_resumes_after_last_shortcode_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw_root = Path(temporary)
            checkpoint_path = raw_root / "user-reels-run.checkpoint.json"
            collected_a = target.normalize_post(
                FakePost("AAA", 30), "2026-08-19T00:00:00Z"
            )
            collected_b = target.normalize_post(
                FakePost("BBB", 20), "2026-08-19T00:00:00Z"
            )
            target.atomic_write_json(
                checkpoint_path,
                {
                    "schema_version": 1,
                    "username": "user",
                    "run_id": "run",
                    "collection_started_at": "2026-08-19T00:00:00Z",
                    "profile_snapshot": {"userid": 123},
                    "posts_scanned": 2,
                    "last_shortcode": "BBB",
                    "reels": [collected_a, collected_b],
                    "scan_complete": False,
                },
            )
            profile = FakeProfile(
                [FakePost("AAA", 30), FakePost("BBB", 20), FakePost("CCC", 10)]
            )
            loader = SimpleNamespace(context=object())

            with (
                patch.object(target, "RAW_ROOT", raw_root),
                patch.object(
                    target.instaloader.Profile,
                    "from_username",
                    return_value=profile,
                ),
            ):
                result = target.collect_profile("user", "run", top=3, loader=loader)

            self.assertTrue(result["scan_complete"])
            self.assertEqual(result["posts_scanned"], 3)
            self.assertEqual(
                [item["shortcode"] for item in result["reels"]], ["AAA", "BBB", "CCC"]
            )
            self.assertFalse(checkpoint_path.exists())
            self.assertNotIn("cdn.example", json.dumps(result))

    def test_build_prompt_normalizes_and_limits_caption(self):
        caption = "  집꾸미기\n<브랜드>  " + ("가" * 900)

        prompt = target.build_prompt(caption)

        self.assertTrue(prompt.startswith(target.PROMPT_PREFIX))
        self.assertNotIn("\n", prompt)
        self.assertNotIn("<", prompt)
        self.assertNotIn(">", prompt)
        self.assertLessEqual(
            len(prompt), len(target.PROMPT_PREFIX) + len(" 연관 게시물 캡션: ") + 800
        )

    def test_sanitize_error_removes_signed_urls(self):
        value = target.sanitize_error(
            "failed https://cdninstagram.example/video.mp4?token=secret more"
        )

        self.assertNotIn("token=secret", value)
        self.assertIn("<media-url>", value)

    def test_next_available_path_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            path.write_text("one", encoding="utf-8")
            (Path(temporary) / "result-attempt2.json").write_text(
                "two", encoding="utf-8"
            )

            available = target.next_available_path(path)

            self.assertEqual(available.name, "result-attempt3.json")

    def test_call_transcription_sends_korean_file_parameters(self):
        with tempfile.TemporaryDirectory() as temporary:
            audio_path = Path(temporary) / "audio.m4a"
            audio_path.write_bytes(b"audio")
            transcriptions = FakeTranscriptions()
            client = SimpleNamespace(
                audio=SimpleNamespace(transcriptions=transcriptions)
            )

            response = target.call_transcription(client, audio_path, "한국어 릴스")

            self.assertEqual(response["text"], "안녕하세요")
            self.assertEqual(transcriptions.arguments["model"], "gpt-transcribe")
            self.assertEqual(transcriptions.arguments["languages"], ["ko"])
            self.assertFalse(transcriptions.arguments["stream"])
            self.assertEqual(transcriptions.arguments["prompt"], "한국어 릴스")

    def test_preflight_fails_before_collection_when_ffmpeg_is_missing(self):
        with (
            patch.object(target.shutil, "which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "ffmpeg, ffprobe"),
        ):
            target.preflight()

    def test_initialize_transcriptions_expands_checkpoint_for_top_100_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "transcriptions.checkpoint.json"
            scan = {
                "username": "user",
                "run_id": "run",
                "reels": [
                    reel("AAA", 30, "2026-08-19T00:00:00Z", rank=1),
                    reel("BBB", 20, "2026-08-18T00:00:00Z", rank=2),
                ],
            }
            initial = target.initialize_transcriptions(
                scan, top=1, checkpoint_path=checkpoint
            )
            initial["items"][0]["status"] = "success"
            initial["items"][0]["transcript"] = "기존 전사"
            target.atomic_write_json(checkpoint, initial)

            expanded = target.initialize_transcriptions(
                scan, top=2, checkpoint_path=checkpoint
            )

            self.assertEqual(len(expanded["items"]), 2)
            self.assertEqual(expanded["items"][0]["status"], "success")
            self.assertEqual(expanded["items"][0]["transcript"], "기존 전사")
            self.assertEqual(expanded["items"][1]["status"], "pending")

    def test_main_requires_owned_profile_confirmation_before_audio(self):
        exit_code = target.main(
            ["--username", "hehe_home_tem", "--top", "10", "--transcribe-limit", "5"]
        )

        self.assertEqual(exit_code, 2)

    def test_write_processed_csv_includes_pending_rows_and_audio_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "top.csv"
            scan = {
                "reels": [
                    reel("AAA", 10, "2026-08-19T00:00:00Z", rank=1),
                    reel("BBB", 9, "2026-08-18T00:00:00Z", rank=2),
                ]
            }
            transcription = {
                "model": target.MODEL,
                "items": [
                    {
                        "shortcode": "AAA",
                        "status": "success",
                        "transcript": "첫 번째",
                        "detected_languages": ["ko"],
                        "audio": {
                            "path": "data/raw/audio/user/AAA.m4a",
                            "sha256": "abc",
                            "size_bytes": 123,
                            "duration_seconds": 11.0,
                        },
                        "error": None,
                        "transcribed_at": "2026-08-19T01:00:00Z",
                    },
                    {
                        "shortcode": "BBB",
                        "status": "pending",
                        "transcript": None,
                        "detected_languages": [],
                        "audio": None,
                        "error": None,
                        "transcribed_at": None,
                    },
                ],
            }

            target.write_processed_csv(output, scan, transcription, top=2)

            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["transcript"], "첫 번째")
            self.assertEqual(rows[0]["audio_sha256"], "abc")
            self.assertEqual(rows[1]["transcription_status"], "pending")
            self.assertEqual(json.loads(rows[0]["detected_languages"]), ["ko"])


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required"
)
class AudioTests(unittest.TestCase):
    def make_media(self, directory):
        source = Path(directory) / "source.mp4"
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.4",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(result.stderr)
        return source

    def test_extract_audio_retains_and_reuses_m4a(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.make_media(temporary)
            destination = Path(temporary) / "audio.m4a"

            first = target.extract_audio(str(source), destination)
            second = target.extract_audio("unused", destination)

            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())
            self.assertEqual(first["codec_name"], "aac")
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(first["sha256"], second["sha256"])

    def test_existing_invalid_audio_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "audio.m4a"
            destination.write_text("not audio", encoding="utf-8")

            with self.assertRaises(target.ExistingAudioInvalidError):
                target.extract_audio("unused", destination)

            self.assertEqual(destination.read_text(encoding="utf-8"), "not audio")

    def test_openai_derivative_keeps_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_media = self.make_media(temporary)
            source_audio = Path(temporary) / "audio.m4a"
            target.extract_audio(str(source_media), source_audio)
            derivative = Path(temporary) / "audio.openai.m4a"

            metadata = target.create_openai_derivative(source_audio, derivative)

            self.assertTrue(source_audio.exists())
            self.assertTrue(derivative.exists())
            self.assertEqual(metadata["sample_rate"], 16000)
            self.assertEqual(metadata["channels"], 1)
            self.assertTrue(metadata["derived_for_openai"])


if __name__ == "__main__":
    unittest.main()
