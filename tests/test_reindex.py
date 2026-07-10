"""Tests for scripts/reindex.py — idempotent coverage.md marker rewrite and
errors/log.md facet materialization.

Convention mirrors test_doctor.py / test_log_tool.py:
- stdlib only (no pytest)
- tmp course fixtures via tempfile.TemporaryDirectory
- imports reindex module directly
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import SCRIPTS

sys.path.insert(0, str(SCRIPTS))
import paideia_lib as plib
import reindex

try:
    import yaml  # PyYAML — present in dev env; the plugin scripts themselves are
    _HAVE_YAML = True  # stdlib-only, so the round-trip check is a bonus gate.
except ImportError:  # pragma: no cover - env without PyYAML
    _HAVE_YAML = False


SEED_HEADER = plib.ERRORS_LOG_SEED


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_course(tmp: Path, with_meta: bool = True) -> Path:
    if with_meta:
        (tmp / ".course-meta").write_text(
            "COURSE_NAME: Test\nEXAM_DATE: 2026-12-01\nINTERFACE_LANG: en\n",
            encoding="utf-8",
        )
    (tmp / "course-index").mkdir(exist_ok=True)
    (tmp / "errors").mkdir(exist_ok=True)
    return tmp


def _write_coverage(tmp: Path, text: str) -> Path:
    p = tmp / "course-index" / "coverage.md"
    p.write_text(text, encoding="utf-8")
    return p


def _write_log(tmp: Path, text: str) -> Path:
    p = tmp / "errors" / "log.md"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1 — coverage retired → canonical
# ---------------------------------------------------------------------------

class TestCoverageRetiredToCanonical(unittest.TestCase):
    """After --fix, coverage.md must contain zero retired markers."""

    MIXED_COVERAGE = """\
| § | Title | HW coverage | Exam tier |
|---|---|---|---|
| §1 | Intro | hw1(3) | ✅✅ |
| §2 | Limits | hw2(2) | ✅ |
| §3 | Weak section | hw3(1) | 🔴 ⚠weak |
| §4 | Skipped | hw0(0) | 🔴🔴 |
| §5 | Already done | hw5(5) | 🔥🔥 |
"""

    def test_retired_markers_gone_after_fix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.MIXED_COVERAGE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            for retired in ("✅✅", "✅", "🔴🔴", "🔴"):
                self.assertNotIn(retired, result,
                                 f"retired marker {retired!r} still present after fix")

    def test_canonical_markers_present_after_fix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.MIXED_COVERAGE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            for canonical in ("🔥🔥", "🔥", "🟡", "⚪"):
                self.assertIn(canonical, result,
                              f"canonical marker {canonical!r} missing after fix")


# ---------------------------------------------------------------------------
# Test 2 — data byte-preserving
# ---------------------------------------------------------------------------

class TestCoverageDataBytePreserved(unittest.TestCase):
    """§, Title, HW coverage cells, ⚠weak, table header must be byte-identical."""

    COVERAGE_TEXT = """\
| § | Title | HW coverage | Exam tier |
|---|---|---|---|
| §1 | Fourier Series | hw1(3/5) | ✅✅ |
| §2 | Green Theorem | hw2(1/2) ⚠weak | 🔴 |
"""

    def test_data_cells_byte_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.COVERAGE_TEXT)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            # Data cells must be byte-preserved
            self.assertIn("§1", result)
            self.assertIn("Fourier Series", result)
            self.assertIn("hw1(3/5)", result)
            self.assertIn("§2", result)
            self.assertIn("Green Theorem", result)
            self.assertIn("hw2(1/2)", result)
            self.assertIn("⚠weak", result)
            # Table header preserved
            self.assertIn("| § | Title | HW coverage | Exam tier |", result)


# ---------------------------------------------------------------------------
# Test 2b — rewrite is scoped to the Exam-tier column (data cells with a
#           retired glyph must survive byte-for-byte). Regression for defect-2.
# ---------------------------------------------------------------------------

class TestCoverageRewriteTierColumnScoped(unittest.TestCase):
    """A retired glyph living in a DATA cell (e.g. a section title) must NOT be
    rewritten — only the last (Exam-tier) cell is in scope (reindex.md:26)."""

    # §7 title deliberately contains a retired ✅ glyph; tier cell is 🔥 (already
    # canonical). Whole-line replace would corrupt the title ✅ → 🔥; the scoped
    # rewrite must leave the title byte-identical.
    TITLE_GLYPH_CANONICAL_TIER = (
        "| § | Title | HW coverage | Exam tier |\n"
        "|---|---|---|---|\n"
        "| §7 | Checklist ✅ done | hw7(2) | 🔥 |\n"
    )

    def test_data_cell_glyph_preserved_when_tier_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.TITLE_GLYPH_CANONICAL_TIER)
            before = p.read_text(encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            after = p.read_text(encoding="utf-8")
            # Tier already canonical AND the only retired glyph is in a data cell
            # → nothing in scope → zero rewrites, file byte-identical (idempotent).
            self.assertEqual(count, 0,
                             "a retired glyph in a data cell must not count as needing rewrite")
            self.assertEqual(before, after,
                             "data-cell glyph + canonical tier → byte-identical (no whole-line replace)")
            # The title glyph must still be the retired ✅, NOT rewritten to 🔥.
            self.assertIn("Checklist ✅ done", after,
                          "section-title ✅ was corrupted by an out-of-scope rewrite")
            self.assertNotIn("Checklist 🔥 done", after,
                             "title ✅ must not be rewritten to 🔥 (whole-line replace regression)")

    # Adversarial: title carries a retired ✅ AND the tier cell is retired ✅✅.
    # Only the tier cell must be rewritten (✅✅ → 🔥🔥); the title ✅ survives.
    TITLE_GLYPH_RETIRED_TIER = (
        "| § | Title | HW coverage | Exam tier |\n"
        "|---|---|---|---|\n"
        "| §7 | Checklist ✅ done | hw7(2) | ✅✅ |\n"
    )

    def test_only_tier_cell_rewritten_data_cell_glyph_survives(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.TITLE_GLYPH_RETIRED_TIER)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertEqual(count, 1, "exactly one row (the tier cell) needed rewrite")
            after = p.read_text(encoding="utf-8")
            # Tier cell rewritten…
            self.assertIn("| 🔥🔥 |", after, "tier cell ✅✅ must become 🔥🔥")
            # …title ✅ preserved (not swept into the tier substitution).
            self.assertIn("Checklist ✅ done", after,
                          "title ✅ must survive the tier-scoped rewrite")
            self.assertNotIn("Checklist 🔥 done", after,
                             "title ✅ must not be rewritten (tier-column scope violated)")

    def test_scoped_rewrite_is_idempotent(self):
        """Running --fix twice on the title-glyph case is a no-op the 2nd time
        (and the first pass rewrites only the tier cell)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.TITLE_GLYPH_RETIRED_TIER)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
                after1 = p.read_text(encoding="utf-8")
                count2, _ = reindex._process_coverage(p, fix=True)
                after2 = p.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)
            self.assertEqual(count2, 0, "second pass must find nothing to rewrite")
            self.assertEqual(after1, after2, "scoped rewrite is idempotent")


# ---------------------------------------------------------------------------
# Test 2c — tier-not-last-column rows (regression guard for P11-loop3 defect)
# ---------------------------------------------------------------------------

class TestCoverageTierNotLastColumn(unittest.TestCase):
    """When the Exam-tier column is NOT the last populated column (e.g. a
    Reverse-map row has extra annotation columns like 'notes' or 'L2' after the
    tier), the rewrite must still target the correct Exam-tier cell — not the
    last populated cell — and dry-run must NOT report 'already canonical' (exit 1
    while retired markers survive).

    Verified defect: `_rewrite_coverage_line('| §1.6 | Title | ✅ | L2 |\\n')`
    returned the input UNCHANGED (False) under the old 'last populated cell'
    heuristic, and `_process_coverage` returned retired_count=0 → false exit 0.
    """

    # Tier column (3rd data column, pipe-split index 3) is NOT the last populated.
    # The 'Notes' column (index 4) comes after it.
    TIER_NOT_LAST_HEADER = (
        "| § | Title | Exam tier | Notes |\n"
        "|---|---|---|---|\n"
    )

    def _coverage_with_header(self, *data_rows: str) -> str:
        return self.TIER_NOT_LAST_HEADER + "".join(data_rows)

    # (a) basic: ✅ in tier, non-tier column after it
    def test_retired_checkmark_tier_not_last_rewritten(self):
        text = self._coverage_with_header("| §1.6 | Title | ✅ | L2 |\n")
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, text)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertEqual(count, 1, "tier ✅ in non-last column must count as needing rewrite")
            result = p.read_text(encoding="utf-8")
            self.assertIn("| 🔥 |", result, "tier cell ✅ must become 🔥")
            self.assertIn("L2", result, "notes column L2 must be byte-preserved")
            self.assertIn("Title", result, "Title cell must be byte-preserved")

    # (a') dry-run needs-fix: the exact false-exit-0 regression guard
    def test_dryrun_exits_needs_fix_for_tier_not_last(self):
        """Regression: old code returned retired_count=0 (→ exit 0 'already canonical')
        for `| §1.6 | Title | ✅ | L2 |`. Must now return count>0 (→ exit 1 needs-fix)."""
        text = self._coverage_with_header("| §1.6 | Title | ✅ | L2 |\n")
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, text)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=False)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertGreater(count, 0,
                               "dry-run must return count>0 (exit 1 needs-fix) for tier-not-last "
                               "row with retired marker — regression for false 'already canonical' exit 0")
            # File must be untouched (dry-run)
            self.assertEqual(p.read_text(encoding="utf-8"), text)

    # (a'') direct unit test of _rewrite_coverage_line — Verified Fault exact form
    def test_rewrite_line_direct_tier_not_last(self):
        """Direct guard for `_rewrite_coverage_line('| §1.6 | Title | ✅ | L2 |\\n')`.
        Old code: returned input UNCHANGED. Must now return ✅→🔥 with L2 preserved."""
        from reindex import _rewrite_coverage_line, _find_tier_col_idx
        lines_with_header = [
            "| § | Title | Exam tier | Notes |\n",
            "|---|---|---|---|\n",
        ]
        tier_col_idx = _find_tier_col_idx(lines_with_header)
        line = "| §1.6 | Title | ✅ | L2 |\n"
        out = _rewrite_coverage_line(line, tier_col_idx)
        self.assertNotEqual(out, line,
                            "✅ in non-last tier column must be rewritten (was left untouched — regression)")
        self.assertIn("🔥", out, "✅ must become 🔥")
        self.assertIn("L2", out, "non-tier L2 cell must be preserved")

    def test_all_four_retired_glyphs_rewritten_tier_not_last(self):
        """All four retired glyphs (✅✅, ✅, 🔴🔴, 🔴) must be rewritten in non-last-column tier."""
        pairs = [
            ("✅✅", "🔥🔥"),
            ("✅",   "🔥"),
            ("🔴🔴", "⚪"),
            ("🔴",   "🟡"),
        ]
        for retired, canonical in pairs:
            text = self._coverage_with_header(f"| §1 | Title | {retired} | notes |\n")
            with tempfile.TemporaryDirectory() as td:
                tmp = _make_course(Path(td))
                p = _write_coverage(tmp, text)
                old_cwd = Path.cwd()
                os.chdir(tmp)
                try:
                    count, err = reindex._process_coverage(p, fix=True)
                finally:
                    os.chdir(old_cwd)
                self.assertFalse(err)
                self.assertEqual(count, 1, f"tier {retired!r} in non-last column: count must be 1")
                result = p.read_text(encoding="utf-8")
                self.assertIn(canonical, result, f"{retired!r} must become {canonical!r}")
                self.assertIn("notes", result, "notes column must be preserved")


# ---------------------------------------------------------------------------
# Test 2d — non-pipe legend/prose lines (regression guard for P11-loop3 defect)
# ---------------------------------------------------------------------------

class TestCoverageProseLegendLines(unittest.TestCase):
    """Legend and aggregation prose lines (no pipe '|') that contain retired tier
    markers must be normalized by rewrite, and dry-run must report needs-fix.

    Verified defect: `_rewrite_coverage_line('Legend: ✅ = high exam priority\\n')`
    returned the line UNCHANGED because `len(cells) < 3` triggered an early return.
    """

    COVERAGE_WITH_PROSE = (
        "| § | Title | HW coverage | Exam tier |\n"
        "|---|---|---|---|\n"
        "| §1 | Intro | hw1(3) | 🔥🔥 |\n"
        "\n"
        "Legend: ✅ = high exam priority\n"
        "Aggregate: 3 sections at ✅, 1 at 🔴🔴.\n"
    )

    def test_prose_legend_lines_rewritten_on_fix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.COVERAGE_WITH_PROSE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertGreater(count, 0, "prose lines with retired markers must be counted")
            result = p.read_text(encoding="utf-8")
            self.assertNotIn("Legend: ✅", result, "retired ✅ in Legend line must be rewritten")
            self.assertIn("Legend: 🔥", result, "✅ in Legend must become 🔥")
            self.assertNotIn("3 sections at ✅", result, "retired ✅ in Aggregate prose must be rewritten")
            self.assertIn("🔥", result, "canonical 🔥 must appear in result")
            self.assertNotIn("🔴🔴", result, "retired 🔴🔴 in prose must be rewritten")
            self.assertIn("⚪", result, "🔴🔴 in prose must become ⚪")

    def test_prose_legend_dryrun_reports_needs_fix(self):
        """Dry-run on a file with prose retired markers must return count>0 (exit 1 path)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.COVERAGE_WITH_PROSE)
            before = p.read_text(encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=False)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertGreater(count, 0,
                               "dry-run must count prose retired markers as needs-fix (exit 1 path)")
            # File untouched in dry-run
            self.assertEqual(p.read_text(encoding="utf-8"), before,
                             "dry-run must not modify the file")


# ---------------------------------------------------------------------------
# Test 2e — real convergence: fix then dry-run must exit 0; 1st dry-run must exit 1
# ---------------------------------------------------------------------------

class TestCoverageConvergence(unittest.TestCase):
    """A file with retired markers in both tier-not-last-column rows AND prose lines:
    - 1st dry-run: count>0 (exit 1 needs-fix)
    - fix: rewrites all retired markers
    - 2nd dry-run (post-fix): count=0 (exit 0 fully canonical)

    Guards the 'false already canonical' false negative where the old code claimed
    exit 0 before any retired marker was actually removed."""

    MIXED_DEFECT_COVERAGE = (
        "| § | Title | Exam tier | Notes |\n"
        "|---|---|---|---|\n"
        "| §1 | Intro | ✅✅ | L1 |\n"
        "| §2 | Limits | ✅ | L2 |\n"
        "| §3 | Weak | 🔴 | L2 |\n"
        "| §4 | Skip | 🔴🔴 | L3 |\n"
        "\n"
        "Legend: ✅ = high exam priority\n"
    )

    def test_first_dryrun_needs_fix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.MIXED_DEFECT_COVERAGE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count1, err = reindex._process_coverage(p, fix=False)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertGreater(count1, 0,
                               "1st dry-run must report needs-fix (count>0) before any fix applied")

    def test_fix_then_dryrun_exits_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.MIXED_DEFECT_COVERAGE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                # apply fix
                reindex._process_coverage(p, fix=True)
                # post-fix dry-run must be clean
                count2, err = reindex._process_coverage(p, fix=False)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err)
            self.assertEqual(count2, 0,
                             "after --fix, dry-run must return count=0 (exit 0 — fully converged)")

    def test_fix_removes_all_retired_markers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, self.MIXED_DEFECT_COVERAGE)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            # No retired markers anywhere in tier columns or prose
            self.assertNotIn("Legend: ✅", result, "prose ✅ must be gone after fix")
            # Tier column cells rewritten
            self.assertIn("🔥🔥", result)
            self.assertIn("🔥", result)
            self.assertIn("🟡", result)
            self.assertIn("⚪", result)
            # Non-tier annotation column preserved
            self.assertIn("L1", result)
            self.assertIn("L2", result)
            self.assertIn("L3", result)


# ---------------------------------------------------------------------------
# Test 3 — longest marker first (no double-substitution)
# ---------------------------------------------------------------------------

class TestCoverageMarkerOrderCorrect(unittest.TestCase):
    """✅✅ must become 🔥🔥 (not 🔥🔥🔥 or 🔥🔥 with extra ✅ from partial match)."""

    def test_double_check_becomes_double_fire(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp,
                "| §1 | A | hw(1) | ✅✅ |\n"
                "| §2 | B | hw(2) | ✅ |\n"
            )
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            self.assertIn("🔥🔥", result, "✅✅ must map to 🔥🔥")
            self.assertIn("🔥", result, "✅ must map to 🔥")
            # No triple fire (double-substitution bug)
            self.assertNotIn("🔥🔥🔥", result, "double-substitution must not produce 🔥🔥🔥")

    def test_double_red_becomes_white(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp,
                "| §1 | A | hw(1) | 🔴🔴 |\n"
                "| §2 | B | hw(2) | 🔴 |\n"
            )
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            self.assertIn("⚪", result, "🔴🔴 must map to ⚪")
            self.assertIn("🟡", result, "🔴 must map to 🟡")
            # No corruption from partial match
            self.assertNotIn("⚪🟡", result, "🔴🔴 must not partially expand via 🔴→🟡 first")


# ---------------------------------------------------------------------------
# Test 4 — log facet materialization
# ---------------------------------------------------------------------------

_LOG_NO_FACETS = """\
# Error log

<!-- Append-only YAML entries. -->

- problem_id: hw3-p2
  pattern: P6
  error_type: sign
  summary: "wrong sign"
  source: answers/converted/hw3.md
  date: 2026-06-01
- problem_id: hw3-p1
  pattern: P3
  error_type: pattern-missed
  summary: "missed the pattern"
  source: answers/converted/hw3.md
  date: 2026-06-01
"""


class TestLogFacetMaterialized(unittest.TestCase):
    """After --fix, log entries without phase/nature get DEFAULT values on disk."""

    def test_phase_written_to_disk(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_log(tmp, _LOG_NO_FACETS)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertFalse(err, "write should not fail")
            self.assertGreater(count, 0, "should have materialized some entries")
            result = p.read_text(encoding="utf-8")
            # sign → execution (DEFAULT_PHASE)
            self.assertIn("phase: execution", result)
            # pattern-missed → transformation (DEFAULT_PHASE)
            self.assertIn("phase: transformation", result)

    def test_nature_written_to_disk(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_log(tmp, _LOG_NO_FACETS)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            # sign → slip (DEFAULT_NATURE)
            self.assertIn("nature: slip", result)
            # pattern-missed → misconception (DEFAULT_NATURE)
            self.assertIn("nature: misconception", result)


# ---------------------------------------------------------------------------
# Test 4b — materialized facets are well-formed YAML at the SIBLING indent.
#           Regression for the 4-space-indent defect: _insert_facets used to
#           prepend an extra "  " onto the (already 2-space) error_type indent,
#           emitting `    phase:` under `  error_type:` → malformed YAML.
#           Test 4 only did assertIn("phase: execution", ...) — indent-agnostic —
#           so it stayed green through the bug (false negative). These tests gate
#           the exact leading whitespace, and (where PyYAML is available) that
#           the materialized block round-trips through yaml.safe_load.
# ---------------------------------------------------------------------------

def _entry_blocks(log_text: str) -> list[list[str]]:
    """Split a materialized log into per-entry line lists (data blocks only,
    header comment excluded) — reusing reindex's own comment-aware splitter."""
    lines = log_text.splitlines(keepends=True)
    return [lines[s:e] for s, e in reindex._split_blocks(log_text)]


def _key_indent(block_lines: list[str], key: str) -> str | None:
    """Leading whitespace of the mapping line for `key` (None if absent).

    Skips the block-opening `- problem_id:` line's dash so `problem_id`'s own
    indent is reported as the mapping-key indent (2 spaces), matching siblings.
    """
    rx = re.compile(rf"^(\s*)(?:-\s+)?{re.escape(key)}\s*:")
    for ln in block_lines:
        m = rx.match(ln)
        if m:
            return m.group(1) if key != "problem_id" else "  "
    return None


class TestLogFacetIndentAndYAML(unittest.TestCase):
    """phase/nature must be emitted at the SAME indent as the sibling required-6
    keys, producing parseable YAML — not one level deeper."""

    def _materialize(self, tmp: Path) -> str:
        p = _write_log(tmp, _LOG_NO_FACETS)
        old_cwd = Path.cwd()
        os.chdir(tmp)
        try:
            _, err = reindex._process_log(p, fix=True)
        finally:
            os.chdir(old_cwd)
        self.assertFalse(err, "materialization write must not fail")
        return p.read_text(encoding="utf-8")

    def test_facets_share_sibling_indent(self):
        """Every entry's phase/nature indent == its pattern/error_type/summary
        indent (2 spaces), not 4. This is what Test 4's substring check missed."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            result = self._materialize(tmp)
            blocks = _entry_blocks(result)
            self.assertGreater(len(blocks), 0, "expected materialized entry blocks")
            for block in blocks:
                sib = _key_indent(block, "error_type")
                self.assertIsNotNone(sib, "block missing error_type sibling")
                for facet in ("phase", "nature"):
                    facet_indent = _key_indent(block, facet)
                    self.assertIsNotNone(
                        facet_indent, f"{facet} not materialized into block")
                    self.assertEqual(
                        facet_indent, sib,
                        f"{facet} indent {facet_indent!r} != sibling error_type "
                        f"indent {sib!r} — facet emitted one level too deep "
                        f"(4-space regression). Block:\n{''.join(block)}")
                # Cross-check against the other required-6 siblings too.
                for other in ("pattern", "summary", "source", "date"):
                    self.assertEqual(
                        _key_indent(block, other), sib,
                        f"{other} sibling indent drifted from error_type")

    def test_facet_lines_are_exactly_two_spaces(self):
        """Pin the concrete canonical indent (2 spaces) so a future change that
        moves ALL keys in lockstep can't silently satisfy the relative check."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            result = self._materialize(tmp)
            for block in _entry_blocks(result):
                for facet in ("phase", "nature"):
                    self.assertEqual(
                        _key_indent(block, facet), "  ",
                        f"{facet} must be indented exactly 2 spaces (mapping key "
                        f"under `- problem_id:`)")

    @unittest.skipUnless(_HAVE_YAML, "PyYAML not installed")
    def test_materialized_entries_parse_as_yaml(self):
        """Each materialized entry block must round-trip through yaml.safe_load.

        The 4-space bug made PyYAML raise ScannerError('mapping values are not
        allowed here') on the `phase:` line — parsing the block is the direct,
        engine-level gate the old substring assert could not provide."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            result = self._materialize(tmp)
            for block in _entry_blocks(result):
                doc = "".join(block)
                try:
                    loaded = yaml.safe_load(doc)
                except yaml.YAMLError as e:  # noqa: PERF203
                    self.fail(
                        f"materialized entry is not valid YAML "
                        f"({type(e).__name__}: {str(e).splitlines()[0]}):\n{doc}")
                # A well-formed entry parses to a single-element list of one
                # mapping carrying all six required keys + the two facets.
                self.assertIsInstance(loaded, list, f"entry not a YAML list:\n{doc}")
                self.assertEqual(len(loaded), 1, f"entry parsed to !=1 mapping:\n{doc}")
                entry = loaded[0]
                self.assertIsInstance(entry, dict, f"entry not a mapping:\n{doc}")
                for k in ("problem_id", "pattern", "error_type", "summary",
                          "source", "date", "phase", "nature"):
                    self.assertIn(k, entry,
                                  f"parsed entry missing '{k}':\n{doc}")

    @unittest.skipUnless(_HAVE_YAML, "PyYAML not installed")
    def test_full_log_parses_as_yaml_after_materialize(self):
        """The whole data region (all entries, header comment stripped) must
        load as one YAML sequence — catches inter-entry indent corruption too."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            result = self._materialize(tmp)
            # Strip the leading `<!-- ... -->` header comment; YAML-load the rest.
            data_region = "".join(
                ln for block in _entry_blocks(result) for ln in block)
            loaded = yaml.safe_load(data_region)
            self.assertIsInstance(loaded, list)
            self.assertEqual(len(loaded), 2, "two entries expected")
            phases = {e["phase"] for e in loaded}
            self.assertEqual(phases, {"execution", "transformation"},
                             "phase values must match DEFAULT_PHASE promotion")


# ---------------------------------------------------------------------------
# Test 5 — required-6 byte-preserved
# ---------------------------------------------------------------------------

class TestLogRequired6BytePreserved(unittest.TestCase):
    def test_required6_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_log(tmp, _LOG_NO_FACETS)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            # All required-6 values must be exactly present
            self.assertIn("problem_id: hw3-p2", result)
            self.assertIn("pattern: P6", result)
            self.assertIn("error_type: sign", result)
            self.assertIn('summary: "wrong sign"', result)
            self.assertIn("source: answers/converted/hw3.md", result)
            self.assertIn("date: 2026-06-01", result)


# ---------------------------------------------------------------------------
# Test 6 — explicit facet wins
# ---------------------------------------------------------------------------

_LOG_EXPLICIT_FACETS = """\
# Error log

- problem_id: hw1-p1
  pattern: P1
  error_type: sign
  phase: reading
  nature: gap
  summary: "explicit"
  source: answers/converted/hw1.md
  date: 2026-06-01
"""


class TestLogExplicitFacetWins(unittest.TestCase):
    def test_explicit_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_log(tmp, _LOG_EXPLICIT_FACETS)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, _ = reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(count, 0, "explicit facets mean no materialization needed")
            result = p.read_text(encoding="utf-8")
            # Explicit values must be preserved
            self.assertIn("phase: reading", result)
            self.assertIn("nature: gap", result)
            # Default for sign would be execution/slip — must NOT appear
            self.assertNotIn("phase: execution", result)
            self.assertNotIn("nature: slip", result)


# ---------------------------------------------------------------------------
# Test 7 — atomic write safety
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):
    """Atomic write helper: successful write replaces file."""

    def test_atomic_write_success(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = tmp / "test.txt"
            f.write_text("original", encoding="utf-8")
            reindex._atomic_write(f, "new content")
            self.assertEqual(f.read_text(encoding="utf-8"), "new content")

    def test_atomic_write_no_tmp_on_success(self):
        """After successful write, no .reindex_tmp_* file remains."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = tmp / "test.txt"
            f.write_text("x", encoding="utf-8")
            reindex._atomic_write(f, "y")
            leftovers = list(tmp.glob(".reindex_tmp_*"))
            self.assertEqual(leftovers, [], f"leftover tmp files: {leftovers}")


# ---------------------------------------------------------------------------
# Test 8 — idempotent
# ---------------------------------------------------------------------------

_CANONICAL_COVERAGE = """\
| § | Title | HW coverage | Exam tier |
|---|---|---|---|
| §1 | A | hw(3) | 🔥🔥 |
| §2 | B | hw(1) | 🟡 ⚠weak |
| §3 | C | hw(0) | ⚪ |
"""

_LOG_ALREADY_MATERIALIZED = """\
# Error log

- problem_id: hw1-p1
  pattern: P1
  error_type: sign
  phase: execution
  nature: slip
  summary: "s"
  source: answers/converted/hw1.md
  date: 2026-06-01
"""


class TestIdempotent(unittest.TestCase):
    def test_coverage_already_canonical_no_change(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_coverage(tmp, _CANONICAL_COVERAGE)
            before = p.read_text(encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_coverage(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(count, 0, "no retired markers, count should be 0")
            self.assertFalse(err)
            after = p.read_text(encoding="utf-8")
            self.assertEqual(before, after, "byte-identical: no change on canonical coverage")

    def test_log_already_materialized_no_change(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p = _write_log(tmp, _LOG_ALREADY_MATERIALIZED)
            before = p.read_text(encoding="utf-8")
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                count, err = reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            self.assertEqual(count, 0, "all facets present, count should be 0")
            self.assertFalse(err)
            after = p.read_text(encoding="utf-8")
            self.assertEqual(before, after, "byte-identical: no change on materialized log")

    def test_double_run_idempotent(self):
        """Two consecutive fix runs produce the same result."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            p_cov = _write_coverage(tmp, """\
| §1 | A | hw(1) | ✅ |
""")
            p_log = _write_log(tmp, _LOG_NO_FACETS)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_coverage(p_cov, fix=True)
                reindex._process_log(p_log, fix=True)
                after1_cov = p_cov.read_text(encoding="utf-8")
                after1_log = p_log.read_text(encoding="utf-8")
                reindex._process_coverage(p_cov, fix=True)
                reindex._process_log(p_log, fix=True)
                after2_cov = p_cov.read_text(encoding="utf-8")
                after2_log = p_log.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)
            self.assertEqual(after1_cov, after2_cov, "coverage idempotent on 2nd run")
            self.assertEqual(after1_log, after2_log, "log idempotent on 2nd run")


# ---------------------------------------------------------------------------
# Test 9 — no course-meta is no-op
# ---------------------------------------------------------------------------

class TestNoCourseMetaIsNoop(unittest.TestCase):
    def test_no_course_meta_returns_early(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # No .course-meta
            result = reindex._course_root(tmp)
            self.assertIsNone(result, "without .course-meta, _course_root must return None")

    def test_with_course_meta_returns_path(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".course-meta").write_text("COURSE_NAME: X\n", encoding="utf-8")
            result = reindex._course_root(tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result, tmp)


# ---------------------------------------------------------------------------
# Test 10 — reuses DEFAULT maps from paideia_lib
# ---------------------------------------------------------------------------

class TestReusesDefaultMaps(unittest.TestCase):
    """Verify reindex.py imports constants from paideia_lib (single-source contract)."""

    def test_retired_to_canonical_is_plib_constant(self):
        """reindex.RETIRED_TO_CANONICAL must be plib.RETIRED_TO_CANONICAL (same object or equal)."""
        self.assertEqual(reindex.RETIRED_TO_CANONICAL, plib.RETIRED_TO_CANONICAL,
                         "reindex.RETIRED_TO_CANONICAL must equal plib.RETIRED_TO_CANONICAL")

    def test_default_phase_imported(self):
        """Materialization must use plib.DEFAULT_PHASE (not a private copy)."""
        # We verify by checking the phase inserted for 'sign' matches plib
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            log_text = (
                "# Error log\n\n"
                "- problem_id: x\n  pattern: P1\n  error_type: sign\n"
                '  summary: "s"\n  source: s\n  date: 2026-01-01\n'
            )
            p = _write_log(tmp, log_text)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            expected_phase = plib.DEFAULT_PHASE.get("sign")
            self.assertIn(f"phase: {expected_phase}", result,
                          f"phase for 'sign' must match plib.DEFAULT_PHASE['sign']={expected_phase!r}")

    def test_default_nature_imported(self):
        """Materialization must use plib.DEFAULT_NATURE."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            log_text = (
                "# Error log\n\n"
                "- problem_id: x\n  pattern: P1\n  error_type: definition\n"
                '  summary: "s"\n  source: s\n  date: 2026-01-01\n'
            )
            p = _write_log(tmp, log_text)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            expected_nature = plib.DEFAULT_NATURE.get("definition")
            self.assertIn(f"nature: {expected_nature}", result,
                          f"nature for 'definition' must match plib.DEFAULT_NATURE['definition']={expected_nature!r}")


# ---------------------------------------------------------------------------
# Test 11 — overridden_by preserved
# ---------------------------------------------------------------------------

class TestOverriddenByPreserved(unittest.TestCase):
    def test_overridden_by_byte_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_course(Path(td))
            log_text = (
                "# Error log\n\n"
                "- problem_id: hw1-p1\n  pattern: P1\n  error_type: sign\n"
                '  summary: "s"\n  source: s\n  date: 2026-01-01\n'
                "  overridden_by: grade/2026-06-01\n"
            )
            p = _write_log(tmp, log_text)
            old_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                reindex._process_log(p, fix=True)
            finally:
                os.chdir(old_cwd)
            result = p.read_text(encoding="utf-8")
            self.assertIn("overridden_by: grade/2026-06-01", result,
                          "overridden_by must be byte-preserved after facet materialization")


if __name__ == "__main__":
    unittest.main()
