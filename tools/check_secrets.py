#!/usr/bin/env python3
"""Static scan for hardcoded credentials and forbidden insecure calls.

Covers the S1 rules of the security test plan that generic linters cannot
express reliably:

* S1-01 forbidden TLS/verification bypasses (``verify=False``,
  ``ssl._create_unverified_context``);
* S1-02 forbidden dynamic-execution / shell primitives (``eval``, ``exec``,
  ``pickle.loads``, ``os.system``, ``shell=True``);
* S1-03 hardcoded credential assignments (``client_secret=`` ... ) and
  private-key blocks, plus well-known token prefixes.

Usage:
    python tools/check_secrets.py [--json reports/ci/secrets.json] [--root .]
    python tools/check_secrets.py --history   # also scan every commit's added lines

Exit code 0 when clean, 1 when findings exist.  A line containing
``secret-scan: allow`` is skipped deliberately (documented suppression).
Placeholder-looking values (test/fake/example/...) are ignored so fixtures can
use obvious dummy credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "dist",
    "build",
    "node_modules",
    "QQ机器人开发参考",
}
EXCLUDED_FILES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml"}
TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".sh",
    ".ps1",
    ".env",
    ".example",
}

PLACEHOLDER_MARKERS = (
    "test",
    "fake",
    "dummy",
    "example",
    "placeholder",
    "your",
    "xxx",
    "changeme",
    "sample",
    "top-secret",
    "not-log",
    "secret-",
    "-secret",
    "**",
    "...",
    # Values that merely spell out the field name are documentation placeholders.
    "clientsecret",
    "client_secret",
    "appsecret",
    "app_secret",
    "access_token",
    "refresh_token",
    "api_key",
    "secret_key",
)

# Forbidden-call rules only make sense in executable/configuration files; prose
# in Markdown may legitimately quote the very patterns this scanner forbids.
CODE_SUFFIXES = {".py", ".sh", ".ps1", ".toml", ".cfg", ".ini", ".yaml", ".yml"}

CREDENTIAL_ASSIGN = re.compile(
    r"""(?ix)
    \b(client[_-]?secret|app[_-]?secret|appsecret|access[_-]?token|refresh[_-]?token
      |api[_-]?key|secret[_-]?key|private[_-]?key)\b
    \s*[:=]\s*
    (["'])(?P<value>[^"'\s]{12,})\2
    """
)
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
TOKEN_PREFIXES = re.compile(
    r"\b(ghp_[A-Za-z0-9]{30,}|gitee_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_\-]{20,}"
    r"|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)

FORBIDDEN_CALLS: list[tuple[str, re.Pattern[str]]] = [
    ("S1-01", re.compile(r"ssl\._create_unverified_context")),
    ("S1-01", re.compile(r"\bverify\s*=\s*False\b")),
    ("S1-02", re.compile(r"(?<![\w.])eval\s*\(")),
    ("S1-02", re.compile(r"(?<![\w.])exec\s*\(")),
    ("S1-02", re.compile(r"pickle\.loads?\s*\(")),
    ("S1-02", re.compile(r"os\.system\s*\(")),
    ("S1-02", re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")),
]

ALLOW_MARKER = "secret-scan: allow"


@dataclass(slots=True)
class Finding:
    file: str
    line: int
    rule: str
    kind: str
    snippet: str


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _iter_files(root: Path):
    own_file = Path(__file__).resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve() == own_file:
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    relative = path.relative_to(root).as_posix()
    suffix = path.suffix.lower()
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line or "# nosec" in line:
            continue
        snippet = line.strip()[:120]

        if suffix in CODE_SUFFIXES:
            for rule, pattern in FORBIDDEN_CALLS:
                if pattern.search(line):
                    findings.append(Finding(relative, number, rule, "forbidden-call", snippet))

        if PRIVATE_KEY_BLOCK.search(line):
            findings.append(Finding(relative, number, "S1-03", "private-key", snippet))

        prefix = TOKEN_PREFIXES.search(line)
        if prefix:
            findings.append(Finding(relative, number, "S1-03", "token-prefix", snippet))

        match = CREDENTIAL_ASSIGN.search(line)
        if match:
            value = match.group("value")
            if not _is_placeholder(value):
                masked = value[:4] + "***" if len(value) > 4 else "***"
                findings.append(
                    Finding(
                        relative,
                        number,
                        "S1-03",
                        "hardcoded-credential",
                        snippet.replace(value, masked),
                    )
                )
    return findings


def scan_history(root: Path) -> list[Finding]:
    """Scan added lines of every commit for leaked credentials.

    Working-tree scans cannot see secrets that were committed and later
    removed; this streams ``git log -p`` and applies the credential rules to
    added lines.  Commit hashes are reported in the ``file`` column so the
    finding can be traced to the exact commit.
    """

    import subprocess  # noqa: PLC0415 - keep module import surface small

    try:
        result = subprocess.run(
            ["git", "log", "-p", "--all", "--no-merges", "--unified=0", "--format=@@COMMIT@@%H"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"secret scan: history scan skipped ({exc})", file=sys.stderr)
        return []
    if result.returncode != 0:
        print("secret scan: history scan skipped (not a git repository?)", file=sys.stderr)
        return []

    findings: list[Finding] = []
    commit = "unknown"
    path = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("@@COMMIT@@"):
            commit = line[len("@@COMMIT@@") :].strip()
            continue
        if line.startswith("+++ b/"):
            path = line[len("+++ b/") :].strip()
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        if ALLOW_MARKER in added or "# nosec" in added:
            continue
        snippet = added.strip()[:120]

        matched = False
        if PRIVATE_KEY_BLOCK.search(added):
            findings.append(
                Finding(f"history {commit[:12]}:{path}", 0, "S1-03", "private-key", snippet)
            )
            matched = True
        if TOKEN_PREFIXES.search(added):
            findings.append(
                Finding(f"history {commit[:12]}:{path}", 0, "S1-03", "token-prefix", snippet)
            )
            matched = True
        match = CREDENTIAL_ASSIGN.search(added)
        if match and not _is_placeholder(match.group("value")):
            value = match.group("value")
            masked = value[:4] + "***" if len(value) > 4 else "***"
            findings.append(
                Finding(
                    f"history {commit[:12]}:{path}",
                    0,
                    "S1-03",
                    "hardcoded-credential",
                    snippet.replace(value, masked),
                )
            )
            matched = True
        del matched
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to scan")
    parser.add_argument("--json", dest="json_path", help="write findings as JSON")
    parser.add_argument(
        "--history",
        action="store_true",
        help="also scan added lines across all commits (needs a git checkout with full history)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings: list[Finding] = []
    scanned = 0
    for path in _iter_files(root):
        scanned += 1
        findings.extend(scan_file(path, root))
    if args.history:
        history_findings = scan_history(root)
        findings.extend(history_findings)
        print(f"secret scan: history scanned ({len(history_findings)} finding(s))")

    for finding in findings:
        print(f"{finding.file}:{finding.line}: [{finding.rule}] {finding.kind}: {finding.snippet}")

    payload = {
        "scanned_files": scanned,
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    if args.json_path:
        target = Path(args.json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if findings:
        print(f"\nsecret scan: {len(findings)} finding(s) in {scanned} files", file=sys.stderr)
        return 1
    print(f"secret scan: clean ({scanned} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
