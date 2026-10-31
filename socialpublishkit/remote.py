"""Python client for the same gateway used by JavaScript and Rust."""

import base64
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .models import ValidationError


class GatewayError(RuntimeError):
    def __init__(self, status: int | None):
        self.status = status
        super().__init__(f"Gateway request failed ({status or 'connection'}). Query the same publication ID before retrying.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class GatewayClient:
    def __init__(self, token: str, base_url: str = "http://127.0.0.1:8787"):
        parts = urlsplit(base_url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path not in ("", "/")
                or (parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"))):
            raise ValidationError("Use HTTPS or a loopback HTTP gateway URL without credentials/path/query.")
        if not isinstance(token, str) or not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValidationError("A nonempty ASCII bearer token without whitespace is required.")
        self._token, self.base_url = token, base_url.rstrip("/")

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ValidationError("Use a stable 8-128 character publication ID.")

    def _request(self, path, body=None, key=None):
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(self.base_url + path, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise GatewayError(status) from None
        except (OSError, ValueError):
            raise GatewayError(None) from None

    def accounts(self):
        return self._request("/v1/accounts")["accounts"]

    def publication(self, publication_id):
        self._key(publication_id)
        return self._request("/v1/publications/" + publication_id)

    def publish(self, *, publication_id, account, video, caption, title="", tags=(), tiktok=None, youtube=None):
        self._key(publication_id)
        path = Path(video)
        if path.suffix.lower() != ".mp4" or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
            raise ValidationError("Provide a nonempty MP4 up to 32 MiB.")
        body = {"account": account, "video_base64": base64.b64encode(path.read_bytes()).decode(),
                "caption": caption, "title": title, "tags": list(tags)}
        from dataclasses import asdict
        for key, options in (("tiktok", tiktok), ("youtube", youtube)):
            if options is not None:
                body[key] = asdict(options)
        return self._request("/v1/publications", body, publication_id)
