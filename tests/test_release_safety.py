"""Regression coverage for review findings. All network endpoints are local or mocked."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from socialpublishkit import (Account, Platform, Publisher, PublishingError, PublishResult,
                             PublishStatus, ValidationError, VideoPost, YouTubeOptions)
from socialpublishkit import providers
from socialpublishkit.gateway import Gateway


class Response:
    status = 200

    def __init__(self, data, headers=None):
        self.body = BytesIO(json.dumps(data).encode())
        self.headers = headers or {}

    def read(self, size=-1):
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class PublisherSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / 'video.mp4'
        self.video.write_bytes(b'fake-mp4')
        self.post = VideoPost(self.video, 'Example', 'Title')

    def test_refresh_is_persisted_before_upload_start(self):
        saved, requests = [], []
        account = Account(Platform.YOUTUBE, 'old-token', 'channel', refresh_token='refresh', expires_at=0)
        publisher = Publisher({'GOOGLE_CLIENT_ID': 'test', 'GOOGLE_CLIENT_SECRET': 'test'},
                              on_account_update=lambda a: saved.append(a.access_token))

        def request(req, timeout):
            requests.append(req)
            if len(requests) == 1:
                return Response({'access_token': 'new-token', 'expires_in': 3600})
            self.assertEqual(saved, ['new-token'])
            raise urllib.error.URLError('private-provider-detail')

        with patch.object(providers, '_open', request), self.assertRaises(PublishingError) as error:
            publisher.publish(account, self.post)
        self.assertTrue(error.exception.outcome_unknown)
        self.assertNotIn('private-provider-detail', str(error.exception))

    def test_persistence_failure_stops_upload(self):
        account = Account(Platform.YOUTUBE, 'old', 'channel', refresh_token='refresh', expires_at=0)
        def fail(_):
            raise OSError('storage failed')
        publisher = Publisher({'GOOGLE_CLIENT_ID': 'a', 'GOOGLE_CLIENT_SECRET': 'b'}, on_account_update=fail)
        with patch.object(providers, '_open', return_value=Response({'access_token': 'new'})) as request:
            with self.assertRaises(PublishingError):
                publisher.publish(account, self.post)
            self.assertEqual(request.call_count, 1)

    def test_expiry_and_scope_only_refresh_is_persisted(self):
        saved = []
        account = Account(Platform.TIKTOK, 'same-token', 'creator', expires_at=100, scopes=('video.upload',))
        publisher = Publisher(on_account_update=lambda a: saved.append((a.expires_at, a.scopes)))
        publisher._persist_refresh(account, {'jeton': 'same-token', 'expire': 200, 'scope': ''})
        self.assertEqual(saved, [(200, ())])

    def test_malformed_provider_success_is_an_unknown_outcome(self):
        with patch.object(providers.YouTube, 'publier', return_value={'status': 'unexpected', 'id': 'id'}):
            with self.assertRaises(PublishingError) as error:
                Publisher().publish(Account(Platform.YOUTUBE, 'fake', 'channel'), self.post)
        self.assertTrue(error.exception.outcome_unknown)

    def test_invalid_types_are_rejected_before_network(self):
        account = Account(Platform.YOUTUBE, 'fake', 'channel')
        with patch.object(providers, '_open') as request:
            for invalid in (replace(account, expires_at='tomorrow'), replace(account, expires_at=True),
                            replace(account, scopes='video.upload'), replace(account, refresh_token=12)):
                with self.assertRaises(ValidationError):
                    Publisher().publish(invalid, self.post)
            for invalid in (replace(self.post, title=None), replace(self.post, tags='not-an-array')):
                with self.assertRaises(ValidationError):
                    Publisher().publish(account, invalid)
            request.assert_not_called()

    def test_youtube_visibility_and_audience_are_explicit(self):
        for options, expected in ((None, 'private'), (YouTubeOptions(privacy='public', made_for_kids=True), 'public')):
            calls = []
            responses = iter([Response({}, {'Location': 'https://upload.example/video'}), Response({'id': 'video'})])
            def request(req, timeout):
                calls.append(req)
                return next(responses)
            with patch.object(providers, '_open', request):
                Publisher().publish(Account(Platform.YOUTUBE, 'fake', 'channel'), self.post, youtube=options)
            payload = json.loads(calls[0].data)
            self.assertEqual(payload['status']['privacyStatus'], expected)
            self.assertEqual(payload['status']['selfDeclaredMadeForKids'], options is not None)
            self.assertNotIn('defaultLanguage', payload['snippet'])

    def test_http_upload_urls_rejected_without_transmission(self):
        with patch.object(providers, '_open') as request:
            for url in ('http://upload.example/video', 'https://secret@upload.example/video'):
                with self.assertRaises(providers.ErreurReseau):
                    providers._http('PUT', url, b'private-video')
            request.assert_not_called()

    def test_provider_redirect_does_not_forward_credentials(self):
        received = []
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/leak')
                self.end_headers()
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/start',
                                         headers={'Authorization': 'Bearer fake-secret'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                providers._open(req, timeout=2)
            error.exception.close()
            self.assertEqual(received, ['/start'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class GatewaySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.started, self.release = threading.Event(), threading.Event()
        self.calls = 0
        case = self
        class FakePublisher:
            def publish(self, account, post, **options):
                case.calls += 1
                case.started.set()
                case.release.wait(10)
                return PublishResult(account.platform, PublishStatus.DRAFT_DELIVERED, 'fake')
        self.publisher = FakePublisher()
        self.account = Account(Platform.TIKTOK, 'fake-token', 'creator')
        self.gateway = Gateway(self.publisher, {'creator': self.account}, token='x' * 32, state_dir=self.tmp.name)
        self.body = {'account': 'creator', 'caption': 'Example', 'video_base64': base64.b64encode(b'fake').decode()}

    def tearDown(self):
        self.release.set()
        self.gateway.close()

    def test_concurrent_identical_requests_publish_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.gateway.submit('same-request', self.body), range(20)))
        self.assertTrue(self.started.wait(2))
        self.assertEqual(self.calls, 1)
        self.assertTrue(all(status == 202 for status, _ in results))
        self.release.set()
        self.gateway.close()
        self.assertEqual(self.gateway.get('same-request')['state'], 'completed')

    def test_full_queue_and_shutdown_do_not_reserve_rejected_jobs(self):
        for i in range(8):
            self.assertEqual(self.gateway.submit(f'request-{i}', self.body)[0], 202)
        self.assertEqual(self.gateway.submit('overflow-request', self.body)[0], 429)
        self.assertIsNone(self.gateway.get('overflow-request'))
        self.release.set()
        self.gateway.close()
        self.assertEqual(self.gateway.submit('closed-request', self.body)[0], 503)
        self.assertIsNone(self.gateway.get('closed-request'))

    def test_missing_or_duplicate_destinations_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for accounts in ({'a': replace(self.account, account_id='')}, {'a': self.account, 'b': self.account}):
                with self.assertRaises(ValidationError):
                    Gateway(self.publisher, accounts, token='x' * 32, state_dir=folder)
