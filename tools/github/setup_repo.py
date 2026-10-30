#!/usr/bin/env python3
"""Configure GitHub repository settings for the RayBot project.

Idempotent; run from the repository root:

    python tools/github/setup_repo.py --dry-run    # print the planned changes
    python tools/github/setup_repo.py              # apply

The token is read from ``GITHUB_TOKEN`` / ``GH_TOKEN`` or from the git
credential manager (``git credential fill`` for github.com).  It is never
printed.  Required token scopes: ``repo`` (branch protection / settings) and
``workflow`` (not needed here, but needed when pushing workflow files).

What it enforces:
* repo: delete branch on merge, auto-merge allowed;
* security: secret scanning + push protection, vulnerability alerts,
  automated security fixes;
* Actions: read-only default workflow token, no PR approvals by Actions;
* branch protection for main and develop: required checks
  ``quality`` + ``test-windows``, strict (up-to-date), admins enforced,
  no force pushes, no branch deletion, conversation resolution required;
* tag ruleset (when supported): v* tags cannot be deleted or moved.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
DEFAULT_REPO = "AutoMioRay/RayBot"
REQUIRED_CHECKS = ["quality", "test-windows"]
PROTECTED_BRANCHES = ["main", "develop"]


def resolve_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    creds = {}
    if proc is not None and proc.stdout:
        creds = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    token = creds.get("password", "")
    if not token:
        raise SystemExit("no GitHub token found (set GITHUB_TOKEN or store one with git)")
    return token


class Client:
    def __init__(self, token: str, repo: str, dry_run: bool) -> None:
        self._token = token
        self.repo = repo
        self.dry_run = dry_run

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        url = f"{API}{path}"
        if self.dry_run and method != "GET":
            print(
                f"[dry-run] {method} {path} {json.dumps(body, ensure_ascii=False) if body else ''}"
            )
            return 0, None
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            return exc.code, detail
        except urllib.error.URLError as exc:
            raise SystemExit(f"network error calling {path}: {exc}") from exc

    def expect(self, method: str, path: str, body: dict | None = None) -> None:
        status, payload = self.call(method, path, body)
        if status >= 400:
            raise SystemExit(f"{method} {path} failed: HTTP {status} {payload}")
        print(f"  ok: {method} {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo")
    parser.add_argument("--dry-run", action="store_true", help="print planned API calls only")
    args = parser.parse_args()

    token = resolve_token()
    client = Client(token, args.repo, args.dry_run)

    status, repo = client.call("GET", f"/repos/{args.repo}")
    if status != 200 or not isinstance(repo, dict):
        raise SystemExit(f"cannot read repository {args.repo}: HTTP {status}")
    admin = bool(repo.get("permissions", {}).get("admin"))
    print(
        f"repository: {repo.get('full_name')} | admin={admin} | default={repo.get('default_branch')}"
    )
    if not admin:
        raise SystemExit("token lacks admin rights on the repository")

    print("\n[1/5] repository settings")
    client.expect(
        "PATCH",
        f"/repos/{args.repo}",
        {
            "delete_branch_on_merge": True,
            "allow_auto_merge": True,
            "allow_squash_merge": True,
            "allow_merge_commit": True,
            "allow_rebase_merge": False,
        },
    )

    print("\n[2/5] security features")
    client.expect(
        "PATCH",
        f"/repos/{args.repo}",
        {
            "security_and_analysis": {
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_push_protection": {"status": "enabled"},
            }
        },
    )
    client.expect("PUT", f"/repos/{args.repo}/vulnerability-alerts")
    client.expect("PUT", f"/repos/{args.repo}/automated-security-fixes")

    print("\n[3/5] Actions permissions")
    client.expect(
        "PUT",
        f"/repos/{args.repo}/actions/permissions/workflow",
        {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    )

    print("\n[4/5] branch protection")
    for branch in PROTECTED_BRANCHES:
        client.expect(
            "PUT",
            f"/repos/{args.repo}/branches/{branch}/protection",
            {
                "required_status_checks": {"strict": True, "contexts": REQUIRED_CHECKS},
                "enforce_admins": True,
                "required_pull_request_reviews": None,
                "restrictions": None,
                "allow_force_pushes": False,
                "allow_deletions": False,
                "required_conversation_resolution": True,
            },
        )

    print("\n[5/5] tag protection (v*)")
    status, payload = client.call(
        "POST",
        f"/repos/{args.repo}/rulesets",
        {
            "name": "protect-release-tags",
            "target": "tag",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
        },
    )
    if status in (200, 201):
        print("  ok: tag ruleset protect-release-tags")
    elif status == 409:
        print("  skip: tag ruleset already exists")
    else:
        print(f"  warn: tag ruleset not applied (HTTP {status}: {str(payload)[:200]})")

    print("\ndone. Manual follow-ups:")
    print("  * Settings -> Environments -> release: add a second maintainer as required reviewer")
    print(
        "  * Settings -> Environments -> live-smoke: add QQBOT_APP_ID / QQBOT_CLIENT_SECRET secrets"
    )
    print("  * PyPI: configure trusted publisher for the release workflow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
