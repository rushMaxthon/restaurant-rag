"""Rider documents in a private Supabase Storage bucket, over its REST API.

No SDK: four calls (upload, create bucket, sign, delete) through `httpx`,
which the backend already has. The service key never leaves the server; an
admin sees a document through a signed link that expires in five minutes, so
a link pasted into a chat stops working before it can travel far.

A file's type is read from its first bytes (`sniff_image`), never from its
name or the client's Content-Type: a PDF or a page of HTML renamed to .jpg
must not be stored and then opened in an admin's browser.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SIGNED_SECONDS = 300
EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class StorageUnavailable(Exception):
    """No bucket configured, or Supabase refused. Reported, never worked around."""


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class StorageClient:
    def __init__(self, url: str, key: str, bucket: str, transport: httpx.BaseTransport | None = None) -> None:
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self._client = httpx.Client(
            timeout=20,
            transport=transport,
            headers={"Authorization": f"Bearer {key}", "apikey": key},
        )

    def _make_bucket(self) -> None:
        # Private: `public: false` is the whole point. Created on first use so
        # nobody has to remember to click it into existence in a dashboard.
        response = self._client.post(
            f"{self.base}/bucket", json={"id": self.bucket, "name": self.bucket, "public": False}
        )
        if response.status_code >= 400 and "already exists" not in response.text:
            raise StorageUnavailable(f"Could not create the documents bucket ({response.status_code})")

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        def send() -> httpx.Response:
            return self._client.post(
                f"{self.base}/object/{self.bucket}/{path}",
                content=data,
                headers={"Content-Type": content_type, "x-upsert": "false"},
            )

        response = send()
        if response.status_code in (400, 404) and "Bucket not found" in response.text:
            self._make_bucket()
            response = send()
        if response.status_code >= 400:
            logger.warning("Document upload refused: %s %s", response.status_code, response.text[:200])
            raise StorageUnavailable(f"The document store refused the upload ({response.status_code})")

    def signed_url(self, path: str, seconds: int = SIGNED_SECONDS) -> str:
        response = self._client.post(f"{self.base}/object/sign/{self.bucket}/{path}", json={"expiresIn": seconds})
        if response.status_code >= 400:
            raise StorageUnavailable(f"Could not sign a document link ({response.status_code})")
        return self.base + response.json()["signedURL"]

    def delete(self, path: str) -> None:
        # Best effort: an orphaned object is a little storage, not a leak -
        # nothing points at it and the bucket is private.
        try:
            self._client.request("DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": [path]})
        except httpx.HTTPError:
            logger.warning("Could not delete an old document %s", path)


def configured() -> bool:
    settings = get_settings()
    return bool(settings.supabase_url and settings.supabase_service_key)


def client() -> StorageClient:
    settings = get_settings()
    if not configured():
        raise StorageUnavailable("storage_not_configured")
    return StorageClient(settings.supabase_url, settings.supabase_service_key, settings.rider_docs_bucket)


def upload(path: str, data: bytes, content_type: str) -> None:
    client().upload(path, data, content_type)


def signed_url(path: str, seconds: int = SIGNED_SECONDS) -> str:
    return client().signed_url(path, seconds)


def delete(path: str) -> None:
    if configured():
        client().delete(path)
