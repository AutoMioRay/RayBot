#!/usr/bin/env python3
"""Build the curated user-facing `main` tree from `develop`.

`main` is a strict subset of `develop`: it keeps the package, functional and
security tests, the user manual and the two test reports, and drops
development-only material listed in ``tools/release/main-excludes.txt``.

Usage:
    python tools/release/prepare_main.py --dry-run   # show what would be removed
    python tools/release/prepare_main.py             # create release/main-clean

The script never pushes.  After it finishes, push the branch and open a PR into
``main``; the required checks (quality, test-windows) must pass before merge.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDES_FILE = ROOT / "tools" / "release" / "main-excludes.txt"


def git(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=capture,
        text=True,
    )


def load_excludes() -> list[str]:
    entries: list[str] = []
    for line in EXCLUDES_FILE.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", default="develop", help="source branch (default: develop)")
    parser.add_argument("--branch", default="release/main-clean", help="branch to create")
    parser.add_argument(
        "--dry-run", action="store_true", help="only print the paths that would be removed"
    )
    parser.add_argument("--no-commit", action="store_true", help="leave the removals staged")
    args = parser.parse_args()

    if not (ROOT / ".git").exists():
        raise SystemExit("not a git checkout")
    if git("status", "--porcelain", capture=True).stdout.strip():
        raise SystemExit("working tree is dirty; commit or stash changes first")

    excludes = load_excludes()
    if args.dry_run:
        print(f"source branch: {args.source}")
        print("would exclude:")
        for entry in excludes:
            print(" -", entry)
        return 0

    git("checkout", "-B", args.branch, args.source)
    removed: list[str] = []
    for entry in excludes:
        path = ROOT / entry.rstrip("/")
        if not path.exists():
            continue
        result = git("rm", "-r", "-q", "--ignore-unmatch", entry, check=False, capture=True)
        if result.returncode == 0:
            removed.append(entry)

    staged = git("diff", "--cached", "--name-only", capture=True).stdout.strip()
    if not staged:
        print(f"branch {args.branch} is already curated; nothing to remove")
        return 0

    print(f"removed {len(removed)} development-only path(s):")
    for entry in removed:
        print(" -", entry)

    # Sanity: the curated tree must still contain the package and the tests.
    for required in ("RayBot/__init__.py", "tests", "docs/index.md", "reports/功能测试报告.md"):
        if not (ROOT / required).exists():
            raise SystemExit(f"curated tree is missing required path: {required}")

    if args.no_commit:
        print("removals staged; not committing (--no-commit)")
        return 0

    message = "chore(release): curate the user-facing main tree\n\n" + "\n".join(
        f"- exclude {entry}" for entry in removed
    )
    git(
        "-c",
        "user.name=MioRay",
        "-c",
        "user.email=MioRay@foxmail.com",
        "commit",
        "-q",
        "-m",
        message,
    )
    print(
        f"\ncreated branch {args.branch} at {git('rev-parse', '--short', 'HEAD', capture=True).stdout.strip()}"
    )
    print("next steps:")
    print(f"  git push <remote> {args.branch}")
    print("  open a PR into main; merge after quality + test-windows pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
