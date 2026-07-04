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


if __name__ == "__main__":
    unittest.main()
