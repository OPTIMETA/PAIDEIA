"""Contract lints over the prose specs (commands/ + skills/).

The commands and skills are executable specifications: LLM-generated artifacts
on one side, rigid regex consumers (statusline.py, weakmap, hwmap, alt) on the
other. These lints pin the contracts so a future edit can't silently
reintroduce the drift class fixed across v0.9.9–v0.9.21.
"""
from __future__ import annotations

import unittest

from fixtures import COMMANDS, REPO, SCRIPTS, SKILLS

import paideia_lib as plib

# Lines that legitimately NAME the retired vocabulary (to ban it) are allowed;
# anything else is a regression.
_ALLOW_MARKERS = ("retired", "do NOT emit")


def spec_files():
    return sorted(list(COMMANDS.glob("*.md")) + list(SKILLS.rglob("*.md")))


class TestRetiredTierVocabulary(unittest.TestCase):
    def test_no_retired_markers_outside_ban_notices(self):
        offenders = []
        for f in spec_files():
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if any(tok in line for tok in ("✅✅", "🔴", "Critical Blind", "Critical column")):
                    if not any(m in line for m in _ALLOW_MARKERS):
                        offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()[:80]}")
        self.assertEqual(offenders, [],
                         "retired ✅/🔴 coverage vocabulary resurfaced:\n" + "\n".join(offenders))

    def test_canonical_tiers_present_where_expected(self):
        coverage_spec = (SKILLS / "course-builder" / "SKILL.md").read_text(encoding="utf-8")
        for tok in ("🔥🔥", "⚪", "⚠weak"):
            self.assertIn(tok, coverage_spec)
        analyze = (COMMANDS / "analyze.md").read_text(encoding="utf-8")
        for tok in ("🔥🔥 Exam-primary", "⚠weak"):
            self.assertIn(tok, analyze)


class TestCommandInventory(unittest.TestCase):
    def test_sixteen_commands(self):
        self.assertEqual(len(list(COMMANDS.glob("*.md"))), 16)

    def test_hwmap_blind_not_recommended_anywhere(self):
        """`/hwmap blind` is a legacy alias for HOT — recommending it as a
        blind-spot review sends users to the opposite of what's promised."""
        offenders = []
        for f in spec_files():
            text = f.read_text(encoding="utf-8")
            if "hwmap blind" in text:
                offenders.append(str(f.relative_to(REPO)))
        self.assertEqual(offenders, [])


class TestAnchors(unittest.TestCase):
    """Literal section anchors that python/regex consumers depend on."""

    def test_weakmap_anchors(self):
        text = (COMMANDS / "weakmap.md").read_text(encoding="utf-8")
        for anchor in ("## One-line verdict", "## Top 5 weaknesses",
                       "## User-declared weaknesses", "weakmap_<YYYY-MM-DD_HHmm>.md"):
            self.assertIn(anchor, text)

    def test_canonical_drill_timestamp(self):
        text = (SKILLS / "exam-drill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("date +%Y%m%d_%H%M%S", text)

    def test_error_schema_keys_everywhere(self):
        for rel in ("commands/blind.md", "skills/answer-processing/SKILL.md",
                    "skills/exam-drill/SKILL.md"):
            text = (REPO / "plugins" / "paideia" / rel).read_text(encoding="utf-8")
            for key in ("problem_id:", "pattern:", "error_type:", "summary:",
                        "source:", "date:"):
                self.assertIn(key, text, f"{rel} lost schema key {key}")


class TestLogToolRouting(unittest.TestCase):
    def test_every_log_writer_routes_through_log_tool(self):
        for rel in ("commands/grade.md", "commands/blind.md",
                    "skills/answer-processing/SKILL.md",
                    "skills/exam-drill/SKILL.md"):
            text = (REPO / "plugins" / "paideia" / rel).read_text(encoding="utf-8")
            self.assertIn("log_tool.py", text, f"{rel} must write via log_tool.py")


class TestSeedParity(unittest.TestCase):
    def test_init_course_heredoc_matches_lib_seed(self):
        ic = (COMMANDS / "init-course.md").read_text(encoding="utf-8")
        heredoc = ic.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0] + "\n"
        self.assertEqual(heredoc, plib.ERRORS_LOG_SEED,
                         "init-course seed drifted from paideia_lib.ERRORS_LOG_SEED")


class TestIngestChunking(unittest.TestCase):
    def test_page_cap_and_padding(self):
        for rel in ("commands/ingest.md", "skills/pdf/VISION.md"):
            text = (REPO / "plugins" / "paideia" / rel).read_text(encoding="utf-8")
            self.assertIn("30 pages", text, f"{rel} lost the per-agent page cap")
            self.assertIn("p{i:03d}", text, f"{rel} lost 3-digit page padding")
            self.assertNotIn("p{i:02d}.png", text.replace("with `p{i:02d}`", ""))


class TestScriptsInventory(unittest.TestCase):
    def test_shared_lib_is_the_only_meta_parser(self):
        """Exactly one definition of the .course-meta parser may exist."""
        definers = []
        for py in SCRIPTS.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            if "def parse_meta(" in src:
                definers.append(py.name)
        self.assertEqual(definers, ["paideia_lib.py"], definers)


if __name__ == "__main__":
    unittest.main()
