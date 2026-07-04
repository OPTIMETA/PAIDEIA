from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

from fixtures import make_course

import paideia_lib as plib


class TestParseMeta(unittest.TestCase):
    def test_comment_stripping_and_values(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01")
            meta = plib.parse_meta(tmp)
            self.assertEqual(meta["COURSE_NAME"], "Complex Analysis")
            self.assertEqual(meta["OCR_ENGINE"], "claude")
            self.assertEqual(plib.interface_lang(meta), "ko")

    def test_absent_meta_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(plib.parse_meta(Path(td)), {})

    def test_interface_lang_normalizes_garbage_to_en(self):
        self.assertEqual(plib.interface_lang({"INTERFACE_LANG": "FR"}), "en")
        self.assertEqual(plib.interface_lang({}), "en")


class TestDaysUntil(unittest.TestCase):
    def test_today_is_zero(self):
        self.assertEqual(plib.days_until(str(datetime.date.today())), 0)

    def test_bad_date_is_none(self):
        self.assertIsNone(plib.days_until("not-a-date"))
        self.assertIsNone(plib.days_until(""))


class TestPhaseMachine(unittest.TestCase):
    """Phase precedence: cool > cram > mock > setup > drill > diag."""

    def test_setup_when_no_patterns(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01",
                              with_patterns=False, with_quiz=False, with_errors=False)
            self.assertEqual(plib.phase(tmp, 99), "setup")

    def test_diag_when_patterns_but_no_graded_quiz(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01", with_quiz=False, with_errors=False)
            self.assertEqual(plib.phase(tmp, 99), "diag")

    def test_drill_when_quiz_and_errors(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01")
            self.assertEqual(plib.phase(tmp, 99), "drill")

    def test_mock_beats_drill(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01", with_mock=True)
            self.assertEqual(plib.phase(tmp, 99), "mock")

    def test_cram_beats_mock(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01", with_mock=True, with_cheatsheet=True)
            self.assertEqual(plib.phase(tmp, 99), "cram")

    def test_cool_overrides_everything_on_d0(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01", with_mock=True, with_cheatsheet=True)
            self.assertEqual(plib.phase(tmp, 0), "cool")


class TestLogHelpers(unittest.TestCase):
    def test_mock_detection_and_top_pattern(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01", with_mock=True)
            text = plib.read_errors_log(tmp)
            self.assertTrue(plib.has_error_entries(text))
            self.assertTrue(plib.mock_was_graded(text))
            self.assertEqual(plib.top_pattern(text), "P6")  # 2×P6 vs 1×P2

    def test_seed_has_no_entries(self):
        self.assertFalse(plib.has_error_entries(""))
        self.assertIsNone(plib.top_pattern(""))


if __name__ == "__main__":
    unittest.main()
