"""Shared API-group base class."""

from __future__ import annotations

from urllib.parse import quote

from ..http import APIClient


def segment(value: str | int) -> str:
    """Percent-encode one path segment (OpenIDs, message ids, strategy ids)."""

    return quote(str(value), safe="")


class BaseAPI:
    """Base class holding the shared :class:`APIClient`."""

    __slots__ = ("_client",)

    def __init__(self, client: APIClient) -> None:
        self._client = client

    @property
    def client(self) -> APIClient:
        return self._client


__all__ = ["BaseAPI", "segment"]
