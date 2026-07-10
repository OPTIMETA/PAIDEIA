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

    def test_all_errorlog_headers_match_seed(self):
        """Every errors/log.md in the repo must have a header comment identical
        to the canonical ERRORS_LOG_SEED header block.  This catches the
        header/data drift fixed by FND-012 (source key undeclared in header).
        """
        # Extract the canonical '<!-- … -->' block from the seed.
        seed = plib.ERRORS_LOG_SEED
        s_start = seed.find("<!--")
        s_end = seed.find("-->", s_start) + 3
        canonical_header = seed[s_start:s_end]

        def _live_header(text: str) -> str:
            start = text.find("<!--")
            if start == -1:
                return ""
            end = text.find("-->", start)
            if end == -1:
                return ""
            return text[start:end + 3]

        # Walk repo root + demo-run for all errors/log.md files.
        repo_root = REPO.parent  # PAIDEIA repo root (one level above PAIDEIA/)
        offenders = []
        for log_path in sorted(repo_root.rglob("errors/log.md")):
            # Skip node_modules or other tooling artefacts.
            if any(p.name in ("node_modules", ".git", "target") for p in log_path.parents):
                continue
            text = log_path.read_text(encoding="utf-8", errors="replace")
            live = _live_header(text)
            if live != canonical_header:
                offenders.append(
                    f"{log_path.relative_to(repo_root)}: header differs from seed\n"
                    f"  expected: {canonical_header[:60]!r}…\n"
                    f"  got:      {live[:60]!r}…"
                )
        self.assertEqual(offenders, [],
                         "errors/log.md header drift detected:\n" + "\n".join(offenders))


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

    # AC-10 — first-batch cap: analyze.md and SKILL.md both anchor the small first-batch rule.
    def test_first_batch_cap(self):
        for anchor in ("first batch", "provably commit", "inside the standard window"):
            self.assertIn(anchor, self.analyze,
                          f"analyze.md must anchor first-batch cap with phrase '{anchor}'")
        self.assertIn("first batch", self.skill,
                      "SKILL.md must describe the small first-batch cap rule")
        self.assertIn("provably commits inside the window", self.skill,
                      "SKILL.md must state the first batch provably commits inside the window")
        # Ban K=8 / T=30 even as defense-in-depth (already covered by AC-7, repeated here).
        for token in ("K = 8", "T = 30"):
            self.assertNotIn(token, self.analyze,
                             f"analyze.md must not contain forked constant '{token}'")
            self.assertNotIn(token, self.skill,
                             f"SKILL.md must not contain forked constant '{token}'")

    # AC-11 — resume entry-point: argument-hint and body both carry --resume; force/resume exclusion stated.
    def test_resume_entrypoint(self):
        front = self.analyze.split("---", 2)[1]
        self.assertIn("--resume", front,
                      "analyze.md argument-hint (front-matter) must include --resume")
        self.assertIn("--resume", self.analyze,
                      "analyze.md body must reference --resume")
        self.assertIn("--force", self.analyze,
                      "analyze.md must document --force flag")
        # Mutual-exclusion wording must be present.
        self.assertIn("mutually exclusive", self.analyze,
                      "analyze.md must state --force and --resume are mutually exclusive")

    # AC-12 — resume procedure contract: not-yet-processed fan-out, merge, no re-read, partial=false goal.
    def test_resume_procedure_contract(self):
        self.assertIn("not-yet-processed", self.analyze,
                      "analyze.md resume must fan out only not-yet-processed files")
        self.assertIn("merge", self.analyze,
                      "analyze.md resume must merge into the existing index (not overwrite)")
        self.assertIn("do NOT re-read", self.analyze,
                      "analyze.md resume must forbid re-reading converted source files")
        self.assertIn("partial=false", self.analyze,
                      "analyze.md resume must target partial=false as the completion state")
        self.assertIn("files=A/N", self.analyze,
                      "analyze.md resume must update files=A/N in the COVERAGE comment")

    # AC-13 — rename completion contract: renames complete before next batch; no orphan .partial.
    def test_rename_completion_contract(self):
        # 'before' + 'next batch' must appear together in the rename obligation text.
        self.assertIn("before", self.analyze,
                      "analyze.md must state renames complete BEFORE the next batch spawns")
        self.assertIn("next batch", self.analyze,
                      "analyze.md must reference 'next batch' in the completion gate")
        self.assertIn("orphan", self.analyze,
                      "analyze.md must forbid leaving a .partial orphan (torn-file prevention)")
        # The .partial write literals must still be present (AC-2 regression guard).
        for scratch in ("summary.md.partial", "patterns.md.partial", "coverage.md.partial"):
            self.assertIn(scratch, self.analyze,
                          f"AC-13 regression: analyze.md must still carry {scratch}")

    # AC-14 — cadence sync: first-batch + resume sentences in SKILL.md; banned strings absent.
    def test_cadence_sync_first_batch_resume(self):
        # SKILL.md must carry both new sentences alongside existing cadence anchors.
        self.assertIn("first batch is capped small", self.skill,
                      "SKILL.md must carry first-batch cap sentence (cadence sync)")
        self.assertIn("--resume", self.skill,
                      "SKILL.md must mention --resume (cadence sync)")
        # Existing cadence anchors must still be present (regression guard for AC-8).
        self.assertIn("`.partial`", self.skill,
                      "SKILL.md cadence anchor `.partial` must still be present")
        self.assertIn("as soon as any batch completes", self.skill,
                      "SKILL.md must still carry 'as soon as any batch completes'")
        # Banned cadence strings must remain absent.
        self.assertNotIn("After EACH batch completes, all three", self.skill,
                         "SKILL.md must not contain banned cadence string")
        self.assertNotIn("after batch 1 completes, immediately write", self.analyze,
                         "analyze.md must not contain banned cadence string")


class TestLogToolOverride(unittest.TestCase):
    """Pin the override contract so prose specs can't silently lose the feature."""

    def test_grade_md_has_override_verb(self):
        text = (COMMANDS / "grade.md").read_text(encoding="utf-8")
        self.assertIn("override", text,
                      "grade.md must document the override subcommand")
        self.assertIn("overridden_by", text,
                      "grade.md must mention the overridden_by marker")

    def test_answer_processing_skill_has_override_verb(self):
        text = (SKILLS / "answer-processing" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("override", text,
                      "answer-processing/SKILL.md must document the override subcommand")
        self.assertIn("overridden_by", text,
                      "answer-processing/SKILL.md must mention the overridden_by marker")

    def test_paideia_lib_has_override_key_constant(self):
        text = (SCRIPTS / "paideia_lib.py").read_text(encoding="utf-8")
        self.assertIn("OVERRIDE_KEY", text,
                      "paideia_lib.py must define OVERRIDE_KEY constant")
        self.assertIn("overridden_by", text,
                      "paideia_lib.py must reference overridden_by in ERRORS_LOG_SEED")

    def test_six_required_keys_unchanged(self):
        """REQUIRED_KEYS in log_tool must still be the original six — override_key is optional."""
        import log_tool
        self.assertEqual(set(log_tool.REQUIRED_KEYS),
                         {"problem_id", "pattern", "error_type", "summary", "source", "date"},
                         "REQUIRED_KEYS must remain the canonical 6 keys")
        self.assertNotIn("overridden_by", log_tool.REQUIRED_KEYS,
                         "overridden_by must NOT be a required key")


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


class TestGradeVerifyBadge(unittest.TestCase):
    """C3 spec-lint: grade.md must expose SymPy column and demotion badge (C2)."""

    def setUp(self):
        self.grade = (COMMANDS / "grade.md").read_text(encoding="utf-8")

    def test_sympy_column_in_table_header(self):
        self.assertIn("SymPy", self.grade,
                      "grade.md table header must include the SymPy column")
        # Ensure it appears in the markdown table row (pipe-delimited)
        import re
        table_line = [l for l in self.grade.splitlines() if "SymPy" in l and "|" in l]
        self.assertTrue(table_line,
                        "grade.md must have a pipe-delimited table row containing 'SymPy'")

    def test_grade_consumes_verify_reachable_or_verify_mode(self):
        has_reachable = "verify_reachable" in self.grade
        has_mode = "verify_mode" in self.grade
        self.assertTrue(has_reachable or has_mode,
                        "grade.md must reference verify_reachable or verify_mode")

    def test_llm_only_demotion_badge_en(self):
        self.assertIn("Symbolic verification off", self.grade,
                      "grade.md must include English demotion badge text "
                      "'Symbolic verification off'")

    def test_llm_only_demotion_badge_ko(self):
        self.assertIn("기호 검산 꺼짐", self.grade,
                      "grade.md must include Korean demotion badge text '기호 검산 꺼짐'")

    def test_sympy_in_header_english_fixed_list(self):
        """L8 English-fixed header list must include SymPy."""
        self.assertIn("SymPy", self.grade,
                      "grade.md output-language rule must list SymPy as an English-fixed header")

    def test_opt_out_default_is_capital_Y(self):
        """4b-pre prompt default must be [Y/n] (capital Y = install), not [y/N]."""
        self.assertIn("[Y/n]", self.grade,
                      "grade.md 4b-pre prompt must use [Y/n] (install by default)")
        # Ensure the old [y/N] opt-in form is gone
        self.assertNotIn("[y/N]", self.grade,
                         "grade.md must not contain old [y/N] opt-in form")


class TestInitCourseVerifyStep(unittest.TestCase):
    """C3 spec-lint: init-course.md must contain Step 3b with verify plumbing (C1)."""

    def setUp(self):
        self.ic = (COMMANDS / "init-course.md").read_text(encoding="utf-8")

    def test_step_3b_present(self):
        self.assertIn("Step 3b", self.ic,
                      "init-course.md must contain Step 3b for symbolic grading setup")

    def test_install_verify_flag_referenced(self):
        self.assertIn("--install-verify", self.ic,
                      "init-course.md Step 3b must reference --install-verify flag")

    def test_verify_reachable_probe_consumed(self):
        self.assertIn("verify_reachable", self.ic,
                      "init-course.md Step 3b must consume verify_reachable from doctor --json")

    def test_opt_out_prompt_en(self):
        self.assertIn("[Y/n]", self.ic,
                      "init-course.md Step 3b must have [Y/n] opt-out prompt (en)")

    def test_both_languages_present(self):
        # en prompt
        self.assertIn("Symbolic (SymPy) grading is not installed", self.ic,
                      "init-course.md must have English opt-out prompt text")
        # ko prompt
        self.assertIn("기호(SymPy) 검산이 미설치입니다", self.ic,
                      "init-course.md must have Korean opt-out prompt text")

    def test_nonblocking_on_failure(self):
        """Step 3b must not block bootstrap on install failure."""
        self.assertIn("does **not** block", self.ic,
                      "init-course.md must state that install failure does not block bootstrap")

    def test_skip_message_en(self):
        self.assertIn("Skipped — grading will use LLM-only", self.ic,
                      "init-course.md must have English skip message")

    def test_skip_message_ko(self):
        self.assertIn("건너뜀 —", self.ic,
                      "init-course.md must have Korean skip message")


if __name__ == "__main__":
    unittest.main()
