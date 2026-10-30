"""IP and URL helpers for outbound connection validation."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def parse_ip(value: str | None) -> IPAddress | None:
    """Parse one IPv4/IPv6 address, returning ``None`` when invalid."""

    if not value:
        return None
    text = value.strip().strip("[]")
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def is_loopback_host(host: str) -> bool:
    """Return whether a host is a loopback address."""

    if host in {"localhost", "::1"}:
        return True
    parsed = parse_ip(host)
    return parsed.is_loopback if parsed is not None else False


def is_trusted_gateway_url(
    url: str,
    *,
    allowed_host_suffixes: Iterable[str],
    allow_insecure_ws: bool = False,
) -> tuple[bool, str]:
    """Validate a gateway WebSocket URL before connecting.

    The gateway URL comes from an API response and the access token is sent to
    it inside the Identify payload, so a manipulated URL would leak the token
    and point the connection at an arbitrary host.  The rules are:

    * ``wss://`` is always required, except plain ``ws://`` on loopback hosts
      (used by local test servers) or when ``allow_insecure_ws`` is set;
    * non-loopback hosts must match one of ``allowed_host_suffixes`` (either
      equal to the suffix or a subdomain of it).  Relaxing the scheme never
      relaxes the host check.

    Returns:
        ``(True, "")`` when the URL is acceptable, otherwise ``(False, reason)``.
    """

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        return False, f"gateway URL could not be parsed: {exc}"
    if parsed.username or parsed.password:
        return False, "gateway URL must not contain credentials"
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    if not host:
        return False, "gateway URL has no hostname"
    if scheme not in {"ws", "wss"}:
        return False, f"gateway URL scheme must be ws:// or wss://, got {scheme!r}"
    if scheme == "ws" and not allow_insecure_ws and not is_loopback_host(host):
        return False, "gateway URL must use wss:// (ws:// is only allowed for loopback hosts)"
    if is_loopback_host(host):
        return True, ""
    for suffix in allowed_host_suffixes:
        trusted = str(suffix).lower().strip(".")
        if not trusted:
            continue
        if host == trusted or host.endswith(f".{trusted}"):
            return True, ""
    return False, f"gateway host {host!r} is not in the allowed hosts"


__all__ = [
    "IPAddress",
    "is_loopback_host",
    "is_trusted_gateway_url",
    "parse_ip",
]
