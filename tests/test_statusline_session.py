from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import SCRIPTS, make_course


def run_statusline(payload: dict, home: str) -> str:
    env = dict(os.environ, HOME=home)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "statusline.py")],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    ).stdout


def run_session_start(cwd: Path) -> str:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "session_start.py")],
        capture_output=True, text=True, cwd=cwd,
    ).stdout


class TestStatusline(unittest.TestCase):
    def test_renders_cool_on_exam_day_and_caches(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            tmp = make_course(Path(td), str(datetime.date.today()))
            payload = {"session_id": "s1", "cwd": str(tmp)}
            out = run_statusline(payload, home)
            for token in ("paideia", "Complex Analysis", "D-0", "cool", "P6"):
                self.assertIn(token, out)
            self.assertEqual(run_statusline(payload, home), out,
                             "cache hit must render identically")

    def test_silent_outside_course_folder(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            out = run_statusline({"session_id": "s1", "cwd": td}, home)
            self.assertEqual(out, "")


class TestSessionStart(unittest.TestCase):
    def test_banner_matches_statusline_phase_on_d0(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), str(datetime.date.today()))
            out = run_session_start(tmp)
            self.assertIn("phase=cool", out)
            self.assertIn("시험 당일", out)  # ko D-0 label
            self.assertIn("P6", out)

    def test_silent_outside_course_folder(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_session_start(Path(td)), "")

    def test_phase_parity_source_of_truth(self):
        """Both consumers must call the shared phase machine — a private copy
        reintroduces the cool-phase divergence this suite exists to prevent."""
        for script in ("statusline.py", "session_start.py"):
            src = (SCRIPTS / script).read_text(encoding="utf-8")
            self.assertIn("plib.phase(", src, f"{script} must use paideia_lib.phase")
            self.assertNotIn("def detect_phase", src)
            self.assertNotIn("def current_phase", src)


if __name__ == "__main__":
    unittest.main()
