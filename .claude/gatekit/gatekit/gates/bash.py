"""PreToolUse gate for Bash — shell writes obey the same rules as Write.

The Write gate (:mod:`gatekit.gates.write`) decides whether a path may be
written. Without this gate that decision is trivially bypassed: ``cat > x``,
``sed -i``, ``tee``, ``git apply`` all create or change files through the Bash
tool, which the Write gate never sees. A rule that only binds the honest
tool is a convention, not a gate.

This module extracts the files a shell command **would write** and hands each
one to :func:`write.decide_path`. It is a static reading of the command text —
no execution — and it is deliberately conservative:

* When code is not locked (spec gate approved, or no ``spec/`` at all) the
  command is allowed without parsing.
* A target that was read is judged like a Write call, by both rules of the
  Write gate: the approval record ``.gatekit/approvals.json`` is refused, and
  so is code before the spec gate is approved.
* When a write's target **cannot be determined** — a variable in the path,
  ``eval``, ``xargs``, ``git apply``, inline interpreter code such as
  ``python3 -c`` — and a restriction is active, the command is **denied**.
  "Could not tell" is not rounded to "allowed", by the same rule that keeps
  ``unverified`` from being rounded to ``ok``.
* Programs invoked by name (``npm run build``, ``python3 script.py``) are
  outside its reach: it reads shell syntax, not what every binary does.

What it reads of the shell grammar: the command after a reserved word
(``if``/``then``/``else``/``elif``/``do``/``while``/``until``/``!``/``{``),
the body of a function definition, the body of a command substitution
(``$(...)`` and backticks, inside double quotes as well) and ``#`` comments.

What it does not read (known limits, ADR-0004): brace expansion
(``touch docs/{a.md,../src/x.ts}`` is judged as one path), a ``<<word`` inside
quotes or arithmetic (taken for a here-document, the lines after it are
dropped) and a quoted argument made only of operator characters
(``rm ';' x`` is split at the ``;``).

Denial reasons are written in the session's ``output_lang``.
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex
from typing import Any, Callable, Dict, List, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio  # noqa: E402
from gatekit.gates import write  # noqa: E402

#: Tokens that end one simple command and start the next.
_SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;"}

#: Shell wrappers whose real command follows after their own options.
_WRAPPERS = {"sudo", "doas", "env", "nohup", "time", "nice", "command", "exec", "builtin"}

#: Reserved words that open or close a command list. The command after one
#: (``then rm x``, ``do cp a b``, ``! rm x``, ``{ rm x``) is read like any other.
_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "esac"}

#: Reserved words followed by a name and a list of data: ``for f in a b``,
#: ``select f in a b``, ``case x in``.
_HEADERS = {"for", "select", "case"}

#: Command substitutions and ``sh -c`` scripts nested deeper than this are not read.
_MAX_DEPTH = 12

#: After this many unquoted substitutions that are never closed, the closing
#: bracket is no longer searched for: each search reads to the end of the text,
#: and bash runs nothing after the first one anyway.
_MAX_UNCLOSED = 16

#: Stands in the prepared text for a command substitution whose body was
#: lifted out. The ``$`` keeps the word it sits in unresolvable as a path.
_SUB_RE = re.compile("\\$\x00(\\d+)\x00")

#: Inside backticks a backslash escapes only these three characters.
_BACKTICK_ESCAPE_RE = re.compile(r"\\([\\`$])")

#: Commands that rewrite the working tree at paths we cannot read off argv.
_GIT_OPAQUE = {
    "apply", "am", "checkout", "restore", "switch", "reset", "merge", "rebase",
    "pull", "cherry-pick", "revert", "stash", "clean", "mv", "rm", "worktree",
    "submodule", "filter-branch", "read-tree", "checkout-index", "init", "clone",
}

#: ``git`` global options that take the next argument as their value. The
#: ``--name=value`` spellings are one word and need no entry. ``--exec-path``
#: is not here: its value is only ever attached (``--exec-path[=<path>]``).
GIT_VALUE_FLAGS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env", "--attr-source",
})

#: Editors and languages that write wherever their own script says.
_OPAQUE_PROGRAMS = {
    "eval", "xargs", "patch", "trap", "awk", "gawk", "mawk", "nawk",
    "ed", "ex", "vi", "vim", "nvim", "nano", "emacs", "busybox",
}

#: Interpreters that take inline code; with such code we cannot see the writes.
_INTERPRETERS = {
    "python", "python2", "python3", "node", "ruby", "perl", "php", "deno", "bun",
    "ts-node", "tsx", "pwsh",
}
_INLINE_FLAGS = {"-c", "-e", "-E", "-"}

#: Nested shells whose ``-c`` string is parsed recursively.
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}

#: Devices that are never a project write.
_DEVICE_PREFIXES = ("/dev/", "/proc/")

#: ``<<EOF`` … ``EOF`` bodies are data, not commands.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

_MESSAGES = {
    "en": {
        "opaque": (
            "gatekit: cannot determine which files this shell command writes "
            "({why}), and writes are currently restricted. Use the Write/Edit "
            "tool, or a plain command whose target paths are literal. Command: {cmd}"
        ),
    },
    "ko": {
        "opaque": (
            "gatekit: 이 셸 명령이 어떤 파일을 쓰는지 판별할 수 없고({why}) "
            "현재 쓰기가 제한된 상태입니다. Write/Edit 도구를 쓰거나 대상 경로가 "
            "리터럴인 명령을 사용하세요. 명령: {cmd}"
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


class WriteTargets:
    """Result of :func:`extract_write_targets`."""

    __slots__ = ("targets", "opaque", "why")

    def __init__(self) -> None:
        self.targets: List[str] = []
        self.opaque: bool = False
        self.why: str = ""

    def mark_opaque(self, why: str) -> None:
        if not self.opaque:
            self.opaque = True
            self.why = why


# --------------------------------------------------------------------------
# lexing
# --------------------------------------------------------------------------
def _strip_heredocs(text: str) -> str:
    """Remove here-document bodies so their lines are not read as commands."""
    lines = text.split("\n")
    out: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        for match in _HEREDOC_RE.finditer(line):
            terminator = match.group(2)
            while index < len(lines) and lines[index].strip() != terminator:
                index += 1
            index += 1  # the terminator line itself
    return "\n".join(out)


def _close_backtick(text: str, i: int) -> int:
    """Index of the backtick closing a substitution whose body starts at *i*; -1 if none."""
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return i
        i += 1
    return -1


def _close_paren(text: str, i: int) -> int:
    """Index of the ``)`` closing a ``$(`` whose body starts at *i*; -1 if none.

    Quotes inside the body are skipped, and a ``$(`` inside double quotes
    nests. A ``)`` that closes a ``case`` pattern is not told apart: the body
    then ends early and the rest is read as part of the outer command.
    """
    stack = [")"]
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            i = _close_backtick(text, i + 1)
            if i < 0:
                return -1
        elif stack[-1] == '"':
            if ch == '"':
                stack.pop()
            elif ch == "$" and text.startswith("(", i + 1):
                stack.append(")")
                i += 1
        elif ch == "'":
            i = text.find("'", i + 1)
            if i < 0:
                return -1
        elif ch == '"':
            stack.append('"')
        elif ch == "(":
            stack.append(")")
        elif ch == ")":
            stack.pop()
            if not stack:
                return i
        i += 1
    return -1


def _prepare(text: str) -> Tuple[str, List[str]]:
    """Make *text* ready for the tokenizer: (prepared text, substitution bodies).

    Outside quotes a newline becomes ``;`` so lines are separate commands, and
    a ``#`` comment is dropped up to its newline. A backslash-newline joins
    two lines. A command substitution — ``$(...)`` or backticks, inside double
    quotes as well — is lifted out: its body goes into the returned list, to
    be read as commands of its own, and a placeholder (:data:`_SUB_RE`) takes
    its place. ``$((`` is arithmetic and stays as it is; so does an unquoted
    substitution that is never closed (the tokenizer splits it at the ``(``).
    """
    out: List[str] = []
    subs: List[str] = []
    quote = ""
    start = True  # at the start of a word, where a # opens a comment
    misses = 0    # unquoted substitutions found to be never closed
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "\\":
            if text.startswith("\n", i + 1):
                i += 2  # a line continuation: the shell removes both characters
                continue
            out.append(text[i:i + 2])
            i += 2
            start = False
            continue
        end = -1
        opener = ch == "`" or (
            ch == "$" and text.startswith("(", i + 1) and not text.startswith("(", i + 2))
        if opener and (quote or misses < _MAX_UNCLOSED):
            end = _close_backtick(text, i + 1) if ch == "`" else _close_paren(text, i + 2)
            if end < 0 and quote:
                # Never closed, inside double quotes: bash refuses to run this,
                # or the scan above lost its way. The rest is read as the body,
                # so nothing in it passes unread.
                end = n
            elif end < 0:
                misses += 1  # unquoted: the tokenizer splits it at the parenthesis
        if end >= 0:
            body = text[i + 2:end] if ch == "$" else _BACKTICK_ESCAPE_RE.sub(r"\1", text[i + 1:end])
            out.append("$\x00%d\x00" % len(subs))
            subs.append(body)
            i = end + 1
            start = False
            continue
        if quote:  # inside double quotes
            if ch == '"':
                quote = ""
            out.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "#" and start:
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        elif ch == "\n":
            ch = ";"
        out.append(ch)
        start = ch in " \t;&|()<>"
        i += 1
    return "".join(out), subs


def _tokens(command: str, heredocs: bool = True) -> Tuple[Optional[List[str]], List[str]]:
    """Tokenize with shell operators kept as their own tokens.

    Returns the tokens (``None`` if unlexable) and the bodies of the command
    substitutions the tokens refer to by placeholder. *heredocs* is off for
    text whose here-document bodies were already removed.
    """
    prepared, subs = _prepare(_strip_heredocs(command) if heredocs else command)
    lexer = shlex.shlex(prepared, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # _prepare dropped the comments; a # inside a word is text
    try:
        return list(lexer), subs
    except ValueError:
        return None, subs


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in "();<>|&" for ch in token)


def _split_simple(tokens: List[str]) -> List[List[str]]:
    """Split a token stream into simple commands at control operators."""
    commands: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if _is_operator(token) and ">" not in token and "<" not in token:
            if current:
                commands.append(current)
                current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


# --------------------------------------------------------------------------
# path resolution
# --------------------------------------------------------------------------
def _resolve(target: str, cwd: Optional[str]) -> Optional[str]:
    """Resolve *target* against *cwd*; ``None`` when it cannot be known."""
    if "$" in target or "`" in target:
        return None
    if target.startswith("~"):
        target = os.path.expanduser(target)
    if posixpath.isabs(target):
        return posixpath.normpath(target)
    if cwd is None:
        return None
    return posixpath.normpath(posixpath.join(cwd, target))


def _is_device(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _DEVICE_PREFIXES)


def _add(result: WriteTargets, raw: str, cwd: Optional[str], why: str) -> None:
    if raw.startswith("("):
        result.mark_opaque("process substitution")
        return
    resolved = _resolve(raw, cwd)
    if resolved is None:
        result.mark_opaque(why)
        return
    if _is_device(resolved):
        return
    if resolved not in result.targets:
        result.targets.append(resolved)


# --------------------------------------------------------------------------
# one simple command
# --------------------------------------------------------------------------
def _pull_redirects(words: List[str], result: WriteTargets, cwd: Optional[str]) -> List[str]:
    """Record write redirections and return the remaining argument words."""
    rest: List[str] = []
    index = 0
    while index < len(words):
        token = words[index]
        if _is_operator(token) and ">" in token:
            if "(" in token:
                result.mark_opaque("process substitution")
                index += 1
                continue
            # A bare fd number right before the operator belongs to it.
            if rest and rest[-1].isdigit():
                rest.pop()
            target = words[index + 1] if index + 1 < len(words) else None
            index += 2
            if target is None:
                continue
            if token.endswith("&") and (target.isdigit() or target == "-"):
                continue  # fd duplication such as 2>&1
            if _is_operator(target):
                result.mark_opaque("process substitution")
                continue
            _add(result, target, cwd, "variable in redirect target")
            continue
        if _is_operator(token):  # input redirects: skip operator and operand
            index += 2
            continue
        rest.append(token)
        index += 1
    return rest


def _strip_wrappers(words: List[str]) -> List[str]:
    """Drop reserved words and ``sudo``/``env``/``VAR=x`` prefixes to reach the real command.

    ``then rm x``, ``do cp a b``, ``! rm x`` and ``{ rm x`` are the command
    after the reserved word; ``function f { rm x`` is the command after the
    name and the brace. A ``for``/``select``/``case`` header names a variable
    and lists data: nothing in it is a command.
    """
    index = 0
    while index < len(words):
        word = words[index]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            index += 1
            continue
        if word in _KEYWORDS:
            index += 1
            continue
        if word == "function":
            index += 2  # the word and the function's name
            continue
        if word in _HEADERS:
            if words[index + 2:index + 3] == ["in"]:
                return []
            index += 2  # ``for f do rm x``: the list may follow without ``in``
            continue
        if word in _WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
            continue
        break
    return words[index:]


def _positional(args: List[str], consuming: Tuple[str, ...] = ()) -> List[str]:
    """Arguments that are not options; *consuming* options eat their operand."""
    out: List[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in consuming:
            skip = True
            continue
        if arg.startswith("-") and arg != "-":
            continue
        out.append(arg)
    return out


def _sed_in_place(args: List[str]) -> bool:
    for arg in args:
        if arg.startswith("--in-place"):
            return True
        if re.match(r"^-[a-zA-Z]*i", arg):
            return True
    return False


def _flagged_output(
    args: List[str], flags: Tuple[str, ...], result: WriteTargets, cwd: Optional[str], name: str
) -> None:
    """Record the operand of an output flag (``-o file``, ``-o=file``, ``-ofile``)."""
    index = 0
    while index < len(args):
        arg = args[index]
        for flag in flags:
            if arg == flag and index + 1 < len(args):
                _add(result, args[index + 1], cwd, "variable in %s output" % name)
                index += 1
                break
            if arg.startswith(flag + "="):
                _add(result, arg[len(flag) + 1:], cwd, "variable in %s output" % name)
                break
            if len(flag) == 2 and arg.startswith(flag) and len(arg) > 2 and not arg.startswith("--"):
                _add(result, arg[2:], cwd, "variable in %s output" % name)
                break
        index += 1


def _archive(name: str, args: List[str], result: WriteTargets, cwd: Optional[str]) -> None:
    """``tar``/``unzip`` extraction writes into a directory; ``zip`` writes an archive."""
    if name == "zip":
        positional = _positional(args)
        if positional:
            _add(result, positional[0], cwd, "variable in zip target")
        return
    if name == "unzip":
        if any(a in ("-l", "-t", "-z", "-p", "-c") for a in args):
            return  # listing / testing / to stdout
        target = None
        for index, arg in enumerate(args):
            if arg == "-d" and index + 1 < len(args):
                target = args[index + 1]
            elif arg.startswith("-d") and len(arg) > 2:
                target = arg[2:]
        _add(result, target or ".", cwd, "variable in unzip directory")
        return
    # tar: the mode lives in the first bare word (``xzf``) or a dashed
    # cluster (``-xf``) or a long option (``--extract``).
    mode_words = [a for i, a in enumerate(args) if a.startswith("-") or i == 0]
    letters = "".join(a.lstrip("-") for a in mode_words if not a.startswith("--"))
    extracting = "x" in letters or any(a in ("--extract", "--get") for a in mode_words)
    creating = "c" in letters or "--create" in mode_words
    if creating:
        _flagged_output(args, ("--file",), result, cwd, name)
        for index, arg in enumerate(args):
            cluster = arg.lstrip("-")
            if not arg.startswith("--") and cluster.endswith("f") and (index == 0 or arg.startswith("-")):
                if index + 1 < len(args):
                    _add(result, args[index + 1], cwd, "variable in tar archive")
        return
    if extracting:
        target = None
        for index, arg in enumerate(args):
            if arg in ("-C", "--directory") and index + 1 < len(args):
                target = args[index + 1]
            elif arg.startswith("--directory="):
                target = arg.split("=", 1)[1]
        _add(result, target or ".", cwd, "variable in tar directory")


def git_subcommand_index(args: List[str]) -> Optional[int]:
    """Index in *args* (the words after ``git``) of the subcommand, or ``None``.

    Global options come before the subcommand and are skipped: one of
    :data:`GIT_VALUE_FLAGS` together with the word after it (``-C <path>``,
    ``-c <name=value>``, ``--git-dir <path>``), and any other word starting
    with ``-`` (``--no-pager``, ``--git-dir=<path>``, ``-p``). Without this,
    ``git -C dir apply x`` reads ``dir`` as the subcommand and ``apply`` is
    never seen. Shared with the PowerShell gate so the two cannot drift.
    """
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in GIT_VALUE_FLAGS:
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return index
    return None


def _merge(result: WriteTargets, nested: WriteTargets) -> None:
    """Add what a nested script or substitution writes to *result*."""
    result.targets.extend(t for t in nested.targets if t not in result.targets)
    if nested.opaque:
        result.mark_opaque(nested.why)


def _analyze(words: List[str], result: WriteTargets, cwd: Optional[str], depth: int = 0) -> Optional[str]:
    """Inspect one simple command. Returns the new cwd (or ``None`` = unknown)."""
    args = _pull_redirects(words, result, cwd)
    args = _strip_wrappers(args)
    if not args:
        return cwd
    name = posixpath.basename(args[0])
    rest = args[1:]

    if name == "cd":
        if not rest:
            return None  # $HOME — unknown to us
        return _resolve(rest[0], cwd)

    if name in _SHELLS:
        if "-c" in rest:
            script = rest[rest.index("-c") + 1] if rest.index("-c") + 1 < len(rest) else ""
            # A substitution in the script was already read by the caller
            # (the outer shell runs it); inside the script it is a variable.
            _merge(result, _extract(_SUB_RE.sub("$_", script), cwd, depth + 1))
        return cwd

    if name in _OPAQUE_PROGRAMS:
        result.mark_opaque(name)
        return cwd

    if name == "sort":
        _flagged_output(rest, ("-o", "--output"), result, cwd, name)
        return cwd

    if name == "curl":
        if any(a in ("-O", "--remote-name", "-J", "--remote-header-name") for a in rest):
            result.mark_opaque("curl remote file name")
        _flagged_output(rest, ("-o", "--output"), result, cwd, name)
        return cwd

    if name == "wget":
        if "--spider" in rest:
            return cwd
        if any(a in ("-O", "--output-document") or a.startswith(("-O", "--output-document=")) for a in rest):
            _flagged_output(rest, ("-O", "--output-document"), result, cwd, name)
        else:
            result.mark_opaque("wget default file name")
        return cwd

    if name in ("tar", "unzip", "zip"):
        _archive(name, rest, result, cwd)
        return cwd

    if name == "find":
        if any(a in ("-exec", "-execdir", "-ok", "-okdir", "-delete") or a.startswith("-fprint") for a in rest):
            result.mark_opaque("find -exec/-delete")
        return cwd

    if name == "git":
        at = git_subcommand_index(rest)
        sub = rest[at] if at is not None else ""
        if "$" in sub or "`" in sub:
            result.mark_opaque("git subcommand is not literal")
        elif sub in _GIT_OPAQUE:
            result.mark_opaque("git %s" % sub)
        return cwd

    if name == "tee":
        for target in _positional(rest):
            _add(result, target, cwd, "variable in tee target")
        return cwd

    if name == "sed":
        if _sed_in_place(rest):
            files = [f for f in _positional(rest, consuming=("-e", "-f", "--expression", "--file")) if f]
            if not any(a in ("-e", "-f") or a.startswith("--expression") or a.startswith("--file") for a in rest):
                files = files[1:]  # first positional is the script
            for target in files:
                _add(result, target, cwd, "variable in sed target")
        return cwd

    if name == "perl":
        # Any option cluster ending in e/E takes the script as its operand
        # (``-e``, ``-pe``, ``-pie``); ``-i`` anywhere in a cluster is in-place.
        script_flags = tuple(a for a in rest if re.match(r"^-[a-zA-Z]*[eE]$", a))
        if any(re.match(r"^-[a-zA-Z]*i", a) for a in rest):
            for target in _positional(rest, consuming=script_flags):
                _add(result, target, cwd, "variable in perl target")
        elif script_flags or "-" in rest:
            result.mark_opaque("inline perl code")
        return cwd

    if name in _INTERPRETERS or re.match(r"^python\d", name):
        if any(a in _INLINE_FLAGS for a in rest):
            result.mark_opaque("inline %s code" % name)
        return cwd

    if name in ("cp", "mv", "ln", "install", "rsync"):
        positional = _positional(rest, consuming=("-t", "--target-directory", "-m", "-o", "-g"))
        if len(positional) >= 2:
            _add(result, positional[-1], cwd, "variable in destination")
        elif any(a.startswith("-t") or a.startswith("--target-directory") for a in rest):
            result.mark_opaque("%s target directory" % name)
        return cwd

    if name in ("touch", "rm", "rmdir", "unlink", "mkdir", "truncate", "chmod", "chown"):
        consuming = ("-s", "--size") if name == "truncate" else ()
        positional = _positional(rest, consuming=consuming)
        if name in ("chmod", "chown"):
            positional = positional[1:]  # first positional is the mode/owner
        for target in positional:
            _add(result, target, cwd, "variable in %s target" % name)
        return cwd

    if name == "dd":
        for arg in rest:
            if arg.startswith("of="):
                _add(result, arg[3:], cwd, "variable in dd output")
        return cwd

    return cwd


def extract_write_targets(command: str, cwd: Optional[str]) -> WriteTargets:
    """Statically list the paths *command* would write, resolved against *cwd*.

    ``cwd`` may be ``None`` when the working directory is itself unknown, in
    which case every relative target makes the result opaque.
    """
    return _extract(command.replace("\x00", ""), cwd, 0)


def _extract(command: str, cwd: Optional[str], depth: int, heredocs: bool = True) -> WriteTargets:
    """:func:`extract_write_targets` at nesting level *depth*.

    The body of a command substitution is read with the cwd of the simple
    command it sits in, as commands of its own: what it writes is added to the
    result, and a ``cd`` inside it stays inside it.
    """
    result = WriteTargets()
    if depth > _MAX_DEPTH:
        result.mark_opaque("nesting too deep")
        return result
    tokens, subs = _tokens(command, heredocs)
    if tokens is None:
        result.mark_opaque("unbalanced quotes")
        return result
    current = cwd
    for simple in _split_simple(tokens):
        for word in simple:
            for match in _SUB_RE.finditer(word):
                index = int(match.group(1))
                if index < len(subs):
                    # here-document bodies were removed from the whole text already
                    _merge(result, _extract(subs[index], current, depth + 1, heredocs=False))
        current = _analyze(simple, result, current, depth)
    return result


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def judge_command(
    event: Dict[str, Any],
    tool_name: str,
    extract: Callable[[str, Optional[str]], WriteTargets],
) -> Optional[Dict[str, Any]]:
    """Judge every file the shell command in *event* would write.

    Shared by the Bash gate and the PowerShell gate
    (:mod:`gatekit.gates.powershell`): the two differ only in *extract*, the
    function that reads the write targets off the command text. The fast path
    (nothing could be denied, so nothing is parsed), the per-target verdict
    from :func:`write.decide_path` and the denial of an unreadable command are
    the same for both, so they are stated once.
    """
    if event.get("tool_name") != tool_name:
        return hookio.allow()
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return hookio.allow()

    root = hookio.event_root(event)
    if not write.restrictions_active(root):
        return hookio.allow()

    lang = write.session_lang(root, event)
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    found = extract(command, cwd or str(root))

    for target in found.targets:
        decision = write.decide_path(root, target, lang)
        if decision is not None:
            return decision

    if found.opaque:
        shown = command.strip().replace("\n", " ")
        if len(shown) > 120:
            shown = shown[:119] + "…"
        return hookio.deny(_message(lang, "opaque", why=found.why, cmd=shown))
    return hookio.allow()


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Judge every file this Bash command would write."""
    return judge_command(event, "Bash", extract_write_targets)


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
