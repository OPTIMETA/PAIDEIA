#!/usr/bin/env python3
"""
PAIDEIA reindex — idempotent, analyze-free in-place rewrite of course-index artifacts.

Two jobs:
  (A) coverage.md: rewrite retired tier markers to canonical vocabulary.
      Mapping (longest-key-first to prevent double-substitution):
        ✅✅ → 🔥🔥   ✅ → 🔥   🔴🔴 → ⚪   🔴 → 🟡
      Scope is header-driven, not positional:
        - Table rows: the Exam-tier column is located first by the canonical
          `Exam tier` header, then by non-canonical alias headers (e.g. `Strength`,
          `Emphasis`, `Priority`, `Weight`, `Tier`), and finally — when no
          recognised header exists (headless fragment) — by the rightmost cell
          that actually carries a tier glyph (retired or canonical).  Only that
          one cell is rewritten; §, Title, HW coverage and ⚠weak cells are
          preserved byte-for-byte even if a data cell holds a retired glyph.
        - Non-pipe lines (legend keys, aggregation / "Recommended drill priority"
          prose that names tier glyphs outside a table) are rewritten whole-line.
      Every rewritten glyph is counted, so a dry-run exits 1 while ANY retired
      glyph survives anywhere in the file and 0 only after real convergence.
      Write is atomic (tmp + os.replace).

  (B) errors/log.md: materialize phase/nature facets into on-disk data blocks.
      For each entry that lacks explicit phase: or nature:, infer from
      DEFAULT_PHASE / DEFAULT_NATURE (same maps as iter_error_entries at read-time).
      Explicit values win — never overwritten. required-6 / overridden_by byte-preserved.
      Write is atomic.

Usage:
    python3 reindex.py           # dry-run: report counts only, exit 0=clean 1=needs-fix
    python3 reindex.py --fix     # apply in-place; exit 0=already-clean 1=rewrote 2=failure

Must be run from the course root (where .course-meta lives).
Invoked by /paideia:reindex — do not call directly outside that context.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paideia_lib as plib  # noqa: E402

# ---------------------------------------------------------------------------
# Marker vocabulary — imported from paideia_lib (single source of truth, FND-008)
# RETIRED_TO_CANONICAL is defined in paideia_lib.RETIRED_TO_CANONICAL.
# ---------------------------------------------------------------------------
RETIRED_TO_CANONICAL = plib.RETIRED_TO_CANONICAL  # re-export for test_reindex.py import check

# Substitution order: always longest key first to prevent double-substitution.
# (✅✅ before ✅, 🔴🔴 before 🔴)
_ORDERED_RETIRED = sorted(RETIRED_TO_CANONICAL.keys(), key=len, reverse=True)

# Atomic tier glyphs — every single codepoint that names a tier, retired OR
# canonical, derived from the map so it stays single-source (FND-008). Used only
# to *locate* the tier cell in a headerless/ragged fallback (never to rewrite):
# a cell that carries any of these is a tier cell, so we prefer it over a merely
# non-empty trailing cell (e.g. a bare `L2`/`Notes` column) that has no glyph.
_TIER_GLYPHS = frozenset(
    ch
    for tok in (*RETIRED_TO_CANONICAL.keys(), *RETIRED_TO_CANONICAL.values())
    for ch in tok
)

# Canonical header label for the Exam-tier column (analyze.md:288 / course-builder/SKILL.md).
# Matched case-insensitively. The canonical form always wins over aliases.
_TIER_HEADER_CANONICAL = "exam tier"

# Non-canonical alias header labels for the Exam-tier column. These are
# recognized as a secondary match when the canonical `Exam tier` header is absent.
# Matched case-insensitively against the stripped cell content.
# Single source: if you add an alias here, that is the only place to change.
_TIER_HEADER_ALIASES: frozenset[str] = frozenset({
    "strength",
    "emphasis",
    "priority",
    "weight",
    "tier",
})

# Block-start sentinel — reuse paideia_lib's regex directly (single source of
# truth, FND-008). It accepts any whitespace run after the dash (r"^-\s+problem_id"),
# so we stay byte-consistent with iter_error_entries' own block detection even on
# non-canonical hand-edited spacing (two spaces / tab), not just the single-space seed.
_BLOCK_START_RX = plib._BLOCK_START_ENTRY_RX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _course_root(cwd: Path) -> Path | None:
    """Return cwd if .course-meta is present, else None (course-mode gate)."""
    return cwd if (cwd / ".course-meta").is_file() else None


def _atomic_write(path: Path, text: str) -> None:
    """Write text to path atomically via tmp + os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".reindex_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# (A) coverage.md rewrite
# ---------------------------------------------------------------------------

def _sub_retired(text: str) -> str:
    """Substitute retired tier markers with canonical equivalents in a string."""
    for retired in _ORDERED_RETIRED:
        text = text.replace(retired, RETIRED_TO_CANONICAL[retired])
    return text


def _split_cells(stripped: str) -> list[str] | None:
    """Split a pipe-delimited table line into cells, or None if not a table row.

    A genuine table row has a leading and a trailing pipe, so cells[0] and
    cells[-1] are the empty edges and there are >= 3 cells overall.
    """
    if "|" not in stripped:
        return None
    cells = stripped.split("|")
    if len(cells) < 3:
        return None
    return cells


def _find_tier_col_idx(text: str) -> int | None:
    """Locate the Exam-tier column index by scanning for the header row.

    Priority:
      1. Canonical `Exam tier` header (case-insensitive) — always wins.
      2. Alias headers from `_TIER_HEADER_ALIASES` (e.g. `Strength`, `Emphasis`,
         `Priority`, `Weight`, `Tier`) — recognized when the canonical header is
         absent. This is the primary fix for the alias-blindness defect: a
         Reverse-map table with header `Strength` + tier-column NOT rightmost
         was previously undetected → false EXIT 0 with retired glyphs surviving.
      3. None — no recognised header found; callers fall back to the rightmost
         glyph-bearing cell heuristic (_rightmost_glyph_cell).

    Takes the full file text as a string (splitlines internally). Returns the
    cell index (into `line.split("|")`) of the located column.
    """
    canonical_idx: int | None = None
    alias_idx: int | None = None

    for line in text.splitlines():
        cells = _split_cells(line.rstrip("\n"))
        if cells is None:
            continue
        # Skip table separator rows (|---|---|)
        non_edge = cells[1:-1]
        if all(re.match(r"^[\s\-:]+$", c) or c == "" for c in non_edge):
            continue
        for i, cell in enumerate(cells):
            label = cell.strip().lower()
            if label == _TIER_HEADER_CANONICAL:
                canonical_idx = i
                break  # canonical found in this row — no need to check aliases
            if alias_idx is None and label in _TIER_HEADER_ALIASES:
                alias_idx = i

    # Canonical always wins over alias.
    return canonical_idx if canonical_idx is not None else alias_idx


def _rightmost_glyph_cell(cells: list[str]) -> int | None:
    """Index of the rightmost cell that carries a tier glyph, or None.

    A tier glyph is any codepoint in `_TIER_GLYPHS` (retired OR canonical). This
    is the fallback locator when no recognised header (canonical or alias) can pin
    the column — a headerless reverse-map fragment, or a ragged row whose cell
    count is short of the header-identified index. Preferring the rightmost
    *glyph-bearing* cell over the rightmost merely-populated cell means a bare
    `| §1.6 | Title | ✅ | L2 |` headless fragment normalizes the ✅ instead of
    grabbing the trailing non-tier `L2` column and leaving the glyph behind.

    NOTE: alias recognition (step 2 in _find_tier_col_idx) is the primary defence
    against data-cell contamination when the tier column is non-rightmost. This
    fallback handles only genuinely headerless fragments.
    """
    for i in range(len(cells) - 1, -1, -1):
        if any(ch in _TIER_GLYPHS for ch in cells[i]):
            return i
    return None


def _rewrite_coverage_line(line: str, tier_col_idx: int | None) -> str:
    """Rewrite retired tier markers on a single coverage.md line.

    Two disjoint code paths, both counted by _process_coverage:

      * Pipe-delimited table rows — substitution is scoped to the Exam-tier
        column identified by `tier_col_idx` (the cell under the `Exam tier`
        header or a recognized alias header), NOT the rightmost populated cell.
        A retired glyph that legitimately appears in a data cell (a section title
        `Checklist ✅ done`, or a `Notes`/`L2` column to the right of the tier
        column) is preserved byte-for-byte (reindex.md). When the file carries no
        recognised header at all (`tier_col_idx is None` — a bare headless
        fragment), OR the header-identified index overruns a ragged row's cell
        count, we fall back to the rightmost *glyph-bearing* cell so a tier glyph
        at a lower index is still normalized instead of silently leaking. A bare
        trailing `L2`/`Notes` column has no glyph, so it is skipped.

      * Non-pipe lines (legend keys, aggregation / drill-priority prose that
        names tier glyphs outside a table) — `_sub_retired` is applied to the
        whole line, since there is no column structure to scope to.
    """
    # Preserve any trailing newline / whitespace, operate on the bare content.
    stripped = line.rstrip("\n")
    newline = line[len(stripped):]

    cells = _split_cells(stripped)
    if cells is None:
        # Not a table row → legend / aggregation prose. Normalize the whole line.
        rewritten = _sub_retired(stripped)
        if rewritten == stripped:
            return line
        return rewritten + newline

    # Table row: skip separator rows (|---|---|)
    non_edge = cells[1:-1]
    if all(re.match(r"^[\s\-:]+$", c) for c in non_edge if c):
        return line

    # Pick the Exam-tier cell. The header (canonical or alias) wins whenever it
    # addresses a cell in THIS row that actually holds a tier glyph — that is the
    # normal well-formed case, and it keeps a retired glyph in a data cell (a
    # title, or a `Notes`/`L2` column to the right) out of scope. A header cell
    # WITHOUT a glyph means this row is headerless or ragged/misaligned.
    idx = tier_col_idx
    header_hits_glyph = (
        idx is not None
        and idx < len(cells)
        and any(ch in _TIER_GLYPHS for ch in cells[idx])
    )
    if not header_hits_glyph:
        # No recognised header (or header overruns this ragged row, or header lands
        # on a non-glyph cell) → fall back to the rightmost glyph-bearing cell.
        # If no cell carries a tier glyph, there is nothing to do.
        idx = _rightmost_glyph_cell(cells)
    if idx is None or idx >= len(cells):
        return line  # blank row, or no tier cell locatable in this row
    rewritten = _sub_retired(cells[idx])
    if rewritten == cells[idx]:
        return line  # tier cell had no retired marker → byte-identical
    cells[idx] = rewritten
    return "|".join(cells) + newline


def _process_coverage(path: Path, fix: bool) -> tuple[int, bool]:
    """Return (retired_count, write_error).

    retired_count: number of LINES rewritten — table rows whose Exam-tier cell
    (located by canonical header, alias header, or glyph-bearing-cell fallback)
    carried a retired marker PLUS non-pipe legend/prose lines carrying one. A
    dry-run (fix=False) returns this count unchanged so main() exits 1 while ANY
    retired glyph survives anywhere in coverage.md and 0 only after convergence.
    Retired glyphs living only in a preserved data cell (a title, or a Notes/L2
    column) do NOT count — they are intentionally not rewritten.
    write_error: True if an atomic write failed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0, False

    tier_col_idx = _find_tier_col_idx(text)

    lines = text.splitlines(keepends=True)
    retired_count = 0
    new_lines: list[str] = []
    changed = False

    for line in lines:
        new_line = _rewrite_coverage_line(line, tier_col_idx)
        if new_line != line:
            retired_count += 1
            changed = True
        new_lines.append(new_line if fix else line)

    if fix and changed:
        try:
            _atomic_write(path, "".join(new_lines))
        except OSError:
            return retired_count, True

    return retired_count, False


# ---------------------------------------------------------------------------
# (B) errors/log.md facet materialization
# ---------------------------------------------------------------------------

def _split_blocks(text: str) -> list[tuple[int, int]]:
    """Return list of (start_line_idx, end_line_idx) for each entry block.

    Mirrors paideia_lib._split_error_blocks but returns index ranges for
    byte-preserving reconstruction instead of string slices.
    Comment-aware: lines inside <!-- … --> do not start blocks.
    """
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    in_comment = False
    for i, ln in enumerate(lines):
        if not in_comment and _BLOCK_START_RX.match(ln):
            starts.append(i)
        opens = ln.rfind("<!--")
        closes = ln.rfind("-->")
        if opens > closes:
            in_comment = True
        elif closes > opens or (closes >= 0 and opens < 0):
            in_comment = False

    if not starts:
        return []
    ends = starts[1:] + [len(lines)]
    return list(zip(starts, ends))


def _get_field(block_lines: list[str], key: str) -> str | None:
    """Extract field value from block lines."""
    rx = re.compile(rf"^\s*-?\s*{re.escape(key)}\s*:\s*(.+?)\s*$")
    for ln in block_lines:
        m = rx.match(ln)
        if m:
            v = m.group(1).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            return v
    return None


def _has_field(block_lines: list[str], key: str) -> bool:
    rx = re.compile(rf"^\s*-?\s*{re.escape(key)}\s*:")
    return any(rx.match(ln) for ln in block_lines)


def _insert_facets(block_lines: list[str], phase_val: str | None, nature_val: str | None) -> list[str]:
    """Insert phase/nature lines after the error_type line if they are missing.

    Returns new block lines list. Preserves all existing lines byte-for-byte.
    Insertion point: immediately after the first `error_type:` line.
    """
    if not phase_val and not nature_val:
        return block_lines

    result = []
    inserted = False
    for ln in block_lines:
        result.append(ln)
        if not inserted and re.match(r"^\s*-?\s*error_type\s*:", ln):
            # Match the sibling required-6 keys' indent exactly. `error_type:`
            # is itself a 2-space-indented sibling (its `- problem_id:` block
            # opener puts the dash+space at col 0, mapping keys at 2 spaces), so
            # `leading` is already the sibling indent — do NOT add another level,
            # or phase/nature land at 4 spaces and the block is malformed YAML
            # (PyYAML raises ScannerError). This mirrors log_tool.py's
            # inject_override_marker, which writes `  overridden_by:` at 2 spaces.
            leading = re.match(r"^(\s*)", ln).group(1)
            if phase_val:
                result.append(f"{leading}phase: {phase_val}\n")
            if nature_val:
                result.append(f"{leading}nature: {nature_val}\n")
            inserted = True
    return result


def _process_log(path: Path, fix: bool) -> tuple[int, bool]:
    """Return (entries_needing_materialization, write_error).

    Materializes phase/nature into blocks that lack them, using DEFAULT_PHASE /
    DEFAULT_NATURE. Explicit values win. required-6 / overridden_by byte-preserved.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0, False

    lines = text.splitlines(keepends=True)
    block_ranges = _split_blocks(text)

    if not block_ranges:
        return 0, False

    needs_count = 0
    # Build replacement: list of (start_idx, end_idx, new_lines)
    replacements: list[tuple[int, int, list[str]]] = []

    for start, end in block_ranges:
        block_lines = lines[start:end]
        error_type = _get_field(block_lines, "error_type") or ""

        has_phase = _has_field(block_lines, "phase")
        has_nature = _has_field(block_lines, "nature")

        if has_phase and has_nature:
            continue  # already materialized

        infer_phase = plib.DEFAULT_PHASE.get(error_type) if not has_phase else None
        infer_nature = plib.DEFAULT_NATURE.get(error_type) if not has_nature else None

        if infer_phase is None and infer_nature is None:
            # Unknown error_type AND both already present — skip.
            continue

        needs_count += 1
        if fix:
            new_block = _insert_facets(block_lines, infer_phase, infer_nature)
            replacements.append((start, end, new_block))

    if fix and replacements:
        # Apply replacements from back to front to keep indices valid.
        for start, end, new_block in sorted(replacements, key=lambda x: x[0], reverse=True):
            lines[start:end] = new_block
        try:
            _atomic_write(path, "".join(lines))
        except OSError:
            return needs_count, True

    return needs_count, False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent reindex of course-index artifacts (coverage.md marker rewrite + errors/log.md facet materialization)."
    )
    parser.add_argument("--fix", action="store_true",
                        help="Apply rewrites in-place (atomic). Default is dry-run.")
    parser.add_argument("--log", default="errors/log.md",
                        help="Path to errors/log.md relative to CWD (default: errors/log.md).")
    args = parser.parse_args()

    cwd = Path.cwd()
    root = _course_root(cwd)
    if root is None:
        print("reindex: no .course-meta in this directory — course mode required.")
        print("Run /paideia:init-course to create a course folder.")
        # no-op, not a failure
        return 0

    mode = "fix" if args.fix else "dry-run"
    coverage_path = root / "course-index" / "coverage.md"
    log_path = root / args.log

    overall_exit = 0  # 0 = already clean, 1 = needed/performed work

    # --- (A) coverage.md ---
    if coverage_path.is_file():
        retired_count, cov_err = _process_coverage(coverage_path, args.fix)
        if cov_err:
            print(f"reindex [{mode}]: FAILED to write coverage.md (disk error)")
            overall_exit = 2
        elif retired_count > 0:
            if args.fix:
                print(f"reindex [fix]: rewrote coverage.md — {retired_count} retired marker line(s) → canonical")
            else:
                print(f"reindex [dry-run]: coverage.md has {retired_count} retired marker line(s) needing rewrite")
            overall_exit = max(overall_exit, 1)
        else:
            print("reindex: coverage.md already uses canonical tier vocabulary")
    else:
        print("reindex: coverage.md not found — run /paideia:analyze first")

    # --- (B) errors/log.md ---
    if log_path.is_file():
        needs_count, log_err = _process_log(log_path, args.fix)
        if log_err:
            print(f"reindex [{mode}]: FAILED to write {args.log} (disk error)")
            overall_exit = 2
        elif needs_count > 0:
            if args.fix:
                print(f"reindex [fix]: materialized phase/nature into {needs_count} log entr(y/ies)")
            else:
                print(f"reindex [dry-run]: {needs_count} log entr(y/ies) need phase/nature materialization")
            overall_exit = max(overall_exit, 1)
        else:
            print(f"reindex: {args.log} facets already materialized (header-data 1:1)")
    else:
        print(f"reindex: {args.log} not found — run /paideia:init-course or /paideia:doctor --fix")

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
