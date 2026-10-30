# Contributing

Thanks for improving `RayBot`.

## Development setup

Requirements: Python `3.13.12` and `uv`.

The included CI workflow is GitHub Actions compatible. If the GitCode repository uses a different CI format, run the same commands locally and adapt the workflow when CI is configured.

```bash
uv sync
uv run pytest
uv run ruff check src tests examples
uv run ruff format --check src tests examples
uv build
```

## Branch model

| Branch | Purpose |
|---|---|
| `main` | Release-only branch; every commit should be tagged or release-ready |
| `develop` | Integration branch for the next release |
| `feature/*`, `fix/*`, `docs/*` | Short-lived work branches |

Workflow:

1. Branch from `develop`.
2. Open a pull request targeting `develop`.
3. Keep CI and tests green.
4. Release: update `CHANGELOG.md` and the version, merge `develop` into `main`,
   run a final build, and tag `vX.Y.Z` on `main`.
5. Merge `main` back into `develop` after release if release-only commits exist.

Do not commit directly to `main` or `develop` except for maintainer release
commits.

## Commit messages

Use Conventional Commits where practical:

```text
feat: add group mute helpers
fix: use envelope event_id for interaction replies
docs: document credential validation rules
test: cover heartbeat timeout reconnects
security: reject credentials with control characters
chore: release 0.2.0
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
