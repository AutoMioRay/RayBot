# Contributing

Thanks for improving `RayBot`.

## Development setup

Requirements: Python `3.13.12` and `uv`.

The included CI workflow is GitHub Actions compatible. If the GitCode repository uses a different CI format, run the same commands locally and adapt the workflow when CI is configured.

```bash
uv sync
uv run pytest
uv run ruff check RayBot tests examples tools
uv run ruff format --check RayBot tests examples tools
uv build
```

## Branch model

| Branch | Purpose |
|---|---|
| `main` | Release branch: every commit on `main` is release-ready and tagged `vX.Y.Z` |
| `feature/*`, `fix/*`, `docs/*` | Short-lived work branches merged by pull request |

Workflow:

1. Branch from `main`.
2. Open a pull request targeting `main`.
3. Keep CI and tests green (required checks: `quality`, `test-windows`).
4. Update `CHANGELOG.md` and the version in the release pull request.
5. After merge, tag `vX.Y.Z` on `main`; the release workflow builds and
   publishes the artifacts.

Do not commit directly to `main` except for maintainer release commits.

## Commit messages

Use Conventional Commits where practical:

```text
feat: add group mute helpers
fix: use envelope event_id for interaction replies
docs: document credential validation rules
test: cover heartbeat timeout reconnects
security: reject credentials with control characters
chore: release 0.1.0
```

## Pull requests

Please include:

- what changed and why;
- user-visible behavior and compatibility impact;
- tests added or updated;
- documentation and `CHANGELOG.md` updates when relevant;
- security impact for token, credential, or permission changes.

Keep changes focused. Avoid unrelated refactors in the same pull request.

## Code and documentation style

- Async APIs use `async def`; do not block the event loop.
- Add type hints and docstrings for public APIs.
- Use `ruff` for linting and formatting; line length is 100.
- Do not add a QQ bot SDK as a dependency; implement protocol behavior directly.
- Add or update tests for every behavior change, including error paths.
- Keep the API reference organized by user task, not by internal class.
- Do not commit credentials, tokens, `.env` files, or the third-party
  `QQ机器人开发参考/` directory.

## License of contributions

This project is licensed under the MIT License. By submitting a contribution,
you agree that it is your original work (or you have the right to submit it) and
that it may be distributed under the MIT License. No separate CLA is required.

## Security

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
