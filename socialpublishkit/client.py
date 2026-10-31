"""Synchronous, dependency-free publishing client. No implicit credential storage."""

from dataclasses import asdict
import math
from pathlib import Path
import time
from typing import Callable, Mapping
from urllib.parse import urlsplit

from . import providers
from .models import (Account, Platform, PublishingError, PublishResult, PublishStatus,
                     TikTokOptions, ValidationError, VideoPost)

_PROVIDERS = {
    Platform.FACEBOOK_PAGE: providers.Facebook,
    Platform.INSTAGRAM: providers.Instagram,
    Platform.TIKTOK: providers.TikTok,
    Platform.YOUTUBE: providers.YouTube,
}
_IDS = {Platform.FACEBOOK_PAGE: "page", Platform.INSTAGRAM: "ig",
        Platform.TIKTOK: "open_id", Platform.YOUTUBE: "channel_id"}
_MODES = {"draft": "brouillon", "private": "prive", "public": "public"}


class Publisher:
    """One client for authenticated accounts; publishing never retries automatically.

    config uses the documented provider environment variable names, but is explicit:
    no ambient .env files or environment variables are read by this client.
    on_account_update lets the host persist rotated tokens to its own secure store.
    Use a separate Account per destination and do not publish concurrently with it.
    """

    def __init__(self, config: Mapping[str, str] | None = None, *,
                 on_account_update: Callable[[Account], None] | None = None):
        self._config = dict(config or {})
        self._on_account_update = on_account_update

    def _provider(self, platform: Platform, redirect_uri: str | None = None):
        try:
            platform = Platform(platform)
        except (ValueError, TypeError):
            raise ValidationError("Use facebook_page, instagram, tiktok, or youtube. Facebook profiles are unsupported.") from None
        return _PROVIDERS[platform](config=self._config, redirect_uri=redirect_uri)

    @staticmethod
    def _redirect(uri: str):
        parts = urlsplit(uri)
        if (not parts.hostname or parts.username or parts.password or parts.fragment or
                not (parts.scheme == "https" or
                     (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")))):
            raise ValidationError("Use an HTTPS callback or HTTP localhost callback, registered with the provider.")

    def authorization_url(self, platform: Platform, *, state: str, redirect_uri: str) -> str:
        """Host must generate, store, and verify a one-use random OAuth state."""
        self._redirect(redirect_uri)
        if not isinstance(state, str) or not state.strip():
            raise ValidationError("A nonempty OAuth state is required.")
        provider = self._provider(platform, redirect_uri)
        if not provider.configure():
            raise ValidationError("Missing OAuth app configuration: " + ", ".join(provider.variables))
        return provider.adresse(state)

    def exchange_code(self, platform: Platform, *, code: str, redirect_uri: str) -> Account:
        """Call only after the host verifies state and handles OAuth denial/errors."""
        self._redirect(redirect_uri)
        provider = self._provider(platform, redirect_uri)
        platform = Platform(platform)
        if not code or not provider.configure():
            raise ValidationError("Authorization code and OAuth app configuration are required.")
        try:
            data = provider.connecter(code)[provider.cle]
        except Exception:
            # Do not surface provider payloads, URLs, OAuth codes or token-bearing exceptions.
            raise PublishingError(platform, outcome_unknown=False) from None
        account = Account(platform, data["jeton"], str(data.get(_IDS[platform], "")),
                          data.get("nom", ""), data.get("renouvellement"), data.get("expire"),
                          tuple(filter(None, data.get("scope", "").split(","))))
        if self._on_account_update:
            self._on_account_update(account)
        return account

    @staticmethod
    def _credentials(account: Account) -> dict:
        if not isinstance(account.access_token, str) or not account.access_token.strip():
            raise ValidationError("An access token is required.")
        platform = Platform(account.platform)
        if platform in (Platform.FACEBOOK_PAGE, Platform.INSTAGRAM) and not account.account_id:
            raise ValidationError("An explicit Facebook Page or Instagram account ID is required.")
        if platform in (Platform.FACEBOOK_PAGE, Platform.INSTAGRAM) and not str(account.account_id).isdigit():
            raise ValidationError("Facebook Page and Instagram account IDs must be numeric.")
        if account.expires_at is not None and not math.isfinite(account.expires_at):
            raise ValidationError("expires_at must be a finite Unix timestamp.")
        return {"jeton": account.access_token, "nom": account.name,
                "renouvellement": account.refresh_token,
                "expire": account.expires_at if account.expires_at is not None else float("inf"),
                _IDS[platform]: account.account_id, "scope": ",".join(account.scopes)}

    def _persist_refresh(self, account: Account, data: dict):
        changed = (account.access_token != data["jeton"] or
                   account.refresh_token != data.get("renouvellement"))
        if changed:
            account.access_token = data["jeton"]
            account.refresh_token = data.get("renouvellement")
            account.expires_at = data.get("expire")
            if data.get("scope"):
                account.scopes = tuple(data["scope"].split(","))
            if self._on_account_update:
                self._on_account_update(account)

    def tiktok_creator_info(self, account: Account) -> dict:
        """Fetch current creator/privacy limits for the host's direct-post consent UI."""
        if account.platform != Platform.TIKTOK:
            raise ValidationError("A TikTok account is required.")
        provider = self._provider(Platform.TIKTOK)
        data = self._credentials(account)
        try:
            if time.time() > data["expire"] - providers.MARGE:
                if not data["renouvellement"] or not provider.configure():
                    raise ValidationError("Reconnect TikTok or provide refresh credentials.")
                data |= provider._jetons({"grant_type": "refresh_token", "refresh_token": data["renouvellement"]})
                self._persist_refresh(account, data)
            return provider._appel("/v2/post/publish/creator_info/query/", {}, data["jeton"])
        except ValidationError:
            raise
        except Exception:
            raise PublishingError(Platform.TIKTOK, outcome_unknown=False) from None

    def publish(self, account: Account, post: VideoPost, *,
                tiktok: TikTokOptions | None = None) -> PublishResult:
        """Publish exactly once after the host obtains the user's consent.

        A draft delivery is not a public post; a YouTube upload is not proof of
        processing or public visibility. This method does not schedule or fan out.
        """
        provider = self._provider(account.platform)
        platform = Platform(account.platform)
        data = self._credentials(account)
        video = Path(post.video).expanduser().resolve()
        if not video.is_file() or video.suffix.lower() != ".mp4" or video.stat().st_size == 0:
            raise ValidationError("Provide an existing, nonempty MP4 video.")
        if not isinstance(post.caption, str):
            raise ValidationError("caption must be a string.")
        if platform == Platform.YOUTUBE and (not post.title.strip() or len(post.title) > 100):
            raise ValidationError("YouTube requires a title between 1 and 100 characters.")
        if platform == Platform.INSTAGRAM and len(post.caption) > 2200:
            raise ValidationError("Instagram captions are limited to 2200 characters.")
        if time.time() > data["expire"] - providers.MARGE:
            if platform not in (Platform.TIKTOK, Platform.YOUTUBE):
                raise ValidationError("The account token has expired; reconnect it.")
            if not data["renouvellement"] or not provider.configure():
                raise ValidationError("Token renewal requires refresh token and app configuration.")
        options = {}
        if tiktok is not None and platform != Platform.TIKTOK:
            raise ValidationError("TikTok options can only be used with a TikTok account.")
        if platform == Platform.TIKTOK:
            tiktok = tiktok or TikTokOptions()
            if not isinstance(tiktok.mode, str) or tiktok.mode not in _MODES:
                raise ValidationError("TikTok mode must be draft, private, or public.")
            mode = _MODES[tiktok.mode]
            if mode not in provider.modes():
                raise ValidationError("TikTok mode requires an approved and authorized scope in TIKTOK_SCOPES.")
            required_scope = "video.upload" if mode == "brouillon" else "video.publish"
            if account.scopes and required_scope not in account.scopes:
                raise ValidationError("Reconnect TikTok with the required publishing scope.")
            if mode != "brouillon":
                duration = tiktok.duration_seconds
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                    raise ValidationError("Direct posting requires the actual positive duration_seconds.")
                if len(post.caption.encode("utf-16-le")) // 2 > 2200:
                    raise ValidationError("TikTok direct captions are limited to 2200 UTF-16 units.")
            for name in ("disable_comment", "disable_duet", "disable_stitch", "paid_partnership", "own_brand"):
                if type(getattr(tiktok, name)) is not bool:
                    raise ValidationError(f"{name} must be a boolean.")
            if tiktok.ai_generated is not None and type(tiktok.ai_generated) is not bool:
                raise ValidationError("ai_generated must be a boolean or None.")
            options = asdict(tiktok) | {"tiktok": mode}
        text = {"texte": post.caption, "titre": post.title, "description": post.caption,
                "tags": list(post.tags)}
        try:
            try:
                result = provider.publier(data, str(video), text, options)
            finally:
                self._persist_refresh(account, data)
        except Exception:
            # Even a polling failure can follow a successful publication. Never auto-retry.
            raise PublishingError(platform, outcome_unknown=True) from None
        status = PublishStatus(result["status"])
        note = ("Draft delivered to the TikTok inbox. Complete the caption and publish in TikTok."
                if status == PublishStatus.DRAFT_DELIVERED else result.get("note", ""))
        return PublishResult(platform, status, result["id"], result.get("url", ""), note)
