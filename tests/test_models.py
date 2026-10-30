from __future__ import annotations

from RayBot.core.models import (
    C2CMessage,
    GroupAllMessage,
    GroupAtMessage,
    InteractionEvent,
    event_dedup_key,
    parse_event,
)
from RayBot.core.models.outbound import (
    Keyboard,
    KeyboardButton,
    KeyboardContent,
    KeyboardRow,
    MediaInfo,
    MessageMarkdown,
    RenderData,
    command_button,
    keyboard,
)

C2C_PAYLOAD = {
    "id": "ROBOT1.0_x",
    "author": {
        "id": "A1B2",
        "user_openid": "A1B2",
        "username": "tester",
        "bot": False,
    },
    "content": "hello",
    "timestamp": "2026-07-21T10:00:00+08:00",
    "message_type": 0,
    "message_scene": {
        "source": "default",
        "ext": ["msg_idx=REFIDX_1==", "auth_token=tok"],
    },
    "attachments": [
        {
            "content_type": "image/png",
            "filename": "a.png",
            "url": "https://example.com/a.png",
            "width": 10,
            "height": 20,
            "size": 30,
        }
    ],
}


def test_c2c_message_is_typed_and_exposes_scene() -> None:
    event = parse_event("C2C_MESSAGE_CREATE", C2C_PAYLOAD, event_id="ev", seq=9)
    assert isinstance(event, C2CMessage)
    assert event.content == "hello"
    assert event.author.openid == "A1B2"
    assert event.msg_idx == "REFIDX_1=="
    assert event.auth_token == "tok"
    assert event.timestamp is not None
    assert event.timestamp.isoformat() == "2026-07-21T10:00:00+08:00"
    assert event.attachments[0].is_image
    assert event.event_id == "ev"
    assert event.seq == 9


def test_group_messages_have_group_and_member_openids() -> None:
    payload = {
        "id": "ROBOT1.0_y",
        "group_openid": "GROUP",
        "author": {"member_openid": "MEMBER", "member_role": "owner"},
        "content": "hi",
        "message_type": 0,
    }
    at = parse_event("GROUP_AT_MESSAGE_CREATE", payload)
    all_messages = parse_event("GROUP_MESSAGE_CREATE", payload)
    assert isinstance(at, GroupAtMessage)
    assert isinstance(all_messages, GroupAllMessage)
    assert at.group_openid == "GROUP"
    assert at.member_openid == "MEMBER"
    assert at.author.is_admin


def test_quote_message_exposes_quoted_element() -> None:
    payload = {
        "id": "ROBOT1.0_z",
        "author": {"user_openid": "U"},
        "content": "reply",
        "message_type": 103,
        "msg_elements": [{"content": "original"}, {"content": "other"}],
        "message_scene": {"ext": ["ref_msg_idx=REFIDX_0==", "msg_idx=REFIDX_1=="]},
    }
    event = parse_event("C2C_MESSAGE_CREATE", payload)
    assert isinstance(event, C2CMessage)
    assert event.is_quote
    assert event.ref_msg_idx == "REFIDX_0=="
    assert event.quoted is not None and event.quoted.content == "original"


def test_interaction_properties() -> None:
    payload = {
        "id": "interaction-1",
        "type": 11,
        "scene": "c2c",
        "chat_type": 2,
        "user_openid": "U",
        "data": {"type": 11, "resolved": {"button_data": "/check", "button_id": "b1"}},
    }
    event = parse_event("INTERACTION_CREATE", payload)
    assert isinstance(event, InteractionEvent)
    assert event.requires_response
    assert event.button_data == "/check"
    assert event.target_openid == "U"


def test_unknown_event_is_preserved() -> None:
    event = parse_event("FUTURE_EVENT", {"x": 1}, event_id="e", seq=3)
    assert event.name == "FUTURE_EVENT"
    assert event.data == {"x": 1}
    assert event.event_id == "e"


def test_dedup_key_prefers_message_index() -> None:
    first = parse_event("C2C_MESSAGE_CREATE", C2C_PAYLOAD)
    same_id_other_index = {**C2C_PAYLOAD, "message_scene": {"ext": ["msg_idx=OTHER"]}}
    second = parse_event("C2C_MESSAGE_CREATE", same_id_other_index)
    assert event_dedup_key(first) != event_dedup_key(second)


def test_outbound_payload_omits_none_values() -> None:
    keyboard_obj = keyboard(KeyboardRow(buttons=[command_button("签到", "/sign")]))
    assert isinstance(keyboard_obj, Keyboard)
    assert keyboard_obj.content is not None
    assert keyboard_obj.content.rows is not None
    assert keyboard_obj.to_dict() == {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "签到",
                            "render_data": {"label": "签到", "style": 1},
                            "action": {
                                "type": 2,
                                "permission": {"type": 2},
                                "data": "/sign",
                                "enter": False,
                                "reply": False,
                            },
                        }
                    ]
                }
            ]
        }
    }
    assert MessageMarkdown(content="x").to_dict() == {"content": "x"}
    assert MediaInfo(file_info="f").to_dict() == {"file_info": "f"}


def test_payload_can_be_built_directly() -> None:
    keyboard_obj = Keyboard(
        content=KeyboardContent(
            rows=[
                KeyboardRow(
                    buttons=[KeyboardButton(id="b", render_data=RenderData(label="B"), action=None)]
                )
            ]
        )
    )
    assert keyboard_obj.to_dict()["content"]["rows"][0]["buttons"][0]["id"] == "b"


def test_dedup_key_is_stable_without_event_id_or_seq() -> None:
    payload = {
        "timestamp": 1784276757,
        "group_openid": "G",
        "member_openid": "M",
    }
    first = parse_event("GROUP_MEMBER_ADD", payload)
    second = parse_event("GROUP_MEMBER_ADD", payload)
    assert event_dedup_key(first) == event_dedup_key(second)


def test_text_interaction_helpers() -> None:
    from RayBot import command_enter, command_input, mention

    assert mention("U1") == '<qqbot-at-user id="U1" />'
    assert command_enter("a b") == '<qqbot-cmd-enter text="a+b" />'
    assert (
        command_input("a/b", show="x y", reference=True)
        == '<qqbot-cmd-input text="a%2Fb" show="x+y" reference="true" />'
    )
