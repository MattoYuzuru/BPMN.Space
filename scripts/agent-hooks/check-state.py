#!/usr/bin/env python3
"""Привязка интерактивной проверки к изменениям сессии и содержимому checkout."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCOPE = (
    "frontend",
    "backend",
    "scripts",
    "infra",
    "Makefile",
    "package.json",
    "package-lock.json",
    "biome.json",
    "biome.jsonc",
    "tsconfig.json",
)


def relevant(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in SCOPE


def fingerprint(root: Path) -> str:
    # Git привязывает неизменные файлы к HEAD; читаем содержимое только delta.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD", "--", *SCOPE],
        cwd=root,
    )
    untracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--exclude-standard", "--", *SCOPE],
        cwd=root,
    )
    names = (changed + untracked).split(b"\0")
    digest = hashlib.sha256()
    digest.update(head)
    for raw in sorted(set(names) - {b""}):
        path = root / os.fsdecode(raw)
        # Секреты не читаем; окружение и зависимости этот кеш не удостоверяет.
        if path.name == ".env" or (
            path.name.startswith(".env.") and path.suffix != ".example"
        ):
            continue
        digest.update(raw + b"\0")
        try:
            info = path.lstat()
            digest.update(str(stat.S_IMODE(info.st_mode)).encode() + b"\0")
            if path.is_symlink():
                digest.update(os.fsencode(os.readlink(path)))
            elif path.is_file():
                with path.open("rb") as source:
                    for block in iter(lambda: source.read(65536), b""):
                        digest.update(block)
            else:
                raise ValueError(f"unsupported source: {os.fsdecode(raw)}")
        except FileNotFoundError:
            digest.update(b"deleted")
        digest.update(b"\0")
    return digest.hexdigest()


def edit_paths(event: dict, root: Path) -> list[Path]:
    tool = event.get("tool_input", {})
    if not isinstance(tool, dict):
        return []
    values = [tool.get("file_path"), tool.get("path"), tool.get("notebook_path")]
    for edit in tool.get("edits", []):
        if isinstance(edit, dict):
            values.append(edit.get("file_path"))
    paths = []
    for value in values:
        if isinstance(value, str):
            path = Path(value)
            if not path.is_absolute():
                path = Path(event.get("cwd", root)) / path
            if relevant(path, root):
                paths.append(path)
    return list(dict.fromkeys(paths))


def run_check(root: Path, output):
    command = ["make", "check-fast"]
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        return subprocess.CompletedProcess(command, process.wait(timeout=240))
    except subprocess.TimeoutExpired:
        # Завершаем только созданную нами группу, включая дочерние npm/uv.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise


def check(root: Path, state: dict, session: dict, event: dict) -> int:
    if not session.get("pending"):
        return 0
    if any(
        task.get("type") == "shell"
        for task in event.get("background_tasks", [])
        if isinstance(task, dict)
    ):
        print(
            "Фоновая shell-задача ещё работает; проверка отложена до её завершения.",
            file=sys.stderr,
        )
        return 0
    candidate = fingerprint(root)
    if state.get("passed") == candidate:
        session["pending"] = False
        return 0
    if event.get("stop_hook_active") and session.get("failed") == candidate:
        # Не зацикливаем один отказ. Следующий обычный ход повторит проверку.
        print(
            "check-fast уже завершился ошибкой для этого состояния; результат остаётся неуспешным.",
            file=sys.stderr,
        )
        return 0
    with tempfile.TemporaryFile(mode="w+t") as output:
        try:
            result = run_check(root, output)
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            passed = False
            output.write("\ncheck-fast превысил лимит 240 секунд.\n")
        stable = fingerprint(root) == candidate
        if passed and stable:
            state["passed"] = candidate
            session["pending"] = False
            session.pop("failed", None)
            return 0
        session["failed"] = candidate
        output.seek(0)
        lines = output.read().splitlines()
        print(
            "make check-fast не подтвердил текущее состояние. Исправьте ошибки перед завершением.",
            file=sys.stderr,
        )
        if not stable:
            print(
                "Исходники изменились во время проверки; результат нельзя переиспользовать.",
                file=sys.stderr,
            )
        print("\n".join(lines[-60:]), file=sys.stderr)
        return 2


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or not event.get("session_id"):
            raise ValueError("hook event must include session_id")
        root = Path(
            os.environ.get("CLAUDE_PROJECT_DIR", event.get("cwd", "."))
        ).resolve()
        root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=root, text=True
            ).strip()
        ).resolve()
        cache = (
            Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
            / "bpmn-agent-checks"
        )
        cache /= hashlib.sha256(os.fsencode(root)).hexdigest()
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = hashlib.sha256(str(event["session_id"]).encode()).hexdigest()
        state_file = cache / f"{key}.json"
        with (cache / f"{key}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            session = state.setdefault("session", {})
            mode = sys.argv[1]
            command = str(event.get("tool_use_id", ""))
            if mode == "before":
                if not command:
                    raise ValueError("Bash event must include tool_use_id")
                commands = session.setdefault("commands", {})
                commands[command] = fingerprint(root)
                # Потерянный PostToolUse не должен бесконечно раздувать кеш.
                while len(commands) > 64:
                    commands.pop(next(iter(commands)))
            elif mode == "after":
                before = session.setdefault("commands", {}).pop(command, None)
                if (
                    before is None
                    or before != fingerprint(root)
                    or event.get("tool_input", {}).get("run_in_background")
                ):
                    session["pending"] = True
            elif mode == "mark":
                if edit_paths(event, root):
                    session["pending"] = True
            elif mode == "stop":
                if not session.get("pending"):
                    return 0
                # Другие сессии могут продолжать работу; параллельные проверки
                # одного checkout не запускаем. Изменения во время make заметит hash.
                with (cache / "check.lock").open("a") as check_lock:
                    try:
                        fcntl.flock(check_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        print(
                            "Проверка этого checkout уже идёт; дождитесь её и повторите завершение.",
                            file=sys.stderr,
                        )
                        return 2
                    passed_file = cache / "passed"
                    state["passed"] = (
                        passed_file.read_text() if passed_file.exists() else None
                    )
                    result = check(root, state, session, event)
                    if state.get("passed"):
                        passed_file.write_text(state["passed"])
            else:
                raise ValueError("unknown hook mode")
            with tempfile.NamedTemporaryFile(
                mode="w", dir=cache, delete=False
            ) as target:
                json.dump(state, target)
                temporary = target.name
            os.replace(temporary, state_file)
            return result if mode == "stop" else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            f"agent check tracking failed: {exc}; run make check-fast explicitly.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
