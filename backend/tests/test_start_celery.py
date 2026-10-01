"""A Render `dockerCommand` is not a shell line, and both workers died of it.

The first deploy to Render brought the API up cleanly and crash-looped the
worker and beat from the first second, with this in both logs:

    sh: 1: python -m app.scripts.wait_for_schema && exec celery -A
    app.config.celery:celery_app worker --loglevel=info --queues=... : not found

`sh` is naming the WHOLE command as the program it could not find. The
blueprint had asked for `sh -c "python -m ... && exec celery ..."`, which is
correct Docker and correct shell and works under compose. Render consumes the
`sh -c ` itself and hands the remainder to its own shell with the double
quotes still in it; that shell strips them and is left with one enormous word,
so the `&&` is never parsed as an operator and nothing runs.

Two tests, and they guard different halves of the fix.

The first is shaped like the mistake: it reads the blueprint and refuses a
`dockerCommand` containing a quote or a `&&`. That is the silhouette of the
bug, and it is the only mechanical guard against someone reaching for a shell
one-liner again - it looks right, it works on every other platform, and it
fails only in production.

The second covers what replaced it: the wait and the exec are now joined in
Python, where they are ordinary statements rather than shell syntax.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.scripts import start_celery  # noqa: E402

BLUEPRINT = Path(__file__).resolve().parents[2] / "render.yaml"


def docker_commands() -> dict[str, str]:
    """Every `dockerCommand` in the blueprint, folded back into one line.

    Parsed as text rather than with PyYAML on purpose: the assertion is about
    the characters that reach Render, and a YAML loader would happily resolve
    an escape that Render's own splitter would not.
    """

    text = BLUEPRINT.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    service = ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        name = re.match(r"^\s*- name:\s*(\S+)", line)
        if name:
            service = name.group(1)
            continue
        if not re.match(r"^\s*dockerCommand:", line):
            continue
        inline = line.split("dockerCommand:", 1)[1].strip()
        if inline and inline not in {">-", ">", "|-", "|"}:
            found[service] = inline
            continue
        # A folded block: every following line indented further than the key.
        indent = len(line) - len(line.lstrip())
        parts: list[str] = []
        for following in lines[index + 1 :]:
            if not following.strip():
                break
            if len(following) - len(following.lstrip()) <= indent:
                break
            parts.append(following.strip())
        found[service] = " ".join(parts)
    return found


class TheBlueprintCommandsSurviveRenderSplittingThem(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = docker_commands()

    def test_both_celery_services_declare_one(self) -> None:
        # Identified by what they RUN rather than by what they are called. The
        # names carried a `-sg` suffix the day the deployment moved region,
        # because a Render service's region is immutable and moving means
        # creating new services beside the old ones. A test keyed on the name
        # would have failed for a reason that has nothing to do with what it
        # is guarding.
        #
        # This assertion still matters: if neither service declares a command,
        # the rest of the class is vacuously green, which is the usual way a
        # guard test quietly stops guarding anything.
        celery = [name for name, cmd in self.commands.items() if "celery" in cmd]
        self.assertEqual(len(celery), 2, self.commands)
        self.assertTrue(any("worker" in cmd for cmd in self.commands.values()))
        self.assertTrue(any(" beat" in cmd for cmd in self.commands.values()))

    def test_no_command_carries_a_quote(self) -> None:
        for service, command in self.commands.items():
            with self.subTest(service=service):
                self.assertNotIn('"', command)
                self.assertNotIn("'", command)

    def test_no_command_carries_a_shell_operator(self) -> None:
        # `&&` is the one that actually bit, but a `;` or a `|` would arrive
        # just as literally and fail just as confusingly.
        for service, command in self.commands.items():
            with self.subTest(service=service):
                for operator in ("&&", "||", ";", "|", "$("):
                    self.assertNotIn(operator, command)

    def test_the_celery_services_go_through_start_celery(self) -> None:
        # Not cosmetic: this module is what makes the wait happen at all now
        # that `&&` is gone. A command that calls `celery` directly would start
        # against whatever schema happened to be there.
        for service, command in self.commands.items():
            if "celery" not in command:
                continue
            with self.subTest(service=service):
                self.assertTrue(
                    command.startswith("python -m app.scripts.start_celery"),
                    command,
                )


class WaitThenBecomeCelery(unittest.TestCase):
    def test_it_waits_before_it_execs(self) -> None:
        order: list[str] = []

        def wait() -> int:
            order.append("wait")
            return 0

        def execvp(_file: str, _args: list[str]) -> None:
            order.append("exec")

        with mock.patch.object(start_celery, "wait_for_schema", wait):
            with mock.patch.object(os, "execvp", execvp):
                start_celery.main(["-A", "app.config.celery:celery_app", "worker"])

        self.assertEqual(order, ["wait", "exec"])

    def test_the_arguments_are_passed_through_untouched(self) -> None:
        captured: dict[str, object] = {}

        def execvp(file: str, args: list[str]) -> None:
            captured["file"] = file
            captured["args"] = args

        given = [
            "-A",
            "app.config.celery:celery_app",
            "worker",
            "--queues=default,analytics,embeddings,notifications",
            "--concurrency=2",
        ]
        with mock.patch.object(start_celery, "wait_for_schema", lambda: 0):
            with mock.patch.object(os, "execvp", execvp):
                start_celery.main(given)

        self.assertEqual(captured["file"], "celery")
        # argv[0] is the program name Celery sees in its own usage messages.
        self.assertEqual(captured["args"], ["celery", *given])

    def test_a_schema_that_never_arrives_is_not_papered_over(self) -> None:
        # The whole reason the wait exists. Starting anyway would mean a worker
        # selecting columns that do not exist yet, once per task, silently.
        def execvp(_file: str, _args: list[str]) -> None:  # pragma: no cover
            raise AssertionError("celery must not start when the wait failed")

        with mock.patch.object(start_celery, "wait_for_schema", lambda: 1):
            with mock.patch.object(os, "execvp", execvp):
                self.assertEqual(start_celery.main(["worker"]), 1)

    def test_no_arguments_is_refused_rather_than_guessed(self) -> None:
        # A bare `celery` would fail with a Celery error about a missing app,
        # which sends the reader to the wrong file entirely.
        def execvp(_file: str, _args: list[str]) -> None:  # pragma: no cover
            raise AssertionError("nothing should be exec'd without arguments")

        with mock.patch.object(os, "execvp", execvp):
            self.assertEqual(start_celery.main([]), 2)

    def test_it_does_not_wait_before_refusing(self) -> None:
        # Ordering that matters in practice: an empty command should fail in a
        # second, not after five minutes of polling a database for a schema it
        # was never going to use.
        def wait() -> int:  # pragma: no cover
            raise AssertionError("the wait must come after the arguments check")

        with mock.patch.object(start_celery, "wait_for_schema", wait):
            self.assertEqual(start_celery.main([]), 2)


if __name__ == "__main__":
    unittest.main()
