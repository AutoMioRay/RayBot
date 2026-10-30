"""Micro-benchmarks for the parsing-layer optimizations.

Run:  .venv/Scripts/python.exe tools/bench_json.py

Measures, on the current interpreter and host:
1. stdlib json vs the toolkit codec (orjson when installed) for decoding a
   realistic gateway event payload from ``str`` and ``bytes``;
2. stdlib json vs the toolkit codec for encoding an outbound message payload;
3. EventBus subscription resolution: the old copy+sort-per-event approach vs
   the cached implementation.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qqbot_toolkit._json import ORJSON_AVAILABLE, dumps, loads  # noqa: E402
from qqbot_toolkit.events.bus import EventBus  # noqa: E402

EVENT = json.dumps(
    {
        "op": 0,
        "s": 123456,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "id": "ROBOT1.0_aBcDeFgH_1234567890",
        "d": {
            "id": "ROBOT1.0_aBcDeFgH_0987654321",
            "author": {"member_openid": "MEMBER_OPENID_EXAMPLE_1234", "username": "测试用户"},
            "content": "帮我查一下明天的天气怎么样，顺便推荐几个适合周末出游的地方",
            "timestamp": "2026-10-30T12:34:56+08:00",
            "message_type": 0,
            "group_openid": "GROUP_OPENID_EXAMPLE_5678",
            "message_scene": {
                "ext": ["msg_idx=MSG_IDX_EXAMPLE_0001", "ref_msg_idx="],
                "scene": "group",
            },
            "attachments": [],
            "mentions": [],
        },
    }
)


def bench(name: str, func, *, seconds: float = 1.0) -> float:
    """Run ``func`` repeatedly for ``seconds`` and return ops/second."""

    deadline = time.perf_counter() + seconds
    runs: list[int] = []
    while time.perf_counter() < deadline:
        count = 0
        start = time.perf_counter()
        while time.perf_counter() - start < 0.1:
            func()
            count += 1
        runs.append(count / (time.perf_counter() - start))
    best = max(runs)
    median = statistics.median(runs)
    print(f"{name:<46} {median:>12,.0f} ops/s  (best {best:,.0f})")
    return median


def main() -> None:
    print(f"orjson available: {ORJSON_AVAILABLE}")
    print(f"payload size: {len(EVENT)} bytes\n")

    event_str = EVENT
    event_bytes = EVENT.encode("utf-8")

    std_str = bench("stdlib json.loads(str)", lambda: json.loads(event_str))
    ours_str = bench("toolkit loads(str)", lambda: loads(event_str))
    std_bytes = bench("stdlib json.loads(bytes)", lambda: json.loads(event_bytes))
    ours_bytes = bench("toolkit loads(bytes)", lambda: loads(event_bytes))

    payload = {
        "msg_type": 0,
        "msg_seq": 3,
        "content": "回复内容示例：你好，世界！Hello, world!",
        "msg_id": "ROBOT1.0_aBcDeFgH_0987654321",
    }
    std_dump = bench("stdlib json.dumps", lambda: json.dumps(payload, ensure_ascii=False))
    ours_dump = bench("toolkit dumps", lambda: dumps(payload))

    print()
    print(f"decode str speedup:  {ours_str / std_str:>5.1f}x")
    print(f"decode bytes speedup: {ours_bytes / std_bytes:>5.1f}x")
    print(f"encode speedup:       {ours_dump / std_dump:>5.1f}x")

    # --- EventBus subscription resolution -------------------------------------
    bus = EventBus(concurrency=1)
    for index in range(20):
        bus.subscribe(f"EVENT_{index}", lambda event: None, priority=index % 5)
    bus.subscribe_all(lambda event: None, priority=1)
    name = "EVENT_3"
    merged = list(bus._subscriptions.get(name, ())) + list(bus._all)

    def old_resolution() -> None:
        subs = list(bus._subscriptions.get(name, ())) + list(bus._all)
        subs.sort(key=lambda item: item.priority, reverse=True)

    def new_resolution() -> None:
        bus._subscriptions_for(name)

    print()
    old = bench("dispatch resolution: copy+sort per event", old_resolution)
    new = bench("dispatch resolution: cached tuple", new_resolution)
    print(f"resolution speedup:   {new / old:>5.1f}x")
    new_resolution()
    assert tuple(sorted(merged, key=lambda s: s.priority, reverse=True)) == bus._subscriptions_for(
        name
    ), "cached resolution differs from the reference implementation"


if __name__ == "__main__":
    main()
