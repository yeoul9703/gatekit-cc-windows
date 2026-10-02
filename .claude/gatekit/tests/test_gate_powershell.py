"""Tests for gates/powershell.py — PowerShell writes obey the same rules as Write."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, ledger  # noqa: E402
from gatekit.gates import powershell as ps_gate  # noqa: E402
from tests import isolation  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "powershell.py"

#: The working directory the extraction tests resolve against.
CWD = "C:\\proj"


def shown(path: str) -> str:
    """A target as the tests spell it: relative to CWD with forward slashes."""
    if path == CWD:
        return "."
    if path.startswith(CWD + "\\"):
        return path[len(CWD) + 1:].replace("\\", "/")
    return path


def targets_of(command: str, cwd: "str | None" = CWD) -> "tuple[list[str], bool]":
    result = ps_gate.extract_write_targets(command, cwd)
    return sorted(shown(t) for t in result.targets), result.opaque


def why(command: str) -> str:
    return ps_gate.extract_write_targets(command, CWD).why


class TestExtractRedirects(unittest.TestCase):
    def test_truncating_and_appending_redirect(self) -> None:
        self.assertEqual(targets_of("'hello' > out2.txt"), (["out2.txt"], False))
        self.assertEqual(targets_of("echo hi >> notes.txt"), (["notes.txt"], False))

    def test_redirect_without_spaces(self) -> None:
        self.assertEqual(targets_of("'hi'>src\\x.ts"), (["src/x.ts"], False))
        self.assertEqual(targets_of("Write-Output 'hi'>src\\x.ts"), (["src/x.ts"], False))
        # PowerShell reads a > inside a bare word as part of the argument and
        # writes nothing (measured); the gate over-reads it as a redirect,
        # which errs toward a denial.
        self.assertEqual(targets_of("echo hi>src\\x.ts"), (["src/x.ts"], False))

    def test_numbered_and_all_streams(self) -> None:
        self.assertEqual(targets_of("npm test 2>errors.log"), (["errors.log"], False))
        self.assertEqual(targets_of("npm test 2>> errors.log"), (["errors.log"], False))
        self.assertEqual(targets_of("npm test *> all.log"), (["all.log"], False))
        self.assertEqual(targets_of("npm test 3>warn.log 2>err.log"),
                         (["err.log", "warn.log"], False))

    def test_stream_number_is_not_mistaken_for_an_argument(self) -> None:
        self.assertEqual(targets_of("Copy-Item a b 2>err.log"), (["b", "err.log"], False))

    def test_null_and_stream_merges_are_not_writes(self) -> None:
        for cmd in ("ls > $null", "ls 2>$null", "ls *> $null", "ls > $null 2>&1",
                    "ls 2>&1", "ls *>&1", "ls | Out-Null", "ls > NUL", "ls > nul",
                    "ls > ${null}"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_quoted_null_is_a_file_name(self) -> None:
        self.assertEqual(targets_of("ls > '$null'"), (["$null"], False))

    def test_quoted_angle_bracket_is_not_a_redirect(self) -> None:
        self.assertEqual(targets_of('git commit -m "a > b"'), ([], False))
        self.assertEqual(targets_of("Write-Host 'a > b'"), ([], False))

    def test_quoted_target(self) -> None:
        self.assertEqual(targets_of("echo hi > 'my file.txt'"), (["my file.txt"], False))
        self.assertEqual(targets_of('echo hi > "dir/my file.txt"'), (["dir/my file.txt"], False))

    def test_variable_in_redirect_target_is_opaque(self) -> None:
        self.assertTrue(targets_of("echo hi > $out")[1])
        self.assertTrue(targets_of('echo hi > "$env:TEMP\\x.txt"')[1])
        self.assertTrue(targets_of("echo hi > $(Get-Date -Format yyyy).log")[1])

    def test_comment_is_not_read(self) -> None:
        self.assertEqual(targets_of("ls # > fake.txt"), ([], False))
        self.assertEqual(targets_of("ls <# > fake.txt #> > real.txt"), (["real.txt"], False))


class TestExtractCmdlets(unittest.TestCase):
    def test_set_content_forms(self) -> None:
        for cmd in (
            "Set-Content -Path out.txt -Value hello",
            "Set-Content out.txt hello",
            "Set-Content -Value hello -Path out.txt",
            "set-content -path out.txt -value hello",
            "SET-CONTENT -PATH out.txt -VALUE hello",
            "Set-Content -LiteralPath out.txt -Value hello",
            "Set-Content -Path:out.txt -Value:hello",
            "Set-Content -Path 'out.txt' -Value 'a b'",
            'Set-Content -Path "out.txt" -Value "a b"',
            "Microsoft.PowerShell.Management\\Set-Content out.txt hello",
        ):
            self.assertEqual(targets_of(cmd), (["out.txt"], False), cmd)

    def test_aliases(self) -> None:
        # sc is an alias in Windows PowerShell 5.1 only; see
        # test_sc_is_the_service_program_in_powershell_7.
        cases = {
            "sc a.txt x": ["a.txt"], "ac a.txt x": ["a.txt"], "clc a.txt": ["a.txt"],
            "ls | tee build.log": ["build.log"], "ni a.txt": ["a.txt"],
            "cp a b": ["b"], "copy a b": ["b"], "cpi a b": ["b"],
            "mv a b": ["a", "b"], "move a b": ["a", "b"], "mi a b": ["a", "b"],
            "rm a": ["a"], "del a": ["a"], "erase a": ["a"], "rd a": ["a"],
            "ri a": ["a"], "rmdir a": ["a"],
            "ren a b": ["a", "b"], "rni a b": ["a", "b"],
            "mkdir a/b": ["a/b"], "md a": ["a"],
        }
        for cmd, expected in cases.items():
            self.assertEqual(targets_of(cmd), (expected, False), cmd)

    def test_parameter_prefixes(self) -> None:
        self.assertEqual(targets_of("Remove-Item -Pa x"), (["x"], False))
        self.assertEqual(targets_of("Set-Content -Lit x -Va y"), (["x"], False))
        self.assertEqual(targets_of("Set-Content -Pat x -Va y"), (["x"], False))
        self.assertEqual(targets_of("Copy-Item -Pat a -Dest b"), (["b"], False))
        self.assertEqual(targets_of("Remove-Item -r -fo build"), (["build"], False))
        self.assertEqual(targets_of("ls | Out-File -File log.txt -App"), (["log.txt"], False))

    def test_parameter_prefixes_follow_powershell_binding(self) -> None:
        """Each case was run in PowerShell 7 before it was written down here."""
        # An alias may be shortened too: -Pat is Out-File's -Path alias.
        self.assertEqual(targets_of("ls | Out-File -Pat log.txt"), (["log.txt"], False))
        self.assertEqual(targets_of("Remove-Item -PSP x"), (["x"], False))
        # The cmdlet's own parameter wins over a common one: -V is -Value, not
        # -Verbose, and mkdir's -p is -Path.
        self.assertEqual(targets_of("Set-Content -Path x -V y"), (["x"], False))
        self.assertEqual(targets_of("mkdir -p a/b"), (["a/b"], False))
        # -LiteralPath fills -Path's slot, so the next word is the value.
        self.assertEqual(targets_of("Set-Content -LiteralPath x hello"), (["x"], False))

    def test_ambiguous_or_unknown_parameter_is_opaque(self) -> None:
        # -Pa is Path or PassThru for Set-Content; -p is Path or LiteralPath
        # (alias PSPath) for Remove-Item; -w is three common parameters;
        # -Bogus may or may not eat x.
        self.assertTrue(targets_of("Set-Content -Pa x y")[1])
        self.assertTrue(targets_of("Remove-Item -p x")[1])
        self.assertTrue(targets_of("Set-Content x y -w")[1])
        self.assertTrue(targets_of("Set-Content -Bogus x y")[1])
        self.assertTrue(targets_of("rm -rf build")[1])

    def test_switch_before_a_positional_target(self) -> None:
        self.assertEqual(targets_of("New-Item -Force out.txt"), (["out.txt"], False))
        self.assertEqual(targets_of("Remove-Item -Recurse -Force build"), (["build"], False))
        self.assertEqual(targets_of("Remove-Item -Confirm:$false build"), (["build"], False))

    def test_common_parameters_take_their_value(self) -> None:
        self.assertEqual(targets_of("Remove-Item -ErrorAction SilentlyContinue x"), (["x"], False))
        self.assertEqual(targets_of("Remove-Item x -ea 0"), (["x"], False))

    def test_out_file_and_tee_object(self) -> None:
        self.assertEqual(targets_of("Get-Process | Out-File -FilePath log.txt -Append"),
                         (["log.txt"], False))
        self.assertEqual(targets_of("Get-Process | Out-File log.txt utf8"), (["log.txt"], False))
        self.assertEqual(targets_of("make | Tee-Object -FilePath build.log"), (["build.log"], False))
        self.assertEqual(targets_of("make | tee -a build.log"), (["build.log"], False))
        self.assertEqual(targets_of("make | Tee-Object -Variable out"), ([], False))

    def test_new_item_joins_path_and_name(self) -> None:
        self.assertEqual(targets_of("New-Item -Path src -Name x.ts -ItemType File"),
                         (["src/x.ts"], False))
        self.assertEqual(targets_of("New-Item -Name x.ts"), (["x.ts"], False))
        self.assertEqual(targets_of("New-Item -ItemType Directory -Force src/a"), (["src/a"], False))

    def test_copy_move_rename_remove(self) -> None:
        self.assertEqual(targets_of("Copy-Item -Path a.ts -Destination src/b.ts"),
                         (["src/b.ts"], False))
        self.assertEqual(targets_of("Copy-Item -Recurse a b"), (["b"], False))
        self.assertEqual(targets_of("Copy-Item a"), (["."], False))
        self.assertEqual(targets_of("Move-Item a.ts src/b.ts"), (["a.ts", "src/b.ts"], False))
        self.assertEqual(targets_of("Rename-Item src\\a.ts b.ts"), (["src/a.ts", "src/b.ts"], False))
        self.assertEqual(targets_of("Remove-Item a, b"), (["a", "b"], False))
        self.assertEqual(targets_of("Remove-Item a , b"), (["a", "b"], False))
        self.assertEqual(targets_of("Remove-Item ,a"), (["a"], False))
        self.assertEqual(targets_of("Clear-Content src/x.ts"), (["src/x.ts"], False))

    def test_export_cmdlets(self) -> None:
        self.assertEqual(targets_of("ls | Export-Csv -Path r.csv -NoTypeInformation"),
                         (["r.csv"], False))
        self.assertEqual(targets_of("ls | Export-Csv r.csv"), (["r.csv"], False))
        self.assertEqual(targets_of("ls | Export-Clixml r.xml"), (["r.xml"], False))
        self.assertEqual(targets_of("Export-Alias -Path a.txt"), (["a.txt"], False))
        # An Export-* cmdlet with no table here and no readable path parameter.
        self.assertTrue(targets_of("Export-Alias a.txt")[1])
        self.assertEqual(targets_of("Export-ModuleMember -Function f"), ([], False))

    def test_start_transcript_and_archives(self) -> None:
        self.assertEqual(targets_of("Start-Transcript t.log"), (["t.log"], False))
        self.assertTrue(targets_of("Start-Transcript")[1])
        self.assertEqual(targets_of("Compress-Archive -Path src -DestinationPath out.zip"),
                         (["out.zip"], False))
        self.assertEqual(targets_of("Expand-Archive p.zip -DestinationPath src"), (["src"], False))
        self.assertEqual(targets_of("Expand-Archive p.zip"), (["."], False))

    def test_web_request_out_file(self) -> None:
        self.assertEqual(targets_of("Invoke-WebRequest https://x -OutFile dl.zip"),
                         (["dl.zip"], False))
        self.assertEqual(targets_of("iwr -Uri https://x -OutF dl.zip"), (["dl.zip"], False))
        self.assertEqual(targets_of("Invoke-RestMethod https://x -OutFile r.json"),
                         (["r.json"], False))
        self.assertEqual(targets_of("irm https://x"), ([], False))
        self.assertTrue(targets_of("iwr https://x -OutFile $dest")[1])
        # Any shortening of -OutFile is read as the path, down to -O.
        for flag in ("-O", "-Ou", "-Out", "-OutF"):
            self.assertEqual(targets_of("iwr https://x %s dl.zip" % flag), (["dl.zip"], False), flag)
        self.assertEqual(targets_of("iwr https://x -OutVariable r"), ([], False))

    def test_target_from_the_pipeline_is_opaque(self) -> None:
        self.assertTrue(targets_of("Get-ChildItem | Remove-Item")[1])
        self.assertTrue(targets_of("Get-Content a | Set-Content")[1])

    def test_extra_positional_argument_is_opaque(self) -> None:
        self.assertTrue(targets_of("Remove-Item a b")[1])


class TestExtractQuoting(unittest.TestCase):
    def test_single_quotes_are_literal(self) -> None:
        self.assertEqual(targets_of("Set-Content -LiteralPath '$x.txt' y"), (["$x.txt"], False))
        self.assertEqual(targets_of("Set-Content 'it''s.txt' y"), (["it's.txt"], False))

    def test_double_quotes_expand_variables(self) -> None:
        self.assertTrue(targets_of('Set-Content "$name.txt" y')[1])
        self.assertTrue(targets_of('Set-Content "${name}.txt" y')[1])
        self.assertTrue(targets_of('Set-Content "$(Get-Date).txt" y')[1])
        self.assertEqual(targets_of('Set-Content "a`$b.txt" y'), (["a$b.txt"], False))
        self.assertEqual(targets_of('Set-Content "say ""hi"".txt" y'), (['say "hi".txt'], False))

    def test_backtick_escapes(self) -> None:
        self.assertEqual(targets_of("Set-Content my` file.txt y"), (["my file.txt"], False))
        self.assertEqual(targets_of("Set-Content `\n  out.txt `\n  hello"), (["out.txt"], False))
        # `e is the escape character, not the letter e.
        self.assertTrue(targets_of("Set-Content a`e.txt y")[1])

    def test_typographic_quotes_are_quotes(self) -> None:
        self.assertEqual(targets_of("Set-Content \u2018a b.txt\u2019 y"), (["a b.txt"], False))
        self.assertEqual(targets_of("Set-Content \u201ca b.txt\u201d y"), (["a b.txt"], False))

    def test_unicode_dashes_start_a_parameter(self) -> None:
        # PowerShell takes an en dash or em dash for the parameter dash.
        self.assertEqual(targets_of("Set-Content \u2013Path x.txt \u2014Value y"),
                         (["x.txt"], False))
        self.assertEqual(targets_of("Set-Content 'a\u2013b.txt' y"), (["a\u2013b.txt"], False))

    def test_unicode_spaces_separate_words(self) -> None:
        self.assertEqual(targets_of("Set-Content\xa0x.txt y"), (["x.txt"], False))
        self.assertEqual(targets_of("Set-Content\u3000x.txt\u3000y"), (["x.txt"], False))

    def test_unusual_whitespace_is_opaque(self) -> None:
        self.assertTrue(targets_of("Write-Host a\x0bSet-Content x y")[1])
        self.assertTrue(targets_of("Write-Host a\u2028Set-Content x y")[1])
        self.assertTrue(targets_of("Write-Host a\x85Set-Content x y")[1])

    def test_unbalanced_quote_or_bracket_is_opaque(self) -> None:
        self.assertTrue(targets_of('echo "abc')[1])
        self.assertTrue(targets_of("echo 'abc")[1])
        self.assertTrue(targets_of("if ($x) { ls")[1])
        self.assertTrue(targets_of("ls )")[1])

    def test_value_text_is_never_a_target(self) -> None:
        self.assertEqual(targets_of("Set-Content out.txt 'Remove-Item x; echo > y'"),
                         (["out.txt"], False))

    def test_quoted_dash_word_is_an_argument_not_a_parameter(self) -> None:
        self.assertEqual(targets_of("Set-Content '-Force' y"), (["-Force"], False))


class TestExtractHereStrings(unittest.TestCase):
    def test_literal_here_string_body_is_not_parsed(self) -> None:
        cmd = "@'\nfoo > fake.txt\nRemove-Item gone\n'@ | Set-Content out.txt"
        self.assertEqual(targets_of(cmd), (["out.txt"], False))

    def test_here_string_as_a_value(self) -> None:
        cmd = "Set-Content -Path out.txt -Value @'\nline > x\n'@"
        self.assertEqual(targets_of(cmd), (["out.txt"], False))

    def test_expandable_here_string_body_is_not_parsed(self) -> None:
        cmd = 'Set-Content -Path out.txt -Value @"\nhello $name > fake.txt\n"@'
        self.assertEqual(targets_of(cmd), (["out.txt"], False))

    def test_subexpression_inside_an_expandable_here_string_is_read(self) -> None:
        cmd = 'Write-Host @"\n$(Set-Content hidden.txt x)\n"@'
        self.assertEqual(targets_of(cmd), (["hidden.txt"], False))

    def test_command_after_the_here_string_is_parsed(self) -> None:
        cmd = "$body = @'\ntext\n'@\nSet-Content a.txt $body\n'x' > b.txt"
        self.assertEqual(targets_of(cmd), (["a.txt", "b.txt"], False))

    def test_closer_must_start_a_line(self) -> None:
        cmd = "Set-Content out.txt @'\n  '@ still body > fake.txt\n'@"
        self.assertEqual(targets_of(cmd), (["out.txt"], False))

    def test_unterminated_here_string_is_opaque(self) -> None:
        self.assertTrue(targets_of("Set-Content out.txt @'\nbody")[1])

    def test_crlf_line_endings(self) -> None:
        cmd = "@'\r\nfoo > fake.txt\r\n'@ | Set-Content out.txt\r\n'x' > b.txt"
        self.assertEqual(targets_of(cmd), (["b.txt", "out.txt"], False))


class TestExtractStatements(unittest.TestCase):
    def test_separators(self) -> None:
        self.assertEqual(targets_of("sc a x; sc b x"), (["a", "b"], False))
        self.assertEqual(targets_of("sc a x\nsc b x"), (["a", "b"], False))
        self.assertEqual(targets_of("sc a x && sc b x || sc c x"), (["a", "b", "c"], False))
        self.assertEqual(targets_of("Get-Content a | Set-Content b"), (["b"], False))

    def test_script_blocks_and_groups_are_read(self) -> None:
        self.assertEqual(targets_of("if (Test-Path a) { Set-Content b c } else { rm d }"),
                         (["b", "d"], False))
        self.assertEqual(targets_of("1..3 | ForEach-Object { Add-Content log.txt 'x' }"),
                         (["log.txt"], False))
        self.assertEqual(targets_of("$n = (Set-Content a.txt x -PassThru).Length"),
                         (["a.txt"], False))
        self.assertEqual(targets_of('Write-Host "done $(Set-Content q.txt r)"'),
                         (["q.txt"], False))
        self.assertEqual(targets_of("try { sc a x } catch { sc b x } finally { sc c x }"),
                         (["a", "b", "c"], False))

    def test_brackets_attached_to_a_keyword(self) -> None:
        self.assertEqual(targets_of("if($a){Set-Content b c}else{rm d}"), (["b", "d"], False))
        self.assertEqual(targets_of("try{sc a x}catch{sc b x}"), (["a", "b"], False))
        self.assertEqual(targets_of("while($true){ sc a b; break }"), (["a"], False))
        self.assertEqual(targets_of("switch($x){ 'a' { sc one 1 } default { sc two 2 } }"),
                         (["one", "two"], False))
        self.assertEqual(targets_of("'x' | % { $_ > out.txt }"), (["out.txt"], False))

    def test_pipeline_variable_in_a_block_is_opaque(self) -> None:
        self.assertTrue(targets_of("Get-ChildItem | ForEach-Object { Remove-Item $_ }")[1])
        self.assertTrue(targets_of("foreach ($f in $files) { Set-Content $f x }")[1])

    def test_assignment_runs_its_right_hand_side(self) -> None:
        self.assertEqual(targets_of("$x = Set-Content a.txt b -PassThru"), (["a.txt"], False))
        self.assertEqual(targets_of("$x=Set-Content a.txt b"), (["a.txt"], False))
        self.assertEqual(targets_of("$x = Get-Content a.txt"), ([], False))

    def test_hashtable_keys_are_not_commands(self) -> None:
        self.assertEqual(targets_of("$a = @{ rm = 'x'; Path = 'y' }"), ([], False))
        self.assertEqual(targets_of("$a = @{ k = (Set-Content a.txt b) }"), (["a.txt"], False))

    def test_expression_statements_write_nothing(self) -> None:
        for cmd in ("'just a string'", "1 + 2", "$x", "$x.Name", "[int]'5'", "@(1, 2)"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)


class TestExtractPaths(unittest.TestCase):
    def test_backslash_and_forward_slash_are_the_same(self) -> None:
        self.assertEqual(targets_of("sc src\\auth\\x.ts y"), (["src/auth/x.ts"], False))
        self.assertEqual(targets_of("sc src/auth/x.ts y"), (["src/auth/x.ts"], False))
        self.assertEqual(targets_of("sc .\\src\\..\\x.ts y"), (["x.ts"], False))

    def test_absolute_paths(self) -> None:
        self.assertEqual(targets_of("sc C:\\proj\\src\\x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sc C:/proj/src/x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sc D:\\other\\x.ts y"), (["D:\\other\\x.ts"], False))

    def test_drive_letter_case_is_normalized(self) -> None:
        self.assertEqual(targets_of("sc c:\\proj\\x.ts y"), (["x.ts"], False))
        self.assertEqual(targets_of("sc x.ts y", cwd="c:\\proj"), (["x.ts"], False))
        self.assertEqual(targets_of("sc x.ts y", cwd="C:/proj"), (["x.ts"], False))

    def test_root_relative_path_takes_the_cwd_drive(self) -> None:
        self.assertEqual(targets_of("sc \\tmp\\x y"), (["C:\\tmp\\x"], False))

    def test_drive_relative_path_is_opaque(self) -> None:
        self.assertTrue(targets_of("sc C:x.ts y")[1])

    def test_unc_path_is_a_target_outside_the_project(self) -> None:
        self.assertEqual(targets_of("sc \\\\server\\share\\x y"),
                         (["\\\\server\\share\\x"], False))

    def test_tilde_is_expanded(self) -> None:
        targets, opaque = targets_of("sc ~\\x y")
        self.assertFalse(opaque)
        self.assertEqual(targets, [os.path.join(os.path.expanduser("~"), "x")])

    def test_trailing_dots_and_spaces_are_dropped(self) -> None:
        self.assertEqual(targets_of("sc 'src/x.ts.' y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sc 'src/x.ts ' y"), (["src/x.ts"], False))

    def test_alternate_data_stream_is_opaque(self) -> None:
        self.assertTrue(targets_of("sc x.md:hidden y")[1])

    def test_provider_qualified_file_system_path(self) -> None:
        self.assertEqual(targets_of("sc 'FileSystem::C:\\proj\\x.ts' y"), (["x.ts"], False))

    def test_non_file_drives_are_not_writes(self) -> None:
        for cmd in ("Set-Content Env:FOO 1", "Remove-Item Env:\\FOO", "Set-Item Variable:x 1",
                    "New-Item HKCU:\\Software\\X"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_alias_and_function_drives_are_opaque(self) -> None:
        # Set-Alias through the provider: the new name would hide a write cmdlet.
        for cmd in ("Set-Item Alias:w Set-Content; w src/x.ts y",
                    "New-Item -Path Alias:\\w -Value Set-Content",
                    "Set-Content Function:\\w 'param($p) Set-Content $p 1'",
                    "Remove-Item Function:\\f"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_unknown_drive_is_opaque(self) -> None:
        self.assertTrue(targets_of("sc Temp:\\x y")[1])
        self.assertTrue(targets_of("sc MyDrive:\\x y")[1])

    def test_variables_in_a_path_are_opaque(self) -> None:
        for cmd in ("Set-Content $x y", "Set-Content $env:TEMP\\x y", "Set-Content $HOME/x y",
                    "Set-Content -Path $PSScriptRoot\\x y", "Set-Content (Join-Path a b) y",
                    "Set-Content $(Get-Location)\\x y", "Remove-Item @args",
                    "Set-Content @params", "New-Item -Path src -Name $n",
                    "Copy-Item a -Destination $dest"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_wildcards_are_opaque_unless_literal(self) -> None:
        for cmd in ("Remove-Item *.tmp", "Remove-Item 'src/*'", "Remove-Item a?.txt",
                    "Set-Content 'app/[id]/page.tsx' x", "echo hi > a*.txt",
                    "Remove-Item src/* -Include *.ts"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        self.assertEqual(targets_of("Set-Content -LiteralPath 'app/[id]/page.tsx' x"),
                         (["app/[id]/page.tsx"], False))

    def test_a_filter_narrows_the_path_it_is_given(self) -> None:
        # -Include, -Exclude and -Filter pick among what the path names; they
        # never add a file, so the path is the target that is judged.
        for flags in ("-Include *.ts", "-Exclude a", "-Filter *.ts", "-Recurse -Include $pattern"):
            self.assertEqual(targets_of("Remove-Item src " + flags), (["src"], False), flags)
        self.assertTrue(targets_of("Get-ChildItem | Remove-Item -Include *.ts")[1])

    def test_unknown_cwd_makes_relative_writes_opaque(self) -> None:
        self.assertTrue(targets_of("sc x y", cwd=None)[1])
        self.assertEqual(targets_of("sc C:\\proj\\x y", cwd=None), (["x"], False))


class TestExtractCwd(unittest.TestCase):
    def test_set_location_then_write(self) -> None:
        for cd in ("cd", "Set-Location", "sl", "chdir", "Push-Location", "pushd",
                   "Set-Location -Path", "Set-Location -LiteralPath"):
            self.assertEqual(targets_of("%s src; sc x.ts y" % cd), (["src/x.ts"], False), cd)

    def test_newline_and_pipeline_chain(self) -> None:
        self.assertEqual(targets_of("cd src\nsc x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("cd src && 'x' > y.ts"), (["src/y.ts"], False))

    def test_cd_up_is_normalized(self) -> None:
        self.assertEqual(targets_of("cd src/auth; sc ..\\other.ts y"), (["src/other.ts"], False))

    def test_cd_to_a_variable_makes_relative_writes_opaque(self) -> None:
        self.assertTrue(targets_of("cd $dir; sc x.ts y")[1])
        self.assertTrue(targets_of("cd (Split-Path $p); sc x.ts y")[1])
        self.assertTrue(targets_of("cd -; sc x.ts y")[1])
        self.assertTrue(targets_of("cd src; Pop-Location; sc x.ts y")[1])
        self.assertTrue(targets_of("cd src; popd; sc x.ts y")[1])

    def test_cd_to_a_variable_then_absolute_write_is_fine(self) -> None:
        self.assertEqual(targets_of("cd $dir; sc C:\\proj\\x y"), (["x"], False))

    def test_cd_inside_a_block_makes_the_cwd_unknown(self) -> None:
        self.assertTrue(targets_of("if ($a) { cd src }; sc x.ts y")[1])


class TestExtractOpaque(unittest.TestCase):
    def test_invoke_expression(self) -> None:
        for cmd in ('Invoke-Expression "Set-Content x y"', "iex $cmd", "'sc x y' | iex"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_call_operator_on_a_variable_or_script_block(self) -> None:
        for cmd in ("& $cmd", "& $cmd a b", "& { Set-Content a b }", ". $script",
                    ". { Set-Content a b }", "$r = & $cmd", "& (Get-Command sc) x y",
                    "ls | & $filter", "&$cmd", "&{Set-Content a b}", ".{Set-Content a b}",
                    ".$script", "& \"$tool\" x"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_a_called_script_block_is_still_read(self) -> None:
        # Denied as a call, and its literal target is judged as well.
        self.assertEqual(targets_of("& { Set-Content a.txt b }"), (["a.txt"], True))

    def test_call_operator_on_a_literal_name_is_read_as_that_command(self) -> None:
        self.assertEqual(targets_of("& 'Set-Content' a.txt b"), (["a.txt"], False))
        self.assertEqual(targets_of("&\"Set-Content\" a.txt b"), (["a.txt"], False))
        self.assertEqual(targets_of("$r = & 'Set-Content' a.txt b"), (["a.txt"], False))
        self.assertEqual(targets_of("$out = & git status"), ([], False))
        self.assertTrue(targets_of("$out = & git apply p.diff")[1])
        self.assertTrue(targets_of("& 'C:\\Program Files\\Git\\bin\\git.exe' apply p.diff")[1])
        self.assertEqual(targets_of("& npm run build"), ([], False))
        self.assertEqual(targets_of(". .\\profile.ps1"), ([], False))

    def test_background_operator_is_not_a_call(self) -> None:
        self.assertEqual(targets_of("npm run dev &"), ([], False))

    def test_start_process_and_jobs(self) -> None:
        for cmd in ("Start-Process notepad x.txt", "saps cmd", "start notepad",
                    "Start-Job { sc a b }", "Invoke-Command { sc a b }", "Invoke-Item x.bat"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_dotnet_calls(self) -> None:
        for cmd in (
            "[System.IO.File]::WriteAllText('x', 'y')",
            "[IO.File]::WriteAllLines('x', $lines)",
            "[System.IO.File]::Delete('x')",
            "[IO.Directory]::CreateDirectory('x')",
            "$w = [System.IO.StreamWriter]::new('x')",
            "$doc.Save('x.xml')",
            "$client.DownloadFile($url, 'x')",
            "$type::WriteAllText('x', 'y')",
            "New-Object System.IO.StreamWriter 'x'",
            "New-Object -TypeName Net.WebClient",
            "Add-Type -TypeDefinition $src",
            'Write-Host "$([IO.File]::WriteAllText(\'x\', \'y\'))"',
        ):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_harmless_dotnet_is_not_flagged(self) -> None:
        for cmd in (
            "[math]::Round(1.5)", "[System.IO.Path]::Combine('a', 'b')",
            "[IO.File]::ReadAllText('x')", "[System.IO.File]::Exists('x')",
            "[Environment]::NewLine", "[datetime]::Now.ToString('o')",
            "'abc'.Replace('a', 'b').Trim()", "$s.Split(',')[0].ToUpper()",
            "(Get-Date).AddDays(1)", "$list.Add(1)", "$x.Count",
            "New-Object PSObject -Property @{ a = 1 }",
            "New-Object System.Collections.ArrayList",
        ):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_inline_interpreter_code_is_opaque(self) -> None:
        for cmd in (
            "python -c \"open('x','w')\"",
            "python3 -c 'print(1)'",
            "py -c 'print(1)'",
            "python.exe -c 'print(1)'",
            "node -e 'require(\"fs\").writeFileSync(\"x\",\"\")'",
            "node --eval 'x'",
            "ruby -e 'File.write(\"x\", \"\")'",
            "perl -pi -e 's/a/b/' x.ts",
            "pwsh -Command \"Set-Content x y\"",
            "pwsh -c 'sc x y'",
            "pwsh -NoProfile -Command sc x y",
            "powershell -Command \"Set-Content x y\"",
            "powershell.exe -EncodedCommand AAAA",
            "pwsh",
            "cmd /c \"echo hi > x\"",
            "cmd.exe /C del x",
            "cmd /k echo",
            "bash -c 'cat > x'",
            "wsl touch x",
            "'print(1)' | python",
            "@'\nprint(1)\n'@ | python -",
        ):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_running_a_script_file_is_not_flagged(self) -> None:
        for cmd in ("python script.py", "python -m unittest discover", "node scripts/build.js",
                    "npm run build", "uv run pytest", "uv run --frozen python -m unittest",
                    "pwsh -File scripts/setup.ps1", "pwsh -NoProfile -File x.ps1 -Install",
                    "python --version", "node -v", "bash scripts/x.sh", ".\\build.ps1",
                    "& .\\build.ps1 -Fast"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_git_working_tree_mutations_are_opaque(self) -> None:
        for cmd in ("git apply p.diff", "git checkout -- src/x.ts", "git restore x",
                    "git stash pop", "git reset --hard", "git clone https://x/y src/c",
                    "git -C sub checkout x", "git.exe apply p.diff", "git $sub",
                    "git -C dir apply x", "git -c core.x=y checkout -- f",
                    "git --git-dir=.git --work-tree=. checkout x", "git --git-dir .git reset --hard",
                    "git --no-pager stash pop", "git -C a -c k=v --no-pager apply x",
                    "git '--no-pager' apply x", "git --exec-path apply p", "git -C dir $sub"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_git_global_option_value_is_not_read_as_the_subcommand(self) -> None:
        for cmd in ("git -C apply status", "git -c apply=1 log", "git --git-dir=checkout diff",
                    "git --no-pager log", "git -C", "git --no-pager", "git"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_git_options_are_read_by_the_bash_gate_function(self) -> None:
        from gatekit.gates import bash as bash_gate
        from gatekit.gates import powershell as powershell_gate

        self.assertFalse(hasattr(powershell_gate, "_GIT_VALUE_FLAGS"))
        self.assertIn("-C", bash_gate.GIT_VALUE_FLAGS)

    def test_git_metadata_commands_are_fine(self) -> None:
        for cmd in ("git status", "git add -A", "git commit -m x", "git diff", "git log",
                    "git -C sub status"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_the_git_list_is_the_bash_gate_list(self) -> None:
        from gatekit.gates import bash as bash_gate

        for sub in sorted(bash_gate._GIT_OPAQUE):
            self.assertTrue(targets_of("git %s x" % sub)[1], sub)

    def test_aliasing_a_write_cmdlet_is_opaque(self) -> None:
        self.assertTrue(targets_of("Set-Alias w Set-Content; w x y")[1])
        self.assertTrue(targets_of("New-Alias w Set-Content")[1])

    def test_function_bodies_are_read(self) -> None:
        self.assertTrue(targets_of("function w($p) { Set-Content $p 1 }; w x")[1])
        self.assertEqual(targets_of("function w { Set-Content fixed.txt 1 }; w"),
                         (["fixed.txt"], False))

    def test_programs_that_write_by_their_own_arguments(self) -> None:
        for cmd in ("sed -i 's/a/b/' src/x.ts", "tar -xf p.tar", "robocopy a b",
                    "xcopy a b", "touch x", "curl -O https://x/y.ts",
                    "curl.exe -o $f https://x"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        self.assertEqual(targets_of("curl -o src/x.ts https://x"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sed -n 's/a/b/p' x.ts"), ([], False))
        self.assertEqual(targets_of("curl -s https://x"), ([], False))

    def test_the_reason_names_what_could_not_be_read(self) -> None:
        self.assertIn("variable", why("Set-Content $x y"))
        self.assertIn("wildcard", why("Remove-Item *.tmp"))
        self.assertIn("-Bogus", why("Set-Content -Bogus x y"))
        self.assertIn("git apply", why("git apply p.diff"))
        self.assertIn("WriteAllText", why("[System.IO.File]::WriteAllText('x','y')"))

    def test_deep_nesting_is_opaque_not_a_crash(self) -> None:
        cmd = "{ " * 40 + "sc a b" + " }" * 40
        self.assertTrue(targets_of(cmd)[1])

    def test_member_access_through_anything_but_a_bare_word_is_a_dotnet_call(self) -> None:
        # Each form parses as a static member access (PowerShell 7.6.6 parser).
        for cmd in ("Write-Host $x::Member", "[IO.File]::\nWriteAllText('x', 'y')",
                    "[IO.File]:: WriteAllText('x', 'y')", "[ IO.File ]::WriteAllText('x', 'y')",
                    "([type]'System.IO.File')::WriteAllText('x', 'y')",
                    "'System.IO.File'::WriteAllText('x', 'y')"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_member_name_on_the_next_word_is_still_a_call(self) -> None:
        # Measured: `$doc. Save('x')` and `$doc.<newline>Save('x')` write the file.
        for cmd in ("$doc = [xml]'<a/>'; $doc. Save('src/x.ts')", "$doc.\nSave('src/x.ts')",
                    "(Get-Item x).\nDelete()", "'a'.\nSave('x')"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        # A path that ends in a dot is not a member access.
        for cmd in ("cd $dir\\..; ls", "Get-ChildItem $HOME\\.", "git add .", "ls ..", "$a..$b"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_a_cast_to_a_writer_type_opens_the_file(self) -> None:
        # Measured: [IO.StreamWriter]'x' creates or truncates x.
        for cmd in ("[IO.StreamWriter]'src/x.ts'", "$w = [System.IO.StreamWriter]'x'",
                    "'x' -as [IO.StreamWriter]", "[io.streamwriter] 'x'"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        self.assertEqual(targets_of("[IO.StreamReader]'x'"), ([], False))


class TestBypassRegressions(unittest.TestCase):
    """The three wrong allows found on 2026-10-02 (a leading backtick, ``7z``,
    ``cd..``). Every form was put to the PowerShell 7.6.6 parser, and the
    location functions were run, before being written down here."""

    def test_a_leading_backtick_does_not_hide_the_command(self) -> None:
        self.assertEqual(targets_of("`Set-Content src/x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("`Set-Content -Path src/x.ts -Value y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("Set-`Content src/x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("`S`E`T-`C`O`N`T`E`N`T src/x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("`del a"), (["a"], False))
        self.assertEqual(targets_of("ls; `Set-Content a y"), (["a"], False))
        self.assertEqual(targets_of("if ($a) { `Set-Content a y }"), (["a"], False))
        self.assertEqual(targets_of("$r = `Set-Content a y"), (["a"], False))
        for cmd in ("`certutil -decode a b", "`iex $c", "`7z x a.zip", "`Start-Process x"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_a_control_escape_in_the_name_is_opaque(self) -> None:
        # `r is a carriage return: the name is not "rm", and no such command
        # exists. Reading the control character is not attempted; it is denied.
        self.assertTrue(targets_of("`rm a")[1])
        self.assertTrue(targets_of("S`et-Content a y")[1])

    def test_a_name_finished_by_a_variable_is_not_a_literal_command(self) -> None:
        # `S$x is the command whose name is "S" plus the value of $x.
        self.assertTrue(targets_of("$x = 'et-Content'; `S$x a b")[1])
        self.assertTrue(targets_of("S$x a b")[1])

    def test_an_escaped_dash_is_an_argument_not_a_parameter(self) -> None:
        # Traced: Set-Content `-Path x binds Path='-Path' and Value='x'.
        self.assertEqual(targets_of("Set-Content `-Path x"), (["-Path"], False))
        self.assertEqual(targets_of("Set-Content `x.ts y"), (["x.ts"], False))

    def test_a_name_that_starts_with_a_digit_is_a_command(self) -> None:
        for cmd in ("7z x a.zip -osrc", "7z", "7Z a out.7z src", "7z.exe x a.zip",
                    "7'z' x a.zip", "7`z x a.zip", "& 7z x a.zip", "ls; 7z x a.zip"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        for word in ("7z", "7zip", "7za", "1kbx", "0x1g", "1e3x", "1dd", "1_000", "3dsmax",
                     "2to3", "1password"):
            self.assertIsNone(ps_gate._NUMBER_RE.fullmatch(word), word)

    def test_numbers_are_still_expressions(self) -> None:
        for word in ("1", "1kb", "10gb", "1lkb", "0x10", "0b101", "1e3", "1.5", ".5", "1d",
                     "1l", "1ul", "1y", "1uy", "1s", "1us", "1n", "1u", "-5", "+5"):
            self.assertIsNotNone(ps_gate._NUMBER_RE.fullmatch(word), word)
        for cmd in ("1kb", "0x10", "1 + 2", "1..3 | ForEach-Object { $_ }", "5 -gt 3"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)
        self.assertEqual(targets_of("5 > five.txt"), (["five.txt"], False))

    def test_location_functions_move_the_working_directory(self) -> None:
        docs = CWD + "\\docs"
        self.assertEqual(targets_of("cd docs; cd..; Set-Content x.ts y"), (["x.ts"], False))
        self.assertEqual(targets_of("cd..; Set-Content x.ts y", cwd=docs), (["x.ts"], False))
        self.assertEqual(targets_of("cd\\; Set-Content x.ts y", cwd=docs), (["C:\\x.ts"], False))
        self.assertEqual(targets_of("cd src/auth; cd..; Set-Content other.ts y"),
                         (["src/other.ts"], False))
        self.assertEqual(targets_of("cd src/auth\ncd..\ncd..\nSet-Content x.ts y"),
                         (["x.ts"], False))
        # The name is case-insensitive, & calls it, and its arguments are ignored (run).
        for cmd in ("CD..; Set-Content x.ts y", "& cd..; Set-Content x.ts y",
                    "cd.. ignored; Set-Content x.ts y", "`cd..; Set-Content x.ts y"):
            self.assertEqual(targets_of(cmd, cwd=docs), (["x.ts"], False), cmd)
        targets, opaque = targets_of("cd~; Set-Content x y")
        self.assertFalse(opaque)
        self.assertEqual(targets, [os.path.join(os.path.expanduser("~"), "x")])

    def test_names_that_only_look_like_a_location_function(self) -> None:
        # cd/ and cd..\src are not functions: the location stays (parser: one command name).
        for cmd in ("cd/; Set-Content x.ts y", "cd..\\src; Set-Content x.ts y"):
            self.assertEqual(targets_of(cmd, cwd=CWD + "\\docs"), (["docs/x.ts"], False), cmd)

    def test_a_drive_switch_makes_relative_writes_opaque(self) -> None:
        for cmd in ("D:; Set-Content x.ts y", "d:\nSet-Content x.ts y", "D:; 'x' > x.ts",
                    "D:; C:; Set-Content x.ts y", "if ($a) { D: }; Set-Content x.ts y"):
            self.assertTrue(targets_of(cmd)[1], cmd)
        self.assertIn("cannot resolve", why("D:; Set-Content x.ts y"))
        self.assertEqual(targets_of("D:; Set-Content C:\\proj\\x.ts y"), (["x.ts"], False))
        # The drive the session is already on: nothing moves.
        self.assertEqual(targets_of("C:; Set-Content x.ts y"), (["x.ts"], False))
        self.assertEqual(targets_of("D:; Get-ChildItem"), ([], False))

    def test_location_function_inside_a_block_makes_the_cwd_unknown(self) -> None:
        self.assertTrue(targets_of("if ($a) { cd.. }; Set-Content x.ts y")[1])


class TestOrdinaryCommandsAreRead(unittest.TestCase):
    """Commands that used to be refused although PowerShell 7 writes nothing,
    or writes a path the gate can read. Each row was checked against
    PowerShell 7.6.6 (the parser, or a binding trace in a scratch folder)."""

    def test_double_colon_in_a_bare_argument_is_text(self) -> None:
        for cmd in ("rg std::vector", "rg std::vector src", "std::vector",
                    "pytest tests/test_x.py::TestA::test_b", "uv run pytest tests/a.py::test_b",
                    "cargo test module::tests::name", "git log --format=%H::%s",
                    "Write-Host -x:foo::bar", "npm run x -- --a::b", "Write-Host a,b::c"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_dynamic_parameters_bind_after_static_ones(self) -> None:
        # -e is -Exclude (static) although -Encoding (dynamic) starts with e too.
        self.assertEqual(targets_of("Set-Content x y -e utf8"), (["x"], False))
        self.assertEqual(targets_of("Add-Content x y -e utf8"), (["x"], False))
        for flags in ("-en utf8", "-enc utf8", "-n", "-no", "-a", "-s z", "-st z", "-fo", "-wh"):
            self.assertEqual(targets_of("Set-Content x y " + flags), (["x"], False), flags)
        self.assertEqual(targets_of("Remove-Item x -s z"), (["x"], False))
        self.assertEqual(targets_of("Clear-Content x -s q"), (["x"], False))
        self.assertEqual(targets_of("Copy-Item x z -e q"), (["z"], False))
        self.assertEqual(targets_of("'y' | Out-File x -e utf8"), (["x"], False))

    def test_a_prefix_powershell_calls_ambiguous_stays_opaque(self) -> None:
        # PowerShell refuses to bind these, and a table here may be incomplete.
        for cmd in ("Set-Content x y -f", "Set-Content x y -w", "Set-Content -p x y",
                    "New-Item q.txt -t File"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_sc_is_the_service_program_in_powershell_7(self) -> None:
        for cmd in ("sc query Spooler", "SC qc Spooler", "sc", "sc.exe start Spooler",
                    "sc.exe a.txt x", "sc \\\\server query Spooler",
                    "C:\\Windows\\System32\\sc.exe config x start= auto"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)
        # Windows PowerShell 5.1 still reads this one as Set-Content.
        self.assertEqual(targets_of("sc src/x.ts y"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sc -Path src/x.ts -Value y"), (["src/x.ts"], False))

    def test_parameters_of_a_command_without_a_table_are_not_read(self) -> None:
        for cmd in ("Get-Content x -e utf8", "Get-Content x -t 1", "Get-ChildItem -Bogus x",
                    "Select-String -Pa x -Pat y", "ls -la", "Test-Path -p x",
                    "Get-ChildItem -Path . -Filter *.py -Recurse"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)


def run_gate_subprocess(event: dict, env_extra: "dict | None" = None, raw: "str | None" = None,
                        *, cwd: pathlib.Path):
    """The gate as a process standing in *cwd*, the test's own project: an event without
    a usable ``cwd`` sends the gate to its working directory (tests/isolation.py)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    proc = isolation.run_gate(
        [sys.executable, str(GATE_SCRIPT)],
        cwd=cwd,
        input=raw if raw is not None else json.dumps(event),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class PowerShellGateProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.gate_md.write_text("# Gate\n", encoding="utf-8")

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("GATEKIT_"):
                del os.environ[key]
        self._tmp.cleanup()

    def event(self, command: str, cwd: "str | None" = None, tool: str = "PowerShell") -> dict:
        return {
            "session_id": "sess-ps",
            "hook_event_name": "PreToolUse",
            "cwd": cwd or str(self.root),
            "tool_name": tool,
            "tool_input": {"command": command, "description": "test"},
        }

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def reason(self, result: dict) -> str:
        return result["hookSpecificOutput"]["permissionDecisionReason"]

    def denied(self, command: str, **kwargs) -> dict:
        result = ps_gate.handle(self.event(command, **kwargs))
        self.assertIsNotNone(result, command)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        return result

    def allowed(self, command: str, **kwargs) -> None:
        self.assertIsNone(ps_gate.handle(self.event(command, **kwargs)), command)


class TestMeasuredHookInput(PowerShellGateProject):
    """The two payloads recorded by the probe of 2026-10-02 (ADR-0021), with
    only ``cwd`` and ``transcript_path`` pointed at this test's project."""

    def measured(self, command: str, description: str, mode: str) -> dict:
        return {
            "session_id": "3b6c13a4-e888-403b-9517-6b52a571e15f",
            "transcript_path": str(self.root / "transcript.jsonl"),
            "cwd": str(self.root),
            "prompt_id": "d37a22e5-e504-4661-85bf-35359224a463",
            "permission_mode": mode,
            "effort": {"level": "medium"},
            "hook_event_name": "PreToolUse",
            "tool_name": "PowerShell",
            "tool_input": {"command": command, "description": description},
            "tool_use_id": "toolu_01JTcbjjDJSi8g5jRJEbj9ot",
        }

    def test_set_content_payload_is_denied_before_approval(self) -> None:
        event = self.measured("Set-Content -Path out.txt -Value hello",
                              'Write "hello" to out.txt', "bypassPermissions")
        result = ps_gate.handle(event)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("out.txt", self.reason(result))

    def test_redirect_payload_is_denied_before_approval(self) -> None:
        event = self.measured("'hello' > out2.txt", "Write 'hello' to out2.txt", "default")
        result = ps_gate.handle(event)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("out2.txt", self.reason(result))

    def test_both_payloads_are_allowed_after_approval(self) -> None:
        self.approve()
        for command in ("Set-Content -Path out.txt -Value hello", "'hello' > out2.txt"):
            self.assertIsNone(ps_gate.handle(self.measured(command, "d", "default")), command)

    def test_bash_shaped_payload_is_left_to_the_bash_gate(self) -> None:
        event = self.measured("echo hi > out.txt", "Print hi", "default")
        event["tool_name"] = "Bash"
        self.assertIsNone(ps_gate.handle(event))


class TestSpecBeforeCode(PowerShellGateProject):
    def test_denies_writes_into_code_before_approval(self) -> None:
        self.assertIn("src/x.ts", self.reason(self.denied("Set-Content src/x.ts y")))
        self.denied("'x' > src\\x.ts")
        self.denied("New-Item -ItemType File src/x.ts")
        self.denied("Remove-Item src/x.ts")
        self.denied("Copy-Item spec/a.md src/a.ts")

    def test_allows_spec_and_docs_targets(self) -> None:
        self.allowed("Set-Content spec/01-prd.md y")
        self.allowed("Set-Content -Path spec\\01-prd.md -Value y")
        self.allowed("'x' > docs/notes.md")
        self.allowed("ls | Tee-Object README.md")
        self.allowed("'x' | Out-File -FilePath .gatekit/note.txt")

    def test_allows_after_approval(self) -> None:
        self.approve()
        self.allowed("Set-Content src/x.ts y")

    def test_allows_when_no_spec_dir(self) -> None:
        self.gate_md.unlink()
        (self.root / "spec").rmdir()
        self.allowed("Set-Content src/x.ts y")

    def test_read_only_commands_always_allowed(self) -> None:
        self.allowed("Get-ChildItem src | Select-String ts > $null")
        self.allowed("git status; Get-Content src/x.ts")
        self.allowed("ls 2>&1 | Out-Null")
        self.allowed("uv run --frozen python -m unittest")

    def test_opaque_write_denied_before_approval(self) -> None:
        for cmd in ("Set-Content $path y", "git apply p.diff", "python -c \"open('x','w')\"",
                    "iex $c", "[System.IO.File]::WriteAllText('x','y')", "Remove-Item *.ts"):
            self.assertIn("판별할 수 없고", self.reason(self.denied(cmd)), cmd)  # the opaque denial

    def test_opaque_write_allowed_after_approval(self) -> None:
        self.approve()
        self.allowed("git apply p.diff")
        self.allowed("Set-Content $path y")

    def test_literal_denial_is_reported_before_the_opaque_one(self) -> None:
        result = self.denied("Set-Content src/x.ts y; iex $c")
        self.assertIn("src/x.ts", self.reason(result))

    def test_relative_cd_inside_command(self) -> None:
        self.denied("cd src; Set-Content x.ts y")
        self.allowed("cd spec; Set-Content 01-prd.md y")

    def test_cwd_from_event_is_honoured(self) -> None:
        (self.root / "src").mkdir()
        self.denied("Set-Content x.ts y", cwd=str(self.root / "src"))
        (self.root / "docs").mkdir()
        self.allowed("Set-Content x.md y", cwd=str(self.root / "docs"))

    def test_absolute_windows_path_inside_the_project(self) -> None:
        self.allowed("Set-Content '%s' y" % (self.root / "spec" / "01-prd.md"))
        self.denied("Set-Content '%s' y" % (self.root / "src" / "x.ts"))

    def test_drive_letter_case_does_not_put_a_path_outside_the_project(self) -> None:
        inside = str(self.root / "spec" / "01-prd.md")
        self.assertRegex(inside, r"^[A-Za-z]:\\")
        self.allowed("Set-Content '%s' y" % (inside[0].lower() + inside[1:]))
        self.allowed("Set-Content '%s' y" % (inside[0].upper() + inside[1:]))

    def test_existing_directory_case_is_ignored(self) -> None:
        # realpath restores the on-disk spelling of the part that exists.
        self.allowed("Set-Content SPEC/01-prd.md y")
        self.allowed("Set-Content Spec\\new.md y")

    def test_reason_is_korean_by_default(self) -> None:
        self.assertFalse(ledger.Ledger.exists(self.root, "sess-ps"))  # nothing stored a language
        literal = self.reason(self.denied("Set-Content src/x.ts y"))
        self.assertIn("승인", literal)
        self.assertNotIn("writing code is blocked", literal)
        opaque = self.reason(self.denied("Set-Content $x y"))
        self.assertIn("파일", opaque)
        self.assertNotIn("cannot determine", opaque)

    def test_non_powershell_tool_is_ignored(self) -> None:
        self.allowed("Set-Content src/x.ts y", tool="Bash")
        self.allowed("Set-Content src/x.ts y", tool="Read")

    def test_missing_or_empty_command_is_allowed(self) -> None:
        event = self.event("")
        self.assertIsNone(ps_gate.handle(event))
        event["tool_input"] = {}
        self.assertIsNone(ps_gate.handle(event))
        event["tool_input"] = "not a dict"
        self.assertIsNone(ps_gate.handle(event))

    def test_optional_tool_input_keys_are_ignored(self) -> None:
        event = self.event("Set-Content spec/a.md y")
        event["tool_input"].update({"timeout": 5000, "run_in_background": True})
        self.assertIsNone(ps_gate.handle(event))

    def test_long_command_is_shortened_in_the_reason(self) -> None:
        reason = self.reason(self.denied("iex $c; " + "Write-Host aaaaaaaaaa; " * 30))
        self.assertIn("…", reason)


class TestReproducedBypasses(PowerShellGateProject):
    """The PowerShell inputs of the reproduction of 2026-10-02: each one wrote a
    code file while the spec gate was unapproved, and was allowed."""

    def setUp(self) -> None:
        super().setUp()
        for name in ("docs", "src"):
            (self.root / name).mkdir()

    def test_every_reproduction_input_is_denied(self) -> None:
        self.denied("Set-Content src/x.ts y")  # the control
        self.assertIn("src/x.ts", self.reason(self.denied("`Set-Content src/x.ts y")))
        self.assertIn("7z", self.reason(self.denied("7z x a.zip -osrc")))
        self.assertIn("x.ts", self.reason(self.denied("cd docs; cd..; Set-Content x.ts y")))
        self.denied("cd..; Set-Content x.ts y", cwd=str(self.root / "docs"))
        self.denied("cd\\; Set-Content x.ts y", cwd=str(self.root / "docs"))

    def test_the_same_moves_are_allowed_where_the_target_is(self) -> None:
        # Reading cd.. must not turn a documentation write into a denial.
        self.allowed("cd src; cd..; Set-Content docs/n.md y")
        self.allowed("cd..; Set-Content n.md y", cwd=str(self.root / "docs"))
        self.allowed("`Set-Content docs/n.md y")
        self.denied("cd docs; cd..; cd src; Set-Content n.md y")

    def test_a_drive_switch_before_a_relative_write_is_denied(self) -> None:
        self.assertIn("판별할 수 없고", self.reason(self.denied("D:; Set-Content n.md y")))
        self.allowed("D:; Get-ChildItem")

    def test_the_denial_says_how_to_retry(self) -> None:
        reason = self.reason(self.denied("$p = 'docs/n.md'; Set-Content $p y"))
        self.assertIn("Write/Edit", reason)
        self.assertIn("리터럴", reason)

    def test_ordinary_commands_pass_while_writes_are_restricted(self) -> None:
        for cmd in (
            "Get-ChildItem -Recurse src", "Get-Content src/x.ts | Select-String foo",
            "Get-Content x -e utf8", "Get-ChildItem -Path . -Filter *.ts -Recurse",
            "git status", "git diff --stat", "git log --oneline -5", "git add -A",
            "npm test", "npm run build", "node --version", "python script.py",
            "uv run --frozen python -m unittest", "rg std::vector src",
            "pytest tests/test_x.py::TestA::test_b", "cargo test module::tests::name",
            "sc query Spooler", "sc.exe start Spooler",
            "cd src; Get-ChildItem; cd..", "cd..; Get-ChildItem", "D:; Get-ChildItem",
            "Test-Path src/x.ts", "$files = Get-ChildItem src; $files.Count",
            "Get-ChildItem src | Where-Object { $_.Length -gt 10 } | ForEach-Object { $_.Name }",
            "if (Test-Path x) { 'yes' } else { 'no' }", "$env:FOO = 'bar'; npm test",
            "ls 2>&1 | Out-Null", "Write-Host 'done'", "Get-Date -Format 'yyyy-MM-dd'",
            "[math]::Round(1.5)", "(Get-Content package.json | ConvertFrom-Json).version",
            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5",
            "1..3 | ForEach-Object { $_ * 2 }", "7zip --help", "2to3 --help",
            "Set-Content docs/notes.md y", "Set-Content spec/01-prd.md y -e utf8",
            "Set-Content docs/n.md y -en utf8 -n", "Remove-Item docs -Recurse -Include *.tmp",
        ):
            self.allowed(cmd)


class TestFastPath(PowerShellGateProject):
    def test_command_is_not_parsed_when_nothing_could_be_denied(self) -> None:
        self.approve()
        original = ps_gate._run

        def boom(*args, **kwargs):
            raise AssertionError("the command was parsed on the fast path")

        ps_gate._run = boom
        try:
            self.allowed("Set-Content src/x.ts y")
        finally:
            ps_gate._run = original

    def test_unmanaged_project_gets_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(os.path.realpath(tmp))
            (root / ".git").mkdir()
            self.assertIsNone(ps_gate.handle(self.event("Set-Content src/x.ts y", cwd=str(root))))
            self.assertFalse((root / ".gatekit").exists())


class TestTaskScope(PowerShellGateProject):
    def setUp(self) -> None:
        super().setUp()
        self.approve()
        task_dir = self.root / ".gatekit" / "jobs" / "job-1" / "tasks" / "auth"
        task_dir.mkdir(parents=True)
        self.task_json = task_dir / "task.json"
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": ["src/auth/**"]}))
        os.environ["GATEKIT_TASK_ID"] = "auth"
        os.environ["GATEKIT_JOB_ID"] = "job-1"

    def test_write_inside_scope_allowed(self) -> None:
        self.allowed("Set-Content src/auth/token.ts y")
        self.allowed("Set-Content src\\auth\\token.ts y")
        self.allowed("'x' > src/auth/deep/a.ts")

    def test_write_outside_scope_denied(self) -> None:
        self.assertIn("src/auth/**", self.reason(self.denied("Set-Content src/other.ts y")))
        self.denied("'x' > spec/01-prd.md")

    def test_escape_via_cd_denied(self) -> None:
        self.denied("cd src/auth; Set-Content ..\\other.ts y")

    def test_reproduced_bypasses_are_denied(self) -> None:
        self.denied("Set-Content src/other.ts y")  # the control
        self.assertIn("src/other.ts", self.reason(self.denied("`Set-Content src/other.ts y")))
        self.assertIn("src/other.ts",
                      self.reason(self.denied("cd src/auth; cd..; Set-Content other.ts y")))
        self.denied("7z x a.zip -osrc/auth")
        self.denied("cd src/auth; D:; Set-Content token.ts y")
        self.allowed("cd src; cd..; Set-Content src/auth/token.ts y")
        self.allowed("`Set-Content src/auth/token.ts y")

    def test_second_command_in_chain_is_checked(self) -> None:
        self.denied("Set-Content src/auth/a.ts y; Set-Content spec/01-prd.md y")
        self.denied("Set-Content src/auth/a.ts y | Out-File spec/01-prd.md")

    def test_move_source_outside_scope_denied(self) -> None:
        self.denied("Move-Item src/other.ts src/auth/other.ts")
        self.allowed("Move-Item src/auth/a.ts src/auth/b.ts")

    def test_opaque_denied_for_scoped_worker(self) -> None:
        self.denied("git checkout -- src/auth/a.ts")
        self.denied("Set-Content $target y")

    def test_read_only_task_denies_any_write_but_allows_reads(self) -> None:
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": "read-only"}))
        self.denied("Set-Content src/auth/token.ts y")
        self.allowed("Get-Content src/auth/token.ts | Measure-Object -Line")

    def test_outside_root_denied(self) -> None:
        self.denied("Set-Content C:\\Windows\\Temp\\escape.ts y")
        self.denied("Set-Content ..\\escape.ts y")
        self.denied("Set-Content \\\\server\\share\\x y")


class TestSubprocessContract(PowerShellGateProject):
    def test_deny_is_json_on_stdout_exit_zero(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("Set-Content src/x.ts y"), cwd=self.root)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allow_prints_nothing_exit_zero(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("Get-ChildItem"), cwd=self.root)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_internal_error_still_exits_zero(self) -> None:
        code, out, _ = run_gate_subprocess({}, raw="this is not json", cwd=self.root)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_non_string_command_exits_zero(self) -> None:
        event = self.event("x")
        event["tool_input"] = {"command": ["not", "a", "string"]}
        code, out, _ = run_gate_subprocess(event, cwd=self.root)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_unreadable_project_state_still_exits_zero(self) -> None:
        # A directory where config.json should be: whatever the gate makes of
        # it, the hook must not fail.
        (self.root / ".gatekit" / "config.json").mkdir()
        code, out, err = run_gate_subprocess(self.event("Set-Content src/x.ts y"), cwd=self.root)
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)

    def test_a_fault_in_the_parser_denies_rather_than_allows(self) -> None:
        """hookio.run turns an exception into "allow"; a command the parser
        broke on was not read, so it must come out opaque instead."""
        original = ps_gate._run

        def boom(*args, **kwargs):
            raise IndexError("injected parser failure")

        ps_gate._run = boom
        try:
            found = ps_gate.extract_write_targets("Set-Content src/x.ts y", str(self.root))
            result = ps_gate.handle(self.event("Set-Content src/x.ts y"))
        finally:
            ps_gate._run = original
        self.assertTrue(found.opaque)
        self.assertIn("IndexError", found.why)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("parser error", self.reason(result))

    def test_exception_outside_the_parser_is_logged_exit_zero(self) -> None:
        import io

        from gatekit import hookio
        from gatekit.gates import write

        original = write.restrictions_active

        def boom(root):
            raise RuntimeError("injected gate failure")

        write.restrictions_active = boom
        try:
            code = hookio.run(ps_gate.handle,
                              stdin=io.StringIO(json.dumps(self.event("Set-Content src/x.ts y"))),
                              exit_process=False)
        finally:
            write.restrictions_active = original
        self.assertEqual(code, 0)
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertTrue(log.is_file())
        text = log.read_text(encoding="utf-8")
        self.assertIn("PreToolUse", text)
        self.assertIn("injected gate failure", text)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_through_the_cli_dispatcher(self) -> None:
        launcher = pathlib.Path(__file__).resolve().parents[1] / "bin" / "gatekit.py"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        proc = isolation.run_gate(
            [sys.executable, str(launcher), "_gate", "powershell"],
            cwd=self.root,
            input=json.dumps(self.event("'x' > src/x.ts")).encode("utf-8"),
            capture_output=True, env=env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")


class TestRegistration(unittest.TestCase):
    def test_settings_json_routes_powershell_to_this_gate(self) -> None:
        # .claude/gatekit/tests/test_gate_powershell.py -> parents[3] == repo root
        settings_path = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        matchers = {entry.get("matcher"): entry for entry in settings["hooks"]["PreToolUse"]}
        self.assertIn("PowerShell", matchers)
        self.assertEqual(len(matchers["PowerShell"]["hooks"]), 1)
        hook = matchers["PowerShell"]["hooks"][0]
        # exec form: no shell string, the gate name is the last argv element
        self.assertEqual(hook["type"], "command")
        self.assertTrue(hook["command"].endswith(".venv/Scripts/python.exe"))
        self.assertEqual(hook["args"][-2:], ["_gate", "powershell"])
        self.assertTrue(hook["args"][0].endswith("bin/gatekit.py"))
        self.assertEqual(len(hook["args"]), 3)
        # The Bash matcher stays its own entry: it does not fire for PowerShell.
        self.assertEqual(matchers["Bash"]["hooks"][0]["args"][-2:], ["_gate", "bash"])

    def test_settings_keep_the_powershell_tool_switched_on(self) -> None:
        settings_path = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["env"]["CLAUDE_CODE_USE_POWERSHELL_TOOL"], "1")
        self.assertEqual(settings["defaultShell"], "powershell")

    def test_cli_and_doctor_list_the_gate(self) -> None:
        from gatekit import cli, doctor

        self.assertIn("powershell", cli.GATES)
        self.assertIn("powershell.py", doctor.GATE_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
