# Security Policy

## Supported versions

| Version | Supported |
|---|---|
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

## Transport scope: WebSocket only

This release provides the WebSocket transport only. A Webhook implementation
would expose a callback-validation endpoint (`op=13`) that signs arbitrary
tokens with the same Ed25519 key used to verify event signatures. Exposed
publicly, that endpoint acts as a signing oracle and can be used to forge
events; removing the risk requires additional deployment-side infrastructure
(inbound IP allowlists, TLS termination, per-IP rate limiting). Webhook is
therefore intentionally out of scope for this release. WebSocket
authenticates on the platform side and requires no inbound ports.
