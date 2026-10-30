"""Interactive callback acknowledgement."""

from __future__ import annotations

from ..constants import InteractionCode
from .base import BaseAPI, segment


class InteractionsAPI(BaseAPI):
    """Acknowledge ``INTERACTION_CREATE`` events."""

    async def respond(
        self, interaction_id: str, code: int | InteractionCode = InteractionCode.SUCCESS
    ) -> None:
        """Respond to a message-button or quick-menu interaction.

        The request must arrive before the platform timeout (about three
        seconds) and may be sent only once per ``interaction_id``.
        """

        await self._client.put(
            f"/interactions/{segment(interaction_id)}",
            json={"code": int(code)},
            route="interaction.respond",
        )


__all__ = ["InteractionsAPI"]
