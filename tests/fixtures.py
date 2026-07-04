"""Shared helpers for the paideia test suite (stdlib only — no pytest)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugins" / "paideia" / "scripts"
COMMANDS = REPO / "plugins" / "paideia" / "commands"
SKILLS = REPO / "plugins" / "paideia" / "skills"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_course(
    tmp: Path,
    exam_date: str,
    lang: str = "ko",
    with_patterns: bool = True,
    with_quiz: bool = True,
    with_errors: bool = True,
    with_mock: bool = False,
    with_cheatsheet: bool = False,
) -> Path:
    """Build a minimal course workspace exercising every phase input."""
    (tmp / ".course-meta").write_text(
        "COURSE_NAME: Complex Analysis  # main\n"
        f"EXAM_DATE: {exam_date}\n"
        "EXAM_TYPE: final\n"
        "USER_WEAK_ZONES: residues\n"
        "OCR_ENGINE: claude\n"
        f"INTERFACE_LANG: {lang}\n",
        encoding="utf-8",
    )
    if with_patterns:
        (tmp / "course-index").mkdir(exist_ok=True)
        (tmp / "course-index" / "patterns.md").write_text("### P1. x\n", encoding="utf-8")
    if with_quiz:
        (tmp / "quizzes").mkdir(exist_ok=True)
        (tmp / "quizzes" / "diagnostic_20260601_120000.md").write_text("## P1\n", encoding="utf-8")
        (tmp / "quizzes" / "diagnostic_20260601_120000_answers.md").write_text("## P1\n", encoding="utf-8")
    if with_errors:
        (tmp / "errors").mkdir(exist_ok=True)
        log = (
            "# Error log\n\n"
            "- problem_id: hw3-p2\n  pattern: P6\n  error_type: sign\n"
            '  summary: "s"\n  source: answers/converted/hw3.md\n  date: 2026-06-01\n'
            "- problem_id: hw3-p1\n  pattern: P6\n  error_type: algebraic\n"
            '  summary: "s"\n  source: answers/converted/hw3.md\n  date: 2026-06-01\n'
        )
        if with_mock:
            log += (
                "- problem_id: mock_x-P1\n  pattern: P2\n  error_type: pattern-missed\n"
                '  summary: "m"\n  source: answers/converted/mock_20260601.md\n  date: 2026-06-02\n'
            )
        (tmp / "errors" / "log.md").write_text(log, encoding="utf-8")
    if with_cheatsheet:
        (tmp / "cheatsheet").mkdir(exist_ok=True)
        (tmp / "cheatsheet" / "final.md").write_text("x\n", encoding="utf-8")
    return tmp
