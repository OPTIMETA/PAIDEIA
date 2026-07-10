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


class TestAnalyzeFanOut(unittest.TestCase):
    """Lints for the analyze fan-out / partial-commit spec (canonical, TKT-ANALYZE-BUDGET-PARTIAL-COMMIT).

    Pins the *canonical* mechanisms — per-FILE parallel fan-out (FND-002),
    `.partial` atomic writes, and the `<!-- COVERAGE: … -->` telemetry — and bans
    the forked K=8/T=30/--full/deferred-comment constructs that once diverged from
    the OPTIMETA vendored corpus. Cadence wording is pinned across both files.
    """

    def setUp(self):
        self.analyze = (COMMANDS / "analyze.md").read_text(encoding="utf-8")
        self.skill = (SKILLS / "course-builder" / "SKILL.md").read_text(encoding="utf-8")

    # AC-1 — per-FILE parallel fan-out (NOT a single sequential-read agent per batch).
    def test_per_file_parallel_fanout(self):
        self.assertIn("Task sub-agent **per file**", self.analyze,
                      "analyze.md must fan out one Task sub-agent PER FILE (ingest precedent, FND-002)")
        self.assertIn("single-pass over the full converted directory is forbidden", self.analyze,
                      "analyze.md must forbid the single-pass design that caused the SIGTERM")
        # The defeating 'one sub-agent per BATCH reading sequentially' model must NOT resurface.
        self.assertNotIn("one sub-agent per batch", self.analyze.lower(),
                         "per-BATCH sequential-read model defeats early batch-1 flush (issue #3)")
        self.assertIn("parallel batches sized to the concurrency ceiling", self.skill,
                      "SKILL.md must describe parallel per-file batches, not a per-batch serial reader")

    # AC-2 — `.partial` atomic-write convention is the artifact the acceptance gate counts.
    def test_partial_atomic_writes(self):
        for scratch in ("summary.md.partial", "patterns.md.partial", "coverage.md.partial"):
            self.assertIn(scratch, self.analyze,
                          f"analyze.md must write {scratch} scratch then rename (atomic write)")
        self.assertIn("then rename to the final path", self.analyze,
                      "analyze.md must rename the .partial scratch to the final path")
        self.assertIn("`.partial` then rename", self.skill,
                      "SKILL.md must state the .partial-then-rename atomic convention")

    # AC-3 — COVERAGE telemetry comment (files=/partial= signal the gate reads).
    def test_coverage_metadata_comment(self):
        self.assertIn("<!-- COVERAGE: files=", self.analyze,
                      "analyze.md must emit the <!-- COVERAGE: files=A/N, partial=… --> telemetry")
        self.assertIn("partial=", self.analyze,
                      "analyze.md COVERAGE comment must carry the partial= flag")

    # AC-4 — Reduce entered as soon as one batch completes (early partial flush guarantee).
    def test_reduce_enters_on_first_batch(self):
        self.assertIn("The Reduce phase (Steps 1–3) must be entered even if not all fan-out agents have completed",
                      self.analyze,
                      "analyze.md must mandate entering Reduce before all agents finish")
        self.assertIn("as soon as any batch completes", self.skill,
                      "SKILL.md must state Reduce is entered as soon as any batch completes")

    # AC-5 — canonical subset flags (no forked --full / auto-narrow).
    def test_canonical_subset_flags(self):
        front = self.analyze.split("---", 2)[1]
        for flag in ("--files=", "--since=", "--lectures-only"):
            self.assertIn(flag, front, f"analyze.md argument-hint must list {flag}")
            self.assertIn(flag, self.analyze, f"analyze.md body must reference {flag}")
        self.assertIn("--files=", self.skill)
        self.assertIn("--since=", self.skill)
        self.assertIn("--lectures-only", self.skill)

    # AC-6 — 6-key schema / canonical tier vocabulary intact.
    def test_six_key_schema_headers_unchanged(self):
        for header in ("Problem", "Primary §", "Secondary §",
                       "Patterns", "HW coverage", "Exam tier"):
            self.assertIn(header, self.analyze,
                          f"analyze.md must retain 6-key header '{header}'")
        # The full 4-tier vocabulary, not the forked '🔥 Exam-likely' ceiling.
        for tier in ("🔥🔥 Exam-primary", "🔥 Exam-likely", "🟡 Exam-possible", "⚪ Low-risk"):
            self.assertIn(tier, self.analyze,
                          f"analyze.md must carry canonical tier '{tier}'")

    # AC-7 — forked constructs must NOT resurface in either file.
    def test_forked_constructs_absent(self):
        for f, name in ((self.analyze, "analyze.md"), (self.skill, "course-builder/SKILL.md")):
            for token in ("K = 8", "T = 30", "--full", "Auto-narrow",
                          "auto-narrow", "deferred: solutions pass"):
                self.assertNotIn(token, f,
                                 f"{name} must not reintroduce forked construct '{token}' "
                                 "(sync FROM canonical, do not fork the spec)")

    # AC-8 — cadence wording pinned IDENTICALLY across both files (issue #7).
    def test_cadence_wording_shared_across_files(self):
        # Both spec files must agree on the partial-commit cadence via a shared phrase,
        # not a bare 'partial'/'batch' substring that lets the two drift.
        shared = "`.partial`"
        self.assertIn(shared, self.analyze, "analyze.md must name the .partial atomic scratch")
        self.assertIn(shared, self.skill, "SKILL.md must name the .partial atomic scratch")
        # Neither file may describe a 'flush after batch 1 then merge' vs 'rewrite after each
        # batch' split: the canonical intent is a single cadence — valid/merged state after
        # every batch, first flush on the first completed batch.
        self.assertNotIn("after batch 1 completes, immediately write", self.analyze)
        self.assertNotIn("After EACH batch completes, all three", self.skill)

    # AC-9 — i18n: $INTERFACE_LANG gating + verbatim-token note preserved.
    def test_interface_lang_gating(self):
        self.assertIn("$INTERFACE_LANG", self.analyze,
                      "analyze.md must gate user-facing prose on $INTERFACE_LANG")
        self.assertIn("verbatim", self.analyze,
                      "analyze.md must note that token identifiers stay verbatim")


class TestReadmeClaims(unittest.TestCase):
    """Facts the READMEs state about the repo must match the repo."""

    def test_command_count_claims(self):
        for name in ("README.md", "README.ko.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertNotIn("14 `/paideia:`", text, f"{name} stale command count")
            self.assertNotIn("14개의 `/paideia:`", text, f"{name} stale command count")

    def test_what_ships_lists_every_script(self):
        shipped = {p.name for p in SCRIPTS.glob("*.py")}
        for name in ("README.md", "README.ko.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            missing = [s for s in shipped if s not in text]
            self.assertEqual(missing, [], f"{name} What-ships tree missing {missing}")


if __name__ == "__main__":
    unittest.main()
