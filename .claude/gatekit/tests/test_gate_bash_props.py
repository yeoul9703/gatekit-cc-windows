"""Property tests for gates/bash.py: a command is read in every context of the grammar.

The example tests pin single commands. These put a generated command into each
context a shell offers — after a reserved word, in a block, a function body,
a nested shell, a command substitution (quoted, unquoted, backticks), after a
comment line — and check two things:

* a write with a literal path is read as exactly that path (a write the gate
  loses is a wrong allow);
* a command that writes nothing stays a command that writes nothing (a
  context must not turn a read into a denial).

The expected path is computed here, apart from the gate. Not covered, because
the gate does not read them (ADR-0004, known limits): brace expansion, a
``<<word`` inside quotes or arithmetic, a quoted argument made only of
operator characters.
"""
from __future__ import annotations

import os
import posixpath
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import paths  # noqa: E402
from gatekit.gates import bash as bash_gate  # noqa: E402
from tests.props_support import EXAMPLES, assume, given, requires_hypothesis, settings, st  # noqa: E402

CWD = "/proj"

#: The default run draws the same inputs every time; a deep run
#: (GATEKIT_PROPS_EXAMPLES set) explores at random. No example database: it
#: would write a .hypothesis directory into the kit.
SETTINGS = settings(max_examples=EXAMPLES, deadline=None, database=None,
                    derandomize="GATEKIT_PROPS_EXAMPLES" not in os.environ)

#: Where a command can stand: the compound commands of the bash grammar, the
#: pipeline and list operators, prefixes, a nested shell, command substitution.
CONTEXTS = (
    "{w}",
    "if true; then {w}; fi",
    "if false; then :; else {w}; fi",
    "if false; then :; elif true; then {w}; fi",
    "if {w}; then :; fi",
    "if true\nthen\n  {w}\nfi",
    "while false; do {w}; done",
    "until true; do {w}; done",
    "for f in a; do {w}; done",
    "for f in a\ndo\n  {w}\ndone",
    "case x in x) {w};; esac",
    "{{ {w}; }}",
    "( {w} )",
    "! {w}",
    "time {w}",
    "true && {w}",
    "false || {w}",
    "true | {w}",
    "{w} &",
    "f() {{ {w}; }}; f",
    "function f {{ {w}; }}; f",
    "A=1 {w}",
    "sudo {w}",
    "env A=1 {w}",
    "bash -c '{w}'",
    "echo $({w})",
    "x=$({w})",
    'echo "$({w})"',
    'x="$({w})"',
    "echo `{w}`",
    'echo "`{w}`"',
    'echo "$(echo "$({w})")"',
    'if true; then echo "$({w})"; fi',
    "# a note\n{w}",
    "ls # a note\n{w}",
)

WRITERS = (
    "cat > {p}", "echo hi >> {p}", "cmd 2> {p}", "make | tee {p}", "touch {p}", "rm -rf {p}",
    "mkdir -p {p}", "cp a.txt {p}", "mv a.txt {p}", "sed -i s/a/b/ {p}", "dd if=/dev/zero of={p}",
    "truncate -s 0 {p}", "sort -o {p} in.txt", "curl -o {p} https://x",
)

#: Commands that write nothing: fixed ones, and readers of a generated path.
READS = (
    "ls -la src", "git status", "git diff --stat", "git log --oneline -5", "git rev-parse HEAD",
    "cat a.txt | wc -l", "grep -r x src", "npm run build", "python3 -m unittest discover",
    "[ -f src/x.ts ]", "test -d src", "ls > /dev/null 2>&1", "true", 'echo "$HOME"', 'echo "a > b"',
    'find . -name "*.ts"', paths.CLI_INVOCATION + " spec validate --json",
)
READERS = (
    "cat {p}", "ls -la {p}", "grep -r x {p}", "wc -l {p}", "[ -f {p} ]", "head -n 5 {p}",
    "diff {p} b.txt", "git log -- {p}", "python3 {p}", "node {p}",
)

NAME = st.text(alphabet=list("abcxyzABC019_.-"), min_size=1, max_size=6).filter(
    lambda text: text[0] not in "-." and not text.isdigit())


@st.composite
def literal_path(draw):
    """A path with nothing the shell expands: names, ``.`` and ``..``, maybe absolute."""
    parts = draw(st.lists(st.one_of(NAME, st.sampled_from([".", ".."])), min_size=1, max_size=4))
    assume(parts[-1] not in (".", ".."))
    return draw(st.sampled_from(["", "", "./", "/proj/", "/tmp/"])) + "/".join(parts)


def expected(path: str) -> str:
    """Where the shell puts *path* when it runs in :data:`CWD`."""
    return posixpath.normpath(path if path.startswith("/") else CWD + "/" + path)


def read(command: str) -> "tuple[list[str], bool]":
    result = bash_gate.extract_write_targets(command, CWD)
    return sorted(result.targets), result.opaque


@requires_hypothesis
class TestCommandContexts(unittest.TestCase):
    @given(st.sampled_from(WRITERS), literal_path())
    @SETTINGS
    def test_a_write_is_read_in_every_context(self, writer: str, path: str) -> None:
        write = writer.format(p=path)
        for context in CONTEXTS:
            command = context.format(w=write)
            self.assertEqual(read(command), ([expected(path)], False), command)

    @given(st.one_of(st.sampled_from(READS),
                     st.builds(lambda reader, path: reader.format(p=path),
                               st.sampled_from(READERS), literal_path())))
    @SETTINGS
    def test_a_read_only_command_writes_nothing_in_any_context(self, command: str) -> None:
        for context in CONTEXTS:
            wrapped = context.format(w=command)
            self.assertEqual(read(wrapped), ([], False), wrapped)


if __name__ == "__main__":
    unittest.main()
