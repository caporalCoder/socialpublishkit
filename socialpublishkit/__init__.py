"""SocialPublishKit: official-API video publishing, without a hosted subscription."""

from .client import Publisher
from .models import (Account, Platform, PublishingError, PublishResult, PublishStatus,
                     TikTokOptions, YouTubeOptions, ValidationError, VideoPost)
from .remote import GatewayClient, GatewayError

__version__ = "0.1.1"
__all__ = ["Publisher", "Account", "Platform", "VideoPost", "TikTokOptions", "YouTubeOptions",
           "PublishResult", "PublishStatus", "PublishingError", "ValidationError",
           "GatewayClient", "GatewayError"]
