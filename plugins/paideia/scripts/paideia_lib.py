"""
Shared helpers for the paideia plugin scripts.

Single source of truth for `.course-meta` parsing, exam D-day math, the
study-phase state machine, and errors/log.md pattern counting. Previously
statusline.py, session_start.py, doctor.py, and vision_ocr.py each carried a
private copy guarded by "all three parsers must agree" comments — the comment
being needed at all was the bug. Now they import this.

Import pattern (the scripts can be invoked from any CWD, so pin the path):

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import paideia_lib as plib
"""
from __future__ import annotations

import datetime
import glob
import re
from pathlib import Path

VALID_ENGINES = {"claude", "ollama", "tesseract"}
VALID_LANGS = {"en", "ko"}

ERROR_TYPES = {
    "pattern-missed", "wrong-variable", "wrong-end-form",
    "algebraic", "sign", "definition",
}

# Seed for errors/log.md — the same text init-course Step 4 writes and doctor
# --fix restores, so /grade and /weakmap always find the schema they expect.
ERRORS_LOG_SEED = """# Error log

<!-- Append-only YAML entries. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts>>
  date: <ISO8601>
Write entries via scripts/log_tool.py (idempotent per source) — do not hand-edit appends.
-->
"""

_META_RX = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(.+?)\s*$")

# Robust to schema drift: the canonical /grade entry uses `pattern:` but older
# /blind entries may have used `pattern_missed_initial:`. Accept both.
PATTERN_RX = re.compile(r"\b(?:pattern|pattern_missed_initial)\s*:\s*(P\d+)")


def parse_meta(cwd: Path) -> dict[str, str]:
    """Parse `.course-meta` into a dict. Empty dict when absent/unreadable.

    Every value has a trailing `# comment` stripped, so a hand-annotated line
    like `COURSE_NAME: Complex Analysis  # main` doesn't leak the annotation
    into the statusline / SessionStart banner / VLM prompt.
    """
    meta: dict[str, str] = {}
    p = cwd / ".course-meta"
    if not p.exists():
        return meta
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _META_RX.match(line)
            if m:
                meta[m.group(1)] = m.group(2).split("#", 1)[0].strip()
    except OSError:
        pass
    return meta


def interface_lang(meta: dict[str, str]) -> str:
    """Normalized interface language from parsed meta — always 'en' or 'ko'."""
    lang = meta.get("INTERFACE_LANG", "en").strip().lower()
    return lang if lang in VALID_LANGS else "en"


def days_until(exam_date: str) -> int | None:
    try:
        d = datetime.datetime.strptime(exam_date.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    return (d - datetime.date.today()).days


# --------------------------------------------------------------------------- #
# phase detection (artifact/activity derived, not time derived)
# --------------------------------------------------------------------------- #

def read_errors_log(cwd: Path) -> str:
    log = cwd / "errors" / "log.md"
    if not log.exists():
        return ""
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def quiz_problems_exist(cwd: Path) -> bool:
    """True iff at least one quiz PROBLEM file exists (excluding _answers siblings)."""
    for p in glob.glob(str(cwd / "quizzes" / "*.md")):
        if not p.endswith("_answers.md"):
            return True
    return False


def has_error_entries(log_text: str) -> bool:
    return bool(re.search(r"^\s*-\s+problem_id\s*:", log_text, re.MULTILINE))


def mock_was_graded(log_text: str) -> bool:
    """Did at least one grade write back a mock-sourced entry?"""
    if re.search(r"^\s*source\s*:\s*(?:answers/converted/)?mock[/_]", log_text, re.MULTILINE):
        return True
    if re.search(r"^\s*problem_id\s*:\s*['\"]?mock[_\-]", log_text, re.MULTILINE):
        return True
    return False


def phase(cwd: Path, days: int | None) -> str:
    """One phase implementation for BOTH the statusline and the SessionStart
    hook — they previously had separate copies that disagreed on D-0 (the hook
    lacked `cool`, so on exam day the status bar and the banner showed
    different phases).

      setup - course-index/patterns.md absent
      diag  - patterns exist, but no quiz problems yet, or no graded error yet
      drill - quiz problems exist AND errors/log.md has a graded entry
      mock  - a mock exam has been graded (errors/log.md has a mock source)
      cram  - cheatsheet/final.{md,pdf} present
      cool  - D-0 (today == exam date) overrides all
    """
    if days == 0:
        return "cool"
    cheatsheet = cwd / "cheatsheet"
    if (cheatsheet / "final.pdf").exists() or (cheatsheet / "final.md").exists():
        return "cram"
    log_text = read_errors_log(cwd)
    if mock_was_graded(log_text):
        return "mock"
    if not (cwd / "course-index" / "patterns.md").exists():
        return "setup"
    if quiz_problems_exist(cwd) and has_error_entries(log_text):
        return "drill"
    return "diag"


# --------------------------------------------------------------------------- #
# weakmap / error-log helpers
# --------------------------------------------------------------------------- #

def latest_weakmap(cwd: Path) -> Path | None:
    wms = sorted(glob.glob(str(cwd / "weakmap" / "weakmap_*.md")), reverse=True)
    return Path(wms[0]) if wms else None


def top_pattern(log_text: str) -> str | None:
    """Most frequent Pk across errors/log.md entries, None when no matches."""
    counts: dict[str, int] = {}
    for m in PATTERN_RX.finditer(log_text):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)
