"""Contract lints over the prose specs (commands/ + skills/).

The commands and skills are executable specifications: LLM-generated artifacts
on one side, rigid regex consumers (statusline.py, weakmap, hwmap, alt) on the
other. These lints pin the contracts so a future edit can't silently
reintroduce the drift class fixed across v0.9.9–v0.9.21.
"""
from __future__ import annotations

import json
import re
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
    def test_eighteen_commands(self):
        self.assertEqual(len(list(COMMANDS.glob("*.md"))), 18)

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

    def test_grade_4bpre_has_tty_branch(self):
        """B1: grade.md 4b-pre must contain the non-interactive auto-provision path."""
        self.assertIn("--ensure-verify", self.grade,
                      "grade.md 4b-pre must reference --ensure-verify for headless auto-provisioning")
        # Must have either 'test -t 0' or 'non-interactive' phrasing
        has_tty_check = ("test -t 0" in self.grade or "non-interactive" in self.grade
                         or "Non-interactive" in self.grade)
        self.assertTrue(has_tty_check,
                        "grade.md 4b-pre must document the TTY/non-interactive branch gate")

    def test_grade_writes_verify_badge_file(self):
        """B3: grade.md must document per-step SymPy badge file at answers/converted/<stem>.verify.json."""
        self.assertIn(".verify.json", self.grade,
                      "grade.md must reference the .verify.json per-step badge file")
        self.assertIn("answers/converted", self.grade,
                      "grade.md must write the badge to answers/converted/ directory")

    def test_verify_badge_is_additive_anchor(self):
        """B4: grade.md must state the badge is additive and does not replace existing contracts."""
        self.assertIn("additive", self.grade,
                      "grade.md must declare the verify badge file as a new additive anchor")
        # The badge must not be claimed to replace GRADE_RECORD_JSON
        self.assertIn("GRADE_RECORD_JSON", self.grade,
                      "grade.md must still reference GRADE_RECORD_JSON anchor (not replaced)")

    def test_grade_headless_demotion_badge_en(self):
        """B1: grade.md must include the headless-specific demotion badge text (en)."""
        self.assertIn("Symbolic verify auto-provision failed in non-interactive run", self.grade,
                      "grade.md must include English headless demotion message")

    def test_grade_headless_demotion_badge_ko(self):
        """B1: grade.md must include the headless-specific demotion badge text (ko)."""
        self.assertIn("비대화형 실행에서 기호 검산 자동 설치 실패", self.grade,
                      "grade.md must include Korean headless demotion message")

    def test_sympy_table_header_is_exactly_six_columns(self):
        """T-GRADE-BADGE-EMIT AC-1: The SymPy table header must be exactly 6 columns in the
        canonical order P#, Pattern, Vars, SymPy, End form, Overall.
        A 5-column collapse (SymPy column omitted) must fail this check."""
        import re
        # Find the canonical header line (must contain all 6 headers and pipe delimiters)
        expected = ["P#", "Pattern", "Vars", "SymPy", "End form", "Overall"]
        header_lines = [
            l for l in self.grade.splitlines()
            if "|" in l and "SymPy" in l and "P#" in l and "Pattern" in l
        ]
        self.assertTrue(header_lines,
                        "grade.md must have a pipe-delimited table header row containing P#, Pattern, SymPy")
        # Check that the first matching header line has exactly the 6 expected columns
        header = header_lines[0]
        cells = [c.strip() for c in header.split("|") if c.strip()]
        self.assertEqual(cells, expected,
                         f"grade.md table header must be exactly {expected}, got {cells}. "
                         "A 5-column collapse omitting SymPy is FORBIDDEN.")

    def test_grade_forbids_five_column_collapse(self):
        """T-GRADE-BADGE-EMIT AC-1: grade.md must explicitly prohibit collapsing to a
        5-column table or substituting SymPy results with prose."""
        has_forbidden = "FORBIDDEN" in self.grade
        self.assertTrue(has_forbidden,
                        "grade.md must contain 'FORBIDDEN' keyword explicitly prohibiting "
                        "5-column table collapse or prose substitution of SymPy column")
        # Also verify that the prohibition mentions the SymPy column context
        forbidden_idx = self.grade.index("FORBIDDEN")
        context = self.grade[max(0, forbidden_idx - 200):forbidden_idx + 200]
        has_five_col = "5-column" in context or "five column" in context.lower() or "prose" in context
        self.assertTrue(has_five_col,
                        "The FORBIDDEN clause in grade.md must reference 5-column collapse or prose substitution")

    def test_grade_badge_is_mandatory_not_optional(self):
        """T-GRADE-BADGE-EMIT AC-2: grade.md 4c must declare badge write as MANDATORY/MUST-EMIT,
        covering both verify_modes including llm-only."""
        has_must_emit = "MUST-EMIT" in self.grade or "MANDATORY" in self.grade
        self.assertTrue(has_must_emit,
                        "grade.md must contain MUST-EMIT or MANDATORY language making badge write mandatory")
        # Verify it covers llm-only explicitly
        self.assertIn("MUST write", self.grade,
                      "grade.md must include 'MUST write' language for badge file (even for llm-only)")
        # Verify it requires badge before step 5
        has_before_step5 = "before rendering the grade table" in self.grade or "before step 5" in self.grade.lower() or "before the grade table" in self.grade
        self.assertTrue(has_before_step5,
                        "grade.md must require badge write BEFORE the grade table (step 5)")

    def test_grade_has_badge_selfcheck_gate(self):
        """T-GRADE-BADGE-EMIT AC-3: grade.md must include a self-check gate that verifies
        the badge file exists after writing it, using 'test -f' and '.verify.json'."""
        self.assertIn("test -f", self.grade,
                      "grade.md must include 'test -f' for badge existence self-check")
        # The test -f must reference a .verify.json file
        import re
        testf_matches = [l for l in self.grade.splitlines() if "test -f" in l and ".verify.json" in l]
        self.assertTrue(testf_matches,
                        "grade.md must have a 'test -f ... .verify.json' self-check gate line")

    def test_grade_badge_selfcheck_has_en_ko_warnings(self):
        """T-GRADE-BADGE-EMIT AC-3 i18n: The badge self-check failure path must have en+ko warning text."""
        self.assertIn("Badge file write failed", self.grade,
                      "grade.md must include English badge write failure warning text")
        self.assertIn("배지 파일 쓰기 실패", self.grade,
                      "grade.md must include Korean badge write failure warning text")

    def test_grade_single_call_three_views(self):
        """T-GRADE-BADGE-EMIT AC-4: grade.md must declare that SymPy column, badge checks[],
        and GRADE_RECORD_JSON steps[].sympy.result all derive from a single verify_tool.py call."""
        has_single_call = "single" in self.grade.lower() and "three views" in self.grade.lower()
        self.assertTrue(has_single_call,
                        "grade.md must state the 'single call, three views' invariant for verify_tool.py results")


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

    def test_initcourse_step3b_has_tty_branch(self):
        """D1: init-course.md Step 3b must have non-interactive auto-provisioning path."""
        self.assertIn("--ensure-verify", self.ic,
                      "init-course.md Step 3b must reference --ensure-verify for headless path")
        has_tty = ("test -t 0" in self.ic or "non-interactive" in self.ic
                   or "Non-interactive" in self.ic)
        self.assertTrue(has_tty,
                        "init-course.md Step 3b must document TTY/non-interactive branch")
        # en/ko prompts must still be present (preserved for TTY sessions)
        self.assertIn("Symbolic (SymPy) grading is not installed", self.ic,
                      "init-course.md must retain English opt-out prompt for TTY path")
        self.assertIn("기호(SymPy) 검산이 미설치입니다", self.ic,
                      "init-course.md must retain Korean opt-out prompt for TTY path")


class TestGraphCommand(unittest.TestCase):
    """Spec-lint: graph.md contract anchors (FND-023, FND-029)."""

    def setUp(self):
        self.graph = (COMMANDS / "graph.md").read_text(encoding="utf-8")

    def test_graph_command_exists(self):
        self.assertTrue((COMMANDS / "graph.md").exists(),
                        "commands/graph.md must exist for /paideia:graph")

    def test_graph_single_mermaid_fence_rule(self):
        """FND-023 regression guard: spec must mandate exactly one closing fence."""
        text = self.graph
        # Must contain the single-fence rule or double-fence prohibition
        has_single_rule = ("exactly one" in text and "fence" in text)
        has_double_ban = ("double" in text.lower() and "fence" in text.lower())
        self.assertTrue(has_single_rule or has_double_ban,
                        "graph.md must mandate a single mermaid fence and/or ban double fences (FND-023)")

    def test_graph_interface_lang_labels(self):
        """Node labels must follow INTERFACE_LANG, not be hardcoded to English."""
        self.assertIn("INTERFACE_LANG", self.graph,
                      "graph.md must reference INTERFACE_LANG for node labels")
        # Must be explicit that labels follow the course language
        has_lang_label = ("node label" in self.graph.lower() or "labels" in self.graph.lower())
        self.assertTrue(has_lang_label,
                        "graph.md must mention that node labels follow INTERFACE_LANG")

    def test_graph_wikilink_contract(self):
        """Obsidian wikilink interoperability must be specified."""
        self.assertIn("[[", self.graph,
                      "graph.md must specify wikilink [[…]] node annotation (Obsidian interop)")

    def test_graph_document_order_ids(self):
        """C-IDs must be document-order deterministic."""
        self.assertIn("document", self.graph.lower(),
                      "graph.md must specify document-order ID assignment")
        self.assertIn("C1", self.graph,
                      "graph.md must reference the C1..Cn ID scheme")

    def test_graph_no_fan_out_by_default(self):
        """Default path must NOT fan out to converted/ — index-shortcut only."""
        self.assertIn("index", self.graph.lower(),
                      "graph.md must describe the index-shortcut default path")
        self.assertIn("--rebuild", self.graph,
                      "graph.md must gate converted/ fan-out behind --rebuild flag")


class TestManifestConsistency(unittest.TestCase):
    """Pin plugin.json / marketplace.json version + command-count so a feature
    commit can't add a command without bumping the manifest (release contract).

    Regression guard for defect-1: /reindex + /graph were added but the manifest
    still advertised '16 slash commands' at rc.25 while the READMEs said 18.
    """

    PLUGIN_JSON = REPO / "plugins" / "paideia" / ".claude-plugin" / "plugin.json"
    MARKETPLACE_JSON = REPO / ".claude-plugin" / "marketplace.json"
    _SEMVER_RC_RX = re.compile(r"^1\.0\.0-rc\.\d+$")

    def setUp(self):
        self.plugin = json.loads(self.PLUGIN_JSON.read_text(encoding="utf-8"))
        self.market = json.loads(self.MARKETPLACE_JSON.read_text(encoding="utf-8"))
        self.market_entry = next(
            p for p in self.market["plugins"] if p["name"] == "paideia"
        )
        self.n_commands = len(list(COMMANDS.glob("*.md")))

    def test_plugin_version_is_wellformed_rc(self):
        self.assertRegex(self.plugin["version"], self._SEMVER_RC_RX,
                         "plugin.json version must be a 1.0.0-rc.N release string")

    def test_marketplace_version_matches_plugin(self):
        self.assertEqual(self.market_entry["version"], self.plugin["version"],
                         "marketplace.json version must equal plugin.json version "
                         "(the two manifests must be bumped together)")

    def test_plugin_description_command_count_matches_disk(self):
        """plugin.json description must advertise the true on-disk command count."""
        desc = self.plugin["description"]
        m = re.search(r"(\d+) slash commands", desc)
        self.assertIsNotNone(m, "plugin.json description must state 'N slash commands'")
        self.assertEqual(int(m.group(1)), self.n_commands,
                         f"plugin.json says {m.group(1)} slash commands but "
                         f"{self.n_commands} exist on disk")

    def test_marketplace_description_command_count_matches_disk(self):
        """marketplace.json description must advertise the true on-disk count."""
        desc = self.market_entry["description"]
        m = re.search(r"(\d+) commands", desc)
        self.assertIsNotNone(m, "marketplace.json description must state 'N commands'")
        self.assertEqual(int(m.group(1)), self.n_commands,
                         f"marketplace.json says {m.group(1)} commands but "
                         f"{self.n_commands} exist on disk")

    def test_new_commands_advertised_in_plugin_description(self):
        """A shipped command must be discoverable from the manifest changelog.
        Guards the specific defect: /reindex and /graph were added silently."""
        desc = self.plugin["description"]
        for cmd in ("/paideia:reindex", "/paideia:graph"):
            self.assertIn(cmd, desc,
                          f"plugin.json description must mention {cmd} "
                          "(new commands require a manifest changelog clause)")


class TestReindexCommand(unittest.TestCase):
    """Spec-lint: reindex.md contract anchors (defect-1 coverage)."""

    def setUp(self):
        self.reindex = (COMMANDS / "reindex.md").read_text(encoding="utf-8")

    def test_reindex_command_exists(self):
        self.assertTrue((COMMANDS / "reindex.md").exists(),
                        "commands/reindex.md must exist for /paideia:reindex")

    def test_reindex_no_analyze(self):
        """Reindex must explicitly state it does NOT run analyze."""
        text = self.reindex.lower()
        self.assertIn("analyze", text,
                      "reindex.md must mention analyze (to ban it)")
        # Must contain a negation of analyze invocation
        has_no_analyze = (
            "does not run" in text or
            "not run" in text or
            "without running" in text or
            "no sub-agent" in text or
            "no fan-out" in text
        )
        self.assertTrue(has_no_analyze,
                        "reindex.md must explicitly state it does not invoke analyze/sub-agents")

    def test_reindex_atomic_write(self):
        """Atomic write contract must be stated."""
        self.assertIn("atomic", self.reindex.lower(),
                      "reindex.md must specify atomic write (tmp + os.replace pattern)")

    def test_reindex_byte_preserving(self):
        """Data byte-preservation contract must be stated."""
        self.assertIn("byte", self.reindex.lower(),
                      "reindex.md must state data entries are byte-preserved")

    def test_reindex_idempotent(self):
        """Idempotence must be stated."""
        self.assertIn("idempotent", self.reindex.lower(),
                      "reindex.md must state idempotence guarantee")

    def test_reindex_course_mode_gate(self):
        """course-meta gate must be documented."""
        self.assertIn(".course-meta", self.reindex,
                      "reindex.md must document the .course-meta course-mode gate")

    def test_reindex_interface_lang(self):
        """INTERFACE_LANG must be referenced."""
        self.assertIn("INTERFACE_LANG", self.reindex,
                      "reindex.md must reference INTERFACE_LANG for output language")


if __name__ == "__main__":
    unittest.main()
