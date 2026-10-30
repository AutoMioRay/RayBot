from __future__ import annotations

import asyncio

from RayBot.core.events import EventBus
from RayBot.core.models import parse_event


def message_event(content: str = "hi", msg_idx: str = "M1"):
    return parse_event(
        "C2C_MESSAGE_CREATE",
        {
            "id": "msg",
            "author": {"user_openid": "U"},
            "content": content,
            "message_scene": {"ext": [f"msg_idx={msg_idx}"]},
        },
        event_id="event",
        seq=1,
    )


async def test_handlers_run_in_priority_order() -> None:
    bus = EventBus(concurrency=2, queue_size=8)
    bus.start()
    order: list[str] = []

    async def low(event) -> None:
        order.append("low")

    async def high(event) -> None:
        await asyncio.sleep(0)
        order.append("high")

    bus.subscribe("C2C_MESSAGE_CREATE", low, priority=0)
    bus.subscribe("C2C_MESSAGE_CREATE", high, priority=10)
    await bus.publish(message_event())
    await bus.drain()
    await bus.stop()

    assert order == ["high", "low"]


async def test_once_handler_is_removed_after_first_event() -> None:
    bus = EventBus(concurrency=1, queue_size=8)
    bus.start()
    seen: list[str] = []

    @bus.on("C2C_MESSAGE_CREATE", once=True)
    async def handler(event) -> None:
        seen.append(event.content)

    await bus.publish(message_event("one", "M1"))
    await bus.publish(message_event("two", "M2"))
    await bus.drain()
    await bus.stop()

    assert seen == ["one"]


async def test_exception_is_routed_to_error_handler() -> None:
    bus = EventBus(concurrency=1, queue_size=8)
    bus.start()
    errors: list[tuple[str, str]] = []

    @bus.on("C2C_MESSAGE_CREATE")
    async def broken(event) -> None:
        raise RuntimeError("boom")

    @bus.on_error
    async def on_error(event, handler, exc) -> None:
        errors.append((event.content, str(exc)))

    await bus.publish(message_event())
    await bus.drain()
    await bus.stop()

    assert errors == [("hi", "boom")]


async def test_subscribe_all_receives_unknown_events() -> None:
    bus = EventBus(concurrency=1, queue_size=8)
    bus.start()
    seen: list[str] = []
    bus.subscribe_all(lambda event: seen.append(event.name))
    event = parse_event("FUTURE_EVENT", {"x": 1})
    await bus.publish(event)
    await bus.drain()
    await bus.stop()
    assert seen == ["FUTURE_EVENT"]


async def test_publish_nowait_reports_full_queue() -> None:
    bus = EventBus(concurrency=1, queue_size=1)
    bus.start()

    async def slow(event) -> None:
        await asyncio.sleep(0.2)

    bus.subscribe("C2C_MESSAGE_CREATE", slow)
    assert bus.publish_nowait(message_event("1", "M1"))
    assert not bus.publish_nowait(message_event("2", "M2"))
    await bus.drain()
    await bus.stop()


async def test_stop_drains_without_losing_events() -> None:
    bus = EventBus(concurrency=1, queue_size=8)
    bus.start()
    seen: list[str] = []
    bus.subscribe("C2C_MESSAGE_CREATE", lambda event: seen.append(event.content))
    for index in range(5):
        await bus.publish(message_event(str(index), f"M{index}"))
    await bus.stop(drain=True)
    assert seen == ["0", "1", "2", "3", "4"]
