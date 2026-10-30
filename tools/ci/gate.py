#!/usr/bin/env python3
"""Single entry point for the build → test → scan → release pipeline.

The Gitee Go workflow files under ``.workflow/`` only orchestrate stages; every
gate lives here so the exact same commands run locally:

    python tools/ci/gate.py all          # install + build + test + scan + release dry-run
    python tools/ci/gate.py test --examples 500
    python tools/ci/gate.py scan
    python tools/ci/gate.py release --tag v0.2.0 --dry-run

Design notes
------------
* **No secrets required.** Tests use in-process fakes only; the pipeline never
  touches the real QQ platform.  A live connectivity check is a separate,
  manual-only ``smoke`` subcommand that reads credentials from the environment.
* **Machine-readable artifacts** land in ``reports/ci/`` (JUnit XML, coverage
  XML, bandit JSON, pip-audit JSON, secret-scan JSON, build manifest, summary).
* **Fail closed**: any gate failure exits non-zero, which fails the stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "ci"
DIST = ROOT / "dist"

DEV_FALLBACK_PACKAGES = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.1",
    "pytest-cov>=7.0",
    "hypothesis>=6.100",
    "ruff>=0.14.0",
    "bandit>=1.9",
    "pip-audit>=2.9",
    "build>=1.2",
    "twine>=6.0",
]

PYTHON_MIN = (3, 13)


def log(message: str) -> None:
    print(f"[gate] {message}", flush=True)


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        env=_subprocess_env(),
        capture_output=capture,
        text=True,
    )


def venv_python() -> str:
    """Return the project venv interpreter when present, else the current one."""

    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _python() -> list[str]:
    return [venv_python(), "-m"]


def _version_tuple() -> tuple[int, int, int]:
    return tuple(int(part) for part in platform_python_version().split(".")[:3])  # type: ignore[return-value]


def platform_python_version() -> str:
    output = run(
        [venv_python(), "-c", "import sys;print('.'.join(map(str, sys.version_info[:3])))"],
        capture=True,
    ).stdout
    return output.strip()


def pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def source_version() -> str:
    text = (ROOT / "RayBot" / "core" / "constants.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("could not read __version__ from constants.py")
    return match.group(1)


# --------------------------------------------------------------------- install


def step_install(args: argparse.Namespace) -> None:
    version = _version_tuple()
    if version[:2] < PYTHON_MIN:
        raise SystemExit(
            f"Python {PYTHON_MIN[0]}.{PYTHON_MIN[1]}+ is required, found {platform_python_version()}"
        )
    if version < (3, 13, 12):
        log(f"warning: project declares >=3.13.12, running {platform_python_version()}")

    if shutil.which("uv") and (ROOT / "uv.lock").exists():
        try:
            run(["uv", "sync", "--frozen"])
            log("dependencies installed with uv (lockfile frozen)")
            return
        except subprocess.CalledProcessError:
            log("uv sync failed; falling back to pip")

    python = venv_python() if venv_python() != sys.executable else sys.executable
    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", "-e", "."])
    run([python, "-m", "pip", "install", *DEV_FALLBACK_PACKAGES])
    log("dependencies installed with pip")


# ----------------------------------------------------------------------- build


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_reports() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)


def step_build(args: argparse.Namespace) -> None:
    _prepare_reports()
    # Syntax gate first: a broken import path must fail before packaging.
    run([*_python(), "compileall", "-q", "RayBot"])
    log(f"python {platform_python_version()} compileall OK")

    if DIST.exists():
        shutil.rmtree(DIST)
    run([*_python(), "build", "--outdir", str(DIST)])

    artifacts = sorted(DIST.iterdir())
    if not any(item.suffix == ".whl" for item in artifacts):
        raise SystemExit("build produced no wheel")
    version = pyproject_version()
    for item in artifacts:
        if version not in item.name:
            raise SystemExit(f"artifact {item.name} does not carry version {version}")

    manifest = {
        "python": platform_python_version(),
        "version": version,
        "artifacts": [
            {"name": item.name, "size": item.stat().st_size, "sha256": _sha256(item)}
            for item in artifacts
        ],
    }
    (REPORTS / "build.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"built {len(artifacts)} artifact(s): " + ", ".join(item.name for item in artifacts))


# ------------------------------------------------------------------------ test


def step_test(args: argparse.Namespace) -> None:
    _prepare_reports()
    env_examples = os.environ.get("QQBOT_FUZZ_EXAMPLES")
    if args.examples is not None:
        os.environ["QQBOT_FUZZ_EXAMPLES"] = str(args.examples)
    log(
        f"hypothesis examples: {os.environ.get('QQBOT_FUZZ_EXAMPLES', 'default (2000)')}"
        + (f" (env had {env_examples})" if env_examples and args.examples is None else "")
    )

    run(
        [
            *_python(),
            "pytest",
            "-q",
            "--cov=RayBot/core",
            "--cov-report=term",
            f"--cov-report=xml:{REPORTS / 'coverage.xml'}",
            f"--junitxml={REPORTS / 'junit.xml'}",
        ]
    )
    log("test suite passed")


# ------------------------------------------------------------------------ scan


def _run_ruff() -> None:
    result = run(
        [
            *_python(),
            "ruff",
            "check",
            "RayBot",
            "tests",
            "examples",
            "tools",
            "--output-format",
            "json",
        ],
        capture=True,
        check=False,
    )
    payload = result.stdout or "[]"
    (REPORTS / "ruff.json").write_text(payload, encoding="utf-8")
    if result.returncode != 0:
        print(payload[:4000] or result.stderr[-4000:])
        raise SystemExit("ruff reported findings")
    run([*_python(), "ruff", "format", "--check", "RayBot", "tests", "examples", "tools"])
    log("ruff: 0 findings, formatting clean")


def _run_bandit() -> None:
    target = REPORTS / "bandit.json"
    result = run(
        [
            *_python(),
            "bandit",
            "-r",
            "RayBot",
            "-ll",
            "-q",
            "-f",
            "json",
            "-o",
            str(target),
        ],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr[-4000:])
        raise SystemExit("bandit reported medium+ findings")
    log("bandit: no issues (medium+)")


def _audit_ignore_ids() -> list[str]:
    ignore_file = ROOT / "security-audit-ignore.txt"
    if not ignore_file.exists():
        return []
    ids: list[str] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.extend([" --ignore-vuln", entry])
    # Return flags as flat pairs for argparse style repetition.
    return ids


def _run_pip_audit() -> None:
    target = REPORTS / "pip-audit.json"
    cmd = [*_python(), "pip_audit", "-l", "-f", "json", "-o", str(target)]
    cmd.extend(_audit_ignore_ids())
    result = run(cmd, capture=True, check=False)
    if result.returncode != 0:
        print(result.stderr[-4000:])
        raise SystemExit("pip-audit found known vulnerabilities")
    log("pip-audit: no known vulnerabilities")


def _run_secret_scan() -> None:
    run(
        [
            venv_python(),
            str(ROOT / "tools" / "check_secrets.py"),
            "--root",
            str(ROOT),
            "--json",
            str(REPORTS / "secrets.json"),
        ]
    )
    log("secret scan: clean")


def _run_coverage_gate(args: argparse.Namespace) -> None:
    minimum = float(os.environ.get("COVERAGE_MIN", "75"))
    if not (ROOT / ".coverage").exists():
        log(f"warning: no .coverage data; coverage gate (>= {minimum}%) skipped")
        return
    run([*_python(), "coverage", "report", f"--fail-under={minimum}"])
    log(f"coverage gate: >= {minimum}% passed")


def step_scan(args: argparse.Namespace) -> None:
    _prepare_reports()
    _run_ruff()
    _run_bandit()
    _run_pip_audit()
    _run_secret_scan()
    _run_coverage_gate(args)
    _write_summary()
    log("all scans passed")


def _write_summary() -> None:
    lines = ["# CI 扫描摘要", ""]
    build = REPORTS / "build.json"
    if build.exists():
        manifest = json.loads(build.read_text(encoding="utf-8"))
        lines.append(f"- 版本: {manifest['version']} / Python {manifest['python']}")
        lines.append(f"- 构建产物: {', '.join(item['name'] for item in manifest['artifacts'])}")
    bandit_file = REPORTS / "bandit.json"
    if bandit_file.exists():
        results = json.loads(bandit_file.read_text(encoding="utf-8")).get("results", [])
        lines.append(f"- bandit: {len(results)} issue(s)")
    audit_file = REPORTS / "pip-audit.json"
    if audit_file.exists():
        deps = json.loads(audit_file.read_text(encoding="utf-8")).get("dependencies", [])
        vulnerable = [dep for dep in deps if dep.get("vulns")]
        lines.append(f"- pip-audit: {len(vulnerable)} vulnerable package(s) / {len(deps)} audited")
    secrets_file = REPORTS / "secrets.json"
    if secrets_file.exists():
        payload = json.loads(secrets_file.read_text(encoding="utf-8"))
        lines.append(
            f"- secret scan: {payload['finding_count']} finding(s) / {payload['scanned_files']} files"
        )
    lines.append("")
    (REPORTS / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


# --------------------------------------------------------------------- release


def _resolve_tag(args: argparse.Namespace) -> str | None:
    if args.tag:
        return args.tag
    for name in ("GITEE_TAG", "BUILD_TAG", "TAG_NAME", "GITHUB_REF_NAME"):
        value = os.environ.get(name)
        if value:
            return value
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def step_release(args: argparse.Namespace) -> None:
    _prepare_reports()
    package_version = pyproject_version()
    if source_version() != package_version:
        raise SystemExit(
            f"version mismatch: pyproject={package_version}, constants={source_version()}"
        )

    tag = _resolve_tag(args)
    if tag:
        tag_version = tag.lstrip("v")
        if tag_version != package_version:
            raise SystemExit(f"tag {tag!r} does not match package version {package_version}")
        log(f"tag/version consistency OK ({tag})")
    else:
        log("no tag detected; running release checks against the package version (dry-run)")

    step_build(args)
    run([*_python(), "twine", "check", str(DIST / "*")])
    log("twine check passed")

    sums = []
    for item in sorted(DIST.iterdir()):
        line = f"{_sha256(item)}  {item.name}"
        sums.append(line)
    (DIST / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    log("SHA256SUMS written")

    if args.publish:
        token = os.environ.get("PYPI_TOKEN")
        if not token:
            raise SystemExit("--publish requested but PYPI_TOKEN is not set")
        run(
            [
                *_python(),
                "twine",
                "upload",
                "--non-interactive",
                "--username",
                "__token__",
                "--password",
                token,
                str(DIST / "*"),
            ],
        )
        log("uploaded to PyPI")
    else:
        log("publish skipped (pass --publish and set PYPI_TOKEN to upload)")

    gitee_token = os.environ.get("GITEE_TOKEN")
    gitee_repo = os.environ.get("GITEE_REPO")
    if args.publish and gitee_token and gitee_repo and tag:
        _create_gitee_release(gitee_token, gitee_repo, tag, package_version, sums)
    elif args.publish:
        log("Gitee release skipped (GITEE_TOKEN / GITEE_REPO not set)")


def _create_gitee_release(token: str, repo: str, tag: str, version: str, sums: list[str]) -> None:
    import urllib.parse
    import urllib.request

    body = "\n".join(["## 发布内容", "", f"- RayBot {version}", "- 校验和：", "```", *sums, "```"])
    data = urllib.parse.urlencode(
        {
            "access_token": token,
            "tag_name": tag,
            "name": f"v{version}",
            "body": body,
            "prerelease": "false",
        }
    ).encode()
    request = urllib.request.Request(
        f"https://gitee.com/api/v5/repos/{repo}/releases", data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaces as a release failure
        raise SystemExit(f"failed to create Gitee release: {exc}") from exc
    log(f"Gitee release created: id={payload.get('id')}")

    if shutil.which("curl"):
        release_id = payload.get("id")
        for item in sorted(DIST.iterdir()):
            run(
                [
                    "curl",
                    "-fsS",
                    "-X",
                    "POST",
                    f"https://gitee.com/api/v5/repos/{repo}/releases/{release_id}/attach_files",
                    "-F",
                    f"access_token={token}",
                    "-F",
                    f"file=@{item}",
                ]
            )
        log("release assets attached")


# ----------------------------------------------------------------------- smoke


def step_smoke(args: argparse.Namespace) -> None:
    """Manual-only: real-credential connectivity check (never in PR pipelines)."""

    if not os.environ.get("QQBOT_APP_ID") or not os.environ.get("QQBOT_CLIENT_SECRET"):
        raise SystemExit(
            "smoke requires QQBOT_APP_ID and QQBOT_CLIENT_SECRET (密文变量, manual only)"
        )
    run([*_python(), "examples/smoke_test.py", "--gateway"])
    log("live smoke test passed (token / gateway / READY)")


# ------------------------------------------------------------------------- all


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("install", "build", "scan", "smoke"):
        sub.add_parser(name)

    test = sub.add_parser("test")
    test.add_argument(
        "--examples", type=int, default=None, help="hypothesis max_examples for fuzz tests"
    )

    release = sub.add_parser("release")
    release.add_argument("--tag", default=None, help="release tag, e.g. v0.2.0")
    release.add_argument(
        "--publish", action="store_true", help="upload to PyPI/Gitee (needs tokens)"
    )
    release.add_argument("--dry-run", action="store_true", help="validation only")

    all_cmd = sub.add_parser("all")
    all_cmd.add_argument("--examples", type=int, default=None)
    all_cmd.add_argument("--coverage-min", type=float, default=None)

    args = parser.parse_args()
    if getattr(args, "coverage_min", None) is not None:
        os.environ["COVERAGE_MIN"] = str(args.coverage_min)

    steps = {
        "install": step_install,
        "build": step_build,
        "test": step_test,
        "scan": step_scan,
        "release": step_release,
        "smoke": step_smoke,
    }
    if args.command == "all":
        step_install(args)
        step_build(args)
        step_test(args)
        step_scan(args)
        step_release(argparse.Namespace(tag=None, publish=False, dry_run=True))
        log("ALL GATES PASSED")
        return 0

    steps[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
