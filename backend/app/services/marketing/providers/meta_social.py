"""Instagram and Facebook, through Meta's Graph API.

One module for both because they are one API with two shapes, and the
differences are small enough that two files would drift apart:

    Instagram   two calls. `POST /{ig_user_id}/media` uploads a container and
                returns its id; `POST /{ig_user_id}/media_publish` publishes
                it. A photo is mandatory — Instagram has no text-only post,
                which is why the editor refuses to continue without one.

    Facebook    one call. `POST /{page_id}/photos` with a URL, or
                `POST /{page_id}/feed` when there is no image. A Page post is
                happy with text alone.

**Nothing here has recipients.** `publish` returns a post id and a permalink,
and that is the entire record of the send. There is no per-person row to
write, which is why `dispatch` routes social campaigns down a different path
and why the report reads a promo code rather than an attribution window.

**Insights return what the platform gave, not a fixed shape.** A metric Meta
stops serving should disappear from the report rather than read as zero — an
owner seeing `impressions: 0` on a post that clearly got seen will conclude
the product is broken, and they will be right to.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.models.enums import MarketingChannel
from app.services.marketing.providers.base import (
    ProviderError,
    PublishResult,
    SocialContent,
)

logger = logging.getLogger(__name__)
settings = get_settings()

GRAPH = "https://graph.facebook.com/v21.0"


def _caption(content: SocialContent) -> str:
    """The caption as it is posted, hashtags folded in unless they go below.

    The `hashtags_in_comment` habit is a real second API call, not a
    formatting choice, so the caption genuinely has to omit them.
    """

    if content.hashtags and not content.hashtags_in_comment:
        return f"{content.caption}\n\n{content.hashtags}".strip()
    return content.caption


def _error(response: httpx.Response, *, what: str) -> ProviderError:
    try:
        body = response.json().get("error", {})
        message = body.get("message") or ""
    except ValueError:
        message = ""
    if response.status_code in (401, 403):
        return ProviderError(
            f"Meta rejected your access token, so the {what} was not posted. "
            "Reconnect the account to generate a new one."
        )
    detail = f": {message}" if message else ""
    return ProviderError(f"Meta refused the {what} ({response.status_code}){detail}")


class InstagramProvider:
    channel = MarketingChannel.INSTAGRAM

    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._user_id = str(config.get("ig_user_id") or "").strip()
        self._token = str(credentials.get("access_token") or "").strip()
        if not self._user_id or not self._token:
            raise ProviderError(
                "Instagram is not finished connecting — it still needs an account ID "
                "and an access token."
            )

    def publish(self, content: SocialContent) -> PublishResult:
        if not content.image_url:
            raise ProviderError(
                "Instagram will not accept a post without a photo or a video."
            )

        with httpx.Client(timeout=settings.marketing_provider_timeout_seconds) as client:
            container = self._post(
                client,
                f"{GRAPH}/{self._user_id}/media",
                {"image_url": content.image_url, "caption": _caption(content)},
                what="photo",
            )
            creation_id = container.get("id")
            if not creation_id:
                raise ProviderError("Instagram accepted the photo but returned no id for it.")

            published = self._post(
                client,
                f"{GRAPH}/{self._user_id}/media_publish",
                {"creation_id": creation_id},
                what="post",
            )
            post_id = published.get("id")
            if not post_id:
                raise ProviderError("Instagram did not confirm the post.")

            # The comment is best-effort and deliberately does not fail the
            # publish: the post is already live, and reporting the whole
            # campaign as failed because a hashtag comment did not land would
            # tell the owner something false.
            if content.hashtags and content.hashtags_in_comment:
                try:
                    self._post(
                        client,
                        f"{GRAPH}/{post_id}/comments",
                        {"message": content.hashtags},
                        what="comment",
                    )
                except ProviderError:
                    logger.warning("Hashtag comment failed for IG post %s", post_id)

            return PublishResult(post_id=str(post_id), permalink=self._permalink(client, str(post_id)))

    def insights(self, post_id: str) -> dict[str, int]:
        metrics = "impressions,reach,likes,comments,saved"
        with httpx.Client(timeout=settings.marketing_provider_timeout_seconds) as client:
            response = client.get(
                f"{GRAPH}/{post_id}/insights",
                params={"metric": metrics, "access_token": self._token},
            )
            if response.status_code >= 300:
                raise _error(response, what="post's numbers")
            out: dict[str, int] = {}
            for entry in response.json().get("data", []):
                values = entry.get("values") or []
                if values and isinstance(values[0].get("value"), int):
                    out[entry["name"]] = values[0]["value"]
            return out

    def _permalink(self, client: httpx.Client, post_id: str) -> str | None:
        """Best-effort: the post exists whether or not we can link to it."""

        try:
            response = client.get(
                f"{GRAPH}/{post_id}", params={"fields": "permalink", "access_token": self._token}
            )
            if response.status_code < 300:
                return response.json().get("permalink")
        except httpx.HTTPError:
            logger.debug("Permalink lookup failed for %s", post_id, exc_info=True)
        return None

    def _post(self, client: httpx.Client, url: str, data: dict, *, what: str) -> dict:
        try:
            response = client.post(url, data={**data, "access_token": self._token})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Instagram was unreachable: {exc}", retryable=True) from exc
        if response.status_code >= 300:
            raise _error(response, what=what)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("Instagram sent back something we could not read.") from exc


class FacebookProvider:
    channel = MarketingChannel.FACEBOOK

    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._page_id = str(config.get("page_id") or "").strip()
        self._token = str(credentials.get("access_token") or "").strip()
        if not self._page_id or not self._token:
            raise ProviderError(
                "Facebook is not finished connecting — it still needs a Page ID and an "
                "access token."
            )

    def publish(self, content: SocialContent) -> PublishResult:
        caption = _caption(content)
        with httpx.Client(timeout=settings.marketing_provider_timeout_seconds) as client:
            if content.image_url:
                payload = {"url": content.image_url, "caption": caption}
                url = f"{GRAPH}/{self._page_id}/photos"
            else:
                # A Page post is happy with text alone, unlike Instagram.
                payload = {"message": caption}
                if content.link_url:
                    payload["link"] = content.link_url
                url = f"{GRAPH}/{self._page_id}/feed"

            try:
                response = client.post(url, data={**payload, "access_token": self._token})
            except httpx.HTTPError as exc:
                raise ProviderError(f"Facebook was unreachable: {exc}", retryable=True) from exc
            if response.status_code >= 300:
                raise _error(response, what="post")

            body = response.json()
            # `/photos` answers with `post_id`, `/feed` with `id`. Both name
            # the same thing and the report needs one of them.
            post_id = body.get("post_id") or body.get("id")
            if not post_id:
                raise ProviderError("Facebook did not confirm the post.")
            return PublishResult(
                post_id=str(post_id),
                permalink=f"https://www.facebook.com/{post_id}",
            )

    def insights(self, post_id: str) -> dict[str, int]:
        metrics = "post_impressions,post_impressions_unique,post_engaged_users,post_clicks"
        with httpx.Client(timeout=settings.marketing_provider_timeout_seconds) as client:
            response = client.get(
                f"{GRAPH}/{post_id}/insights",
                params={"metric": metrics, "access_token": self._token},
            )
            if response.status_code >= 300:
                raise _error(response, what="post's numbers")
            out: dict[str, int] = {}
            for entry in response.json().get("data", []):
                values = entry.get("values") or []
                if values and isinstance(values[0].get("value"), int):
                    out[entry["name"]] = values[0]["value"]
            return out
