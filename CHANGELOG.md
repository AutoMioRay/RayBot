# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to semantic versioning.

## [0.1.0] - 2026-10-30

### Added

- Initial release of RayBot, an asyncio-native QQ bot toolkit.
- Package layout: public facade `RayBot` plus implementation under
  `RayBot.core` (api, events, gateway, http, models).
- C2C and group messaging: text, Markdown, rich media, quotes, recall and
  streaming replies, with automatic passive-reply `msg_id` and `msg_seq`.
- Group management: group info, members, mute, blacklist, join approval and
  approval strategies.
- Interaction events: inline keyboards, callbacks, global menu and command
  panels, with interaction acknowledgement helpers.
- WebSocket gateway: heartbeat with ACK detection, Resume, exponential-backoff
  reconnect, sharding and bounded event dispatch.
- Access-token management: single-flight refresh, pre-expiry background
  refresh with jitter, and 401 re-authentication.
- Security hardening: gateway URL allowlist (wss + host suffixes), heartbeat
  interval clamping, credential validation, token never logged or persisted,
  presigned-upload URL validation, upload concurrency cap and deep-JSON
  containment.
- Tests: functional suite plus L2-L5 security suites (parser fuzzing, protocol
  branches, hostile servers and TLS MITM, credential hygiene, backpressure).
- CI: GitHub Actions build/test/scan, CodeQL, dependency review, nightly fuzz,
  tag-gated release with OIDC publishing and build provenance.
- Documentation: user manual, testing guide, functional test report and
  security test report.
