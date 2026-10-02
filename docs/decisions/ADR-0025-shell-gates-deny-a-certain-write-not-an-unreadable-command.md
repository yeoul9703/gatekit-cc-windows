# ADR-0025: A shell gate denies a certain write, not every command it cannot read

Status: accepted 2026-10-02. Amends ADR-0004 (the Bash write gate) and
ADR-0021 (the PowerShell write gate): the rule "an unresolvable write is
denied" is narrowed, and the limits listed here replace the ones those two
records carry.

## Context

Both shell gates read a command without running it and hand every file it
would write to `write.decide_path`. ADR-0004 and ADR-0021 added one rule on
top: when the gate cannot tell what a command writes, deny — "could not tell"
is never rounded to "allowed".

A property-test study on 2026-10-02 found eight inputs that the gates allowed
while a rule forbade the write, among them the everyday shape
`if true; then rm src/x.ts; fi`: the Bash gate took `then` for the command and
never looked at `rm`. The same study showed the opposite failure as well —
ordinary commands refused because the reader stumbled (`rg std::vector` read
as a .NET call, `Set-Content x y -e utf8` refused for an "ambiguous"
parameter).

The audience is a beginner on native Windows who runs through the PowerShell
tool. The user set two bounds for the repair:

- a beginner being stopped in the middle of ordinary work is the worse
  failure; common shapes go through;
- fix what has to be blocked under Windows (PowerShell) syntax, and do not
  rebuild the Bash reader to chase rare shapes.

## Decision

1. **A target that was read is judged by the rules**, as before.
2. **Common syntax is read, so that it is neither blocked nor missed.**
   - Bash: a reserved word in command position (`if then else elif fi do done
     while until ! { } esac`, `function name`) is stepped over and the word
     after it is read as the command; the heads of `for`, `select` and `case`
     are data. The body of `$(…)` and of backticks is read as commands, inside
     double quotes too, with the working directory of the point where it runs.
     A `#` comment ends at the end of its line instead of swallowing the rest
     of the command; a backslash-newline joins two lines.
   - PowerShell: a word that begins with a backtick is a command name
     (`` `Set-Content ``); a number is a number only in PowerShell's own
     grammar, so `7z` is a program; `cd..`, `cd\` and `cd~` change location;
     `-Include`, `-Exclude` and `-Filter` only narrow what a path names, so the
     path is judged; a write cmdlet's dynamic parameters bind after its static
     ones (`-e` is `-Exclude`, as PowerShell binds it); `sc` followed by an
     `sc.exe` verb is the program; `::` inside a bare argument is text.
3. **What is still denied when it cannot be read**, with a reason that says
   how to retry (write the literal path, or use the Write tool):
   - a write command whose target cannot be known — a variable or a
     substitution in the path, a wildcard path, a relative path after a drive
     switch;
   - a construct that runs arbitrary code — `eval`, `xargs`, an inline
     interpreter, `Invoke-Expression`, a script-block or variable call,
     `Start-Process`, a .NET file call, a member call spelled across two words
     (`$doc. Save('src/x.ts')`), a cast that opens a file
     (`[IO.StreamWriter]'src/x.ts'`), the opaque git subcommands.
4. **A reading failure that does not even show a write is allowed.** The gate
   does not guess a write into a command it could not parse.
5. **The Bash reader is not rebuilt.** The shapes below stay open and are
   recorded as limits rather than repaired, because closing them means
   replacing the tokenizer and they are not what a PowerShell-first beginner
   types.

## Known limits

Bash gate, allowed although a rule forbids the write:

- brace expansion: `touch docs/{n.md,../src/x.ts}`;
- `<<` inside quotes, arithmetic or a comment, read as a here-document so the
  following lines are dropped: `echo '<<EOF'` then `touch src/x.ts`;
- an operator character inside quotes read as a separator:
  `rm -f ';' src/x.ts`;
- a wrapper's value option: `sudo -u root rm src/x.ts`, `timeout 5 rm …`,
  `env -C src touch README.md`;
- location changes the reader does not follow: `(cd docs); cat > x.ts`,
  `pushd`, a `cd` behind `|` or after a failed `&&`;
- a script on stdin (`bash <<'EOF'`, `python3 <<'EOF'`), a command held in a
  variable (`c=rm; $c src/x.ts`), a function body read with the directory of
  its definition.

Bash gate, refused although nothing is written: `echo $((1 > 2))`,
`[[ $a > $b ]]`, `echo '>' x`.

PowerShell gate:

- no variable tracking: `$p = 'docs/n.md'; Set-Content $p y` is denied;
- `echo a>b` is read as a redirection (PowerShell reads an argument);
- under Windows PowerShell 5.1 `sc` is `Set-Content`, so `sc query y` writes a
  file named `query` and is allowed; `cd~` exists in PowerShell 7 only;
- `D:; C:; Set-Content x y` returns to the first drive and is still denied;
- `Write-Host a.Save('a')` and `Write-Host [math]::Pi` are text to PowerShell
  and are denied;
- a cast built from a string (`-as`) is not seen;
- an internal error of the reader denies, where the Bash gate's is caught by
  `hookio.run` and allows. Left as it is.

Both gates: a program invoked by name is not inspected (`python script.py`,
`npm run build`), as in ADR-0004.

## Consequences

- One visible change during an enforcing phase: a loop that writes to a
  variable path (`for f in a b; do touch docs/$f.md; done`) is now denied — the
  `touch` used to be invisible. The reason tells the model to write literal
  paths or use the Write tool.
- `tests/test_gate_bash_props.py` and `tests/test_gate_powershell_props.py`
  put a write, in every spelling, into every context the readers know, and a
  read into the same contexts. They need hypothesis (uv dev group) and skip
  without it. Removing either repair makes them fail.
- A hook call costs what it did: about 72 ms for the Bash gate and 132 ms for
  the PowerShell gate while a rule is active.
- A scope pattern reads a bracket as a letter (`write.matches`,
  `ledger.globs_intersect`): `src/app/[id]/page.tsx` names the folder `[id]`.
  Read as a character set it refused that file and allowed `src/app/i/…`.
