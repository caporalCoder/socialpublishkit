"""Authenticated loopback service for the JS/Rust clients. Never serves studio files."""

import base64
from contextlib import contextmanager
import fcntl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading

from .client import Publisher
from .models import Account, PublishingError, TikTokOptions, YouTubeOptions, ValidationError, VideoPost

MAX_VIDEO_BYTES = 32 * 1024 * 1024
MAX_BODY_BYTES = MAX_VIDEO_BYTES * 4 // 3 + 65536
KEY = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")


class _BoundedHTTPServer(ThreadingHTTPServer):
    """Bound simultaneous connections, including clients stalled before authentication."""
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        pass  # socket failures must not log account data or upload contents


class Gateway:
    def __init__(self, publisher: Publisher, accounts: dict[str, Account], *, token: str, state_dir: str | Path):
        if not isinstance(token, str) or len(token) < 32 or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("Use a random ASCII gateway token of at least 32 characters.")
        identities = set()
        for key, account in accounts.items():
            Publisher._credentials(account)
            if not isinstance(key, str) or not key or not account.account_id.strip():
                raise ValidationError("Gateway accounts require a nonempty alias and provider account ID.")
            identity = (account.platform, account.account_id)
            if identity in identities:
                raise ValidationError("Configure each destination once; duplicate aliases can race token refresh.")
            identities.add(identity)
        self.publisher, self.accounts, self._token = publisher, dict(accounts), token
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._process_lock = open(self.state_dir / "gateway.lock", "a")
        try:
            fcntl.flock(self._process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._process_lock.close()
            raise RuntimeError("Another gateway is using this state directory.") from None
        self.database = self.state_dir / "publications.sqlite3"
        fd = os.open(self.database, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(self.database, 0o600)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, digest TEXT, body TEXT)")
            for key, body in db.execute("SELECT id, body FROM jobs").fetchall():
                job = json.loads(body)
                if job["state"] == "processing":
                    job.update(state="unknown", error="Service restarted. Check the destination before retrying.")
                    db.execute("UPDATE jobs SET body=? WHERE id=?", (json.dumps(job), key))
        self._lock = threading.Lock()
        self._account_locks = {key: threading.Lock() for key in accounts}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="social-publish")
        self._pending = 0
        self._closed = False

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=True)
        self._process_lock.close()

    def get(self, key: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT body FROM jobs WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def submit(self, key: str, body: dict) -> tuple[int, dict]:
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValidationError("Idempotency-Key must contain 8-128 letters, digits, underscores or hyphens.")
        if not isinstance(body, dict) or set(body) - {"account", "video_base64", "caption", "title", "tags", "tiktok", "youtube"}:
            raise ValidationError("Unexpected publication fields.")
        account_key = body.get("account")
        if not isinstance(account_key, str) or account_key not in self.accounts:
            raise ValidationError("Unknown account. Use GET /v1/accounts.")
        if not isinstance(body.get("caption"), str) or len(body["caption"]) > 10000:
            raise ValidationError("Provide a caption of at most 10000 characters.")
        if not isinstance(body.get("title", ""), str) or len(body.get("title", "")) > 100:
            raise ValidationError("title must be a string of at most 100 characters.")
        tags = body.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(t, str) or len(t) > 100 for t in tags):
            raise ValidationError("tags must be an array of short strings.")
        try:
            encoded = body["video_base64"]
            if not isinstance(encoded, str):
                raise ValueError()
            video = base64.b64decode(encoded, validate=True)
            if not 0 < len(video) <= MAX_VIDEO_BYTES:
                raise ValueError()
        except (KeyError, ValueError):
            raise ValidationError("Provide a nonempty base64 MP4 up to 32 MiB.") from None
        options = {}
        for name, cls in (("tiktok", TikTokOptions), ("youtube", YouTubeOptions)):
            if body.get(name) is not None:
                try:
                    options[name] = cls(**body[name])
                except (TypeError, ValueError):
                    raise ValidationError(f"Invalid {name} options.") from None
        # Include destination identity so reconnection cannot redirect an old request key.
        account = self.accounts[account_key]
        digest = hashlib.sha256(json.dumps([body, account.platform, account.account_id],
                                            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._lock, self._db() as db:
            if self._closed:
                return 503, {"error": "Gateway is shutting down. Query the same publication ID before retrying."}
            row = db.execute("SELECT digest, body FROM jobs WHERE id=?", (key,)).fetchone()
            if row:
                if row[0] != digest:
                    return 409, {"error": "This idempotency key belongs to a different request or destination."}
                job = json.loads(row[1])
                return (202 if job["state"] == "processing" else 200), job
            if self._pending >= 8:
                return 429, {"error": "Publishing queue is full. Retry later with the same idempotency key."}
            job = {"id": key, "account": account_key, "state": "processing", "result": None, "error": None}
            db.execute("INSERT INTO jobs VALUES (?, ?, ?)", (key, digest, json.dumps(job)))
            db.commit()  # reservation must survive BEFORE the worker makes any provider call
            self._pending += 1
            self._pool.submit(self._publish, job, video, body, options)
        return 202, job

    def _publish(self, job, video, body, options):
        job = dict(job)
        try:
            with self._account_locks[job["account"]]:
                with tempfile.TemporaryDirectory(prefix="upload-", dir=self.state_dir) as folder:
                    path = Path(folder) / "video.mp4"
                    path.write_bytes(video)
                    os.chmod(path, 0o600)
                    result = self.publisher.publish(self.accounts[job["account"]],
                        VideoPost(path, body["caption"], body.get("title", ""), tuple(body.get("tags", []))),
                        **options)
            job.update(state="completed", result=asdict(result))
        except ValidationError:
            job.update(state="failed", error="Request rejected before upload. Check caption, options, token expiry and app configuration.")
        except PublishingError as error:
            job.update(state="unknown" if error.outcome_unknown else "failed", error=str(error))
        except Exception:
            job.update(state="unknown", error="Unconfirmed outcome. Check the destination before retrying.")
        finally:
            with self._lock:
                try:
                    with self._db() as db:
                        db.execute("UPDATE jobs SET body=? WHERE id=?", (json.dumps(job), job["id"]))
                finally:
                    self._pending -= 1

    def server(self, port: int = 8787) -> ThreadingHTTPServer:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # never log request headers, uploaded content or credentials

            def setup(self):
                super().setup()
                self.connection.settimeout(30)

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self):
                actual = self.headers.get("Authorization", "").encode()
                expected = f"Bearer {gateway._token}".encode()
                if self.headers.get("Origin") or not secrets.compare_digest(actual, expected):
                    self._send(401, {"error": "Unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._authorized():
                    return
                if self.path == "/v1/accounts":
                    self._send(200, {"accounts": [{"id": key, "platform": a.platform, "name": a.name,
                                                  "account_id": a.account_id} for key, a in gateway.accounts.items()]})
                elif self.path.startswith("/v1/publications/"):
                    key = self.path.removeprefix("/v1/publications/")
                    job = gateway.get(key) if KEY.fullmatch(key) else None
                    self._send(200 if job else 404, job or {"error": "Publication not found"})
                else:
                    self._send(404, {"error": "Not found"})

            def do_POST(self):
                if not self._authorized():
                    return
                if self.path != "/v1/publications":
                    self._send(404, {"error": "Not found"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_BODY_BYTES:
                        self._send(413, {"error": "Request too large or missing Content-Length"})
                        return
                    if self.headers.get_content_type() != "application/json":
                        self._send(415, {"error": "Use application/json"})
                        return
                    body = json.loads(self.rfile.read(size))
                    status, response = gateway.submit(self.headers.get("Idempotency-Key", ""), body)
                    self._send(status, response)
                except (ValidationError, ValueError, TypeError):
                    self._send(400, {"error": "Invalid publication request. Check fields, video and idempotency key."})

        return _BoundedHTTPServer(("127.0.0.1", port), Handler)
