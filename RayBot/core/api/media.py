"""Rich-media and Markdown image upload endpoints."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import pathlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import HTTPConfig
from ..constants import FileType
from ..errors import APIError
from ..http import APIClient
from ..models.common import (
    MaterialImage,
    MaterialImagePage,
    MessageResponse,
    UploadPrepareResult,
)
from ..net import is_loopback_host
from .base import BaseAPI, segment

DIRECT_UPLOAD_LIMIT = 5 * 1024 * 1024
HASH_WINDOW = 10_002_432
IMAGE_LIMIT = 10 * 1024 * 1024
MAX_UPLOAD_CONCURRENCY = 16
IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
VOICE_SUFFIXES = {".silk", ".mp3", ".wav", ".ogg"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass(slots=True, frozen=True)
class MediaTarget:
    """Address of a C2C or group media bucket.

    Uploaded files are isolated per scenario: a file uploaded for C2C cannot be
    sent to a group and vice versa.
    """

    kind: str
    openid: str

    def __post_init__(self) -> None:
        if self.kind not in {"c2c", "group"}:
            raise ValueError("MediaTarget.kind must be 'c2c' or 'group'")
        if not self.openid:
            raise ValueError("MediaTarget.openid is required")

    @classmethod
    def c2c(cls, user_openid: str) -> MediaTarget:
        return cls("c2c", user_openid)

    @classmethod
    def group(cls, group_openid: str) -> MediaTarget:
        return cls("group", group_openid)

    @property
    def base_path(self) -> str:
        if self.kind == "c2c":
            return f"/v2/users/{segment(self.openid)}"
        return f"/v2/groups/{segment(self.openid)}"


@dataclass(slots=True, frozen=True)
class FileHashes:
    md5: str
    sha1: str
    md5_10m: str


class MediaAPI(BaseAPI):
    """Upload files for message attachments and Markdown images."""

    def __init__(
        self,
        client: APIClient,
        config: HTTPConfig,
        *,
        plain_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client)
        self._config = config
        self._owns_plain = plain_client is None
        self._plain = plain_client or httpx.AsyncClient(
            timeout=httpx.Timeout(max(config.timeout, 10.0), connect=config.connect_timeout),
            trust_env=config.trust_env,
            follow_redirects=False,
            headers={"User-Agent": config.user_agent},
        )

    async def upload_prepare(
        self,
        target: MediaTarget,
        *,
        file_type: int | FileType,
        file_size: int,
        file_name: str,
        hashes: FileHashes,
    ) -> UploadPrepareResult:
        """Start a chunked upload and return presigned part URLs."""

        data = await self._client.post(
            f"{target.base_path}/upload_prepare",
            json={
                "file_type": int(file_type),
                "file_size": str(file_size),
                "file_name": file_name,
                "md5": hashes.md5,
                "sha1": hashes.sha1,
                "md5_10m": hashes.md5_10m,
            },
            route="media.prepare",
        )
        return UploadPrepareResult.from_dict(data or {})

    async def upload_part_finish(
        self,
        target: MediaTarget,
        *,
        upload_id: str,
        part_index: int,
        block_size: int,
        md5: str | None = None,
    ) -> None:
        """Notify the platform that one presigned part has been uploaded."""

        body: dict[str, Any] = {
            "upload_id": upload_id,
            "part_index": part_index,
            "block_size": str(block_size),
        }
        if md5:
            body["md5"] = md5
        await self._client.post(
            f"{target.base_path}/upload_part_finish",
            json=body,
            route="media.part_finish",
        )

    async def upload(
        self,
        target: MediaTarget,
        *,
        file_type: int | FileType,
        url: str | None = None,
        upload_id: str | None = None,
        file_name: str | None = None,
        file_data: str | None = None,
        srv_send_msg: bool = False,
    ) -> MessageResponse:
        """Upload or merge a file and return its ``file_info``.

        Exactly one of ``url``, ``upload_id`` or ``file_data`` must be given.
        When ``srv_send_msg`` is true the platform sends the file immediately
        and the response contains a message ID, consuming active-message quota.
        """

        sources = [value for value in (url, upload_id, file_data) if value is not None]
        if len(sources) != 1:
            raise ValueError("exactly one of url, upload_id or file_data is required")
        body: dict[str, Any] = {
            "file_type": int(file_type),
            "srv_send_msg": srv_send_msg,
        }
        if url is not None:
            body["url"] = url
        if upload_id is not None:
            body["upload_id"] = upload_id
        if file_name is not None:
            body["file_name"] = file_name
        if file_data is not None:
            body["file_data"] = file_data
        data = await self._client.post(
            f"{target.base_path}/files",
            json=body,
            route=f"media.upload.{target.kind}",
        )
        return MessageResponse.from_dict(data or {})

    async def upload_url(
        self,
        target: MediaTarget,
        file_type: int | FileType,
        url: str,
        *,
        srv_send_msg: bool = False,
    ) -> MessageResponse:
        """Ask the platform to download and store a public URL."""

        return await self.upload(target, file_type=file_type, url=url, srv_send_msg=srv_send_msg)

    async def upload_bytes(
        self,
        target: MediaTarget,
        file_type: int | FileType,
        file_name: str,
        data: bytes,
        *,
        srv_send_msg: bool = False,
        force_chunked: bool = False,
    ) -> MessageResponse:
        """Upload in-memory bytes.

        Data up to 5 MB is base64-encoded and sent directly; larger data uses
        the chunked flow automatically.
        """

        hashes = await asyncio.to_thread(hash_bytes, data)
        if force_chunked or len(data) > DIRECT_UPLOAD_LIMIT:
            return await self._upload_chunked(
                target,
                file_type=file_type,
                file_name=file_name,
                file_size=len(data),
                hashes=hashes,
                reader=_bytes_slice_reader(data),
                srv_send_msg=srv_send_msg,
            )
        return await self.upload(
            target,
            file_type=file_type,
            file_name=file_name,
            file_data=base64.b64encode(data).decode("ascii"),
            srv_send_msg=srv_send_msg,
        )

    async def upload_file(
        self,
        target: MediaTarget,
        path: str | pathlib.Path,
        *,
        file_type: int | FileType | None = None,
        file_name: str | None = None,
        srv_send_msg: bool = False,
        force_chunked: bool = False,
    ) -> MessageResponse:
        """Upload a local file, choosing direct or chunked upload by size.

        The file type is inferred from the extension when omitted.  Files above
        5 MB use ``upload_prepare`` -> presigned ``PUT`` -> ``upload_part_finish``
        -> merge, with the server-provided concurrency.
        """

        file_path = pathlib.Path(path)
        try:
            size = (await asyncio.to_thread(file_path.stat)).st_size
        except FileNotFoundError as exc:
            raise FileNotFoundError(file_path) from exc
        name = file_name or file_path.name
        resolved_type = file_type if file_type is not None else infer_file_type(file_path)
        hashes = await asyncio.to_thread(hash_file, file_path)

        if size <= DIRECT_UPLOAD_LIMIT and not force_chunked:
            data = await asyncio.to_thread(file_path.read_bytes)
            return await self.upload(
                target,
                file_type=resolved_type,
                file_name=name,
                file_data=base64.b64encode(data).decode("ascii"),
                srv_send_msg=srv_send_msg,
            )

        return await self._upload_chunked(
            target,
            file_type=resolved_type,
            file_name=name,
            file_size=size,
            hashes=hashes,
            reader=_file_slice_reader(file_path),
            srv_send_msg=srv_send_msg,
        )

    async def upload_image(self, path: str | pathlib.Path) -> MaterialImage:
        """Upload a Markdown image and return its ``qqbot-media://`` reference."""

        file_path = pathlib.Path(path)
        try:
            size = (await asyncio.to_thread(file_path.stat)).st_size
        except FileNotFoundError as exc:
            raise FileNotFoundError(file_path) from exc
        if size > IMAGE_LIMIT:
            raise ValueError("Markdown images must not exceed 10 MB")
        content_type = IMAGE_CONTENT_TYPES.get(file_path.suffix.lower())
        if content_type is None:
            raise ValueError("supported image formats: png, jpeg, gif, webp")

        data = await asyncio.to_thread(file_path.read_bytes)
        hashes = await asyncio.to_thread(hash_bytes, data)
        prepared = await self._client.post(
            "/v2/media-images/prepare",
            json={
                "file_name": file_path.name,
                "file_size": size,
                "content_type": content_type,
                "md5": hashes.md5,
                "sha1": hashes.sha1,
            },
            route="media_image.prepare",
        )
        if (
            not isinstance(prepared, Mapping)
            or not prepared.get("presigned_url")
            or not prepared.get("upload_id")
        ):
            raise APIError(
                "media-image prepare returned no presigned_url or upload_id",
                body=prepared,
            )

        response = await self._put_presigned(
            str(prepared["presigned_url"]), data, content_type=content_type
        )
        etag = response.headers.get("ETag", "").strip('"')
        completed = await self._client.post(
            "/v2/media-images/complete",
            json={"upload_id": str(prepared.get("upload_id", "")), "md5": etag or hashes.md5},
            route="media_image.complete",
        )
        return MaterialImage.from_dict(completed or {})

    async def list_images(self, *, cursor: str | None = None) -> MaterialImagePage:
        """List valid Markdown images, newest first."""

        data = await self._client.get(
            "/v2/media-images",
            params={"cursor": cursor},
            route="media_image.list",
        )
        return MaterialImagePage.from_dict(data or {})

    async def delete_image(self, image_id: str) -> None:
        """Delete a Markdown image and release its quota."""

        await self._client.delete(
            f"/v2/media-images/{segment(image_id)}/delete",
            route="media_image.delete",
        )

    async def _upload_chunked(
        self,
        target: MediaTarget,
        *,
        file_type: int | FileType,
        file_name: str,
        file_size: int,
        hashes: FileHashes,
        reader: Callable[[int, int], Awaitable[bytes]],
        srv_send_msg: bool,
    ) -> MessageResponse:
        prepared = await self.upload_prepare(
            target,
            file_type=file_type,
            file_size=file_size,
            file_name=file_name,
            hashes=hashes,
        )
        if not prepared.upload_id or not prepared.parts:
            raise APIError("upload_prepare returned an incomplete result", body=prepared.raw)
        if prepared.block_size <= 0 and any(part.block_size <= 0 for part in prepared.parts):
            raise APIError("upload_prepare returned no usable block size", body=prepared.raw)

        # The server-provided concurrency is capped: a manipulated config must
        # not be able to open thousands of simultaneous upload connections.
        concurrency = min(int(prepared.upload_config.concurrency), MAX_UPLOAD_CONCURRENCY)
        retry_delay = max(0.1, float(prepared.upload_config.retry_delay))
        semaphore = asyncio.Semaphore(concurrency)

        async def send_part(index: int, presigned_url: str, block_size: int) -> None:
            async with semaphore:
                payload = await reader(index, block_size)
                if not payload:
                    return
                await self._put_presigned(
                    presigned_url, payload, retries=3, retry_delay=retry_delay
                )
                await self.upload_part_finish(
                    target,
                    upload_id=prepared.upload_id,
                    part_index=index,
                    block_size=block_size,
                    md5=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                )

        await asyncio.gather(
            *(
                send_part(
                    part.index,
                    part.presigned_url,
                    part.block_size or prepared.block_size,
                )
                for part in prepared.parts
            )
        )
        return await self.upload(
            target,
            file_type=file_type,
            upload_id=prepared.upload_id,
            file_name=file_name,
            srv_send_msg=srv_send_msg,
        )

    async def _put_presigned(
        self,
        url: str,
        data: bytes,
        *,
        content_type: str | None = None,
        retries: int = 2,
        retry_delay: float = 0.5,
    ) -> httpx.Response:
        _validate_presigned_url(url)
        headers = {"Content-Type": content_type} if content_type else None
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await self._plain.put(url, content=data, headers=headers)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                raise APIError(f"presigned upload failed: {exc.__class__.__name__}") from exc
            if 200 <= response.status_code < 300:
                return response
            if response.status_code >= 500 and attempt < retries:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            raise APIError(
                f"presigned upload failed with HTTP {response.status_code}",
                status=response.status_code,
            )
        raise APIError("presigned upload failed") from last_error

    async def aclose(self) -> None:
        """Close the internal plain HTTP client used for presigned uploads."""

        if self._owns_plain:
            await self._plain.aclose()


def infer_file_type(path: pathlib.Path) -> FileType:
    """Infer ``file_type`` from a file extension."""

    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return FileType.IMAGE
    if suffix == ".mp4":
        return FileType.VIDEO
    if suffix in VOICE_SUFFIXES:
        return FileType.VOICE
    return FileType.FILE


def _validate_presigned_url(url: str) -> None:
    """Reject presigned URLs that are not HTTPS (or loopback plain HTTP).

    The URL comes from an API response and user media is PUT to it.  Sending
    media to an ``http://`` or otherwise manipulated host would leak the file,
    so non-loopback uploads must be encrypted.
    """

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise APIError(f"presigned upload URL is invalid: {exc}") from exc
    if parsed.username or parsed.password:
        raise APIError("presigned upload URL must not contain credentials")
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    if scheme == "https" and host:
        return
    if scheme == "http" and host and is_loopback_host(host):
        return
    raise APIError(f"presigned upload URL must use https://, got {scheme!r} for host {host!r}")


def hash_bytes(data: bytes) -> FileHashes:
    """Compute MD5, SHA1 and the first-10MB MD5 for a byte string."""

    return FileHashes(
        md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
        sha1=hashlib.sha1(data, usedforsecurity=False).hexdigest(),
        md5_10m=hashlib.md5(data[:HASH_WINDOW], usedforsecurity=False).hexdigest(),
    )


def hash_file(path: pathlib.Path) -> FileHashes:
    """Compute upload hashes by streaming a file from disk."""

    md5 = hashlib.md5(usedforsecurity=False)
    sha1 = hashlib.sha1(usedforsecurity=False)
    window = hashlib.md5(usedforsecurity=False)
    remaining = HASH_WINDOW
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            md5.update(chunk)
            sha1.update(chunk)
            if remaining > 0:
                piece = chunk[:remaining]
                window.update(piece)
                remaining -= len(piece)
    return FileHashes(md5=md5.hexdigest(), sha1=sha1.hexdigest(), md5_10m=window.hexdigest())


def _file_slice_reader(
    path: pathlib.Path,
) -> Callable[[int, int], Awaitable[bytes]]:
    def read(offset: int, size: int) -> bytes:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(size)

    async def read_async(index: int, block_size: int) -> bytes:
        return await asyncio.to_thread(read, index * block_size, block_size)

    return read_async


def _bytes_slice_reader(data: bytes) -> Callable[[int, int], Awaitable[bytes]]:
    async def read_async(index: int, block_size: int) -> bytes:
        start = index * block_size
        return data[start : start + block_size]

    return read_async


__all__ = [
    "DIRECT_UPLOAD_LIMIT",
    "FileHashes",
    "MediaAPI",
    "MediaTarget",
    "hash_bytes",
    "hash_file",
    "infer_file_type",
]
