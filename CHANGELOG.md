# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to semantic versioning.

## [0.2.0] - 2026-10-30

### Added

- Gitee Go pipelines under `.workflow/` following the official schema:
  `MasterPipeline` (push to main), `BranchPipeline` (push to develop),
  `PRPipeline` (all PR source branches), `ReleasePipeline` (v* tags with a
  manual approval stage), `NightlyPipeline` (scheduled 10k-example fuzz), and
  `LiveSmokePipeline` (manual real-credential check). Because the official
  `build@python` plugin stops at Python 3.9, every job runs on a self-hosted
  Gitee Go host group (`shell@agent`) with Python 3.13.12.
- `tools/ci/gate.py`, a single build/test/scan/release entry point shared by
  local runs and CI; all pipeline logic lives here so the YAML stays a thin
  orchestrator.
- `tools/check_secrets.py`, a static scanner for hardcoded credentials, private
  keys and forbidden insecure calls (security plan rules S1-01/02/03).
- Fuzz budget is configurable via `QQBOT_FUZZ_EXAMPLES` (PR: 500, nightly and
  release: 10000).
- `tools/soak_test.py`, a local-only long-run (L4) stability harness. Cloud CI
  quotas never pay for hour-long runs: the harness drives a local fake gateway
  (events, garbage frames, forced reconnects) and samples RSS, handles/fds and
  asyncio tasks against the S4-08/10/11 thresholds, writing reports to
  `reports/local-soak/` (gitignored).
- GitHub Actions workflows (primary CI): `ci` (build/test/scan incl. a Windows
  regression job and dependency review on PRs), `codeql`
  (security-extended), `release` (tag verification, OIDC PyPI publishing,
  build provenance attestation, GitHub Release), `nightly` (10k-example fuzz
  plus a full git-history secret scan) and a manual `live-smoke` job behind a
  GitHub environment. Gitee Go definitions remain under `.workflow/` as a
  mirror; both call `tools/ci/gate.py`.
- `tools/check_secrets.py --history` scans every commit's added lines for
  leaked credentials, closing the working-tree-only gap.
- `tools/github/setup_repo.py` configures branch protection, secret scanning,
  Actions permissions and tag rulesets through the GitHub API.

### Changed

- Webhook transport archived verbatim to `archive/webhook/` (including its
  server, signature helpers, tests, and example); the package now supports the
  WebSocket transport only.
- Dropped the `aiohttp` and `cryptography` dependencies, which were used only
  by the archived Webhook code.

### Removed

- `WebhookConfig` and the `BotConfig.webhook` field; `start()`/`run()`/
  `run_forever()` no longer accept `webhook=` and the `bot.webhook` property is
  gone.
- `SignatureVerificationError` and the Webhook-related package exports.

### Security

- `BotConfig` now validates credentials at construction time: values must be
  non-empty, within the maximum length (`app_id` 64, `client_secret` 256),
  without leading/trailing whitespace, and without control characters.

### Documentation

- README, docs, and templates updated for the WebSocket-only transport; the
  Webhook signing-oracle risk, archived contents, and restore steps are
  documented in `archive/webhook/README.md`.

## [0.1.0] - 2026-10-27

### Added

- asyncio-native QQ bot toolkit for C2C and group messages.
- WebSocket gateway with Identify, heartbeat, Resume, reconnect, and sharding.
- Webhook server with Ed25519 signature verification and callback validation.
- C2C text, Markdown, rich media, keyboard, quote, streaming, and recall APIs.
- Group text, Markdown, rich media, mention, keyboard, quote, and recall APIs.
- Group management: info, bot state, members, mute, blacklist, join requests,
  and auto-approval strategies.
- Rich media: URL upload, in-memory bytes, local files, chunked upload, and
  Markdown material images.
- Robot profile, share links, global C2C menu, and command panels.
- Interaction event acknowledgement and passive replies.
- Typed inbound models, outbound payload models, event bus, and de-duplication.
- Access-token caching with early refresh, 401 recovery, background pre-refresh,
  and refresh statistics.
- Per-route and per-relation rate limiting, HTTP retries, and connection pooling.
- Documentation for architecture, configuration, events, gateway, API reference,
  group management, media, and errors.
- Examples for WebSocket echo, Webhook, group management, and live smoke tests.

### Security

- Webhook inbound IP/CIDR allowlist, trusted-proxy handling, and optional
  `X-Forwarded-For` support.
- Runtime toggle for the `op=13` callback validation endpoint.
- Ed25519 signature verification before JSON parsing.
- Timestamp freshness checks for signed Webhook requests.
- Per-IP Webhook rate limiting and request-body size limits.
- HTTPS enforcement for non-loopback API base URLs.
- Optional Webhook TLS requirement and warnings when TLS is not configured.
- `client_secret` excluded from `BotConfig.__repr__`.
- Token refresh endpoints and access tokens are never logged or persisted.

### Documentation

- API reference organized by basic configuration, C2C, group, and group
  management use cases.
- Explicit guidance for the Webhook validation signing-oracle risk and the
  distinction between platform outbound IP allowlists and inbound Webhook
  allowlists.
- Open-source structure: MIT license, contributing guide, security policy,
  code of conduct, changelog, issue/PR templates, and CI workflow.
