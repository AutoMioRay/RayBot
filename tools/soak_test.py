#!/usr/bin/env python3
"""Local-only L4 stability soak test (never run in cloud CI).

Cloud CI (Gitee Go) has resource quotas, so the long-duration stability checks
S4-03/S4-08/S4-10/S4-11 from the security test plan run on a developer machine
instead:

    python tools/soak_test.py --minutes 60
    python tools/soak_test.py --minutes 1440          # ~24h
    python tools/soak_test.py --minutes 30 --fail-on-growth

What it exercises
-----------------
* a real ``GatewayClient`` + ``EventBus`` against an in-process fake gateway
  over loopback ws:// (URL validation allows loopback by design);
* continuous event flow (decode → de-dup → bounded queue → worker dispatch);
* periodic malformed frames (invalid JSON, unknown opcodes, binary garbage);
* periodic disconnect/reconnect with code 4009 (resume path) to churn
  connections, sockets and heartbeat tasks.

Sampled every ``--sample-every`` seconds
---------------------------------------
RSS, file descriptors / Windows handles, asyncio task count, event counters.
The first ``--warmup`` seconds are the baseline; afterwards the run fails the
default criteria when:

* RSS grows more than 10 % above the baseline median (S4-08);
* handles/fds drift more than 8 (S4-10);
* asyncio task count drifts more than 8 (S4-11).

The report (markdown + JSON) is written under ``reports/local-soak/`` even when
interrupted with Ctrl+C.  Reports are gitignored: they are local evidence, not
build artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from RayBot.core.config import GatewayConfig  # noqa: E402
from RayBot.core.events import EventBus  # noqa: E402
from RayBot.core.gateway.ws import GatewayClient  # noqa: E402
from RayBot.core.models import GatewayInfo, SessionStartLimit  # noqa: E402

logger = logging.getLogger("soak")


class FakeTokens:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return "soak-token"


class FakeGatewayAPI:
    def __init__(self, url: str) -> None:
        self.url = url

    async def get(self) -> GatewayInfo:
        return GatewayInfo(
            url=self.url,
            shards=1,
            session_start_limit=SessionStartLimit(max_concurrency=1),
        )


@dataclass(slots=True)
class Sample:
    at: float
    rss: int
    handles: int
    tasks: int
    events: int
    reconnects: int


@dataclass(slots=True)
class SoakState:
    connections: int = 0
    dispatched: int = 0
    server_closes: int = 0
    seq: int = 0
    server_url: str = ""
    stop: asyncio.Event = field(default_factory=asyncio.Event)


def _handles(process: psutil.Process) -> int:
    if hasattr(process, "num_handles"):  # Windows
        return int(process.num_handles())
    if hasattr(process, "num_fds"):  # Unix
        return int(process.num_fds())
    return -1


def _sample(process: psutil.Process, state: SoakState) -> Sample:
    return Sample(
        at=time.monotonic(),
        rss=int(process.memory_info().rss),
        handles=_handles(process),
        tasks=len(asyncio.all_tasks()),
        events=state.dispatched,
        reconnects=max(0, state.connections - 1),
    )


def _fmt_bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


async def _fake_gateway(state: SoakState, args: argparse.Namespace) -> None:
    """In-process gateway: hello → READY → events → garbage → forced reconnect."""

    async def handler(ws: Any) -> None:
        state.connections += 1
        connection_no = state.connections
        connection_started = time.monotonic()
        try:
            await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 45_000}}))
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if first.get("op") == 2:  # Identify
                await ws.send(
                    json.dumps(
                        {
                            "op": 0,
                            "s": 1,
                            "t": "READY",
                            "d": {
                                "version": 1,
                                "session_id": f"soak-session-{connection_no}",
                                "user": {"id": "bot", "username": "soak", "bot": True},
                                "shard": [0, 1],
                            },
                        }
                    )
                )
            ticks = 0
            while not state.stop.is_set():
                ticks += 1
                if args.event_rate > 0:
                    batch = max(1, int(args.event_rate / 10))  # 100 ms tick
                    for _ in range(batch):
                        state.seq += 1
                        await ws.send(
                            json.dumps(
                                {
                                    "op": 0,
                                    "s": state.seq + 1,
                                    "t": "C2C_MESSAGE_CREATE",
                                    "id": f"soak-evt-{state.seq}",
                                    "d": {
                                        "id": f"soak-msg-{state.seq}",
                                        "author": {"user_openid": "SOAK_USER"},
                                        "content": "soak payload",
                                        "message_type": 0,
                                        "message_scene": {"ext": [f"msg_idx=SOAK-{state.seq}"]},
                                    },
                                }
                            )
                        )
                if args.garbage_every > 0 and ticks % max(1, int(args.garbage_every * 10)) == 0:
                    await ws.send("{not-json")
                    await ws.send(json.dumps({"op": 31337, "d": {"junk": [1, 2, 3]}}))
                    await ws.send(b"\xff\xfe binary garbage")
                if (
                    args.reconnect_every > 0
                    and time.monotonic() - connection_started >= args.reconnect_every
                ):
                    state.server_closes += 1
                    # 4009 = rate limited → client may Resume; exercises the
                    # resume + reconnect/backoff path with connection churn.
                    await ws.close(code=4009, reason="soak reconnect")
                    return
                await asyncio.sleep(0.1)
        except (ConnectionClosed, TimeoutError, asyncio.CancelledError):
            return
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state.server_url = f"ws://127.0.0.1:{port}"
        try:
            await state.stop.wait()
        finally:
            server.close()
            await server.wait_closed()


async def run(args: argparse.Namespace) -> int:
    duration = max(5.0, args.minutes * 60.0)
    process = psutil.Process()
    state = SoakState()
    state.server_url = ""

    server_task = asyncio.create_task(_fake_gateway(state, args), name="soak-server")
    while not state.server_url:
        if server_task.done():
            raise RuntimeError("fake gateway failed to start")
        await asyncio.sleep(0.01)
    url = state.server_url

    bus = EventBus(concurrency=args.workers, queue_size=args.queue_size)
    bus.start()

    def handler(event: Any) -> None:
        state.dispatched += 1

    for name in ("C2C_MESSAGE_CREATE", "READY", "RESUMED"):
        bus.subscribe(name, handler)

    client = GatewayClient(
        FakeTokens(),
        FakeGatewayAPI(url),
        GatewayConfig(
            reconnect_initial_delay=0.05,
            reconnect_max_delay=0.2,
            reconnect_max_attempts=None,
            open_timeout=5.0,
            heartbeat_min_interval=1.0,
            heartbeat_max_interval=300.0,
        ),
        bus,
    )
    client_task = asyncio.create_task(client.run(), name="soak-client")

    samples: list[Sample] = []
    started = time.monotonic()
    next_sample = started
    logger.info(
        "soak started: %.1f min, events/s=%s, reconnect every %ss",
        args.minutes,
        args.event_rate,
        args.reconnect_every or "never",
    )
    try:
        while time.monotonic() - started < duration:
            await asyncio.sleep(args.sample_every)
            now = time.monotonic()
            if now < next_sample:
                continue
            next_sample = now + args.sample_every
            sample = _sample(process, state)
            samples.append(sample)
            elapsed = sample.at - started
            logger.info(
                "%6.0fs rss=%s handles=%s tasks=%s events=%s reconnects=%s",
                elapsed,
                _fmt_bytes(sample.rss),
                sample.handles,
                sample.tasks,
                sample.events,
                sample.reconnects,
            )
    except asyncio.CancelledError:
        logger.warning("soak interrupted")
    finally:
        state.stop.set()
        await client.stop()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(client_task, timeout=10)
        await bus.stop(drain=False)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(server_task, timeout=10)
        with contextlib.suppress(Exception):
            await bus.stop()

    if not samples:
        print("no samples collected", file=sys.stderr)
        return 1

    return _report(args, samples, state, duration)


def _report(
    args: argparse.Namespace,
    samples: list[Sample],
    state: SoakState,
    duration: float,
) -> int:
    started_at = datetime.now().astimezone()
    warmup = min(max(5.0, args.warmup), duration * 0.5)
    baseline = [s for s in samples if s.at - samples[0].at <= warmup] or samples[:1]
    final_window = samples[-max(1, len(samples) // 10) :]

    rss_base = int(statistics.median(s.rss for s in baseline))
    rss_final = int(statistics.median(s.rss for s in final_window))
    rss_peak = max(s.rss for s in samples)
    rss_growth = (rss_final - rss_base) / rss_base * 100 if rss_base else 0.0

    handle_base = int(statistics.median(s.handles for s in baseline))
    handle_final = int(statistics.median(s.handles for s in final_window))
    handle_delta = handle_final - handle_base

    task_base = int(statistics.median(s.tasks for s in baseline))
    task_final = int(statistics.median(s.tasks for s in final_window))
    task_delta = task_final - task_base

    checks = {
        "RSS 增长 < 10% (S4-08)": rss_growth < 10.0,
        "句柄/fd 漂移 <= 8 (S4-10)": handle_delta <= 8,
        "asyncio 任务漂移 <= 8 (S4-11)": task_delta <= 8,
    }
    verdict = all(checks.values())

    lines = [
        "# 本地长时稳定性测试报告（L4）",
        "",
        f"- 开始时间：{started_at:%Y-%m-%d %H:%M:%S %Z}",
        f"- 运行时长：{duration / 60:.1f} 分钟（预热 {warmup / 60:.1f} 分钟）",
        f"- 平台：{sys.platform} / Python {sys.version.split()[0]}",
        f"- 负载：事件 {args.event_rate}/s、每 {args.reconnect_every or '-'}s 重连、"
        f"每 {args.garbage_every or '-'}s 注入垃圾帧",
        f"- 事件派发：{state.dispatched}；连接数：{state.connections}；"
        f"服务端主动断开：{state.server_closes}",
        "",
        "| 指标 | 基线 | 最终 | 峰值 | 变化 | 结论 |",
        "|---|---|---|---|---|---|",
        f"| RSS | {_fmt_bytes(rss_base)} | {_fmt_bytes(rss_final)} | {_fmt_bytes(rss_peak)} "
        f"| {rss_growth:+.1f}% | {'PASS' if checks['RSS 增长 < 10% (S4-08)'] else 'FAIL'} |",
        f"| 句柄/fd | {handle_base} | {handle_final} | {max(s.handles for s in samples)} "
        f"| {handle_delta:+d} | {'PASS' if checks['句柄/fd 漂移 <= 8 (S4-10)'] else 'FAIL'} |",
        f"| asyncio 任务 | {task_base} | {task_final} | {max(s.tasks for s in samples)} "
        f"| {task_delta:+d} | {'PASS' if checks['asyncio 任务漂移 <= 8 (S4-11)'] else 'FAIL'} |",
        "",
        f"**总判定：{'PASS' if verdict else 'FAIL'}**",
        "",
        "> 说明：本测试仅供本地执行（云端 CI 配额有限，不跑长时 L4）。"
        "报告生成于 `reports/local-soak/`，已加入 .gitignore，不入库。",
        "",
    ]

    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.report_dir) if args.report_dir else ROOT / "reports" / "local-soak"
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = out_dir / f"soak-{stamp}.md"
    json_path = out_dir / f"soak-{stamp}.json"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "duration_minutes": duration / 60,
                "samples": [asdict(s) for s in samples],
                "checks": checks,
                "verdict": verdict,
                "rss_growth_percent": round(rss_growth, 2),
                "handle_delta": handle_delta,
                "task_delta": task_delta,
                "events_dispatched": state.dispatched,
                "connections": state.connections,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n".join(lines))
    print(f"report: {markdown_path}")
    print(f"json:   {json_path}")
    if args.fail_on_growth and not verdict:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--minutes", type=float, default=60.0, help="run duration in minutes")
    parser.add_argument("--warmup", type=float, default=60.0, help="baseline warm-up seconds")
    parser.add_argument(
        "--sample-every", type=float, default=10.0, help="sampling interval seconds"
    )
    parser.add_argument("--event-rate", type=int, default=50, help="synthetic events per second")
    parser.add_argument(
        "--reconnect-every",
        type=float,
        default=60.0,
        help="force reconnect every N seconds (0=off)",
    )
    parser.add_argument(
        "--garbage-every",
        type=float,
        default=30.0,
        help="inject garbage frames every N seconds (0=off)",
    )
    parser.add_argument("--workers", type=int, default=8, help="event bus worker count")
    parser.add_argument("--queue-size", type=int, default=1024, help="event bus queue size")
    parser.add_argument("--report-dir", default=None, help="report output directory")
    parser.add_argument(
        "--fail-on-growth", action="store_true", help="exit 1 when stability criteria fail"
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("websockets").setLevel(logging.WARNING)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
