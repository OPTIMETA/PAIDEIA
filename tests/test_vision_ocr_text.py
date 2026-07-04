from __future__ import annotations

import unittest

import fixtures  # noqa: F401  (sys.path side effect)

import vision_ocr


class TestDedupeLoops(unittest.TestCase):
    """Regressions for the v0.9.15 rewrite: the ollama tier's post-processing
    must never restructure or delete legitimate page content."""

    def test_headings_and_display_math_keep_their_lines(self):
        t = "We integrate by parts.\n\n## P2\n\n$$x = 2$$\nDone."
        out = vision_ocr.dedupe_loops(t)
        self.assertIn("\n## P2", out)
        self.assertIn("\n$$x = 2$$", out)

    def test_student_prose_that_looks_like_self_talk_survives(self):
        t = ("Let's check the boundary conditions.\n"
             "Actually, we need u(0)=0.\n"
             "잠깐 여기서 부호를 확인하면 된다.")
        out = vision_ocr.dedupe_loops(t)
        self.assertIn("Let's check", out)
        self.assertIn("Actually,", out)
        self.assertIn("잠깐", out)

    def test_three_plus_identical_lines_collapse_to_two(self):
        out = vision_ocr.dedupe_loops("x = 1\nx = 1\nx = 1\nx = 1\ny = 2")
        self.assertEqual(out.count("x = 1"), 2)
        self.assertIn("y = 2", out)

    def test_single_repeat_survives(self):
        out = vision_ocr.dedupe_loops("x = 1\nx = 1\ny = 2")
        self.assertEqual(out.count("x = 1"), 2)

    def test_ngram_tail_trimmed_per_line(self):
        out = vision_ocr.dedupe_loops(("result is " + "a b c d e " * 3).strip())
        self.assertEqual(out.count("a b c d e"), 1)


class TestConfig(unittest.TestCase):
    def test_context_window_fits_generation_budget(self):
        """num_ctx must comfortably exceed num_predict + image/prompt overhead —
        4096 forced context-shifting that evicted the transcription rules."""
        self.assertGreaterEqual(vision_ocr.NUM_CTX, vision_ocr.MAX_TOKENS * 2)

    def test_prompt_contract_clauses_present(self):
        p = vision_ocr.build_prompt("quantum mechanics", "en")
        for clause in ("LaTeX", "[?]", "crossed-out", "Do NOT interpret",
                       "ONLY markdown"):
            self.assertIn(clause, p)

    def test_module_importable_without_pdf2image(self):
        import ast
        src = (fixtures.SCRIPTS / "vision_ocr.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        top_level_imports = [
            n for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module == "pdf2image"
        ]
        self.assertEqual(top_level_imports, [],
                         "pdf2image must stay a lazy import inside ocr_pdf")


if __name__ == "__main__":
    unittest.main()
