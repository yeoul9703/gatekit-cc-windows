"""Property tests for gates/powershell.py: the three bypasses of 2026-10-02.

The example tests pin the inputs that were found. These generate the family
around each one, so that a spelling nobody wrote down is still read:

* **one write, many spellings** — a write cmdlet with a literal path, spelled
  with any case, alias, backtick before a letter (the first one included),
  parameter name, quote, blank and dash PowerShell accepts, in every place a
  command can stand, is read as exactly that path;
* **a name on a deny list is never read as harmless** — whatever its case,
  ``.exe``, backticks or quotes inside it (``7z``, ``7'z'``, `` `7z ``);
* **a location function is the Set-Location it stands for** — ``cd..``,
  ``cd\\``, ``cd~`` and ``D:`` move the directory the next relative write is
  resolved against.

The expected paths are computed here, apart from the gate. Every spelling
rule used below was put to the PowerShell 7.6.6 parser before it went in
(a backtick before a letter other than ``abefnrtuv`` leaves the letter, a
quoted piece inside a bare name is part of the name, the functions exist).
"""
from __future__ import annotations

import ntpath
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit.gates import powershell as ps_gate  # noqa: E402
from tests.props_support import EXAMPLES, given, requires_hypothesis, settings, st  # noqa: E402

CWD = "C:\\proj"
HOME = os.path.expanduser("~")

#: The default run draws the same inputs every time; a deep run
#: (GATEKIT_PROPS_EXAMPLES set) explores at random. No example database, so no
#: failing input is replayed from disk. (hypothesis still keeps its own cache
#: in .hypothesis/, with a .gitignore of its own inside.)
SETTINGS = settings(max_examples=EXAMPLES, deadline=None, database=None,
                    derandomize="GATEKIT_PROPS_EXAMPLES" not in os.environ)

#: Where a statement can stand and still run as that statement.
CONTEXTS = (
    "{w}",
    "Get-ChildItem; {w}",
    "Get-ChildItem\n{w}",
    "Get-ChildItem && {w}",
    "Get-ChildItem || {w}",
    "{w} | Out-Null",
    "if ($a) {{ {w} }}",
    "if ($a) {{ 1 }} else {{ {w} }}",
    "if($a){{{w}}}",
    "foreach ($i in 1..2) {{ {w} }}",
    "while ($false) {{ {w} }}",
    "1..2 | ForEach-Object {{ {w} }}",
    "try {{ {w} }} catch {{ 1 }}",
    "switch (1) {{ 1 {{ {w} }} }}",
    "function f {{ {w} }}",
    "$r = {w}",
    "$r = ({w})",
    "Write-Host \"$({w})\"",
)

#: Backtick before one of these is a control character, not the letter.
SPECIAL = set("0abefnrtuv")
RESERVED = {"nul", "con", "prn", "aux"}


def read(command: str, cwd: "str | None" = CWD):
    result = ps_gate.extract_write_targets(command, cwd)
    return sorted(result.targets), result.opaque


def expected(path: str, cwd: str = CWD) -> str:
    """Where Windows puts *path*: computed here, not taken from the gate."""
    text = path.replace("/", "\\")
    if text[1:3] == ":\\":
        full = text
    elif text.startswith("\\"):
        full = cwd[:2] + text
    else:
        full = cwd + "\\" + text
    drive, tail = ntpath.splitdrive(ntpath.normpath(full))
    return drive.upper() + "\\".join(part.rstrip(" .") or part for part in tail.split("\\"))


# ---------------------------------------------------------------- generators
COMPONENT = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from(list("abcxyzABCXYZ_가나")),
    st.text(alphabet=list("abcxyzABC019_-.가나"), max_size=6),
).filter(lambda text: ntpath.splitext(text)[0].lower() not in RESERVED)


@st.composite
def literal_path(draw):
    """A path with nothing in it the gate treats as syntax."""
    parts = draw(st.lists(st.one_of(COMPONENT, st.sampled_from([".", ".."])), min_size=0, max_size=3))
    parts.append(draw(COMPONENT))
    sep = draw(st.sampled_from(["/", "\\"]))
    prefix = draw(st.sampled_from(["", "", ".\\", "C:\\proj\\", "c:/proj/", "D:\\other\\", "\\"]))
    return prefix + sep.join(parts)


@st.composite
def recased(draw, text):
    return "".join(ch.upper() if draw(st.booleans()) else ch.lower() for ch in text)


@st.composite
def backticked(draw, text, always_first=False):
    """Put a backtick before letters it does not change: `S is S, `n is a newline."""
    out = []
    for index, ch in enumerate(text):
        plain = ch.isascii() and ch.isalnum() and ch not in SPECIAL
        if plain and ((always_first and index == 0) or draw(st.integers(0, 4)) == 0):
            out.append("`")
        out.append(ch)
    return "".join(out)


@st.composite
def quoted_inside(draw, text):
    """Quote one piece of a bare name, never its start: 7'z' is the command 7z."""
    if len(text) < 2 or not draw(st.booleans()):
        return text
    start = draw(st.integers(1, len(text) - 1))
    end = draw(st.integers(start + 1, len(text)))
    quote = draw(st.sampled_from(["'", '"']))
    return text[:start] + quote + text[start:end] + quote + text[end:]


#: cmdlet -> (aliases, spellings of the parameter that takes the path, what follows the path)
WRITERS = {
    "Set-Content": ([], ["", "-Path ", "-Pat ", "-LiteralPath ", "-Lit ", "-PSPath ", "-LP ", "-Path:"], " y"),
    "Add-Content": (["ac"], ["", "-Path ", "-Pat ", "-LiteralPath ", "-Lit ", "-PSPath ", "-LP ", "-Path:"], " y"),
    "Clear-Content": (["clc"], ["", "-Path ", "-LiteralPath ", "-PSPath ", "-LP "], ""),
    "Remove-Item": (["rm", "del", "erase", "rd", "ri", "rmdir"],
                    ["", "-Path ", "-Pa ", "-LiteralPath ", "-PSPath ", "-LP "], ""),
    "New-Item": (["ni"], ["", "-Path ", "-Pa "], ""),
}
QUOTES = [("", ""), ("'", "'"), ('"', '"'), ("\u2018", "\u2019"), ("\u201c", "\u201d")]
BLANKS = [" ", "  ", "\t", "\xa0", "\u3000"]
DASHES = ["-", "\u2013", "\u2014", "\u2015"]


@st.composite
def spelled_write(draw):
    """(the path, one spelling of a command that writes it)."""
    cmdlet = draw(st.sampled_from(sorted(WRITERS)))
    aliases, parameters, tail = WRITERS[cmdlet]
    path = draw(literal_path())
    form = draw(st.sampled_from(["name", "alias", "module", "call"]))
    name = draw(recased(draw(st.sampled_from(aliases)) if form == "alias" and aliases else cmdlet))
    name = draw(backticked(name, always_first=draw(st.booleans())))
    if form == "module":
        name = "Microsoft.PowerShell.Management\\" + name
    elif form == "call":
        name = "& " + name
    blank = draw(st.sampled_from(BLANKS))
    parameter = draw(st.sampled_from(parameters))
    if parameter:
        parameter = draw(st.sampled_from(DASHES)) + draw(recased(parameter[1:])).replace(" ", blank)
    opening, closing = draw(st.sampled_from(QUOTES))
    shown = path if opening else draw(backticked(path))
    return path, name + blank + parameter + opening + shown + closing + tail.replace(" ", blank)


LISTED = sorted(ps_gate._FOREIGN_WRITERS | ps_gate._OPAQUE_COMMANDS)


@st.composite
def listed_command(draw):
    name = draw(recased(draw(st.sampled_from(LISTED))))
    if draw(st.booleans()):
        name = draw(quoted_inside(name))
    else:
        name = draw(backticked(name, always_first=draw(st.booleans())))
    suffix = draw(st.sampled_from(["", "", ".exe"]))
    call = draw(st.sampled_from(["", "", "& "]))
    return call + name + suffix + draw(st.sampled_from(["", " x", " a b", " -x a", " x a.zip -osrc"]))


#: One move, spelled as the function and as the Set-Location it stands for.
MOVES = {"up": ("cd..", "cd .."), "root": ("cd\\", "cd \\"), "home": ("cd~", "cd ~")}
STEP = st.one_of(
    st.sampled_from(["up", "up", "root", "home"]).map(lambda kind: (kind, "")),
    st.sampled_from(["docs", "src", "src\\auth", "a b"]).map(lambda name: ("into", name)),
    st.sampled_from(["C:", "c:", "D:", "z:"]).map(lambda drive: ("drive", drive)),
)


def walk(steps, cwd: "str | None" = CWD) -> "str | None":
    """The directory after *steps*; ``None`` once it cannot be known."""
    for kind, value in steps:
        if kind == "home":
            cwd = HOME
        elif kind == "drive":
            cwd = cwd if cwd is not None and cwd[:2].lower() == value.lower() else None
        elif cwd is None:
            continue
        elif kind == "up":
            cwd = ntpath.normpath(cwd + "\\..")
        elif kind == "root":
            cwd = cwd[:2] + "\\"
        else:
            cwd = ntpath.normpath(cwd + "\\" + value)
    return cwd


# ---------------------------------------------------------------- properties
@requires_hypothesis
class TestSpellings(unittest.TestCase):
    @SETTINGS
    @given(spelled_write(), st.sampled_from(CONTEXTS))
    def test_every_spelling_of_one_write_names_its_path(self, write, context) -> None:
        path, spelling = write
        command = context.format(w=spelling)
        self.assertEqual(read(command), ([expected(path)], False), command)


@requires_hypothesis
class TestDenyLists(unittest.TestCase):
    @SETTINGS
    @given(listed_command(), st.sampled_from(CONTEXTS))
    def test_a_listed_name_is_never_read_as_harmless(self, listed, context) -> None:
        command = context.format(w=listed)
        self.assertTrue(read(command)[1], command)


@requires_hypothesis
class TestLocationFunctions(unittest.TestCase):
    @SETTINGS
    @given(st.lists(STEP, min_size=1, max_size=5), st.sampled_from(["; ", "\n", " ;\n"]),
           st.booleans(), literal_path())
    def test_a_location_function_moves_like_set_location(self, steps, sep, upper, path) -> None:
        def spell(index: int) -> str:
            words = []
            for kind, value in steps:
                if kind == "into":
                    words.append("cd '%s'" % value)
                elif kind == "drive":
                    words.append(value)
                else:
                    words.append(MOVES[kind][index].upper() if upper else MOVES[kind][index])
            return sep.join(words + ["Set-Content '%s' y" % path])

        function, cmdlet = spell(0), spell(1)
        self.assertEqual(read(function), read(cmdlet), function)
        cwd = walk(steps)
        absolute = path.replace("/", "\\")[1:3] == ":\\"
        if cwd is not None:
            self.assertEqual(read(function), ([expected(path, cwd.rstrip("\\"))], False), function)
        elif absolute:
            self.assertEqual(read(function), ([expected(path)], False), function)
        else:
            self.assertTrue(read(function)[1], function)


if __name__ == "__main__":
    unittest.main()
