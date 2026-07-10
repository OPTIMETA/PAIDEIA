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

# Marker key injected onto a superseded entry when a human override corrects a
# misgrade (FND-025). It is NOT one of the six required keys and NOT a routing
# facet — it is a purely additive audit marker: `overridden_by: <source>` names
# the correcting source. Readers that count "current verdicts" (top_pattern,
# and anything built on iter_error_entries) skip blocks carrying it, so an
# overridden original never double-counts against its correction. log_tool
# `override` is the only writer; stdin blocks passing it are rejected.
OVERRIDE_KEY = "overridden_by"

# ---------------------------------------------------------------------------
# v2 오류분류학 상수 — 02 §4.2·§4.3 (전부 가법; ERROR_TYPES 불변)
# ---------------------------------------------------------------------------

PHASE_SET = frozenset({
    "reading", "comprehension", "transformation", "execution", "encoding",
})

NATURE_SET = frozenset({"slip", "misconception", "gap"})

SOLO_SET = frozenset({
    "prestructural", "unistructural", "multistructural", "relational", "extended",
})

KNOWLEDGE_SET = frozenset({"conceptual", "procedural"})

PREDICTED_SET = frozenset({"pass", "partial", "fail"})

# §4.3 확장 controlled vocab: ERROR_TYPES 6종 ⊂ ERROR_TYPES_EXT (신규 leaf는 후순위)
# per 02 §4.3
ERROR_TYPES_EXT = frozenset(ERROR_TYPES | {
    "wrong-approach", "arithmetic", "notation",
    "misread-givens", "wrong-goal", "units", "incomplete",
})

# ---------------------------------------------------------------------------
# v2 하위호환 추론맵 — 02 §4.4
# TS errorsLog.ts DEFAULT_PHASE / DEFAULT_NATURE와 바이트 등가여야 함.
# 교차검증 정본: packages/paideia-core/test/fixtures/errorTaxonomyV2Defaults.json
# ---------------------------------------------------------------------------

DEFAULT_PHASE = {
    "pattern-missed": "transformation",
    "wrong-variable": "transformation",
    "wrong-end-form": "encoding",
    "algebraic": "execution",
    "sign": "execution",
    "definition": "comprehension",
}

DEFAULT_NATURE = {  # 보수적: 애매하면 misconception (과소평가 방지)
    "sign": "slip",
    "algebraic": "slip",
    "arithmetic": "slip",
    "notation": "slip",
    "pattern-missed": "misconception",
    "wrong-variable": "misconception",
    "definition": "gap",
    "wrong-end-form": "misconception",
}

# Seed for errors/log.md — the same text init-course Step 4 writes and doctor
# --fix restores, so /grade and /weakmap always find the schema they expect.
ERRORS_LOG_SEED = """# Error log

<!-- Append-only YAML entries. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  phase: reading | comprehension | transformation | execution | encoding   # optional (F2) — inferred from error_type when absent
  nature: slip | misconception | gap   # optional (F3) — inferred from error_type when absent
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts>>
  date: <ISO8601>
  overridden_by: <source>   # optional — present only on entries superseded by a human override
Only the six keys problem_id/pattern/error_type/summary/source/date are required; phase/nature/overridden_by are optional.
Write entries via scripts/log_tool.py (idempotent per source) — do not hand-edit appends.
-->
"""

_META_RX = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(.+?)\s*$")

# Robust to schema drift: the canonical /grade entry uses `pattern:` but older
# /blind entries may have used `pattern_missed_initial:`. Accept both.
PATTERN_RX = re.compile(r"\b(?:pattern|pattern_missed_initial)\s*:\s*(P\d+)")

# ---------------------------------------------------------------------------
# Tier-marker migration vocabulary — single source of truth (FND-008)
# Longest keys first: substitute ✅✅ before ✅, 🔴🔴 before 🔴 to prevent
# double-substitution (e.g. ✅✅ → 🔥🔥🔥 if ✅ is processed first).
# Used by reindex.py; also re-confirmed in analyze.md:301 / course-builder/SKILL.md:154.
# ---------------------------------------------------------------------------
RETIRED_TO_CANONICAL: dict[str, str] = {
    "✅✅": "🔥🔥",
    "✅":   "🔥",
    "🔴🔴": "⚪",
    "🔴":   "🟡",
}


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
    """Most frequent Pk across *current* errors/log.md entries, None when none.

    "Current" excludes entries a human override superseded (FND-025): a block
    carrying `overridden_by:` is a retained original, not a live verdict, so it
    is skipped here. This keeps the statusline top-miss and the weakmap
    histogram counting the correction, not the correction *and* the original.
    PATTERN_RX still matches both `pattern:` and the legacy
    `pattern_missed_initial:` within each surviving block."""
    counts: dict[str, int] = {}
    for blk in _split_error_blocks(log_text):
        if _block_field(blk, OVERRIDE_KEY) is not None:
            continue  # retained original — not a current verdict
        for m in PATTERN_RX.finditer(blk):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# v2 파서·헬퍼 — 02 §1.1 (순수 함수; log_tool.split_blocks 미러)
# ---------------------------------------------------------------------------

_BLOCK_START_ENTRY_RX = re.compile(r"^-\s+problem_id\s*:")
_ENTRY_FIELD_RX = re.compile(r"^\s*-?\s*(\w[\w\-]*)\s*:\s*(.+?)\s*$")

_V2_FIELDS = (
    "problem_id", "pattern", "error_type", "phase", "nature",
    "knowledge", "solo", "predicted", "fix", "summary", "source", "date",
)


def _unquote_val(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _block_field(block: str, key: str) -> str | None:
    """Extract a single field value from a YAML-list block."""
    rx = re.compile(rf"^\s*-?\s*{re.escape(key)}\s*:\s*(.+?)\s*$", re.MULTILINE)
    m = rx.search(block)
    if m:
        return _unquote_val(m.group(1))
    return None


def _split_error_blocks(log_text: str) -> list[str]:
    """Split errors/log.md into entry-block strings (comment-aware).

    A block starts at a top-level `- problem_id:` line (no leading whitespace —
    byte-identical to log_tool._BLOCK_START_RX and errorsLog.ts BLOCK_START) and
    runs to the next such line or EOF. Lines inside <!-- … --> HTML comments
    (e.g. the seed schema example) never start a block. Sole splitter for both
    iter_error_entries and top_pattern, so the override filter and the metrics
    readers can never disagree on block boundaries."""
    lines = log_text.splitlines()
    starts: list[int] = []
    in_comment = False
    for i, ln in enumerate(lines):
        if not in_comment and _BLOCK_START_ENTRY_RX.match(ln):
            starts.append(i)
        opens = ln.rfind("<!--")
        closes = ln.rfind("-->")
        if opens > closes:
            in_comment = True
        elif closes > opens or (closes >= 0 and opens < 0):
            in_comment = False
    if not starts:
        return []
    return ["\n".join(lines[a:b]).rstrip()
            for a, b in zip(starts, starts[1:] + [len(lines)])]


def iter_error_entries(log_text: str) -> list[dict[str, str | None]]:
    """Parse errors/log.md into a list of dicts, mirroring errorsLog.ts::parseErrorsLog.

    Blocks start at top-level `- problem_id:` lines — a byte-identical sentinel
    to log_tool._BLOCK_START_RX and errorsLog.ts BLOCK_START (no leading
    whitespace class, so an indented `  - problem_id:` line is NOT a block
    start, matching both block splitters).  has_error_entries deliberately
    keeps a looser leading-whitespace probe for its boolean existence check.
    Lines inside <!-- … --> HTML comments (e.g. the seed schema example) never
    start a block.

    For each block, phase and nature are promoted from DEFAULT_PHASE /
    DEFAULT_NATURE when absent.  Unknown error_type produces None for the
    promoted field (lenient — reader never rejects).
    """
    blocks = _split_error_blocks(log_text)
    if not blocks:
        return []

    entries: list[dict[str, str | None]] = []
    for raw in blocks:
        et = _block_field(raw, "error_type")
        key = et or ""

        # v2 phase/nature promotion: explicit field wins; else infer from map
        phase_explicit = _block_field(raw, "phase")
        nature_explicit = _block_field(raw, "nature")
        phase = phase_explicit if phase_explicit is not None else DEFAULT_PHASE.get(key)
        nature = nature_explicit if nature_explicit is not None else DEFAULT_NATURE.get(key)

        entry: dict[str, str | None] = {
            "problem_id": _block_field(raw, "problem_id"),
            "pattern": _block_field(raw, "pattern"),
            "error_type": et,
            "phase": phase,
            "nature": nature,
            "knowledge": _block_field(raw, "knowledge"),
            "solo": _block_field(raw, "solo"),
            "predicted": _block_field(raw, "predicted"),
            "fix": _block_field(raw, "fix"),
            "summary": _block_field(raw, "summary"),
            "source": _block_field(raw, "source"),
            "date": _block_field(raw, "date"),
            # Audit marker (FND-025): present only on entries a human override
            # superseded. Non-None ⇒ this is a retained original, not a current
            # verdict — verdict-counting readers filter it out.
            OVERRIDE_KEY: _block_field(raw, OVERRIDE_KEY),
        }
        entries.append(entry)
    return entries


def phase_counts(log_text: str) -> dict[str, int]:
    """M8 — histogram of promoted phase values across current entries.

    Uses iter_error_entries (which applies DEFAULT_PHASE promotion), so v1
    entries without an explicit phase field are counted under their inferred
    phase. Entries superseded by a human override (`overridden_by:` present) are
    skipped — the correction is the current verdict, not the retained original.
    """
    counts: dict[str, int] = {}
    for entry in iter_error_entries(log_text):
        if entry.get(OVERRIDE_KEY) is not None:
            continue
        p = entry.get("phase")
        if p:
            counts[p] = counts.get(p, 0) + 1
    return counts


def nature_ratio(log_text: str) -> float:
    """M9 — #slip / #(misconception + gap) over current entries.

    Entries superseded by a human override (`overridden_by:` present) are
    skipped — only current verdicts count toward the ratio.

    Denominator-zero guard:
      - both zero  → 0.0
      - slip > 0, denom = 0  → float('inf')
    """
    slip = 0
    other = 0
    for entry in iter_error_entries(log_text):
        if entry.get(OVERRIDE_KEY) is not None:
            continue
        n = entry.get("nature")
        if n == "slip":
            slip += 1
        elif n in ("misconception", "gap"):
            other += 1
    if other == 0:
        return float("inf") if slip > 0 else 0.0
    return slip / other


def calibration_gap(attempts: list[dict[str, str]]) -> float | None:
    """M3 — mean(s(predicted) - s(actual)) for entries where predicted is present.

    Positive = overconfidence.  Returns None when no entry has a predicted key.

    Score map: pass / PASS → 1.0,  partial / PARTIAL → 0.5,  fail / FAIL → 0.0
    """
    _score: dict[str, float] = {
        "pass": 1.0, "PASS": 1.0,
        "partial": 0.5, "PARTIAL": 0.5,
        "fail": 0.0, "FAIL": 0.0,
    }
    diffs: list[float] = []
    for a in attempts:
        pred = a.get("predicted")
        if pred is None:
            continue
        verdict = a.get("verdict", "")
        sp = _score.get(pred)
        sv = _score.get(verdict)
        if sp is None or sv is None:
            continue
        diffs.append(sp - sv)
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


def recurrence(
    entries: list[dict[str, str | None]],
    remediations: list[dict[str, str]],
) -> dict[str, float]:
    """M2 — per-pattern recurrence rate after remediation.

    remediations: list of {"pattern": Pk, "date": "YYYY-MM-DD"}.
    Result: {Pk: #(errors after max-remediation-date) / #(remediations)}.
    Patterns with no remediation are excluded from the result.
    """
    from collections import defaultdict

    # Group remediation dates by pattern
    rem_dates: dict[str, list[str]] = defaultdict(list)
    for r in remediations:
        pat = r.get("pattern")
        dt = r.get("date")
        if pat and dt:
            rem_dates[pat].append(dt)

    result: dict[str, float] = {}
    for pat, dates in rem_dates.items():
        max_rem_date = max(dates)
        n_rem = len(dates)
        # Count error entries for this pattern dated after the last remediation
        n_recur = sum(
            1
            for e in entries
            if e.get("pattern") == pat
            and (e.get("date") or "") > max_rem_date
        )
        result[pat] = n_recur / n_rem
    return result
