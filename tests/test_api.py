from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from qqbot_toolkit import Bot
from qqbot_toolkit.api.media import MediaTarget
from qqbot_toolkit.constants import FileType
from qqbot_toolkit.models import parse_event

from .conftest import api_transport, json_response, make_config


def c2c_event():
    return parse_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "incoming-1",
            "author": {"user_openid": "USER"},
            "content": "hello",
            "message_type": 0,
            "message_scene": {"ext": ["msg_idx=M1"]},
        },
    )


async def test_c2c_send_builds_expected_request() -> None:
    requests: list[httpx.Request] = []

    def callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return json_response({"id": "sent-1", "timestamp": "2026-07-21T10:00:00+08:00"})

    bot = Bot(make_config(), transport=api_transport(callback))
    response = await bot.c2c.send("USER", content="hi", msg_id="incoming-1", msg_seq=2)

    assert response.id == "sent-1"
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v2/users/USER/messages"
    body = json.loads(requests[0].content)
    assert body == {
        "msg_type": 0,
        "msg_seq": 2,
        "content": "hi",
        "msg_id": "incoming-1",
    }
    await bot.aclose()


async def test_markdown_type_is_inferred_and_content_must_be_empty() -> None:
    bodies: list[dict] = []

    def callback(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return json_response({"id": "m"})

    bot = Bot(make_config(), transport=api_transport(callback))
    await bot.c2c.send("USER", markdown="**hi**")
    assert bodies[0]["msg_type"] == 2
    assert bodies[0]["markdown"] == {"content": "**hi**"}
    assert "content" not in bodies[0]

    with pytest.raises(ValueError):
        await bot.c2c.send("USER", content="x", markdown="**hi**")
    with pytest.raises(ValueError):
        await bot.c2c.send("USER", content="x", msg_id="a", event_id="b")
    await bot.aclose()


async def test_group_send_and_recall() -> None:
    requests: list[httpx.Request] = []

    def callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return json_response({"id": "sent-2"})

    bot = Bot(make_config(), transport=api_transport(callback))
    await bot.group.send("GROUP", content="hi", msg_id="incoming-2")
    await bot.group.recall("GROUP", "sent-2")

    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/v2/groups/GROUP/messages"
    assert body["msg_id"] == "incoming-2"
    assert body["msg_seq"] == 1
    assert requests[1].method == "DELETE"
    assert requests[1].url.path == "/v2/groups/GROUP/messages/sent-2"
    await bot.aclose()


async def test_reply_generates_increasing_msg_seq() -> None:
    bodies: list[dict] = []

    def callback(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return json_response({"id": "reply"})

    bot = Bot(make_config(), transport=api_transport(callback))
    event = c2c_event()
    await bot.reply(event, "first")
    await bot.reply(event, "second")

    assert [body["msg_seq"] for body in bodies] == [1, 2]
    assert {body["msg_id"] for body in bodies} == {"incoming-1"}
    await bot.aclose()


async def test_member_pagination_yields_all_members() -> None:
    cursors: list[str | None] = []

    def callback(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        if cursor == "":
            return json_response(
                {
                    "members": [
                        {"member_openid": "A", "username": "a"},
                        {"member_openid": "B", "username": "b"},
                    ],
                    "next_cursor": "page2",
                }
            )
        return json_response(
            {"members": [{"member_openid": "C", "username": "c"}], "next_cursor": ""}
        )

    bot = Bot(make_config(), transport=api_transport(callback))
    members = [member.member_openid async for member in bot.groups.iter_members("GROUP")]
    assert members == ["A", "B", "C"]
    assert cursors == ["", "page2"]
    await bot.aclose()


async def test_mute_member_formats_rfc3339() -> None:
    body: dict = {}

    def callback(request: httpx.Request) -> httpx.Response:
        body.update(json.loads(request.content))
        return json_response({})

    bot = Bot(make_config(), transport=api_transport(callback))
    await bot.groups.mute_member("GROUP", "MEMBER", "2026-08-05T11:23:05+08:00")
    assert body["members"] == [
        {
            "op": "add",
            "member_openid": "MEMBER",
            "mute_expire_at": "2026-08-05T11:23:05+08:00",
        }
    ]
    await bot.aclose()


async def test_strategy_requires_exactly_one_group_selector() -> None:
    bot = Bot(make_config(), transport=api_transport(lambda request: json_response({})))
    with pytest.raises(ValueError):
        await bot.groups.create_strategy()
    with pytest.raises(ValueError):
        await bot.groups.create_strategy(group_openids=["g"], group_ids=[1])
    await bot.aclose()


async def test_chunked_upload_uses_presigned_parts() -> None:
    api_calls: list[tuple[str, dict]] = []
    puts: list[bytes] = []

    def api_callback(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        api_calls.append((path, body))
        if path.endswith("/upload_prepare"):
            return json_response(
                {
                    "upload_id": "upload-1",
                    "block_size": "4",
                    "parts": [
                        {"index": 0, "presigned_url": "https://upload/0", "block_size": "4"},
                        {"index": 1, "presigned_url": "https://upload/1", "block_size": "4"},
                    ],
                    "upload_config": {"concurrency": 2, "retry_delay": 0},
                }
            )
        if path.endswith("/upload_part_finish"):
            return json_response({})
        if path.endswith("/files"):
            return json_response({"file_uuid": "uuid", "file_info": "FILEINFO", "ttl": 300})
        return json_response({})

    def plain_callback(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        puts.append(request.content)
        return httpx.Response(200)

    plain = httpx.AsyncClient(transport=httpx.MockTransport(plain_callback))
    bot = Bot(
        make_config(),
        transport=api_transport(api_callback),
        plain_client=plain,
    )
    result = await bot.media.upload_bytes(
        MediaTarget.c2c("USER"),
        FileType.FILE,
        "demo.bin",
        b"abcdefgh",
        force_chunked=True,
    )

    assert result.file_info == "FILEINFO"
    paths = [path for path, _ in api_calls]
    assert paths[0] == "/v2/users/USER/upload_prepare"
    assert paths.count("/v2/users/USER/upload_part_finish") == 2
    assert paths[-1] == "/v2/users/USER/files"
    assert sorted(puts) == [b"abcd", b"efgh"]
    assert api_calls[-1][1]["upload_id"] == "upload-1"
    await bot.aclose()


async def test_material_image_upload_flow() -> None:
    calls: list[str] = []

    def callback(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/prepare"):
            return json_response(
                {"upload_id": "img-1", "presigned_url": "https://upload/image", "expires_in": 60}
            )
        if request.url.path.endswith("/complete"):
            return json_response(
                {
                    "image_id": "image-1",
                    "url": "qqbot-media://image/v1/token",
                    "ttl": 7776000,
                }
            )
        return json_response({})

    def plain_callback(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Type"] == "image/png"
        return httpx.Response(200, headers={"ETag": '"d41d8cd98f00b204e9800998ecf8427e"'})

    plain = httpx.AsyncClient(transport=httpx.MockTransport(plain_callback))
    bot = Bot(make_config(), transport=api_transport(callback), plain_client=plain)

    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory, "test.png")
        await asyncio.to_thread(path.write_bytes, b"\x89PNG\r\n")
        image = await bot.media.upload_image(path)

    assert image.image_id == "image-1"
    assert calls == [
        "/v2/media-images/prepare",
        "/v2/media-images/complete",
    ]
    await bot.aclose()


async def test_passive_and_stream_validation() -> None:
    bot = Bot(make_config(), transport=api_transport(lambda request: json_response({})))
    with pytest.raises(ValueError):
        await bot.c2c.send("USER", content="x", msg_id="")
    with pytest.raises(ValueError):
        await bot.c2c.send("USER", content="x", msg_id="m", msg_seq=0)
    with pytest.raises(ValueError):
        await bot.c2c.send_stream("USER", content_raw="x", input_state=2)
    with pytest.raises(ValueError):
        await bot.c2c.send_stream("USER", content_raw="x", input_mode="invalid")
    await bot.aclose()


async def test_mute_requires_expiry_for_add_and_update() -> None:
    bot = Bot(make_config(), transport=api_transport(lambda request: json_response({})))
    with pytest.raises(ValueError):
        await bot.groups.set_member_mutes("GROUP", [{"op": "add", "member_openid": "M"}])
    await bot.aclose()


async def test_interaction_reply_uses_envelope_event_id() -> None:
    bodies: list[dict] = []
    paths: list[str] = []

    def callback(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        paths.append(request.url.path)
        return json_response({"id": "reply"})

    bot = Bot(make_config(), transport=api_transport(callback))
    event = parse_event(
        "INTERACTION_CREATE",
        {
            "id": "interaction-id",
            "type": 11,
            "scene": "c2c",
            "chat_type": 2,
            "user_openid": "USER",
            "data": {"type": 11, "resolved": {"button_data": "/check"}},
        },
        event_id="envelope-event-id",
    )
    await bot.reply(event, "clicked")
    assert paths == ["/v2/users/USER/messages"]
    assert bodies[0]["event_id"] == "envelope-event-id"
    assert bodies[0]["event_id"] != "interaction-id"

    without_envelope = parse_event(
        "INTERACTION_CREATE",
        {
            "id": "interaction-only",
            "type": 11,
            "scene": "group",
            "group_openid": "GROUP",
            "data": {"type": 11, "resolved": {}},
        },
    )
    with pytest.raises(ValueError):
        await bot.reply(without_envelope, "clicked")
    await bot.aclose()
