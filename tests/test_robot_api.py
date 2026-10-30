from __future__ import annotations

import json

import httpx
import pytest

from qqbot_toolkit import Bot
from qqbot_toolkit.models.outbound import Panel, PanelItem

from .conftest import api_transport, json_response, make_config


async def test_get_global_menu_parses_items() -> None:
    def callback(request: httpx.Request) -> httpx.Response:
        return json_response(
            {
                "version": 3,
                "menu": {
                    "items": [
                        {"type": "send_message", "name": "帮助", "send_message": "/help"},
                        {
                            "type": "menu",
                            "name": "更多",
                            "sub_menu_items": [
                                {"type": "link", "name": "官网", "link": "https://example.com"}
                            ],
                        },
                    ]
                },
            }
        )

    bot = Bot(make_config(), transport=api_transport(callback))
    info = await bot.bot.get_global_menu()
    assert info.version == 3
    assert info.menu is not None
    assert info.menu.items[0].name == "帮助"
    assert info.menu.items[1].sub_menu_items is not None
    assert info.menu.items[1].sub_menu_items[0].link == "https://example.com"
    await bot.aclose()


async def test_create_panel_sends_full_configuration() -> None:
    captured: dict = {}

    def callback(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return json_response({"panel_id": "p_1"})

    bot = Bot(make_config(), transport=api_transport(callback))
    panel_id = await bot.bot.create_panel(
        scope="group",
        target_type="specific",
        group_openids=["G1"],
        panel=Panel(
            items=[PanelItem(type="command", name="签到", desc="每日签到")],
            remark="test",
        ),
    )

    assert panel_id == "p_1"
    assert captured == {
        "scope": "group",
        "target_type": "specific",
        "group_openids": ["G1"],
        "panel": {
            "items": [{"type": "command", "name": "签到", "desc": "每日签到"}],
            "remark": "test",
        },
    }
    await bot.aclose()


async def test_panel_validation_rejects_invalid_combinations() -> None:
    bot = Bot(make_config(), transport=api_transport(lambda request: json_response({})))
    with pytest.raises(ValueError):
        await bot.bot.create_panel(scope="invalid", panel=Panel())
    with pytest.raises(ValueError):
        await bot.bot.create_panel(
            scope="channel", target_type="specific", group_openids=["G"], panel=Panel()
        )
    with pytest.raises(ValueError):
        await bot.bot.create_panel(scope="group", target_type="specific", panel=Panel())
    with pytest.raises(ValueError):
        await bot.bot.create_panel(
            scope="group", target_type="all", group_openids=["G"], panel=Panel()
        )
    with pytest.raises(ValueError):
        await bot.bot.update_panel_targets("p_1", op="add", user_openids=["U"], group_openids=["G"])
    await bot.aclose()


async def test_list_and_iterate_panels() -> None:
    pages = {
        "": {
            "records": [
                {
                    "panel_id": "p_1",
                    "scope": "c2c",
                    "target_type": "all",
                    "panel": {"items": [{"type": "command", "name": "帮助"}]},
                }
            ],
            "next_cursor": "next",
            "is_end": False,
        },
        "next": {
            "records": [
                {
                    "panel_id": "p_2",
                    "scope": "c2c",
                    "target_type": "all",
                    "panel": {"items": []},
                }
            ],
            "next_cursor": "",
            "is_end": True,
        },
    }

    def callback(request: httpx.Request) -> httpx.Response:
        return json_response(pages[request.url.params.get("cursor", "")])

    bot = Bot(make_config(), transport=api_transport(callback))
    records = [record.panel_id async for record in bot.bot.iter_panels("c2c")]
    assert records == ["p_1", "p_2"]
    await bot.aclose()


async def test_update_panel_returns_version_and_target_update() -> None:
    requests: list[httpx.Request] = []

    def callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT" and request.url.path.endswith("/target"):
            return json_response({})
        return json_response({"version": 7})

    bot = Bot(make_config(), transport=api_transport(callback))
    version = await bot.bot.update_panel(
        "p_1", Panel(items=[PanelItem(type="command", name="新指令")])
    )
    assert version == 7
    await bot.bot.update_panel_targets("p_1", op="add", group_openids=["G2"])

    assert requests[0].method == "PUT"
    assert requests[0].url.path == "/v2/panels/p_1"
    assert requests[1].url.path == "/v2/panels/p_1/target"
    assert json.loads(requests[1].content) == {"op": "add", "group_openids": ["G2"]}
    await bot.aclose()
