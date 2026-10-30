"""Изолированные проверки хуков: Git fixture и поддельный make, без продукта."""

import fcntl
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load("check-state")
push = load("pre-push-check")


class HookTests(unittest.TestCase):
    def setUp(self):
        # Git hooks экспортируют GIT_DIR/INDEX_FILE и config overrides.
        # Синтетический репозиторий не должен обращаться к checkout вызывающего.
        clean = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GIT_", "LEFTHOOK"))
        }
        clean_env = patch.dict(os.environ, clean, clear=True)
        clean_env.start()
        self.addCleanup(clean_env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = (Path(self.tmp.name) / "repo").resolve()
        self.root.mkdir()
        self.git("init", "-q")
        fixture_hooks = Path(self.tmp.name) / "empty-hooks"
        fixture_hooks.mkdir()
        self.git("config", "core.hooksPath", str(fixture_hooks))
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.root / "scripts/agent-hooks").mkdir(parents=True)
        for source in ROOT.glob("*.py"):
            shutil.copy2(source, self.root / "scripts/agent-hooks" / source.name)
        for source in ROOT.glob("*.sh"):
            shutil.copy2(source, self.root / "scripts/agent-hooks" / source.name)
        (self.root / "frontend").mkdir()
        (self.root / "frontend/main.ts").write_text("original\n")
        (self.root / ".gitignore").write_text("node_modules/\n.env\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.env = patch.dict(
            os.environ,
            {
                "CLAUDE_PROJECT_DIR": str(self.root),
                "XDG_CACHE_HOME": str(Path(self.tmp.name) / "cache"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = 0

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root).decode().strip()

    def event(self, mode, session="one", **fields):
        event = {
            "session_id": session,
            "cwd": str(self.root),
            "tool_use_id": "tool-one",
            **fields,
        }
        with (
            patch.object(sys, "argv", ["check-state.py", mode]),
            patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
            redirect_stderr(io.StringIO()),
        ):
            return state.main()

    def make(self, root, output):
        self.assertEqual(root, self.root)
        self.calls += 1
        return subprocess.CompletedProcess(["make", "check-fast"], 0)

    def mark(self, session="one"):
        return self.event(
            "mark",
            session=session,
            tool_input={"file_path": str(self.root / "frontend/main.ts")},
        )

    def test_dirty_checkout_without_session_mutation_does_not_run(self):
        (self.root / "frontend/main.ts").write_text("earlier work\n")
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 0)

    def test_other_session_changes_do_not_trigger_read_only_session(self):
        (self.root / "frontend/main.ts").write_text("other session\n")
        self.mark("writer")
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop", session="reader"), 0)
        self.assertEqual(self.calls, 0)

    def test_success_reused_until_candidate_changes(self):
        self.mark()
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
            self.mark()
            self.assertEqual(self.event("stop"), 0)
            (self.root / "frontend/main.ts").write_text("new candidate\n")
            self.mark()
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 2)

    def test_read_only_bash_does_not_mark_changes(self):
        self.assertEqual(self.event("before"), 0)
        self.assertEqual(self.event("after"), 0)
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 0)

    def test_failed_bash_partial_write_is_tracked(self):
        self.event("before")
        (self.root / "frontend/main.ts").write_text("partially written\n")
        self.event("after", hook_event_name="PostToolUseFailure")
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 1)

    def test_failure_not_cached_and_no_unchanged_stop_loop(self):
        self.mark()
        failed = subprocess.CompletedProcess(["make", "check-fast"], 1)
        with patch.object(state, "run_check", return_value=failed) as run:
            self.assertEqual(self.event("stop"), 2)
            self.assertEqual(self.event("stop", stop_hook_active=True), 0)
            self.assertEqual(self.event("stop"), 2)
        self.assertEqual(run.call_count, 2)

    def test_source_race_does_not_cache_success(self):
        self.mark()

        def racing(root, output):
            (self.root / "frontend/main.ts").write_text("changed during gate\n")
            return subprocess.CompletedProcess(["make", "check-fast"], 0)

        with patch.object(state, "run_check", racing):
            self.assertEqual(self.event("stop"), 2)
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop", stop_hook_active=True), 0)
        self.assertEqual(self.calls, 1)

    def test_fingerprint_ignores_dependency_tree_and_tracks_untracked_source(self):
        before = state.fingerprint(self.root)
        (self.root / "frontend/node_modules").mkdir()
        (self.root / "frontend/node_modules/generated.js").write_text("generated")
        self.assertEqual(state.fingerprint(self.root), before)
        (self.root / "frontend/new.ts").write_text("new")
        self.assertNotEqual(state.fingerprint(self.root), before)

    def test_outside_file_and_docs_do_not_mark_product(self):
        for path in [str(Path(self.tmp.name) / "outside.py"), "docs/context.md"]:
            self.event("mark", tool_input={"file_path": path})
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 0)

    def test_relevant_multiedit_paths_mark_pending(self):
        self.event("mark", tool_input={"edits": [{"file_path": "frontend/main.ts"}]})
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 1)

    def test_invalid_event_reports_tracking_failure(self):
        with (
            patch.object(sys, "argv", ["check-state.py", "stop"]),
            patch.object(sys, "stdin", io.StringIO("{}")),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(state.main(), 2)

    def test_foreign_git_hook_environment_cannot_mutate_ambient_repository(self):
        config = self.root / ".git/config"
        index = self.root / ".git/index"
        before = (
            config.read_bytes(),
            index.read_bytes(),
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain"),
        )
        inherited = dict(os.environ)
        inherited.update(
            {
                "GIT_DIR": str(self.root / ".git"),
                "GIT_WORK_TREE": str(self.root),
                "GIT_INDEX_FILE": str(index),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "user.name",
                "GIT_CONFIG_VALUE_0": "Ambient override",
            }
        )
        child = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "HookTests.test_read_only_bash_does_not_mark_changes",
            ],
            env=inherited,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        after = (
            config.read_bytes(),
            index.read_bytes(),
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain"),
        )
        self.assertEqual(after, before)

    def test_busy_checkout_does_not_start_parallel_checks(self):
        self.mark()
        cache = next((Path(self.tmp.name) / "cache/bpmn-agent-checks").iterdir())
        with (cache / "check.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(state, "run_check", self.make):
                self.assertEqual(self.event("stop"), 2)
        self.assertEqual(self.calls, 0)

    def test_read_only_session_ignores_other_sessions_busy_check_lock(self):
        self.mark("writer")
        cache = next((Path(self.tmp.name) / "cache/bpmn-agent-checks").iterdir())
        with (cache / "check.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(state, "run_check", self.make):
                self.assertEqual(self.event("stop", session="reader"), 0)
        self.assertEqual(self.calls, 0)

    def test_configured_bash_failure_wiring_marks_the_changed_session(self):
        settings = json.loads((ROOT.parents[1] / ".claude/settings.json").read_text())
        before = next(
            h["hooks"][0]["command"]
            for h in settings["hooks"]["PreToolUse"]
            if h["matcher"] == "Bash"
        )
        after = next(
            h["hooks"][0]["command"]
            for h in settings["hooks"]["PostToolUseFailure"]
            if h["matcher"] == "Bash"
        )
        event = {
            "session_id": "one",
            "cwd": str(self.root),
            "tool_use_id": "configured",
        }
        subprocess.run(
            ["bash", "-c", before],
            input=json.dumps(event),
            text=True,
            cwd=self.root,
            check=True,
        )
        (self.root / "frontend/main.ts").write_text("written by failed shell")
        subprocess.run(
            ["bash", "-c", after],
            input=json.dumps(event),
            text=True,
            cwd=self.root,
            check=True,
        )
        with patch.object(state, "run_check", self.make):
            self.assertEqual(self.event("stop"), 0)
        self.assertEqual(self.calls, 1)

    def test_background_command_stays_pending_until_finished(self):
        self.event("before")
        self.event("after", tool_input={"run_in_background": True})
        with patch.object(state, "run_check", self.make):
            self.assertEqual(
                self.event("stop", background_tasks=[{"type": "shell"}]), 0
            )
            self.assertEqual(self.calls, 0)
            self.assertEqual(self.event("stop", background_tasks=[]), 0)
        self.assertEqual(self.calls, 1)

    def test_first_push_scope_contains_all_unpublished_commits(self):
        base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", base)
        (self.root / "README.md").write_text("docs")
        self.git("add", "README.md")
        self.git("commit", "-qm", "docs")
        head = self.git("rev-parse", "HEAD")
        line = f"refs/heads/fix {head} refs/heads/fix {push.ZERO}"
        self.assertEqual(push.pushed_paths(self.root, "origin", [line]), {"README.md"})
        (self.root / "frontend/main.ts").write_text("product")
        self.git("add", "frontend/main.ts")
        self.git("commit", "-qm", "product")
        head = self.git("rev-parse", "HEAD")
        line = f"refs/heads/fix {head} refs/heads/fix {push.ZERO}"
        self.assertEqual(
            push.pushed_paths(self.root, "origin", [line]),
            {"README.md", "frontend/main.ts"},
        )

    def test_updates_compare_remote_oid_to_pushed_head(self):
        base = self.git("rev-parse", "HEAD")
        (self.root / "README.md").write_text("docs")
        self.git("add", "README.md")
        self.git("commit", "-qm", "docs")
        head = self.git("rev-parse", "HEAD")
        line = f"refs/heads/fix {head} refs/heads/fix {base}"
        self.assertEqual(push.pushed_paths(self.root, "origin", [line]), {"README.md"})


class PushScopeTests(unittest.TestCase):
    def test_docs_and_hook_paths_are_focused(self):
        for path in [
            "README.md",
            "docs/guide.md",
            "scripts/agent-hooks/check-state.py",
            "scripts/agent-hooks/tests/test_check_state.py",
            ".claude/settings.json",
            "lefthook.yml",
        ]:
            self.assertTrue(push.focused_path(path), path)

    def test_product_runtime_and_unknown_paths_need_full_gate(self):
        for path in [
            "frontend/README.md",
            "backend/app/main.py",
            "docs/api/openapi.json",
            "package.json",
            "scripts/deploy.sh",
            "compose.yaml",
        ]:
            self.assertFalse(push.focused_path(path), path)

    def test_malformed_push_scope_is_unknown(self):
        self.assertIsNone(push.pushed_paths(Path("."), "origin", ["not git stdin"]))

    def test_nonchecked_out_push_is_rejected(self):
        with (
            patch.object(push, "git", return_value=b"b" * 40),
            self.assertRaises(ValueError),
        ):
            push.pushed_paths(
                Path("."),
                "origin",
                [f"refs/heads/x {'a' * 40} refs/heads/x {'b' * 40}"],
            )

    def invoke(self, paths, result=0):
        with (
            patch.object(push.subprocess, "check_output", return_value="/tmp/repo\n"),
            patch.object(push, "git", return_value=b""),
            patch.object(push, "pushed_paths", return_value=paths),
            patch.object(push, "run_gate", return_value=result) as run,
            patch.object(sys, "argv", ["pre-push-check.py", "origin"]),
            patch.object(sys, "stdin", io.StringIO("fixture push input")),
            redirect_stdout(io.StringIO()),
        ):
            status = push.main()
        return status, [call.args[0] for call in run.call_args_list]

    def test_focused_main_runs_hook_tests_and_shellcheck(self):
        status, commands = self.invoke({"AGENTS.md"})
        self.assertEqual(status, 0)
        self.assertIn("unittest", commands[0])
        self.assertEqual(commands[1][0], "shellcheck")
        self.assertEqual(commands[2], ["./node_modules/.bin/lefthook", "validate"])

    def test_product_and_unknown_main_keep_full_gate(self):
        for paths in [{"frontend/main.ts"}, None]:
            status, commands = self.invoke(paths)
            self.assertEqual(status, 0)
            self.assertEqual(commands, [["make", "check"]])

    def test_focused_failure_propagates_without_running_second_stage(self):
        status, commands = self.invoke({"AGENTS.md"}, result=7)
        self.assertEqual(status, 7)
        self.assertEqual(len(commands), 1)


if __name__ == "__main__":
    unittest.main()
