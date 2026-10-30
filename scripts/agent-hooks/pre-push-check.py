#!/usr/bin/env python3
"""Консервативно выбирает точечный gate для документации и agent hooks."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ZERO = "0" * 40


def focused_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        name
        in {
            "AGENTS.md",
            "CLAUDE.md",
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            ".claude/settings.json",
            "lefthook.yml",
        }
        or (name.startswith("docs/") and path.suffix == ".md")
        or (name.startswith(".claude/skills/") and path.suffix == ".md")
        or (
            name.startswith("scripts/agent-hooks/")
            and path.suffix in {".py", ".sh", ".md"}
        )
    )


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def run_gate(command: list[str], root: Path) -> int:
    return subprocess.run(command, cwd=root, check=False).returncode


def pushed_paths(root: Path, remote: str, lines: list[str]) -> set[str] | None:
    """None означает неизвестный scope, требующий полного gate."""
    names: set[str] = set()
    for line in lines:
        values = line.split()
        if len(values) != 4:
            return None
        _, local, _, old = values
        if not all(re.fullmatch(r"[0-9a-f]{40}", oid) for oid in (local, old)):
            return None
        if local == ZERO:  # Удаление ref не публикует новое содержимое.
            continue
        if local != git(root, "rev-parse", "HEAD").decode().strip():
            raise ValueError("push candidate must be the checked-out HEAD")
        try:
            if old != ZERO:
                changed = git(
                    root, "diff", "--name-only", "--no-renames", "-z", old, local
                )
            else:
                commits = (
                    git(root, "rev-list", local, "--not", f"--remotes={remote}")
                    .decode()
                    .splitlines()
                )
                if len(commits) > 256:
                    return None
                changed = b"".join(
                    git(
                        root,
                        "diff-tree",
                        "-m",
                        "--root",
                        "--no-commit-id",
                        "--no-renames",
                        "--name-only",
                        "-r",
                        "-z",
                        commit,
                    )
                    for commit in commits
                )
            names.update(
                p.decode("utf-8", "surrogateescape") for p in changed.split(b"\0") if p
            )
        except subprocess.CalledProcessError:
            return None
    return names


def main() -> int:
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    remote = sys.argv[1] if len(sys.argv) > 1 else "origin"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
        print(
            "Unsupported remote name; cannot select verification scope.",
            file=sys.stderr,
        )
        return 2
    try:
        lines = sys.stdin.read().splitlines()
        paths = pushed_paths(root, remote, lines)
        # Ручной lefthook run без Git stdin не является свидетельством пустого push.
        if not lines:
            paths = None
        if git(root, "status", "--porcelain").strip():
            raise ValueError("pre-push requires a clean checkout of the pushed commit")
        if paths == set():
            print("No new file content in the pushed refs.")
            return 0
        if paths is not None and all(focused_path(path) for path in paths):
            print("Documentation/agent-hook candidate: focused hook checks.")
            commands = [
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "scripts/agent-hooks/tests",
                    "-p",
                    "test_*.py",
                ],
                [
                    "shellcheck",
                    "scripts/agent-hooks/post-edit.sh",
                    "scripts/agent-hooks/stop-check.sh",
                ],
                ["./node_modules/.bin/lefthook", "validate"],
            ]
        else:
            print("Product/runtime or unknown candidate: full make check.")
            commands = [["make", "check"]]
        for command in commands:
            result = run_gate(command, root)
            if result:
                return result
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"pre-push verification failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
