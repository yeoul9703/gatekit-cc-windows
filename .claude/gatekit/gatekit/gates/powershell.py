"""PreToolUse gate for PowerShell — PowerShell writes obey the same rules as Write.

The Bash gate (:mod:`gatekit.gates.bash`) closes the shell bypass of the Write
gate, but only for the Bash tool. This kit runs on Windows with the PowerShell
tool switched on, and a hook registered on the matcher ``Bash`` does not fire
for a PowerShell call (measured, ADR-0021). Without this gate
``Set-Content src/x.ts`` and ``'x' > src/x.ts`` reach the disk unjudged.

This module extracts the files a PowerShell command **would write** and hands
each one to :func:`write.decide_path`. It is a static reading of the command
text — no execution — and it follows these rules:

* When nothing could be denied anyway (no active task scope, spec gate
  approved or absent) the command is allowed without parsing.
* A target that was read is judged by the rules, whatever spelling it came
  in: ``Set-Content x y -e utf8`` writes ``x`` (``-e`` is ``-Exclude``).
* When a restriction is active and the target **cannot be determined**, the
  command is **denied** where a write is certain or arbitrary code runs: a
  variable, a subexpression or a wildcard in the path of a write cmdlet or a
  redirect, a relative write after the location became unknown (``D:``,
  ``cd $dir``), a parameter of a write cmdlet this gate does not know,
  ``Invoke-Expression``, the call operator on a variable or a script block,
  ``Start-Process``, a .NET call such as ``[System.IO.File]::WriteAllText``,
  inline interpreter code such as ``python -c`` or ``pwsh -Command``, a
  working-tree ``git`` subcommand. The reason says how to retry: a literal
  path, or the Write/Edit tool.
* What PowerShell itself takes as plain text is not a write: an argument such
  as ``std::vector`` or ``tests/a.py::T::t``, any parameter of a command this
  gate has no table for.
* Programs invoked by name (``npm run build``, ``python script.py``,
  ``uv run ...``) are outside its reach: it reads PowerShell syntax, not what
  every binary does.

The reading follows PowerShell 7, the shell this kit requires. Where Windows
PowerShell 5.1 differs and would write, the stricter reading is kept (``sc``
with a path is still ``Set-Content``).

Paths are Windows paths: either separator, drive letters, resolved with
``ntpath`` against the event's ``cwd`` and handed to ``write.decide_path`` as
absolute paths. Denial reasons are written in the session's ``output_lang``.
"""
from __future__ import annotations

import ntpath
import re
from typing import Any, Dict, List, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio  # noqa: E402
from gatekit.gates import bash  # noqa: E402

WriteTargets = bash.WriteTargets

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------
#: PowerShell accepts the typographic quotes as quotes, each class closing itself.
_SQ = "'\u2018\u2019\u201a\u201b"
_DQ = '"\u201c\u201d\u201e'

#: Backtick escapes that stand for a control character, not the letter itself.
_SPECIAL_ESCAPES = "0abefnrtuv"

#: A ``$`` followed by one of these starts a variable reference.
_VAR_START = re.compile(r"[A-Za-z0-9_?$^{]")

#: ``@'`` / ``@"`` opens a here-string only when nothing else follows on the line.
_HERE_OPEN = re.compile("@([" + _SQ + _DQ + "])[ \t]*\n")

#: Characters PowerShell reads as a space between tokens: the Unicode space
#: separators too, which an IME types and a pasted document carries.
_BLANK = (" \t\r\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
          "\u2009\u200a\u202f\u205f\u3000")

#: The en dash, em dash and horizontal bar start a parameter like ``-`` does.
_DASHES = "\u2013\u2014\u2015"

#: Separates the items of an unquoted comma list inside one word's value.
_LIST = "\x00"

#: Statements nested deeper than this are not read.
_MAX_DEPTH = 12

_PARAM_RE = re.compile(r"^-[A-Za-z?]")
#: A PowerShell number: hex, binary or decimal with an exponent, then a type
#: suffix (u l ul s us y uy n d) and a multiplier (kb mb gb tb pb). Anything
#: else that starts with a digit is a command name: ``7z``, ``1kbx``, ``2to3``
#: (measured against the parser).
_NUMBER_RE = re.compile(
    r"(?i)[+-]?(?:0x[0-9a-f]+|0b[01]+|(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)"
    r"(?:u?[lsy]|u|n|d)?(?:[kmgtp]b)?")
_ASSIGN_RE = re.compile(r"^(?:\[[^\]]*\])*\$[^=]*?(?:[-+*/%]|\?\?)?=(.*)$")
_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "??="}
_STATIC_RE = re.compile(r"\[([^\[\]]+)\]::(\w+)")
_TYPE_RE = re.compile(r"\[([^\[\]]+)\]")
_METHOD_RE = re.compile(r"\.(\w+)$")
#: ``$doc.`` at the end of a word: the member name is on the next word or line.
_SPLIT_MEMBER_RE = re.compile(r"(?:^|[\w\])}])\.$")
_DRIVE_FUNCTION_RE = re.compile(r"[a-z]:")
_PROVIDER_RE = re.compile(r"(?i)^(?:microsoft\.powershell\.core\\)?filesystem::")
_LONG_DRIVE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]+):")

#: PowerShell drives that are not the file system: writing there is not a
#: project write (the same standing ``/dev/null`` has in the Bash gate).
#: ``Alias:`` and ``Function:`` are left out on purpose: an item written there
#: is a new command name this gate would not recognise, as with ``Set-Alias``.
_NON_FILE_DRIVES = {"env", "variable", "hklm", "hkcu", "cert", "wsman"}

#: Functions PowerShell defines that change the location and take no argument:
#: ``cd..`` is ``Set-Location ..`` (``cd~`` exists in PowerShell 7 only). The
#: drive functions ``A:`` to ``Z:`` are matched by :data:`_DRIVE_FUNCTION_RE`.
_LOCATION_FUNCTIONS = {"cd..": "..", "cd\\": "\\", "cd~": "~"}

#: The verbs of ``sc.exe``. PowerShell 7 has no ``sc`` alias and runs the
#: service control program (measured on 7.6 and 7.7); Windows PowerShell 5.1
#: reads ``sc`` as ``Set-Content``. See :func:`_is_sc_exe`.
_SC_VERBS = {
    "query", "queryex", "start", "pause", "interrogate", "continue", "stop",
    "config", "description", "failure", "failureflag", "sidtype", "privs",
    "managedaccount", "qc", "qdescription", "qfailure", "qfailureflag",
    "qsidtype", "qprivs", "qtriggerinfo", "qpreferrednode", "qmanagedaccount",
    "qprotection", "quserservice", "delete", "create", "control", "sdshow",
    "sdset", "showsid", "triggerinfo", "preferrednode", "getdisplayname",
    "getkeyname", "enumdepend", "boot", "lock", "querylock",
}

#: Aliases of the cmdlets this gate reads.
_ALIASES = {
    "sc": "set-content", "ac": "add-content", "clc": "clear-content",
    "tee": "tee-object", "ni": "new-item", "mkdir": "new-item", "md": "new-item",
    "si": "set-item",
    "cp": "copy-item", "copy": "copy-item", "cpi": "copy-item",
    "mv": "move-item", "move": "move-item", "mi": "move-item",
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item",
    "rd": "remove-item", "ri": "remove-item", "rmdir": "remove-item",
    "ren": "rename-item", "rni": "rename-item", "epcsv": "export-csv",
    "epal": "export-alias",
    "iwr": "invoke-webrequest", "irm": "invoke-restmethod",
    "cd": "set-location", "sl": "set-location", "chdir": "set-location",
    "pushd": "push-location", "popd": "pop-location",
}

#: Commands that run code or start programs this gate cannot see into.
_OPAQUE_COMMANDS = {
    "invoke-expression", "iex", "invoke-command", "icm", "start-process", "saps",
    "start", "start-job", "sajb", "start-threadjob", "invoke-item", "ii",
    "add-type", "set-alias", "sal", "new-alias", "nal", "import-alias", "ipal",
    "new-psdrive", "ndr", "mount", "subst", "start-bitstransfer",
}

#: Programs on a Windows PATH (Git for Windows, System32) that write wherever
#: their own arguments say. The Bash gate reads their argv; this one does not.
_FOREIGN_WRITERS = {
    "awk", "gawk", "patch", "xargs", "dd", "touch", "truncate", "tar", "unzip",
    "zip", "7z", "ln", "install", "rsync", "robocopy", "xcopy", "wsl", "busybox",
    "certutil", "bitsadmin", "ed", "ex", "vi", "vim", "nvim", "nano", "emacs",
}

#: Interpreters and shells that take inline code or read a script from stdin.
_INTERPRETERS = {
    "python", "python3", "py", "pythonw", "node", "ruby", "perl", "php", "deno",
    "bun", "ts-node", "tsx", "bash", "sh", "zsh", "dash", "ksh",
}
_INLINE_FLAGS = set(bash._INLINE_FLAGS) | {"--eval", "-p", "--print"}
_INFO_FLAGS = {"--version", "-V", "-v", "--help", "-h", "-?", "/?"}
_POWERSHELLS = {"pwsh", "powershell"}


#: .NET types whose static members never write a file.
_PURE_TYPES = {
    "math", "int", "int32", "int64", "long", "double", "decimal", "float",
    "single", "bool", "boolean", "char", "byte", "string", "datetime",
    "datetimeoffset", "timespan", "guid", "regex", "text.regularexpressions.regex",
    "convert", "version", "uri", "array", "environment", "io.path", "text.encoding",
    "console", "bitconverter", "enum", "pscustomobject", "psobject", "ordered",
    "text.stringbuilder", "globalization.cultureinfo", "linq.enumerable",
}
#: File-system types: only the members listed in :data:`_IO_READS` are harmless.
_IO_TYPES = {"io.file", "io.directory"}
#: Types whose one-argument constructor opens a file for writing, so that a
#: cast alone truncates it: ``[IO.StreamWriter]'x'`` (measured).
_WRITER_TYPES = {"io.streamwriter"}
_IO_READS = {
    "exists", "readalltext", "readalllines", "readallbytes", "readlines",
    "getfiles", "getdirectories", "getfilesystementries", "enumeratefiles",
    "enumeratedirectories", "getlastwritetime", "getattributes",
    "getcurrentdirectory", "openread",
}
#: Instance methods of strings, collections and dates. Any other ``.Name(``
#: could be ``$doc.Save('x')`` and is not readable from here.
_PURE_METHODS = {
    "tostring", "trim", "trimstart", "trimend", "split", "replace", "substring",
    "toupper", "tolower", "toupperinvariant", "tolowerinvariant", "contains",
    "startswith", "endswith", "indexof", "lastindexof", "padleft", "padright",
    "insert", "remove", "equals", "compareto", "gettype", "gethashcode", "add",
    "addrange", "clear", "containskey", "trygetvalue", "toarray", "tolist",
    "where", "foreach", "join", "format", "match", "matches", "ismatch",
    "adddays", "addhours", "addminutes", "addseconds", "addmonths", "addyears",
    "tochararray", "getenumerator", "sort", "reverse", "append", "appendline",
    "appendformat", "normalize", "touniversaltime", "tolocaltime",
}
#: ``New-Object`` type names that hold data and nothing else.
_PURE_OBJECTS = {
    "psobject", "pscustomobject", "object", "hashtable", "random", "datetime",
    "timespan", "version", "guid", "text.stringbuilder",
}


class _LexError(Exception):
    """The command text could not be split into tokens."""


class _Word:
    """One argument word: its literal value and what is known about it."""

    __slots__ = ("value", "bare", "dynamic", "quoted", "first_bare", "ticked", "nested", "calls")

    def __init__(self, first_bare: bool = True) -> None:
        self.value = ""        # quotes removed, escapes applied; list items split by _LIST
        self.bare = ""         # the unquoted text only (operators and parameters live here)
        self.dynamic = ""      # why the value is not a literal ("" when it is)
        self.quoted = False
        self.first_bare = first_bare
        self.ticked = False    # opens with a backtick escape: a bare word, never a string
        self.nested: List[Tuple[str, bool]] = []   # (text, is_hashtable) to read as statements
        self.calls: List[str] = []                 # instance methods called: .Name(

    def mark(self, why: str) -> None:
        if not self.dynamic:
            self.dynamic = why


class _Mark:
    """A token that is not a word."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


_SEP = _Mark("sep")            # ; newline | || && and a trailing &
_CALL = _Mark("call")          # & at the start of a command
_REDIRECT = _Mark("redirect")  # > >> N> N>> *> *>>


# --------------------------------------------------------------------------
# lexing
# --------------------------------------------------------------------------
def _single(text: str, i: int) -> Tuple[int, str]:
    """Read a single-quoted string opening at *i*: (index after it, literal)."""
    out: List[str] = []
    j, n = i + 1, len(text)
    while j < n:
        ch = text[j]
        if ch in _SQ:
            if j + 1 < n and text[j + 1] in _SQ:
                out.append("'")
                j += 2
                continue
            return j + 1, "".join(out)
        out.append(ch)
        j += 1
    raise _LexError("unbalanced quotes")


def _expand(body: str, word: _Word) -> None:
    """Note the variables and subexpressions of an expandable here-string body."""
    j, n = 0, len(body)
    while j < n:
        ch = body[j]
        if ch == "`":
            j += 2
            continue
        if ch == "$" and j + 1 < n:
            if body[j + 1] == "(":
                end = _balanced(body, j + 1)
                word.nested.append((body[j + 2:end], False))
                word.mark("subexpression")
                j = end + 1
                continue
            if _VAR_START.match(body[j + 1]):
                word.mark("variable")
        j += 1


def _double(text: str, i: int, word: _Word) -> int:
    """Read a double-quoted string opening at *i* into *word*; index after it."""
    out: List[str] = []
    j, n = i + 1, len(text)
    while j < n:
        ch = text[j]
        if ch == "`" and j + 1 < n:
            if text[j + 1] in _SPECIAL_ESCAPES:
                word.mark("escape sequence")
            out.append(text[j + 1])
            j += 2
            continue
        if ch in _DQ:
            if j + 1 < n and text[j + 1] in _DQ:
                out.append('"')
                j += 2
                continue
            word.value += "".join(out)
            return j + 1
        if ch == "$" and j + 1 < n:
            if text[j + 1] == "(":
                end = _balanced(text, j + 1)
                word.nested.append((text[j + 2:end], False))
                word.mark("subexpression")
                j = end + 1
                continue
            if _VAR_START.match(text[j + 1]):
                word.mark("variable")
        out.append(ch)
        j += 1
    raise _LexError("unbalanced quotes")


def _here(text: str, i: int, word: _Word) -> int:
    """Read a here-string opening at *i* into *word*; index after its closer.

    The body is data: it becomes the word's value and is never read as
    commands, except for the ``$(...)`` of an expandable here-string.
    """
    match = _HERE_OPEN.match(text, i)
    if match is None:  # pragma: no cover - callers check first
        raise _LexError("unbalanced quotes")
    single = match.group(1) in _SQ
    closers = _SQ if single else _DQ
    start = match.end()
    pos = start - 1
    while True:
        newline = text.find("\n", pos)
        if newline < 0:
            raise _LexError("unterminated here-string")
        closer = text[newline + 1:newline + 3]
        if len(closer) == 2 and closer[0] in closers and closer[1] == "@":
            body = text[start:newline] if newline >= start else ""
            word.value += body
            if not single:
                _expand(body, word)
            return newline + 3
        pos = newline + 1


def _balanced(text: str, i: int) -> int:
    """Index of the bracket closing the ``(`` or ``{`` at *i*."""
    stack = [")" if text[i] == "(" else "}"]
    scratch = _Word()
    j, n = i + 1, len(text)
    while j < n:
        ch = text[j]
        if ch == "`":
            j += 2
            continue
        if ch in _SQ:
            j = _single(text, j)[0]
            continue
        if ch in _DQ:
            j = _double(text, j, scratch)
            continue
        if ch == "@" and _HERE_OPEN.match(text, j):
            j = _here(text, j, scratch)
            continue
        if ch == "<" and text.startswith("<#", j):
            end = text.find("#>", j + 2)
            if end < 0:
                raise _LexError("unterminated comment")
            j = end + 2
            continue
        if ch == "#" and text[j - 1] in " \t\n;({|":
            end = text.find("\n", j)
            j = n if end < 0 else end
            continue
        if ch in "({":
            stack.append(")" if ch == "(" else "}")
        elif ch in ")}":
            if stack[-1] != ch:
                raise _LexError("unbalanced brackets")
            stack.pop()
            if not stack:
                return j
        j += 1
    raise _LexError("unbalanced brackets")


class _Lexer:
    """Split PowerShell text into words, separators, call and redirect marks."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens: List[Any] = []
        self.word: Optional[_Word] = None

    def flush(self) -> None:
        if self.word is not None:
            self.tokens.append(self.word)
            self.word = None

    def cur(self, bare: bool = True) -> _Word:
        if self.word is None:
            self.word = _Word(first_bare=bare)
        return self.word

    def group(self, opener: int, why: str, shown: str, hashtable: bool = False) -> int:
        """Take the bracketed group whose bracket sits at *opener* as one dynamic part."""
        end = _balanced(self.text, opener)
        word = self.cur()
        word.nested.append((self.text[opener + 1:end], hashtable))
        word.mark(why)
        word.bare += shown
        return end + 1

    def call_or_background(self, i: int) -> None:
        """A lone ``&``: the call operator when a command follows, else a job."""
        rest = self.text[i + 1:].lstrip(_BLANK)
        if rest and rest[0] not in "\n;)}|":
            self.tokens.append(_CALL)
        else:
            self.tokens.append(_SEP)

    def redirect(self, i: int) -> int:
        """Read a redirection operator at *i*; index after it."""
        text = self.text
        word = self.word
        if (word is not None and not word.quoted and word.value == word.bare
                and word.bare in ("1", "2", "3", "4", "5", "6", "*")):
            self.word = None  # the stream number belongs to the operator
        else:
            self.flush()
        i += 1
        if text[i:i + 1] == ">":
            i += 1
        if text[i:i + 1] == "&" and text[i + 1:i + 2].isdigit():
            return i + 2  # 2>&1 merges streams; nothing is written
        self.tokens.append(_REDIRECT)
        return i

    def run(self) -> List[Any]:
        text, n = self.text, len(self.text)
        i = 0
        while i < n:
            ch = text[i]
            nxt = text[i + 1] if i + 1 < n else ""
            if ch in _BLANK:
                self.flush()
                i += 1
            elif ch != "\n" and ch.isspace():
                # A vertical tab, NEL or line separator: a space or a new
                # statement, depending on who reads it.
                raise _LexError("unusual whitespace")
            elif ch == "\n":
                self.flush()
                self.tokens.append(_SEP)
                i += 1
            elif ch == "`":
                if nxt == "\n":
                    self.flush()  # line continuation
                elif nxt:
                    if self.word is None:
                        # `Set-Content is the command Set-Content (measured):
                        # the escaped character is never syntax, so the word
                        # is not a parameter, and it is not a string either.
                        self.cur(False).ticked = True
                    word = self.cur()
                    if nxt in _SPECIAL_ESCAPES:
                        word.mark("escape sequence")
                    word.value += nxt
                i += 2
            elif ch == "#" and self.word is None:
                end = text.find("\n", i)
                i = n if end < 0 else end
            elif ch == "<" and nxt == "#":
                end = text.find("#>", i + 2)
                if end < 0:
                    raise _LexError("unterminated comment")
                i = end + 2
            elif ch in _SQ:
                word = self.cur(False)
                i, literal = _single(text, i)
                word.value += literal
                word.quoted = True
            elif ch in _DQ:
                word = self.cur(False)
                i = _double(text, i, word)
                word.quoted = True
            elif ch == "@" and _HERE_OPEN.match(text, i):
                word = self.cur(False)
                i = _here(text, i, word)
                word.quoted = True
            elif ch == "@" and nxt == "(":
                i = self.group(i + 1, "expression", "@()")
            elif ch == "@" and nxt == "{":
                i = self.group(i + 1, "expression", "@{}", hashtable=True)
            elif ch == "$" and nxt == "(":
                i = self.group(i + 1, "subexpression", "$()")
            elif ch == "$" and nxt == "{":
                end = text.find("}", i)
                if end < 0:
                    raise _LexError("unbalanced brackets")
                word = self.cur()
                word.mark("variable")
                word.bare += text[i:end + 1]
                word.value += text[i:end + 1]
                i = end + 1
            elif ch == "(":
                if self.word is not None:
                    method = _METHOD_RE.search(self.word.bare)
                    if method:  # $x.Name( ... ): an instance method call
                        self.word.calls.append(method.group(1).lower())
                    elif not self.word.bare.endswith(("]", ")")) and "::" not in self.word.bare:
                        self.flush()  # if(...) / foo(...): the group is its own word
                i = self.group(i, "expression", "()")
            elif ch == "{":
                self.flush()  # try{...} / catch{...}: a block always starts a word
                i = self.group(i, "script block", "{}")
            elif ch in ")}":
                raise _LexError("unbalanced brackets")
            elif ch == ";":
                self.flush()
                self.tokens.append(_SEP)
                i += 1
            elif ch == "|":
                self.flush()
                self.tokens.append(_SEP)
                i += 2 if nxt == "|" else 1
            elif ch == "&" and nxt == "&":
                self.flush()
                self.tokens.append(_SEP)
                i += 2
            elif ch == "&":
                self.flush()
                self.call_or_background(i)
                i += 1
            elif ch == ">":
                i = self.redirect(i)
            elif ch == "<":
                self.flush()  # PowerShell has no input redirection
                i += 1
            elif ch == ",":
                word = self.cur()
                word.value += _LIST
                word.bare += ","
                i += 1
                while i < n and (text[i] in _BLANK or text[i] == "\n"):
                    i += 1
            else:
                if self.word is None and ch in _DASHES:
                    ch = "-"
                word = self.cur()
                if ch == "$" and nxt and _VAR_START.match(nxt):
                    word.mark("variable")
                elif ch == "@" and not word.value and not word.quoted and (nxt.isalpha() or nxt == "_"):
                    word.mark("splat")
                word.value += ch
                word.bare += ch
                i += 1
        self.flush()
        return _merge_lists(self.tokens)


def _merge_lists(tokens: List[Any]) -> List[Any]:
    """Join ``a , b`` (a comma after a space) back into one list word.

    The word before must be an argument: ``Remove-Item ,a`` is a command and a
    one-item list, never one word.
    """
    out: List[Any] = []
    for token in tokens:
        if (isinstance(token, _Word) and token.value.startswith(_LIST)
                and len(out) >= 2 and isinstance(out[-1], _Word)
                and isinstance(out[-2], _Word)):
            prev = out[-1]
            prev.value += token.value
            prev.bare += token.bare
            prev.quoted = prev.quoted or token.quoted
            prev.nested.extend(token.nested)
            prev.calls.extend(token.calls)
            if token.dynamic:
                prev.mark(token.dynamic)
            continue
        out.append(token)
    return out


# --------------------------------------------------------------------------
# path resolution
# --------------------------------------------------------------------------
_SKIP = ""  # resolved, and not a project write (a device or a non-file drive)


def _resolve(target: str, cwd: Optional[str]) -> Optional[str]:
    """Resolve *target* to an absolute Windows path.

    Returns :data:`_SKIP` for a target that is not a file (``NUL``, ``Env:``)
    and ``None`` when the path cannot be known.
    """
    text = _PROVIDER_RE.sub("", target).replace("/", "\\")
    if not text.strip():
        return None
    if text.startswith("\\\\.\\") or text.startswith("\\\\?\\"):
        return _SKIP if text[4:].lower() == "nul" else None
    long_drive = _LONG_DRIVE_RE.match(text)
    if long_drive:
        return _SKIP if long_drive.group(1).lower() in _NON_FILE_DRIVES else None
    if text == "~" or text.startswith("~\\"):
        text = ntpath.expanduser(text)
        if text.startswith("~"):
            return None
    drive, tail = ntpath.splitdrive(text)
    if drive:
        if not tail.startswith("\\"):
            return None  # C:foo is relative to that drive's own current directory
    elif tail.startswith("\\"):
        base_drive = ntpath.splitdrive(cwd)[0] if cwd else ""
        if not base_drive:
            return None
        text = base_drive + tail
    else:
        if cwd is None:
            return None
        text = ntpath.join(cwd, text)
    drive, tail = ntpath.splitdrive(ntpath.normpath(text))
    if ":" in tail:
        return None  # an alternate data stream, or a path this gate cannot read
    # Windows drops trailing dots and spaces of a name: "x.ts." is "x.ts".
    parts = [part.rstrip(" .") or part for part in tail.split("\\")]
    if parts and ntpath.splitext(parts[-1])[0].lower() == "nul":
        return _SKIP
    if len(drive) == 2:
        drive = drive.upper()
    return drive + "\\".join(parts)


def _normal_cwd(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    return ntpath.normpath(cwd.replace("/", "\\"))


def _add(result: WriteTargets, raw: str, cwd: Optional[str], literal: bool, what: str) -> None:
    if not literal and any(ch in raw for ch in "*?[]"):
        result.mark_opaque("wildcard in %s" % what)
        return
    resolved = _resolve(raw, cwd)
    if resolved is None:
        result.mark_opaque("cannot resolve %s" % what)
        return
    if resolved != _SKIP and resolved not in result.targets:
        result.targets.append(resolved)


def _values(word: _Word) -> Optional[List[str]]:
    """The literal values of *word* (several for a comma list); ``None`` if dynamic."""
    if word.dynamic:
        return None
    return [item for item in word.value.split(_LIST) if item]


def _is_null(word: _Word) -> bool:
    return not word.quoted and word.bare.lower() in ("$null", "${null}")


# --------------------------------------------------------------------------
# cmdlet parameter tables
# --------------------------------------------------------------------------
class _Spec:
    """The parameters of one cmdlet.

    Written as ``name|alias:K@n=slot`` items. ``K`` is the kind: ``P`` a path
    this cmdlet writes (wildcards are expanded), ``L`` the same taken
    literally, ``N`` a name joined to the path, ``R`` a path it only reads,
    ``V`` any other value, ``X`` a filter that narrows the paths (it never
    adds one, so the paths themselves are what is judged); no kind means a
    switch. A ``*`` after the kind marks a dynamic parameter, one the
    FileSystem provider adds. ``@n`` is the positional order and ``=slot``
    names the parameter whose positional slot this one fills
    (``-LiteralPath`` fills ``-Path``'s).
    """

    __slots__ = ("kinds", "slots", "aliases", "positional", "common", "dynamic")

    def __init__(self, text: str) -> None:
        self.kinds: Dict[str, str] = {}
        self.slots: Dict[str, str] = {}
        self.aliases: Dict[str, str] = {}
        self.common = set()
        self.dynamic = set()
        order: List[Tuple[int, str]] = []
        for source, is_common in ((text, False), (_COMMON, True)):
            for item in source.split():
                names, _, rest = item.partition(":")
                canonical, *aliases = names.split("|")
                match = re.fullmatch(r"([A-Z])?(\*)?(?:@(\d))?(?:=(\w+))?", rest)
                if match is None:  # pragma: no cover - a typo in a table below
                    raise ValueError("bad parameter spec: %s" % item)
                self.kinds.setdefault(canonical, match.group(1) or "S")
                self.slots.setdefault(canonical, match.group(4) or canonical)
                for alias in aliases:
                    self.aliases.setdefault(alias, canonical)
                if match.group(2):
                    self.dynamic.add(canonical)
                if is_common:
                    self.common.add(canonical)
                elif match.group(3):
                    order.append((int(match.group(3)), canonical))
        self.positional = [name for _, name in sorted(order)]

    def find(self, given: str) -> Optional[str]:
        """The parameter *given* names, by PowerShell's own rule (measured).

        An exact name or alias wins. Otherwise every name and alias that
        starts with *given* is a candidate. Static parameters are bound before
        dynamic ones (``Set-Content -e`` is ``-Exclude``, ``-en`` is
        ``-Encoding``); several candidates are narrowed to the cmdlet's own
        parameters (``-V`` is ``-Value``, not ``-Verbose``), and anything but
        exactly one is ambiguous: ``None``.
        """
        key = given.lower()
        if key in self.kinds:
            return key
        if key in self.aliases:
            return self.aliases[key]
        found = {name for name in self.kinds if name.startswith(key)}
        found |= {name for alias, name in self.aliases.items() if alias.startswith(key)}
        found = (found - self.dynamic) or found
        if len(found) > 1:
            found = {name for name in found if name not in self.common}
        return found.pop() if len(found) == 1 else None


#: Common parameters every cmdlet accepts.
_COMMON = (
    "verbose|vb debug|db whatif|wi confirm|cf erroraction|ea:V warningaction|wa:V "
    "informationaction|infa:V progressaction|proga:V errorvariable|ev:V "
    "warningvariable|wv:V informationvariable|iv:V outvariable|ov:V outbuffer|ob:V "
    "pipelinevariable|pv:V"
)

_LITERAL = "literalpath|pspath|lp:L=path"
_CONTENT = ("path:P@0 " + _LITERAL + " value:V@1 passthru filter:X include:X exclude:X "
            "force credential:V nonewline:* encoding:V* asbytestream:* stream:V*")
_FILE_OUT = "filepath|path:P@0 literalpath|pspath|lp:L=filepath"
_LOCATION = "path:P@0 " + _LITERAL + " passthru stackname:V"

_CMDLETS = {name: _Spec(text) for name, text in {
    "set-content": _CONTENT,
    "add-content": _CONTENT,
    "clear-content": "path:P@0 " + _LITERAL + " filter:X include:X exclude:X force "
                     "credential:V stream:V*",
    "out-file": _FILE_OUT + " encoding:V@1 append force noclobber|nooverwrite width:V "
                "nonewline inputobject:V",
    "tee-object": _FILE_OUT + " append encoding:V inputobject:V variable:V",
    "new-item": "path:P@0 name:N itemtype|type:V value|target:V force credential:V",
    "set-item": "path:P@0 " + _LITERAL + " value:V@1 force passthru filter:X include:X "
                "exclude:X credential:V",
    "copy-item": "path:R@0 literalpath|pspath|lp:R=path destination:P@1 container force "
                 "filter:V include:V exclude:V recurse passthru credential:V "
                 "fromsession:V* tosession:V*",
    "move-item": "path:P@0 " + _LITERAL + " destination:P@1 force filter:X include:X "
                 "exclude:X passthru credential:V",
    "remove-item": "path:P@0 " + _LITERAL + " filter:X include:X exclude:X recurse force "
                   "credential:V stream:V*",
    "rename-item": "path:P@0 " + _LITERAL + " newname:N@1 force passthru credential:V",
    "export-csv": "path:P@0 " + _LITERAL + " delimiter:V@1 inputobject:V force "
                  "noclobber|nooverwrite encoding:V append useculture "
                  "includetypeinformation|iti notypeinformation|nti quotefields|qf:V "
                  "usequotes|uq:V noheader",
    "export-clixml": "path:P@0 " + _LITERAL + " inputobject:V depth:V force "
                     "noclobber|nooverwrite encoding:V",
    "start-transcript": "path:P@0 " + _LITERAL + " outputdirectory:P append force "
                        "noclobber|nooverwrite includeinvocationheader useminimalheader",
    "compress-archive": "path:R@0 literalpath|pspath|lp:R=path destinationpath:P@1 "
                        "compressionlevel:V update force passthru",
    "expand-archive": "path:R@0 literalpath|pspath|lp:R=path destinationpath:P@1 force "
                      "passthru",
    "set-location": _LOCATION,
    "push-location": _LOCATION,
}.items()}


def _parameter(word: _Word) -> Optional[Tuple[str, Optional[_Word]]]:
    """Split a ``-Name`` or ``-Name:value`` word; ``None`` when it is an argument."""
    if not word.first_bare or not _PARAM_RE.match(word.bare):
        return None
    colon = word.bare.find(":")
    if colon < 0:
        return word.bare[1:], None
    inline = _Word(first_bare=False)
    inline.value = word.value[colon + 1:]
    inline.dynamic = word.dynamic
    inline.quoted = word.quoted
    return word.bare[1:colon], (inline if inline.value or inline.dynamic else None)


def _bind(spec: _Spec, name: str, args: List[_Word], result: WriteTargets) -> Optional[Dict[str, List[_Word]]]:
    """Bind *args* to the parameters of *spec* the way PowerShell would.

    Returns ``None`` (and marks the command opaque) when the binding cannot be
    known: a splatted argument, an unknown or ambiguous parameter — it may or
    may not consume the next word — or more positional words than slots.
    """
    if any(arg.dynamic == "splat" for arg in args):
        result.mark_opaque("splatted arguments to %s" % name)
        return None
    bound: Dict[str, List[_Word]] = {}
    positional: List[_Word] = []
    index, literal_rest = 0, False
    while index < len(args):
        arg = args[index]
        index += 1
        if not literal_rest and arg.first_bare and arg.bare == "--" and arg.value == "--":
            literal_rest = True
            continue
        parameter = None if literal_rest else _parameter(arg)
        if parameter is None:
            positional.append(arg)
            continue
        given, inline = parameter
        canonical = spec.find(given)
        if canonical is None:
            result.mark_opaque("parameter -%s of %s" % (given, name))
            return None
        if spec.kinds[canonical] == "S":
            continue
        if inline is not None:
            bound.setdefault(canonical, []).append(inline)
        elif index < len(args):
            bound.setdefault(canonical, []).append(args[index])
            index += 1
    filled = {spec.slots[canonical] for canonical in bound}
    for canonical in spec.positional:
        if not positional:
            break
        if spec.slots[canonical] in filled:
            continue
        bound[canonical] = [positional.pop(0)]
        filled.add(spec.slots[canonical])
    if positional:
        result.mark_opaque("extra argument to %s" % name)
        return None
    return bound


def _loose_value(args: List[_Word], names: Tuple[str, ...], minimum: int) -> List[_Word]:
    """Values of the parameters in *names*, for cmdlets with no table here."""
    found: List[_Word] = []
    for index, arg in enumerate(args):
        parameter = _parameter(arg)
        if parameter is None:
            continue
        given, inline = parameter
        key = given.lower()
        if len(key) < minimum or not any(name.startswith(key) for name in names):
            continue
        if inline is not None:
            found.append(inline)
        elif index + 1 < len(args):
            found.append(args[index + 1])
    return found


# --------------------------------------------------------------------------
# one command
# --------------------------------------------------------------------------
def _cmdlet(name: str, args: List[_Word], result: WriteTargets, cwd: Optional[str]) -> None:
    """Record what one of the table cmdlets writes."""
    spec = _CMDLETS[name]
    bound = _bind(spec, name, args, result)
    if bound is None:
        return

    readable = True
    targets: List[Tuple[str, bool]] = []
    names: List[str] = []
    for canonical, words in bound.items():
        kind = spec.kinds[canonical]
        if kind not in "PLN":
            continue
        for word in words:
            values = _values(word)
            if values is None:
                result.mark_opaque("%s in %s target" % (word.dynamic, name))
                readable = False
            elif kind == "N":
                names.extend(values)
            else:
                targets.extend((value, kind == "L") for value in values)
    if not readable:
        return

    if name == "new-item" and names:
        targets = [(ntpath.join(path, item), literal)
                   for path, literal in targets or [(".", True)] for item in names]
    elif name == "rename-item":
        if not names:
            targets = []
        targets = targets + [(ntpath.join(ntpath.dirname(path), names[0]), literal)
                             for path, literal in targets]
    elif name in ("copy-item", "expand-archive") and not targets:
        targets = [(".", True)]  # no destination: the current directory
    elif name == "tee-object" and not targets and "variable" in bound:
        return

    if not targets:
        # The path comes down the pipeline, or the cmdlet picks its own.
        result.mark_opaque("%s target is not on the command line" % name)
        return
    for raw, literal in targets:
        _add(result, raw, cwd, literal, "%s target" % name)


def _location(name: str, args: List[_Word], cwd: Optional[str]) -> Optional[str]:
    """The directory after ``Set-Location``/``Push-Location``; ``None`` = unknown."""
    scratch = WriteTargets()
    bound = _bind(_CMDLETS[name], name, args, scratch)
    if bound is None or len(bound.get("path", []) + bound.get("literalpath", [])) != 1:
        return None
    word = (bound.get("path") or bound.get("literalpath") or [None])[0]
    values = _values(word) if word is not None else None
    if not values or len(values) != 1:
        return None
    if values[0] in ("-", "+") or ("path" in bound and any(ch in values[0] for ch in "*?[]")):
        return None  # location history, or a wildcard
    return _resolve(values[0], cwd) or None


def _type_name(text: str) -> str:
    name = text.lower().replace(" ", "")
    return name[len("system."):] if name.startswith("system.") else name


def _check_dotnet(word: _Word, result: WriteTargets) -> None:
    """Deny a .NET call unless the type or method is known not to write."""
    bare = word.bare
    statics = list(_STATIC_RE.finditer(bare))
    if bare.count("::") != len(statics):
        # A bare word is text to PowerShell: rg std::vector, pytest a.py::T::t
        # (measured). A member access has a variable, an expression, a string
        # or a type literal before the ::, or its member on the next word.
        if word.dynamic or word.quoted or "]::" in bare or bare.endswith("::"):
            result.mark_opaque(".NET call")
    if (word.dynamic or word.quoted) and _SPLIT_MEMBER_RE.search(bare):
        # $doc.<newline>Save('x') is one call (measured): the name comes next.
        result.mark_opaque(".NET member access split across words")
    for match in _TYPE_RE.finditer(bare):
        if _type_name(match.group(1)) in _WRITER_TYPES:
            result.mark_opaque(".NET type [%s]" % match.group(1))
    for match in statics:
        type_name = _type_name(match.group(1))
        member = match.group(2).lower()
        if type_name in _IO_TYPES:
            harmless = member in _IO_READS
        else:
            harmless = type_name in _PURE_TYPES
        if not harmless:
            result.mark_opaque(".NET call [%s]::%s" % (match.group(1), match.group(2)))
    for method in word.calls:
        if method not in _PURE_METHODS:
            result.mark_opaque(".NET method call .%s()" % method)


def _command_name(value: str) -> str:
    base = ntpath.basename(value.replace("/", "\\")).lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def _is_expression(word: _Word) -> bool:
    """True when a statement starting with *word* is an expression, not a command."""
    if word.ticked:
        return False  # `Set-Content: an escaped first character still names a command
    if not word.first_bare:
        return True  # starts with a quote: a string, PowerShell prints it
    if word.bare and word.bare[0] in "$(@[{!+,-":
        return True
    # A number only when the whole word is one: 7z, 7'z' and 7`z are commands.
    return word.bare == word.value and bool(_NUMBER_RE.fullmatch(word.bare))


def _is_sc_exe(raw: str, args: List[_Word]) -> bool:
    """True when ``sc`` is the service control program, not ``Set-Content``.

    PowerShell 7 has no ``sc`` alias: the name always runs ``sc.exe``. Windows
    PowerShell 5.1 still has it, so ``sc`` followed by anything but one of
    ``sc.exe``'s own verbs keeps being read as ``Set-Content``. In PowerShell
    7 such a line only prints usage, so nothing ordinary is refused by that.
    """
    if raw.lower() != "sc":
        return True  # sc.exe, or a path to it: never an alias
    if not args:
        return True
    first = args[0]  # a verb, or \\server before the verb
    return not first.dynamic and (
        first.value.lower() in _SC_VERBS or bool(re.fullmatch(r"\\\\[^\\/]+", first.value)))


def _location_function(raw: str, cwd: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Read ``cd..``, ``cd\\``, ``cd~`` and ``D:``: (is one, the cwd after it)."""
    name = raw.lower()
    if name in _LOCATION_FUNCTIONS:
        return True, (_resolve(_LOCATION_FUNCTIONS[name], cwd) or None)
    if _DRIVE_FUNCTION_RE.fullmatch(name):
        # Another drive's location is whatever the session left there: unknown.
        return True, (cwd if cwd is not None and cwd[:2].lower() == name else None)
    return False, cwd


def _interpreter(name: str, args: List[_Word], result: WriteTargets) -> None:
    values = [arg.value for arg in args]
    if name in _POWERSHELLS:
        lowered = [value.lower() for value in values]
        if any(re.fullmatch(r"-f(i(l(e)?)?)?", value) for value in lowered):
            return  # a script file: a program invoked by name
        if lowered and all(value in ("-version", "-v", "-help", "-h", "-?", "/?") for value in lowered):
            return
        result.mark_opaque("inline %s code" % name)
        return
    if name == "cmd":
        if values != ["/?"]:
            result.mark_opaque("cmd command line")
        return
    if any(value in _INLINE_FLAGS for value in values):
        result.mark_opaque("inline %s code" % name)
    elif (not any(not value.startswith("-") for value in values)
          and not any(value in _INFO_FLAGS for value in values)):
        result.mark_opaque("%s code on stdin" % name)


def _git(args: List[_Word], result: WriteTargets) -> None:
    # Global options are skipped by the Bash gate's reader (one rule for both).
    at = bash.git_subcommand_index([arg.value for arg in args])
    if at is None:
        return
    arg = args[at]
    if arg.dynamic:
        result.mark_opaque("git subcommand is not literal")
    elif arg.value in bash._GIT_OPAQUE:
        result.mark_opaque("git %s" % arg.value)


def _curl(args: List[_Word], result: WriteTargets, cwd: Optional[str]) -> None:
    for index, arg in enumerate(args):
        value = arg.value
        target: Optional[_Word] = None
        if value in ("-O", "--remote-name", "-J", "--remote-header-name"):
            result.mark_opaque("curl remote file name")
        elif value in ("-o", "--output") and index + 1 < len(args):
            target = args[index + 1]
        elif value.startswith("--output=") or (value.startswith("-o") and len(value) > 2):
            target = _Word()
            target.value = value.split("=", 1)[1] if value.startswith("--") else value[2:]
            target.dynamic = arg.dynamic
        if target is not None:
            values = _values(target)
            if values is None:
                result.mark_opaque("%s in curl output" % target.dynamic)
            else:
                for item in values:
                    _add(result, item, cwd, True, "curl output")


def _dispatch(name: str, args: List[_Word], result: WriteTargets, cwd: Optional[str]) -> Optional[str]:
    """Inspect one command by name. Returns the new cwd (``None`` = unknown)."""
    name = _ALIASES.get(name, name)

    if name in ("set-location", "push-location"):
        return _location(name, args, cwd)
    if name == "pop-location":
        return None
    if name in _CMDLETS:
        _cmdlet(name, args, result, cwd)
        return cwd
    if name in _OPAQUE_COMMANDS or name in _FOREIGN_WRITERS:
        result.mark_opaque(name)
        return cwd
    if name in _INTERPRETERS or name in _POWERSHELLS or name == "cmd" or re.match(r"^python\d", name):
        if name == "perl" and any(re.match(r"^-[a-zA-Z]*[ieE]", arg.value) for arg in args):
            result.mark_opaque("inline perl code")
        _interpreter(name, args, result)
        return cwd
    if name == "sed":
        if any(re.match(r"^-[a-zA-Z]*i|^--in-place", arg.value) for arg in args):
            result.mark_opaque("sed -i")
        return cwd
    if name == "git":
        _git(args, result)
        return cwd
    if name == "curl":
        _curl(args, result, cwd)
        return cwd
    if name == "wget":
        if not any(arg.value == "--spider" for arg in args):
            result.mark_opaque("wget output file")
        return cwd
    if name in ("invoke-webrequest", "invoke-restmethod"):
        for word in _loose_value(args, ("outfile",), 1):
            values = _values(word)
            if values is None:
                result.mark_opaque("%s in %s -OutFile" % (word.dynamic, name))
            else:
                for value in values:
                    _add(result, value, cwd, True, "%s -OutFile" % name)
        return cwd
    if name.startswith("export-") and name != "export-modulemember":
        words = _loose_value(args, ("path", "literalpath", "filepath", "outputpath"), 1)
        if not words:
            result.mark_opaque("%s target is not on the command line" % name)
        for word in words:
            values = _values(word)
            if values is None:
                result.mark_opaque("%s in %s target" % (word.dynamic, name))
            else:
                for value in values:
                    _add(result, value, cwd, False, "%s target" % name)
        return cwd
    if name == "new-object":
        named = _loose_value(args, ("typename",), 1)
        plain = [arg for arg in args if _parameter(arg) is None]
        word = named[0] if named else (plain[0] if plain else None)
        type_name = "" if word is None or word.dynamic else word.value.lower()
        if type_name.startswith("system."):
            type_name = type_name[len("system."):]
        if type_name not in _PURE_OBJECTS and not type_name.startswith("collections."):
            result.mark_opaque("New-Object %s" % (word.value if word is not None else ""))
        return cwd
    return cwd  # a program invoked by name: outside this gate's reach


def _command(words: List[Any], result: WriteTargets, cwd: Optional[str], lhs: bool = False) -> Optional[str]:
    """Inspect one command or expression. Returns the new cwd (``None`` = unknown)."""
    call = bool(words) and words[0] is _CALL
    body = words[1:] if call else words
    if not body:
        return cwd
    first = body[0]
    if not isinstance(first, _Word):
        result.mark_opaque("call operator")
        return cwd
    rest: List[_Word] = [word for word in body[1:] if isinstance(word, _Word)]
    stray = len(rest) != len(body) - 1  # an & that does not start a command

    if call:
        if first.dynamic:
            result.mark_opaque("call operator on a %s" % first.dynamic)
            return cwd
    elif first.first_bare and not first.quoted and first.value == ".":
        if rest and rest[0].dynamic:
            result.mark_opaque("dot-sourcing a %s" % rest[0].dynamic)
        return cwd
    elif lhs or _is_expression(first):
        # An assignment runs the command on its right-hand side.
        match = None if first.quoted else _ASSIGN_RE.match(first.bare)
        if lhs and match is None and "=" in first.bare and not first.quoted:
            match = re.match(r"^[^=]*=(.*)$", first.bare)
        if match is not None:
            head: List[Any] = []
            if match.group(1):
                head = [_Word()]
                head[0].value = head[0].bare = match.group(1)
            return _command(head + body[1:], result, cwd)
        if rest and body[1] is rest[0] and not rest[0].quoted and rest[0].bare in _ASSIGN_OPS:
            return _command(body[2:], result, cwd)
        if stray:
            result.mark_opaque("call operator")
        return cwd
    elif first.dynamic:
        result.mark_opaque("command name is not literal")
        return cwd

    if stray:
        result.mark_opaque("call operator")
    moves, after = _location_function(first.value, cwd)
    if moves:
        return after
    name = _command_name(first.value)
    if name == "sc" and _is_sc_exe(first.value, rest):
        return cwd  # a program invoked by name
    return _dispatch(name, rest, result, cwd)


def _statement(items: List[Any], result: WriteTargets, cwd: Optional[str], depth: int, lhs: bool) -> Optional[str]:
    """Inspect one statement: its redirections, nested blocks, then the command."""
    words: List[Any] = []
    redirects: List[_Word] = []
    index = 0
    while index < len(items):
        item = items[index]
        index += 1
        if item is _REDIRECT:
            if index < len(items) and isinstance(items[index], _Word):
                redirects.append(items[index])
                index += 1
            continue
        words.append(item)

    # Groups, subexpressions and script blocks are statements of their own.
    inner = cwd
    for word in [w for w in words if isinstance(w, _Word)] + redirects:
        for text, hashtable in word.nested:
            inner = _run(text, result, inner, depth + 1, hashtable)
        _check_dotnet(word, result)

    for target in redirects:
        if _is_null(target):
            continue
        values = _values(target)
        if values is None:
            result.mark_opaque("%s in redirect target" % target.dynamic)
            continue
        for value in values:
            _add(result, value, cwd, False, "redirect target")

    after = _command(words, result, cwd, lhs)
    return after if inner == cwd else None  # a cd inside a block: cwd unknown


def _run(text: str, result: WriteTargets, cwd: Optional[str], depth: int, hashtable: bool = False) -> Optional[str]:
    """Read *text* as a sequence of statements. Returns the cwd after it."""
    if depth > _MAX_DEPTH:
        result.mark_opaque("nesting too deep")
        return cwd
    statement: List[Any] = []
    for token in _Lexer(text).run() + [_SEP]:
        if token is _SEP:
            if statement:
                cwd = _statement(statement, result, cwd, depth, hashtable)
                statement = []
            continue
        statement.append(token)
    return cwd


def extract_write_targets(command: str, cwd: Optional[str]) -> WriteTargets:
    """Statically list the paths *command* would write, resolved against *cwd*.

    Targets are absolute Windows paths. ``cwd`` may be ``None`` when the
    working directory is itself unknown, in which case every relative target
    makes the result opaque.
    """
    result = WriteTargets()
    text = command.replace("\r\n", "\n").replace("\r", "\n")
    try:
        _run(text, result, _normal_cwd(cwd), 0)
    except _LexError as err:
        result.mark_opaque(str(err))
    except Exception as err:  # noqa: BLE001 - a fault in this reader is "could not tell"
        # hookio.run would turn an exception into "allow"; while a rule is
        # active a command this parser failed on must not pass unread.
        result.mark_opaque("parser error %s" % type(err).__name__)
    return result


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Judge every file this PowerShell command would write."""
    return bash.judge_command(event, "PowerShell", extract_write_targets)


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
