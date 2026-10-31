"""SDK contract tests: all provider calls mocked, no real publication possible."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from socialpublishkit import (Account, GatewayClient, GatewayError, Platform, Publisher,
    PublishingError, PublishResult, PublishStatus, TikTokOptions, ValidationError, VideoPost)
from socialpublishkit import providers
from socialpublishkit.gateway import Gateway


class Response:
    def __init__(self, body=None, headers=None, status=200):
        self.body = json.dumps(body or {}).encode()
        self.headers, self.status = headers or {}, status
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size=-1): return self.body if size < 0 else self.body[:size]


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / "video.mp4"
        self.video.write_bytes(b"test-mp4")
        self.post = VideoPost(self.video, "Bonjour #CodeExample", "Titre", ("code example",))

    def mock_http(self, *responses):
        calls = []
        queue = list(responses)
        def call(request, timeout=None):
            calls.append(request)
            self.assertTrue(queue, "Unexpected provider call")
            result = queue.pop(0)
            if isinstance(result, Exception): raise result
            return result if isinstance(result, Response) else Response(result)
        mock = patch.object(providers, "_open", call)
        return mock, calls

    def test_imports_do_not_require_studio_dependencies(self):
        code = "import socialpublishkit, sys; assert not any(m in sys.modules for m in ('algovid', 'manim', 'anthropic', 'numpy'))"
        subprocess.run([os.sys.executable, "-c", code], check=True)

    def test_account_repr_does_not_contain_secrets(self):
        account = Account(Platform.TIKTOK, "access-secret", refresh_token="refresh-secret")
        self.assertNotIn("secret", repr(account))
        self.assertNotIn("secret", repr(Publisher({"META_APP_SECRET": "secret"})))

    def test_oauth_is_explicit_and_does_not_use_ambient_env(self):
        with patch.dict(os.environ, {"META_APP_ID": "ambient", "META_APP_SECRET": "ambient"}):
            with self.assertRaises(ValidationError):
                Publisher().authorization_url(Platform.FACEBOOK_PAGE, state="random", redirect_uri="https://example.com/callback")
        url = Publisher({"META_APP_ID": "app", "META_APP_SECRET": "secret"}).authorization_url(
            Platform.FACEBOOK_PAGE, state="random", redirect_uri="https://example.com/callback")
        self.assertIn("state=random", url)
        self.assertIn("pages_manage_posts", url)
        self.assertNotIn("secret", url)

    def test_rejects_profile_missing_identity_and_empty_video_before_network(self):
        with patch.object(providers, "_http") as http:
            for account in (Account("facebook", "secret"), Account(Platform.FACEBOOK_PAGE, "secret")):
                with self.assertRaises(ValidationError): Publisher().publish(account, self.post)
            self.video.write_bytes(b"")
            with self.assertRaises(ValidationError):
                Publisher().publish(Account(Platform.TIKTOK, "secret"), self.post)
            http.assert_not_called()

    def test_tiktok_draft_is_not_published_and_has_no_ai_label(self):
        mock, calls = self.mock_http(
            {"data": {"publish_id": "draft-1", "upload_url": "https://upload.example/video"}}, {},
            {"data": {"status": "SEND_TO_USER_INBOX"}})
        with mock:
            result = Publisher().publish(Account(Platform.TIKTOK, "secret"), self.post)
        self.assertEqual(result.status, PublishStatus.DRAFT_DELIVERED)
        self.assertEqual(result.post_id, "draft-1")
        self.assertNotIn("Bonjour", result.note)
        self.assertNotIn("post_info", json.loads(calls[0].data))

    def test_direct_post_checks_privacy_and_disclosure_is_explicit(self):
        for label in (None, False, True):
            mock, calls = self.mock_http(
                {"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE"], "max_video_post_duration_sec": 60,
                          "comment_disabled": True}},
                {"data": {"publish_id": "direct-1", "upload_url": "https://upload.example/video"}}, {},
                {"data": {"status": "PUBLISH_COMPLETE"}})
            with mock:
                result = Publisher({"TIKTOK_SCOPES": "video.publish"}).publish(
                    Account(Platform.TIKTOK, "secret", scopes=("video.publish",)), self.post,
                    tiktok=TikTokOptions(mode="public", duration_seconds=24, ai_generated=label, disable_comment=False))
            self.assertEqual(result.status, PublishStatus.PUBLISHED)
            self.assertIn("creator_info/query", calls[0].full_url)
            info = json.loads(calls[1].data)["post_info"]
            self.assertTrue(info["disable_comment"])
            if label is None: self.assertNotIn("is_aigc", info)
            else: self.assertIs(info["is_aigc"], label)

    def test_direct_post_requires_scope_duration_and_available_privacy(self):
        with patch.object(providers, "_http") as http:
            with self.assertRaises(ValidationError):
                Publisher().publish(Account(Platform.TIKTOK, "secret"), self.post, tiktok=TikTokOptions(mode="public"))
            with self.assertRaises(ValidationError):
                Publisher({"TIKTOK_SCOPES": "video.publish"}).publish(Account(Platform.TIKTOK, "secret"), self.post,
                                                                      tiktok=TikTokOptions(mode="public"))
            http.assert_not_called()
        mock, calls = self.mock_http({"data": {"privacy_level_options": ["SELF_ONLY"]}})
        with mock, self.assertRaises(PublishingError):
            Publisher({"TIKTOK_SCOPES": "video.publish"}).publish(Account(Platform.TIKTOK, "secret"), self.post,
                                              tiktok=TikTokOptions(mode="public", duration_seconds=24))
        self.assertEqual(len(calls), 1)

    def test_youtube_returns_uploaded_and_refresh_is_persisted_even_on_failure(self):
        saved = []
        account = Account(Platform.YOUTUBE, "old", refresh_token="refresh", expires_at=0)
        mock, calls = self.mock_http({"access_token": "new", "expires_in": 3600},
            Response(headers={"Location": "https://upload.example/video"}), {"id": "yt-id"})
        publisher = Publisher({"GOOGLE_CLIENT_ID": "a", "GOOGLE_CLIENT_SECRET": "b"}, on_account_update=lambda a: saved.append(a.access_token))
        with mock: result = publisher.publish(account, self.post)
        self.assertEqual(result.status, PublishStatus.UPLOADED)
        self.assertEqual(saved, ["new"])
        account.expires_at = 0
        mock, _ = self.mock_http({"access_token": "newer", "expires_in": 3600}, urllib.error.URLError("token=secret"))
        with mock, self.assertRaises(PublishingError) as caught:
            publisher.publish(account, self.post)
        self.assertEqual(saved[-1], "newer")
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.outcome_unknown)

    def test_facebook_and_instagram_shared_transport(self):
        mock, calls = self.mock_http({"video_id": "fb-video"}, {}, {},
                                     {"status": {"publishing_phase": {"status": "complete"}}})
        with mock:
            result = Publisher().publish(Account(Platform.FACEBOOK_PAGE, "secret", "123"), self.post)
        self.assertEqual(result.status, PublishStatus.PUBLISHED)
        self.assertIn("/123/video_reels", calls[0].full_url)
        mock, calls = self.mock_http({"id": "container"}, {}, {"status_code": "FINISHED"},
                                    {"id": "ig-media"}, {"permalink": "https://www.instagram.com/reel/example/"})
        with mock:
            result = Publisher().publish(Account(Platform.INSTAGRAM, "secret", "456"), self.post)
        self.assertEqual(result.post_id, "ig-media")
        self.assertIn("/456/media", calls[0].full_url)


class FakePublisher:
    def __init__(self): self.calls = 0
    def publish(self, account, post, *, tiktok=None):
        self.calls += 1
        return PublishResult(account.platform, PublishStatus.DRAFT_DELIVERED, "fake-draft")


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.publisher = FakePublisher()
        self.gateway = Gateway(self.publisher, {"tiktok": Account(Platform.TIKTOK, "provider-secret", "123", "Creator")},
                               token="g" * 32, state_dir=self.tmp.name)
        self.server = self.gateway.server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = GatewayClient("g" * 32, f"http://127.0.0.1:{self.server.server_port}")
        self.video = Path(self.tmp.name) / "test.mp4"
        self.video.write_bytes(b"test-mp4")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.gateway.close()
        self.tmp.cleanup()

    def completed(self, key):
        for _ in range(100):
            job = self.client.publication(key)
            if job["state"] != "processing": return job
            time.sleep(.01)
        self.fail("Worker did not complete")

    def test_auth_redaction_and_local_file_transfer(self):
        accounts = self.client.accounts()
        self.assertNotIn("provider-secret", json.dumps(accounts))
        with self.assertRaises(GatewayError) as error:
            GatewayClient("wrong", self.client.base_url).accounts()
        self.assertEqual(error.exception.status, 401)
        job = self.client.publish(publication_id="test-job-001", account="tiktok", video=self.video, caption="Bonjour")
        self.assertEqual(job["id"], "test-job-001")
        result = self.completed(job["id"])
        self.assertEqual(result["result"]["status"], "draft_delivered")
        self.assertEqual(list(Path(self.tmp.name).glob("upload-*")), [])

    def test_idempotency_conflict_and_no_duplicate(self):
        kwargs = dict(publication_id="test-job-002", account="tiktok", video=self.video, caption="Bonjour")
        self.client.publish(**kwargs)
        self.completed(kwargs["publication_id"])
        self.client.publish(**kwargs)
        self.assertEqual(self.publisher.calls, 1)
        with self.assertRaises(GatewayError) as error:
            self.client.publish(**(kwargs | {"caption": "Different"}))
        self.assertEqual(error.exception.status, 409)

    def test_unknown_outcome_is_not_retried(self):
        def fail(*a, **k):
            self.publisher.calls += 1
            raise PublishingError(Platform.TIKTOK, outcome_unknown=True)
        self.publisher.publish = fail
        kwargs = dict(publication_id="test-job-003", account="tiktok", video=self.video, caption="Bonjour")
        self.client.publish(**kwargs)
        self.assertEqual(self.completed(kwargs["publication_id"])["state"], "unknown")
        self.client.publish(**kwargs)
        self.assertEqual(self.publisher.calls, 1)

    def test_rejects_file_paths_in_payload_and_second_gateway(self):
        with self.assertRaises(ValidationError):
            self.gateway.submit("test-job-004", {"account": "tiktok", "video": "/etc/passwd", "caption": "a"})
        with self.assertRaises(RuntimeError):
            Gateway(self.publisher, {}, token="g" * 32, state_dir=self.tmp.name)

    def test_restart_turns_processing_into_unknown(self):
        with self.gateway._db() as db:
            db.execute("INSERT INTO jobs VALUES (?, ?, ?)", ("test-job-005", "hash", json.dumps({"state": "processing"})))
        self.gateway.close()
        self.gateway = Gateway(self.publisher, {}, token="g" * 32, state_dir=self.tmp.name)
        self.assertEqual(self.gateway.get("test-job-005")["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
