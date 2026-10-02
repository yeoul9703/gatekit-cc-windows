"""Grep gate: the docs must not describe the old plugin-era structure.

ADRs are historical records and are skipped, except ADR-0018 (the current
decision). README.md, USAGE.md and ARCHITECTURE.md are always checked."""
from __future__ import annotations

import pathlib
import re
import unittest

PROJECT = pathlib.Path(__file__).resolve().parents[3]
DOCS = PROJECT / "docs"

STALE = [
    ("python 3.9", re.compile(r"(?i)python\s*3\.9|3\.9\+|>=\s*3\.9|≥\s*3\.9")),
    ("bin/gatekit wrapper", re.compile(r"bin/gatekit(?!\.py)")),
    ("python3 ", re.compile(r"python3 ")),
    ("hooks.json", re.compile(r"hooks\.json")),
    ("no-install claim", re.compile(r"설치 과정 없이|설치 불필요|설치할 필요가 없")),
    ("seven axes", re.compile(r"7가지 항목|7축|seven axes|7-axis", re.I)),
    ("CLAUDE_PLUGIN_ROOT", re.compile(r"CLAUDE_PLUGIN_ROOT")),
]

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def checked_files() -> list[pathlib.Path]:
    files = [PROJECT / "README.md"]
    for path in sorted(DOCS.rglob("*.md")):
        if path.parent.name == "decisions" and not path.name.startswith(("ADR-0018", "ADR-0020")):
            continue
        files.append(path)
    return files


class TestDocsStale(unittest.TestCase):
    def test_no_stale_phrases(self) -> None:
        hits = []
        for path in checked_files():
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                for label, pattern in STALE:
                    if pattern.search(line):
                        hits.append("%s:%d [%s] %s" % (
                            path.relative_to(PROJECT), lineno, label, line.strip()[:80]))
        self.assertEqual(hits, [], "stale wording found:\n" + "\n".join(hits))

    def test_expected_files_are_checked(self) -> None:
        names = {p.name for p in checked_files()}
        for expected in ("README.md", "USAGE.md", "ARCHITECTURE.md",
                         "ADR-0018-windows-standalone-uv.md",
                         "ADR-0020-skills-under-claude-skills.md"):
            self.assertIn(expected, names)

    def test_relative_links_resolve(self) -> None:
        broken = []
        for path in checked_files():
            for target in LINK.findall(path.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                if not (path.parent / target.split("#")[0]).exists():
                    broken.append("%s -> %s" % (path.relative_to(PROJECT), target))
        self.assertEqual(broken, [])

    def test_templates_name_no_python3_command(self) -> None:
        """A template is copied into the user's spec/, so a command in it must run here."""
        templates = sorted((PROJECT / ".claude" / "skills").glob("*/assets/**/*.md"))
        self.assertTrue(templates, "no template found under .claude/skills/*/assets")
        hits = []
        for path in templates:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "python3 " in line:
                    hits.append("%s:%d %s" % (path.relative_to(PROJECT), lineno, line.strip()[:80]))
        self.assertEqual(hits, [], "a template names python3:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
