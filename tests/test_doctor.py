from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import SCRIPTS, make_course

import doctor


class TestApplyFixesGuard(unittest.TestCase):
    """Regression for the v0.9.14 fix: `doctor --fix` in a folder without
    .course-meta must never scaffold a course skeleton there."""

    def test_global_mode_creates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            actions = doctor.apply_fixes(tmp)
            created = [d for d in doctor.COURSE_DIRS if (tmp / d).exists()]
            self.assertEqual(created, [])
            self.assertFalse((tmp / "errors" / "log.md").exists())
            self.assertFalse((tmp / ".claude").exists())
            self.assertTrue(any("global mode" in a["en"] for a in actions))

    def test_course_mode_repairs(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".course-meta").write_text("COURSE_NAME: X\n", encoding="utf-8")
            doctor.apply_fixes(tmp)
            missing = [d for d in doctor.COURSE_DIRS if not (tmp / d).is_dir()]
            self.assertEqual(missing, [])
            self.assertTrue((tmp / "errors" / "log.md").is_file())


class TestWiring(unittest.TestCase):
    def test_quoted_paths_with_spaces_pass(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spaced = tmp / "dir with space"
            spaced.mkdir()
            sl = spaced / "statusline.py"
            ss = spaced / "session_start.py"
            sl.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            ss.write_text("x\n", encoding="utf-8")
            os.chmod(sl, 0o755)
            (tmp / ".claude").mkdir()
            (tmp / ".claude" / "settings.json").write_text(json.dumps({
                "statusLine": {"type": "command", "command": shlex.quote(str(sl))},
                "hooks": {"SessionStart": [{
                    "matcher": "startup|resume",
                    "hooks": [{"type": "command",
                               "command": f"python3 {shlex.quote(str(ss))}"}],
                }]},
            }), encoding="utf-8")
            r = doctor.check_wiring(tmp)
            self.assertEqual(r.status, doctor.OK, r.detail)

    def test_moved_plugin_detected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".claude").mkdir()
            (tmp / ".claude" / "settings.json").write_text(json.dumps({
                "statusLine": {"type": "command", "command": "/nonexistent/statusline.py"},
            }), encoding="utf-8")
            self.assertEqual(doctor.check_wiring(tmp).status, doctor.FAIL)


class TestGradedPythonDeps(unittest.TestCase):
    def test_three_graded_results(self):
        results = doctor.check_python("claude")
        self.assertEqual([r.key for r in results],
                         ["python_core", "python_ocr", "python_optional"])

    def test_pytesseract_severity_follows_engine(self):
        sev_claude = doctor._ocr_severity("claude", {"ollama", "tesseract"})
        sev_ollama = doctor._ocr_severity("ollama", {"ollama", "tesseract"})
        self.assertEqual(sev_claude, doctor.WARN)
        self.assertEqual(sev_ollama, doctor.FAIL)


class TestEndToEnd(unittest.TestCase):
    def test_json_mode_in_course_folder(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = make_course(Path(td), "2099-01-01")
            r = subprocess.run(
                [sys.executable, str(SCRIPTS / "doctor.py"), "--json"],
                capture_output=True, text=True, cwd=tmp,
            )
            payload = json.loads(r.stdout)
            self.assertTrue(payload["course_mode"])
            self.assertEqual(payload["ocr_engine"], "claude")
            self.assertIn(payload["overall"], ("ok", "warn", "fail"))
            self.assertIn(r.returncode, (0, 1, 2))


class TestSeedParity(unittest.TestCase):
    def test_doctor_seed_is_the_lib_seed(self):
        import paideia_lib as plib
        self.assertEqual(doctor.ERRORS_LOG_SEED, plib.ERRORS_LOG_SEED)


if __name__ == "__main__":
    unittest.main()
