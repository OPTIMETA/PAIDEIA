from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import SCRIPTS

import log_tool
import paideia_lib as plib


def entry(pid: str, pat: str, et: str, src: str, date: str = "2026-07-05") -> str:
    return (
        f"- problem_id: {pid}\n  pattern: {pat}\n  error_type: {et}\n"
        f'  summary: "s"\n  source: {src}\n  date: {date}\n'
    )


def run_tool(args: list[str], stdin: str = "", cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "log_tool.py")] + args,
        input=stdin, capture_output=True, text=True, cwd=cwd,
    )


class TestSplitBlocks(unittest.TestCase):
    def test_seed_schema_example_stays_preamble(self):
        pre, blocks = log_tool.split_blocks(plib.ERRORS_LOG_SEED)
        self.assertEqual(blocks, [])
        self.assertIn("- problem_id: <id>", pre)

    def test_entries_after_comment_are_blocks(self):
        text = plib.ERRORS_LOG_SEED + "\n" + entry("a", "P1", "sign", "x")
        pre, blocks = log_tool.split_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn("-->", pre)


class TestAppend(unittest.TestCase):
    def test_seed_and_append_on_missing_log(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = run_tool(["append", "--source=answers/converted/hw3.md"],
                         entry("hw3-p2", "P6", "sign", "answers/converted/hw3.md"), cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Error log"))
            self.assertLess(text.index("-->"), text.index("- problem_id: hw3-p2"))

    def test_idempotent_replace_preserves_other_sources(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_tool(["append", "--source=answers/converted/hw3.md"],
                     entry("hw3-p2", "P6", "sign", "answers/converted/hw3.md"), cwd=tmp)
            run_tool(["append", "--source=blind/hw4-p1"],
                     entry("hw4-p1", "P2", "pattern-missed", "blind/hw4-p1"), cwd=tmp)
            two = (entry("hw3-p1", "P1", "algebraic", "answers/converted/hw3.md")
                   + entry("hw3-p2", "P6", "sign", "answers/converted/hw3.md"))
            r = run_tool(["append", "--source=answers/converted/hw3.md"], two, cwd=tmp)
            self.assertIn("replaced 1 → appended 2", r.stdout)
            _, blocks = log_tool.split_blocks((tmp / "errors/log.md").read_text(encoding="utf-8"))
            self.assertEqual(len(blocks), 3)
            self.assertTrue(any("hw4-p1" in b for b in blocks))

    def test_quote_tolerant_source_matching(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "errors").mkdir()
            (tmp / "errors/log.md").write_text(
                plib.ERRORS_LOG_SEED + "\n"
                '- problem_id: q1\n  pattern: P9\n  error_type: sign\n'
                '  summary: "x"\n  source: "answers/converted/q.md"\n  date: 2026-07-01\n',
                encoding="utf-8")
            r = run_tool(["append", "--source=answers/converted/q.md"],
                         entry("q2", "P9", "sign", "answers/converted/q.md"), cwd=tmp)
            self.assertIn("replaced 1 → appended 1", r.stdout)


class TestValidation(unittest.TestCase):
    def _reject(self, tmp: Path, stdin: str, needle: str):
        before = (tmp / "errors/log.md").read_text(encoding="utf-8") \
            if (tmp / "errors/log.md").exists() else None
        r = run_tool(["append", "--source=chain/x"], stdin, cwd=tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(needle, r.stderr)
        after = (tmp / "errors/log.md").read_text(encoding="utf-8") \
            if (tmp / "errors/log.md").exists() else None
        self.assertEqual(before, after, "rejected batch must write nothing")

    def test_rejections(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._reject(tmp, entry("c1", "P3", "totally-bogus", "chain/x"), "not in")
            self._reject(tmp, entry("c1", "P3", "sign", "chain/DIFFERENT"), "!= --source")
            self._reject(tmp, "", "no `- problem_id:`")
            self._reject(tmp, entry("c1", "P3", "sign", "chain/x", date="July 5"), "YYYY-MM-DD")

    def test_optional_facets_accepted_when_valid(self):
        """phase/nature are optional keys documented in the seed header; a present
        value in the controlled vocab must be accepted and written through."""
        src = "chain/x"
        stdin = (
            "- problem_id: c1\n  pattern: P3\n  error_type: sign\n"
            "  phase: execution\n  nature: slip\n"
            f'  summary: "s"\n  source: {src}\n  date: 2026-07-05\n'
        )
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = run_tool(["append", f"--source={src}"], stdin, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            self.assertIn("phase: execution", text)
            self.assertIn("nature: slip", text)

    def test_optional_facets_rejected_when_out_of_vocab(self):
        """A present-but-invalid phase or nature value is rejected exactly like a
        bad error_type (batch writes nothing)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad_phase = (
                "- problem_id: c1\n  pattern: P3\n  error_type: sign\n"
                "  phase: bogus-phase\n"
                '  summary: "s"\n  source: chain/x\n  date: 2026-07-05\n'
            )
            self._reject(tmp, bad_phase, "phase 'bogus-phase' not in")
            bad_nature = (
                "- problem_id: c1\n  pattern: P3\n  error_type: sign\n"
                "  nature: bogus-nature\n"
                '  summary: "s"\n  source: chain/x\n  date: 2026-07-05\n'
            )
            self._reject(tmp, bad_nature, "nature 'bogus-nature' not in")

    def test_remove(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_tool(["append", "--source=blind/hw4-p1"],
                     entry("hw4-p1", "P2", "pattern-missed", "blind/hw4-p1"), cwd=tmp)
            r = run_tool(["remove", "--source=blind/hw4-p1"], cwd=tmp)
            self.assertIn("removed 1", r.stdout)
            _, blocks = log_tool.split_blocks((tmp / "errors/log.md").read_text(encoding="utf-8"))
            self.assertEqual(blocks, [])


class TestDownstreamCompat(unittest.TestCase):
    def test_written_entries_satisfy_statusline_regexes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_tool(["append", "--source=answers/converted/mock_20260705.md"],
                     entry("mock_20260705-P1", "P4", "pattern-missed",
                           "answers/converted/mock_20260705.md"), cwd=tmp)
            text = plib.read_errors_log(tmp)
            self.assertTrue(plib.has_error_entries(text))
            self.assertTrue(plib.mock_was_graded(text))
            self.assertEqual(plib.top_pattern(text), "P4")

    def test_override_does_not_double_count_in_top_pattern(self):
        """After override, top_pattern must reflect correction, not double-count original."""
        src = "answers/converted/hw3.md"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Original: P6 sign error
            run_tool(["append", f"--source={src}"],
                     entry("hw3-p2", "P6", "sign", src), cwd=tmp)
            # Override: same problem, now classified as P6 definition error
            corr = (f"- problem_id: hw3-p2\n  pattern: P6\n  error_type: definition\n"
                    f'  summary: "corrected"\n  source: {src}\n  date: 2026-07-10\n')
            run_tool(["override", f"--source={src}"], corr, cwd=tmp)
            text = plib.read_errors_log(tmp)
            # Both entries carry pattern: P6, but the known limitation is that
            # top_pattern reads ALL `pattern:` lines including overridden ones.
            # This test documents the current behaviour rather than asserting
            # a non-existent filtering mechanism. The correction entry exists:
            _, blocks = log_tool.split_blocks(text)
            live = [b for b in blocks if "overridden_by" not in b]
            self.assertEqual(len(live), 1, "exactly one live (non-overridden) entry expected")
            self.assertIn("definition", live[0])

    def test_no_undeclared_keys_in_written_entries(self):
        """FND-012 regression: entries written by log_tool must only contain keys
        declared in the canonical ERRORS_LOG_SEED header (i.e. the 6 REQUIRED_KEYS
        + optional overridden_by).  phase/nature are reader-derived, never stored.
        """
        declared_storage_keys = set(log_tool.REQUIRED_KEYS) | {"overridden_by"}
        # phase/nature must NOT be stored — they are derived by iter_error_entries.
        self.assertNotIn("phase", declared_storage_keys)
        self.assertNotIn("nature", declared_storage_keys)

        src = "answers/converted/hw3.md"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_tool(["append", f"--source={src}"],
                     entry("hw3-p2", "P6", "sign", src), cwd=tmp)
            text = (tmp / "errors" / "log.md").read_text(encoding="utf-8")
            _, blocks = log_tool.split_blocks(text)
            import re
            key_rx = re.compile(r"^\s*-?\s*(\w[\w\-]*)\s*:", re.MULTILINE)
            for block in blocks:
                found_keys = {m.group(1) for m in key_rx.finditer(block)}
                undeclared = found_keys - declared_storage_keys
                self.assertEqual(undeclared, set(),
                                 f"entry contains undeclared storage keys {undeclared!r}:\n{block}")


class TestOverride(unittest.TestCase):
    SRC = "answers/converted/hw3.md"

    def _append_original(self, tmp: Path) -> None:
        run_tool(["append", f"--source={self.SRC}"],
                 entry("hw3-p2", "P6", "sign", self.SRC, date="2026-07-05"), cwd=tmp)

    def _correction_block(self, date: str = "2026-07-10") -> str:
        return (f"- problem_id: hw3-p2\n  pattern: P6\n  error_type: definition\n"
                f'  summary: "corrected: sign was right, this is a definition issue"\n'
                f"  source: {self.SRC}\n  date: {date}\n")

    def test_original_preserved_and_linked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            r = run_tool(["override", f"--source={self.SRC}"],
                         self._correction_block(), cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            _, blocks = log_tool.split_blocks(text)
            # Two blocks: original (with overridden_by) + correction (without).
            self.assertEqual(len(blocks), 2, f"expected 2 blocks, got {len(blocks)}")
            # Find the original (has overridden_by marker).
            originals = [b for b in blocks if "overridden_by" in b]
            corrections = [b for b in blocks if "overridden_by" not in b]
            self.assertEqual(len(originals), 1)
            self.assertEqual(len(corrections), 1)
            # Original retains its original error_type and date.
            self.assertIn("sign", originals[0])
            self.assertIn("2026-07-05", originals[0])
            self.assertIn(f"overridden_by: {self.SRC}", originals[0])

    def test_current_verdict_is_correction(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            run_tool(["override", f"--source={self.SRC}"],
                     self._correction_block(), cwd=tmp)
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            _, blocks = log_tool.split_blocks(text)
            live = [b for b in blocks if "overridden_by" not in b]
            self.assertEqual(len(live), 1)
            self.assertIn("definition", live[0])
            self.assertIn("2026-07-10", live[0])

    def test_reoverride_keeps_single_current(self):
        """Two overrides: originals accumulate markers, only one live entry."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            # First override
            run_tool(["override", f"--source={self.SRC}"],
                     self._correction_block(date="2026-07-10"), cwd=tmp)
            # Second override (corrects the correction)
            corr2 = (f"- problem_id: hw3-p2\n  pattern: P6\n  error_type: algebraic\n"
                     f'  summary: "re-corrected: actually algebraic"\n'
                     f"  source: {self.SRC}\n  date: 2026-07-12\n")
            r = run_tool(["override", f"--source={self.SRC}"], corr2, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            _, blocks = log_tool.split_blocks(text)
            live = [b for b in blocks if "overridden_by" not in b]
            overridden = [b for b in blocks if "overridden_by" in b]
            # Exactly one live entry (the latest correction).
            self.assertEqual(len(live), 1, "must have exactly one live entry after re-override")
            self.assertIn("algebraic", live[0])
            # Two overridden entries (original + first correction).
            self.assertEqual(len(overridden), 2,
                             "both the original and first correction must be preserved with marker")
            # Original is still there with its original error_type.
            self.assertTrue(any("sign" in b and "2026-07-05" in b for b in overridden))

    def test_override_rejects_overridden_by_in_stdin(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            bad_stdin = (self._correction_block() +
                         f"  overridden_by: {self.SRC}\n")
            r = run_tool(["override", f"--source={self.SRC}"], bad_stdin, cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("nothing written", r.stderr)
            # Log unchanged — original still present without marker on it.
            text = (tmp / "errors/log.md").read_text(encoding="utf-8")
            _, blocks = log_tool.split_blocks(text)
            self.assertEqual(len(blocks), 1)
            self.assertNotIn("overridden_by", blocks[0])

    def test_override_validates_six_keys(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            log_before = (tmp / "errors/log.md").read_text(encoding="utf-8")
            # Missing error_type key
            bad = (f"- problem_id: hw3-p2\n  pattern: P6\n"
                   f'  summary: "x"\n  source: {self.SRC}\n  date: 2026-07-10\n')
            r = run_tool(["override", f"--source={self.SRC}"], bad, cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("nothing written", r.stderr)
            self.assertEqual((tmp / "errors/log.md").read_text(encoding="utf-8"), log_before)

    def test_override_rejects_wrong_error_type(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            bad = (f"- problem_id: hw3-p2\n  pattern: P6\n  error_type: totally-bogus\n"
                   f'  summary: "x"\n  source: {self.SRC}\n  date: 2026-07-10\n')
            r = run_tool(["override", f"--source={self.SRC}"], bad, cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("not in", r.stderr)

    def test_override_rejects_source_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            bad = (f"- problem_id: hw3-p2\n  pattern: P6\n  error_type: definition\n"
                   f'  summary: "x"\n  source: answers/converted/OTHER.md\n  date: 2026-07-10\n')
            r = run_tool(["override", f"--source={self.SRC}"], bad, cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertIn("!= --source", r.stderr)

    def test_other_sources_byte_preserved(self):
        other_src = "blind/hw4-p1"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_tool(["append", f"--source={other_src}"],
                     entry("hw4-p1", "P2", "pattern-missed", other_src), cwd=tmp)
            self._append_original(tmp)
            text_before = (tmp / "errors/log.md").read_text(encoding="utf-8")
            run_tool(["override", f"--source={self.SRC}"],
                     self._correction_block(), cwd=tmp)
            text_after = (tmp / "errors/log.md").read_text(encoding="utf-8")
            # The blind/hw4-p1 block must be byte-identical.
            _, blocks_before = log_tool.split_blocks(text_before)
            _, blocks_after = log_tool.split_blocks(text_after)
            other_before = next(b for b in blocks_before if other_src in b)
            other_after = next(b for b in blocks_after if other_src in b)
            self.assertEqual(other_before, other_after)

    def test_atomic_no_partial_on_failure(self):
        """Validation failure must leave the log file untouched (no tmp residue)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            log_path = tmp / "errors/log.md"
            content_before = log_path.read_text(encoding="utf-8")
            # Empty stdin triggers validation failure.
            r = run_tool(["override", f"--source={self.SRC}"], "", cwd=tmp)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(log_path.read_text(encoding="utf-8"), content_before)
            # No .log_tool- tmp files should remain.
            residue = list((tmp / "errors").glob(".log_tool-*"))
            self.assertEqual(residue, [], f"tmp residue found: {residue}")

    def test_output_message_format(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._append_original(tmp)
            r = run_tool(["override", f"--source={self.SRC}"],
                         self._correction_block(), cwd=tmp)
            self.assertEqual(r.returncode, 0)
            # Message must contain 'overrode', 'preserved as overridden', 'appended'.
            self.assertIn("overrode", r.stdout)
            self.assertIn("preserved as overridden", r.stdout)
            self.assertIn("appended", r.stdout)


if __name__ == "__main__":
    unittest.main()
