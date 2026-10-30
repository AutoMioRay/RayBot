"""Gateway endpoint discovery."""

from __future__ import annotations

from ..config import GatewayConfig
from ..constants import DEFAULT_GATEWAY_ENDPOINT, FALLBACK_GATEWAY_ENDPOINT
from ..errors import APIError
from ..models.common import GatewayInfo
from .base import BaseAPI


class GatewayAPI(BaseAPI):
    """Resolve the WebSocket URL and shard recommendation."""

    def __init__(self, client, config: GatewayConfig | None = None) -> None:
        super().__init__(client)
        self._config = config or GatewayConfig()

    async def get(self) -> GatewayInfo:
        """Fetch gateway information.

        Uses ``gateway.endpoint`` when configured; otherwise tries
        ``/gateway/bot`` and falls back to ``/gateway`` for accounts that only
        expose the general endpoint.
        """

        if self._config.endpoint:
            endpoints = [self._config.endpoint]
        else:
            endpoints = [DEFAULT_GATEWAY_ENDPOINT, FALLBACK_GATEWAY_ENDPOINT]

        last_error: APIError | None = None
        for index, endpoint in enumerate(endpoints):
            try:
                data = await self._client.get(endpoint)
            except APIError as exc:
                last_error = exc
                if index + 1 < len(endpoints) and exc.status == 404:
                    continue
                raise
            info = GatewayInfo.from_dict(data or {})
            if not info.url and index + 1 < len(endpoints):
                continue
            return info

        if last_error is not None:
            raise last_error
        raise APIError("no gateway endpoint configured")


__all__ = ["GatewayAPI"]
