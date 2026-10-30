"""Robot profile, share-link, global menu and command-panel endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from ..models.common import BotProfile
from ..models.menu import (
    MenuInfo,
    PanelCreateResult,
    PanelDetail,
    PanelPage,
    PanelRecord,
    PanelVersion,
)
from ..models.outbound import Menu, Panel, Payload
from .base import BaseAPI, segment

PANEL_SCOPES = frozenset({"c2c", "group", "channel", "dm"})
PANEL_TARGET_TYPES = frozenset({"all", "specific"})


class BotAPI(BaseAPI):
    """Operations on the robot account itself."""

    async def get_me(self) -> BotProfile:
        """Get the robot's profile (``GET /users/@me``)."""

        data = await self._client.get("/users/@me", route="bot.me")
        return BotProfile.from_dict(data or {})

    async def generate_share_link(self, callback_data: str | None = None) -> str:
        """Generate a friend-invitation link.

        ``callback_data`` (at most 32 characters) is returned unchanged in the
        ``FRIEND_ADD`` event's ``scene_param`` field.
        """

        if callback_data is not None and len(callback_data) > 32:
            raise ValueError("callback_data must not exceed 32 characters")
        body: dict[str, Any] = {}
        if callback_data is not None:
            body["callback_data"] = callback_data
        data = await self._client.post("/v2/generate_url_link", json=body, route="bot.share_link")
        if not isinstance(data, Mapping):
            return ""
        nested = data.get("data")
        if isinstance(nested, Mapping):
            return str(nested.get("url", ""))
        return str(data.get("url", ""))

    async def get_global_menu(self) -> MenuInfo:
        """Get the current C2C global menu and its version."""

        data = await self._client.get("/v2/menu", route="bot.menu.read")
        return MenuInfo.from_dict(data or {})

    async def update_global_menu(self, menu: Menu | Mapping[str, Any]) -> None:
        """Replace the C2C custom menu.

        The menu applies to every user and does not support per-user content.
        The whole menu is overwritten, so always send the full configuration.
        """

        menu_payload = menu.to_dict() if isinstance(menu, Payload) else dict(menu)
        await self._client.put("/v2/menu", json={"menu": menu_payload}, route="bot.menu.write")

    async def create_panel(
        self,
        *,
        scope: str,
        panel: Panel | Mapping[str, Any],
        target_type: str = "all",
        user_openids: Sequence[str] | None = None,
        group_openids: Sequence[str] | None = None,
    ) -> str:
        """Create a command panel and return its ``panel_id``.

        Args:
            scope: ``c2c``, ``group``, ``channel`` or ``dm``.
            panel: Panel items, remark and optional version.
            target_type: ``all`` or ``specific``.  Only C2C and group panels may
                be specific.
            user_openids: C2C target users, at most 20.
            group_openids: Group target groups, at most 20.
        """

        _validate_scope(scope)
        _validate_target(target_type)
        if target_type == "specific":
            if scope == "c2c":
                _validate_targets(user_openids, "user_openids")
                if group_openids:
                    raise ValueError("group_openids is only valid for group scope")
            elif scope == "group":
                _validate_targets(group_openids, "group_openids")
                if user_openids:
                    raise ValueError("user_openids is only valid for c2c scope")
            else:
                raise ValueError("channel and dm panels only support target_type='all'")
        elif user_openids or group_openids:
            raise ValueError("target openids are only valid with target_type='specific'")

        body: dict[str, Any] = {
            "scope": scope,
            "target_type": target_type,
            "panel": _panel_payload(panel),
        }
        if user_openids:
            body["user_openids"] = list(user_openids)
        if group_openids:
            body["group_openids"] = list(group_openids)
        data = await self._client.post("/v2/panels", json=body, route="bot.panel.write")
        return PanelCreateResult.from_dict(data or {}).panel_id

    async def list_panels(
        self, *, scope: str, cursor: str = "", limit: int | None = None
    ) -> PanelPage:
        """List active command panels for one scope, newest first."""

        _validate_scope(scope)
        data = await self._client.get(
            "/v2/panels",
            params={"scope": scope, "cursor": cursor, "limit": limit},
            route="bot.panel.read",
        )
        return PanelPage.from_dict(data or {})

    async def iter_panels(
        self,
        scope: str,
        *,
        limit: int = 50,
        max_pages: int | None = None,
    ) -> AsyncIterator[PanelRecord]:
        """Yield every command panel in ``scope`` across all pages."""

        cursor = ""
        seen: set[str] = set()
        pages = 0
        while True:
            page = await self.list_panels(scope=scope, cursor=cursor, limit=limit)
            for record in page.records:
                yield record
            pages += 1
            if page.is_end or not page.next_cursor or page.next_cursor in seen:
                return
            if max_pages is not None and pages >= max_pages:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    async def get_panel(self, panel_id: str) -> PanelDetail:
        """Get one panel's full configuration and target lists."""

        data = await self._client.get(f"/v2/panels/{segment(panel_id)}", route="bot.panel.read")
        return PanelDetail.from_dict(data or {})

    async def update_panel(self, panel_id: str, panel: Panel | Mapping[str, Any]) -> int:
        """Replace a panel's items and remark; return the new version."""

        data = await self._client.put(
            f"/v2/panels/{segment(panel_id)}",
            json={"panel": _panel_payload(panel)},
            route="bot.panel.write",
        )
        return PanelVersion.from_dict(data or {}).version

    async def delete_panel(self, panel_id: str) -> None:
        """Delete a panel so it no longer applies to any user or group."""

        await self._client.delete(f"/v2/panels/{segment(panel_id)}", route="bot.panel.write")

    async def update_panel_targets(
        self,
        panel_id: str,
        *,
        op: str,
        user_openids: Sequence[str] | None = None,
        group_openids: Sequence[str] | None = None,
    ) -> None:
        """Add or remove panel targets.

        C2C panels operate on ``user_openids``; group panels operate on
        ``group_openids``.  Each call accepts at most 20 targets.
        """

        if op not in {"add", "del"}:
            raise ValueError("op must be 'add' or 'del'")
        if bool(user_openids) == bool(group_openids):
            raise ValueError("exactly one of user_openids or group_openids is required")
        targets = user_openids or group_openids or ()
        if len(targets) > 20:
            raise ValueError("at most 20 targets are allowed per request")
        body: dict[str, Any] = {"op": op}
        if user_openids:
            body["user_openids"] = list(user_openids)
        else:
            body["group_openids"] = list(group_openids or ())
        await self._client.put(
            f"/v2/panels/{segment(panel_id)}/target",
            json=body,
            route="bot.panel.target",
        )


def _panel_payload(panel: Panel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(panel, Payload):
        return panel.to_dict()
    return dict(panel)


def _validate_scope(scope: str) -> None:
    if scope not in PANEL_SCOPES:
        raise ValueError(f"scope must be one of {sorted(PANEL_SCOPES)}")


def _validate_target(target_type: str) -> None:
    if target_type not in PANEL_TARGET_TYPES:
        raise ValueError(f"target_type must be one of {sorted(PANEL_TARGET_TYPES)}")


def _validate_targets(ids: Sequence[str] | None, name: str) -> None:
    if not ids:
        raise ValueError(f"{name} is required for target_type='specific'")
    if len(ids) > 20:
        raise ValueError(f"{name} must not contain more than 20 entries")


__all__ = ["BotAPI", "PANEL_SCOPES", "PANEL_TARGET_TYPES"]
