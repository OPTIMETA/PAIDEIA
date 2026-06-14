import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins/paideia/scripts/tutorial_harness.py"


PASS_ATTEMPT = """# Tutorial attempt — write here first

## Problem T1

## My attempt

- Split: A(x)=1+\\sum_{n>=1} a_n x^n.
- Recurrence substitution: A(x)=1+\\sum_{n>=1}2a_{n-1}x^n.
- Index shift evidence: with m=n-1, the sum is 2xA(x).
- Closed form: A(x)=1/(1-2x).
"""

PARTIAL_ATTEMPT = """# Tutorial attempt — write here first

## My attempt

- Split: A(x)=1+sum over n>=1.
- Recurrence substitution: I use 2a_{n-1}.
- Index shift evidence: I think it becomes 2A(x).
- Closed form: not sure.
"""

FAIL_ATTEMPT = """# Tutorial attempt — write here first

## My attempt

I do not know how to start this problem, but I tried reading the prompt.
"""


class TutorialHarnessTests(unittest.TestCase):
    def run_harness(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--root", str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=REPO,
            check=False,
        )

    def init_root(self) -> tempfile.TemporaryDirectory[str]:
        td = tempfile.TemporaryDirectory()
        result = self.run_harness(Path(td.name), "init")
        self.assertEqual(result.returncode, 0, result.stderr)
        return td

    def test_init_creates_runnable_artifacts_and_graph(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            for rel in [
                "tutorial/tutorial.md",
                "tutorial/attempt.md",
                "tutorial/rubric.md",
                "tutorial/verify.md",
                "errors/log.md",
                "reviews/actions.md",
                "course-index/context-graph.json",
            ]:
                self.assertTrue((root / rel).exists(), rel)
            graph = json.loads((root / "course-index/context-graph.json").read_text())
            self.assertEqual(graph["state"], "PENDING_ATTEMPT")
            self.assertIn("review_action", {node["type"] for node in graph["nodes"]})

    def test_init_does_not_overwrite_non_placeholder_attempt(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            attempt = root / "tutorial/attempt.md"
            attempt.write_text("## My attempt\nreal work\n", encoding="utf-8")
            result = self.run_harness(root, "init")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains work", result.stderr)
            self.assertEqual(attempt.read_text(encoding="utf-8"), "## My attempt\nreal work\n")

    def test_blank_placeholder_attempt_cannot_verify_without_answer_leak(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "verify", "--root", str(root), "--json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=REPO,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"], "CANNOT_VERIFY")
            verify_md = (root / "tutorial/verify.md").read_text(encoding="utf-8")
            self.assertNotIn("1/(1-2x)", verify_md)
            self.assertNotIn("2xA(x)", verify_md)

    def test_fail_updates_error_log_and_review_action_idempotently(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            (root / "tutorial/attempt.md").write_text(FAIL_ATTEMPT, encoding="utf-8")
            first = self.run_harness(root, "verify")
            second = self.run_harness(root, "verify")
            self.assertEqual(first.returncode, 1)
            self.assertEqual(second.returncode, 1)
            error_log = (root / "errors/log.md").read_text(encoding="utf-8")
            actions = (root / "reviews/actions.md").read_text(encoding="utf-8")
            self.assertEqual(error_log.count("source: tutorial/attempt.md"), 1)
            self.assertIn("problem_id: tutorial-t1", error_log)
            self.assertIn("kind: ReviewAction", actions)
            self.assertIn("/paideia:derive index-shift", actions)

    def test_partial_quotes_attempt_evidence_and_updates_graph(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            (root / "tutorial/attempt.md").write_text(PARTIAL_ATTEMPT, encoding="utf-8")
            result = self.run_harness(root, "verify")
            self.assertEqual(result.returncode, 1)
            verify_md = (root / "tutorial/verify.md").read_text(encoding="utf-8")
            self.assertIn("Status: PARTIAL", verify_md)
            self.assertIn("Evidence quote:", verify_md)
            self.assertIn("2A(x)", verify_md)
            graph = json.loads((root / "course-index/context-graph.json").read_text())
            self.assertEqual(graph["state"], "PARTIAL")

    def test_pass_has_no_error_or_review_action_candidate(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            (root / "tutorial/attempt.md").write_text(PASS_ATTEMPT, encoding="utf-8")
            result = self.run_harness(root, "verify")
            self.assertEqual(result.returncode, 0, result.stderr)
            verify_md = (root / "tutorial/verify.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", verify_md)
            self.assertNotIn("BEGIN paideia-tutorial", (root / "errors/log.md").read_text(encoding="utf-8"))
            self.assertNotIn("kind: ReviewAction", (root / "reviews/actions.md").read_text(encoding="utf-8"))

    def test_graph_check_validates_required_nodes_edges(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            result = self.run_harness(root, "graph-check")
            self.assertEqual(result.returncode, 0, result.stderr)
            graph_path = root / "course-index/context-graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["nodes"] = [node for node in graph["nodes"] if node["type"] != "rubric"]
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            bad = self.run_harness(root, "graph-check")
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("missing node types", bad.stderr)

    def test_guardrail_check_blocks_overclaims_but_allows_negation(self):
        with self.init_root() as root_s:
            root = Path(root_s)
            ok = root / "ok.md"
            ok.write_text("This is not a graph of student cognition; it is source-grounded.\n", encoding="utf-8")
            result = self.run_harness(root, "guardrail-check")
            self.assertEqual(result.returncode, 0, result.stderr)
            bad = root / "bad.md"
            bad.write_text("PAIDEIA builds a graph of student cognition.\n", encoding="utf-8")
            blocked = self.run_harness(root, "guardrail-check")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("overclaiming", blocked.stderr)


if __name__ == "__main__":
    unittest.main()
