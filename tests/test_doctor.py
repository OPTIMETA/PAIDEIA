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


class TestHeaderNormalization(unittest.TestCase):
    """FND-012 regression: doctor --fix normalizes a drifted errors/log.md header
    without touching data entries."""

    _STALE_5KEY_HEADER = (
        "# Error log\n\n"
        "<!-- Append-only YAML entries. Schema:\n"
        "- problem_id: <id>\n"
        "  pattern: <Pk>\n"
        "  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition\n"
        '  summary: "<1 line>"\n'
        "  date: <ISO8601>\n"
        "-->\n"
    )

    def _make_drifted_log(self, tmp: Path, extra_entries: str = "") -> Path:
        """Write a log.md with the old 5-key header plus optional data entries."""
        (tmp / ".course-meta").write_text("COURSE_NAME: X\n", encoding="utf-8")
        (tmp / "errors").mkdir(exist_ok=True)
        log = tmp / "errors" / "log.md"
        log.write_text(self._STALE_5KEY_HEADER + extra_entries, encoding="utf-8")
        return log

    def test_fix_replaces_drifted_header(self):
        """apply_fixes normalizes a 5-key header to the canonical 6-key seed."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            log = self._make_drifted_log(tmp)
            actions = doctor.apply_fixes(tmp)
            text = log.read_text(encoding="utf-8")
            # Header must now contain source: key declaration.
            self.assertIn("source:", text)
            # Must contain the optional overridden_by line.
            self.assertIn("overridden_by:", text)
            # Action was reported.
            self.assertTrue(any("normalized" in a["en"] for a in actions),
                            f"expected 'normalized' action; got {actions}")

    def test_fix_preserves_data_entries(self):
        """Data entries must survive header normalization byte-for-byte."""
        entry = (
            "- problem_id: hw3-p2\n  pattern: P6\n  error_type: sign\n"
            '  summary: "dropped minus"\n  source: answers/converted/hw3.md\n  date: 2026-07-05\n'
        )
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            log = self._make_drifted_log(tmp, extra_entries="\n" + entry)
            doctor.apply_fixes(tmp)
            text = log.read_text(encoding="utf-8")
            # Entry must be present unchanged.
            self.assertIn("hw3-p2", text)
            self.assertIn("dropped minus", text)
            self.assertIn("source: answers/converted/hw3.md", text)

    def test_fix_preserves_block_count(self):
        """split_blocks count must be identical before and after normalization."""
        import log_tool
        entries = (
            "- problem_id: p1\n  pattern: P1\n  error_type: sign\n"
            '  summary: "s"\n  source: answers/converted/hw1.md\n  date: 2026-07-01\n'
            "- problem_id: p2\n  pattern: P2\n  error_type: algebraic\n"
            '  summary: "t"\n  source: answers/converted/hw1.md\n  date: 2026-07-02\n'
        )
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            log = self._make_drifted_log(tmp, extra_entries="\n" + entries)
            before_text = log.read_text(encoding="utf-8")
            _, before_blocks = log_tool.split_blocks(before_text)
            doctor.apply_fixes(tmp)
            after_text = log.read_text(encoding="utf-8")
            _, after_blocks = log_tool.split_blocks(after_text)
            self.assertEqual(len(before_blocks), len(after_blocks),
                             "block count changed after header normalization")

    def test_canonical_header_unchanged_by_fix(self):
        """When log already has the canonical header, apply_fixes must not rewrite it."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".course-meta").write_text("COURSE_NAME: X\n", encoding="utf-8")
            (tmp / "errors").mkdir(exist_ok=True)
            log = tmp / "errors" / "log.md"
            log.write_text(doctor.ERRORS_LOG_SEED, encoding="utf-8")
            mtime_before = log.stat().st_mtime
            doctor.apply_fixes(tmp)
            mtime_after = log.stat().st_mtime
            # File must not have been rewritten (mtime unchanged).
            self.assertEqual(mtime_before, mtime_after,
                             "log.md was needlessly rewritten when header was already canonical")

    def test_normalize_is_pure_header_replacement(self):
        """FND-012 (issue #4): header normalization must be a *pure* header
        replacement — the entry region (including the blank-line separator
        between '-->' and the first '- problem_id:' entry) must be byte-identical
        to a freshly seeded-then-appended log. Guards against lstrip('\\n')
        collapsing the '\\n\\n' body separator to a single '\\n'."""
        import log_tool
        entry = (
            "- problem_id: hw3-p2\n  pattern: P6\n  error_type: sign\n"
            '  summary: "dropped minus"\n  source: answers/converted/hw3.md\n  date: 2026-07-05\n'
        )
        # (a) canonical layout: a fresh log.md seeded + appended by log_tool.
        _, entry_blocks = log_tool.split_blocks(entry)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "errors").mkdir()
            fresh = tmp / "errors" / "log.md"
            log_tool.rewrite(fresh, "answers/converted/hw3.md", entry_blocks)
            fresh_text = fresh.read_text(encoding="utf-8")

        # (b) a log with a drifted OLD 5-key header + the same entry, normalized.
        old_header_log = (
            "# Error log\n\n"
            "<!-- Append-only YAML entries. Schema:\n"
            "- problem_id: <id>\n  pattern: <Pk>\n"
            "  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition\n"
            '  summary: "<1 line>"\n  date: <ISO8601>\n-->\n\n' + entry
        )
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "errors").mkdir()
            drifted = tmp / "errors" / "log.md"
            drifted.write_text(old_header_log, encoding="utf-8")
            doctor._normalize_log_header(drifted)
            normalized_text = drifted.read_text(encoding="utf-8")

        # Full-file byte equality proves the header block AND the entry region
        # (blank-line separator included) match a freshly seeded file exactly.
        self.assertEqual(
            fresh_text, normalized_text,
            "header normalization altered the entry region (body-spacing drift): "
            "a normalized log must be byte-identical to a fresh seed+append")


class TestVerifyReachable(unittest.TestCase):
    """C3: verify_reachable field and related functions in doctor.py."""

    def _run_doctor_json(self, tmp: Path) -> dict:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "doctor.py"), "--json"],
            capture_output=True, text=True, cwd=tmp,
        )
        return json.loads(r.stdout)

    def test_verify_reachable_true_when_both_ok(self):
        """verify_reachable is True when both verify_deps and antlr4_runtime are OK."""
        ok_result = doctor.Result("verify_deps", "verify deps (sympy / math-verify)", doctor.OK)
        antlr_result = doctor.Result("antlr4_runtime", "antlr4-python3-runtime", doctor.OK)
        other = doctor.Result("poppler", "poppler", doctor.OK)

        # Build a minimal results list and call print_json to get the payload
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.print_json([ok_result, antlr_result, other], {}, False, None)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["verify_reachable"])

    def test_verify_reachable_false_when_either_warn(self):
        """verify_reachable is False if either verify_deps or antlr4_runtime is WARN."""
        warn_result = doctor.Result("verify_deps", "verify deps", doctor.WARN)
        antlr_result = doctor.Result("antlr4_runtime", "antlr4-python3-runtime", doctor.OK)

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.print_json([warn_result, antlr_result], {}, False, None)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["verify_reachable"])

    def test_verify_reachable_false_when_antlr4_warn(self):
        """verify_reachable is False if antlr4_runtime is WARN even if verify_deps is OK."""
        ok_result = doctor.Result("verify_deps", "verify deps", doctor.OK)
        warn_antlr = doctor.Result("antlr4_runtime", "antlr4-python3-runtime", doctor.WARN)

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.print_json([ok_result, warn_antlr], {}, False, None)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["verify_reachable"])

    def test_install_verify_flag_calls_pip_once(self):
        """--install-verify invokes pip install with VERIFY_INSTALL_SPEC exactly once."""
        captured_calls = []

        def fake_run(cmd, **kwargs):
            captured_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        import unittest.mock as mock
        with mock.patch("subprocess.run", side_effect=fake_run):
            result = doctor.install_verify_deps()

        self.assertEqual(len(captured_calls), 1, "pip install must be called exactly once")
        call = captured_calls[0]
        # Must use sys.executable (not a hardcoded "python3")
        self.assertEqual(call[0], sys.executable)
        self.assertIn("-m", call)
        self.assertIn("pip", call)
        self.assertIn("install", call)
        self.assertIn("--user", call)
        self.assertIn("--break-system-packages", call)
        # All VERIFY_INSTALL_SPEC packages must appear
        for spec in doctor.VERIFY_INSTALL_SPEC:
            self.assertIn(spec, call, f"VERIFY_INSTALL_SPEC entry '{spec}' missing from pip call")
        # Result reports success
        self.assertIn("installed", result.get("en", ""))

    def test_fix_alone_never_runs_pip(self):
        """--fix alone must never invoke pip (invariant: never runs pip)."""
        pip_calls = []

        def spy_run(cmd, **kwargs):
            if isinstance(cmd, list) and "pip" in " ".join(str(c) for c in cmd):
                pip_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / ".course-meta").write_text("COURSE_NAME: X\n", encoding="utf-8")
            with mock.patch("subprocess.run", side_effect=spy_run):
                doctor.apply_fixes(tmp)

        self.assertEqual(pip_calls, [], "--fix must not call pip")

    def test_check_verify_is_warn_not_fail_when_absent(self):
        """check_verify returns WARN (not FAIL) when math_verify is missing (03 §1.6)."""
        import unittest.mock as mock
        # Stub _py_missing to return all VERIFY_PY entries as missing
        with mock.patch.object(doctor, "_py_missing", return_value=list(doctor.VERIFY_PY)):
            result = doctor.check_verify()
        self.assertEqual(result.status, doctor.WARN,
                         "check_verify must return WARN not FAIL when verify deps absent")
        self.assertEqual(result.key, "verify_deps")

    def test_check_antlr4_is_warn_not_fail_when_absent(self):
        """check_antlr4 returns WARN (not FAIL) when antlr4 is missing (03 §1.6)."""
        import unittest.mock as mock
        with mock.patch.object(doctor, "_py_missing", return_value=["antlr4"]):
            result = doctor.check_antlr4()
        self.assertEqual(result.status, doctor.WARN,
                         "check_antlr4 must return WARN not FAIL when antlr4 absent")
        self.assertEqual(result.key, "antlr4_runtime")

    def test_verify_tool_exit3_when_absent(self):
        """verify_tool.py returns exit 3 and available:false when math-verify not installed."""
        import io, contextlib
        verify_tool_path = SCRIPTS / "verify_tool.py"
        result = subprocess.run(
            [sys.executable, str(verify_tool_path)],
            input='{"checks":[]}',
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            # math-verify is installed; skip this test
            self.skipTest("math-verify is installed — exit-3 path not reachable in this env")
        self.assertEqual(result.returncode, 3,
                         f"verify_tool.py must exit 3 when math-verify absent, got {result.returncode}")
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("available"), "available must be false when math-verify absent")
        self.assertEqual(payload.get("results"), [],
                         "results must be [] when math-verify absent")


if __name__ == "__main__":
    unittest.main()
