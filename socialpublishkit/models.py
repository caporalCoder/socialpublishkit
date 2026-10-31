"""Public types. Credentials are intentionally excluded from repr/log output."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Platform(str, Enum):
    FACEBOOK_PAGE = "facebook_page"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


class PublishStatus(str, Enum):
    DRAFT_DELIVERED = "draft_delivered"
    UPLOADED = "uploaded"
    PUBLISHED = "published"


@dataclass
class Account:
    platform: Platform
    access_token: str = field(repr=False)
    account_id: str = ""
    name: str = ""
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: float | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoPost:
    video: str | Path
    caption: str
    title: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TikTokOptions:
    # Direct publication is opt-in; application approval is still required.
    mode: str = "draft"  # draft, private, public
    duration_seconds: float | None = None
    disable_comment: bool = True
    disable_duet: bool = True
    disable_stitch: bool = True
    paid_partnership: bool = False
    own_brand: bool = False
    ai_generated: bool | None = None  # explicit disclosure only, never inferred


@dataclass(frozen=True)
class PublishResult:
    platform: Platform
    status: PublishStatus
    post_id: str
    url: str = ""
    note: str = ""


class ValidationError(ValueError):
    """Invalid request, rejected before any upload."""


class PublishingError(RuntimeError):
    """No automatic retry: a provider may already have accepted the video."""

    def __init__(self, platform: Platform, *, outcome_unknown: bool):
        self.platform = platform
        self.outcome_unknown = outcome_unknown
        message = ("Publishing did not return a confirmed result. Check the destination before retrying."
                   if outcome_unknown else "Connection failed. Check app configuration and authorization.")
        super().__init__(f"{platform.value}: {message}")
