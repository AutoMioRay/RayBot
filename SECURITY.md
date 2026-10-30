# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | Yes |
| 0.1.x | Yes |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately to **MioRay@foxmail.com** with:

- affected version or commit;
- a minimal reproduction;
- impact and attack preconditions;
- which component is affected (WebSocket gateway, HTTP API, etc.).

Do not include real bot credentials, access tokens, or user data in the report.
If credentials may have leaked, rotate them in the QQ Open Platform immediately.

This is a community project; reports are handled on a best-effort basis. Please
allow reasonable time for a fix before public disclosure.

## Archived transport: Webhook

The Webhook transport was archived in 0.2.0 precisely because of a known
protocol-level risk: QQ Webhook uses the same Ed25519 key for callback-url
validation (`op=13`) and event signatures, so an exposed validation endpoint
acts as a signing oracle that can be used to forge events. This risk could not
be removed without extra deployment-side infrastructure (inbound IP allowlists,
TLS termination at a reverse proxy, per-IP rate limiting).

The current package therefore supports the WebSocket transport only, which
authenticates on the platform side and requires no inbound ports. The archived
implementation, the full risk description and restore instructions live in
the Webhook transport unless the design is reworked; see `archive/webhook/` on the develop branch. Do not re-enable
Webhook in production without reading that document first.

Note that the platform's **server IP allowlist** restricts outbound calls from
your server to the platform API; it would not restrict inbound access to a
Webhook endpoint.

## Scope

In scope:

- token acquisition, caching and refresh;
- WebSocket gateway handling;
- request construction, rate limiting and error handling;
- documentation examples that could lead to insecure deployments.

Out of scope:

- vulnerabilities in QQ/Tencent platform services;
- misconfiguration of reverse proxies, firewalls or TLS certificates;
- compromised hosts, stolen environment variables, or process memory;
- third-party dependencies (report upstream, but feel free to notify us).
