#!/usr/bin/env python3
"""
PAIDEIA log_tool — the deterministic writer for errors/log.md.

errors/log.md is the heart of the study graph (weakmap, quiz weakmap, and the
cheatsheet are all derived from it), and its idempotence rule — "re-grading
the same source must replace that source's entries, not pile up duplicates" —
used to be executed by the model as a prose instruction: surgically deleting
matching YAML list items inside a markdown file by hand. One slip corrupts the
learning record. This tool makes the contract code:

    # replace-then-append all entries for one source (idempotent):
    python3 log_tool.py append --source=<source> [--log=errors/log.md] <<'YAML'
    - problem_id: hw3-p2
      pattern: P6
      error_type: sign
      summary: "dropped the minus on kappa"
      source: answers/converted/hw3.md
      date: 2026-07-05
    YAML

    # drop every entry for one source (e.g. a grade issued in error):
    python3 log_tool.py remove --source=<source> [--log=errors/log.md]

    # human override — preserve original verdict, append correction, link with overridden_by:
    python3 log_tool.py override --source=<source> [--log=errors/log.md] <<'YAML'
    - problem_id: hw3-p2
      pattern: P6
      error_type: definition
      summary: "corrected: sign error was actually a definition issue"
      source: answers/converted/hw3.md
      date: 2026-07-10
    YAML

Guarantees:
- Every existing entry whose `source:` equals --source is removed first, then
  the stdin entries are appended — the log stays "latest grading per source".
- Entries are schema-validated before anything is written: all six keys
  present, `error_type` in the canonical set, `date` starting YYYY-MM-DD, and
  every entry's `source:` equal to --source (catches drift at the door).
- The write is atomic (tmp file + os.replace) and utf-8.
- Preamble (the seed header comment) and entries for other sources are
  preserved byte-for-byte.
- override: original entries are preserved in the log with `overridden_by: <source>`
  added (one line injected, six required keys untouched). The correction entries
  are appended without `overridden_by`. Callers MUST NOT include `overridden_by`
  in override stdin — the tool assigns it to prevent drift.
- override idempotency: re-running override on the same source marks only the
  current "live" entries (those without `overridden_by`); already-marked originals
  are left unchanged (no duplicate markers). The previous correction becomes the
  new original-with-marker; the new stdin becomes the current verdict.

Exit codes: 0 = ok, 2 = usage/validation error (nothing written).
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paideia_lib as plib  # noqa: E402

REQUIRED_KEYS = ("problem_id", "pattern", "error_type", "summary", "source", "date")

_BLOCK_START_RX = re.compile(r"^-\s+problem_id\s*:")
_KEY_RX = {k: re.compile(rf"^\s*-?\s*{k}\s*:\s*(.+?)\s*$") for k in REQUIRED_KEYS}


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def split_blocks(text: str) -> tuple[str, list[str]]:
    """Split log text into (preamble, [entry blocks]). A block starts at a
    top-level `- problem_id:` line and runs to the next one (or EOF).

    Lines inside `<!-- … -->` HTML comments never start a block — the seed
    header documents the schema with a literal `- problem_id: <id>` example,
    which must stay part of the preamble, not be parsed as an entry."""
    lines = text.splitlines()
    starts: list[int] = []
    in_comment = False
    for i, ln in enumerate(lines):
        if not in_comment and _BLOCK_START_RX.match(ln):
            starts.append(i)
        opens, closes = ln.rfind("<!--"), ln.rfind("-->")
        if opens > closes:
            in_comment = True
        elif closes > opens or (closes >= 0 and opens < 0):
            in_comment = False
    if not starts:
        return text, []
    preamble = "\n".join(lines[: starts[0]])
    blocks = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        blocks.append("\n".join(lines[a:b]).rstrip())
    return preamble, blocks


def block_field(block: str, key: str) -> str | None:
    for ln in block.splitlines():
        m = _KEY_RX[key].match(ln)
        if m:
            return _unquote(m.group(1))
    return None


_OVERRIDE_KEY_RX = re.compile(r"^\s*overridden_by\s*:", re.IGNORECASE)


def block_has_override_marker(block: str) -> bool:
    """Return True if the block already carries an `overridden_by:` line."""
    return any(_OVERRIDE_KEY_RX.match(ln) for ln in block.splitlines())


def inject_override_marker(block: str, source: str) -> str:
    """Append `  overridden_by: <source>` after the `date:` line of a block.
    If `overridden_by` is already present (idempotency), return block unchanged."""
    if block_has_override_marker(block):
        return block
    lines = block.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"^\s*date\s*:", ln):
            lines.insert(i + 1, f"  overridden_by: {source}")
            return "\n".join(lines)
    # date line not found — append at end
    return block + f"\n  overridden_by: {source}"


def validate_entries(blocks: list[str], source: str,
                     reject_override_key: bool = False) -> list[str]:
    """Return a list of human-readable problems; empty = valid.

    When `reject_override_key` is True (used by the `override` subcommand),
    any stdin block that already carries `overridden_by:` is rejected — the
    tool assigns that marker, not the caller.
    """
    problems: list[str] = []
    if not blocks:
        problems.append("stdin contained no `- problem_id:` entry blocks")
    for i, blk in enumerate(blocks, 1):
        if reject_override_key and block_has_override_marker(blk):
            problems.append(
                f"entry {i}: `overridden_by:` must not appear in override stdin — "
                "the tool assigns this marker to prevent drift")
        for k in REQUIRED_KEYS:
            if block_field(blk, k) is None:
                problems.append(f"entry {i}: missing key `{k}:`")
        et = block_field(blk, "error_type")
        if et is not None and et not in plib.ERROR_TYPES:
            problems.append(
                f"entry {i}: error_type '{et}' not in "
                f"{{{' | '.join(sorted(plib.ERROR_TYPES))}}}")
        dt = block_field(blk, "date")
        if dt is not None and not re.match(r"^\d{4}-\d{2}-\d{2}", dt):
            problems.append(f"entry {i}: date '{dt}' does not start YYYY-MM-DD")
        src = block_field(blk, "source")
        if src is not None and src != source:
            problems.append(
                f"entry {i}: source '{src}' != --source '{source}' "
                "(every entry in one append must belong to the source being replaced)")
    return problems


def apply_override(log_path: Path, source: str,
                   correction_blocks: list[str]) -> tuple[int, int, int]:
    """Mark existing blocks for `source` with `overridden_by`, then append corrections.

    Original entries are preserved with `overridden_by: <source>` injected after
    their `date:` line. Blocks that already carry the marker are left unchanged
    (idempotency — re-running override never adds duplicate markers). The
    correction blocks are appended as the new current verdict (no marker).

    Write is atomic (tmp + os.replace), utf-8.

    Returns (marked_count, already_marked_count, appended_count).
    """
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = plib.ERRORS_LOG_SEED
    preamble, blocks = split_blocks(text)

    marked = 0
    already_marked = 0
    out_blocks: list[str] = []
    for blk in blocks:
        if block_field(blk, "source") == source:
            if block_has_override_marker(blk):
                # Already marked in a previous override run — leave as-is.
                already_marked += 1
                out_blocks.append(blk.rstrip())
            else:
                # Live entry for this source — mark it as overridden.
                out_blocks.append(inject_override_marker(blk.rstrip(), source))
                marked += 1
        else:
            out_blocks.append(blk.rstrip())

    out_blocks.extend(b.rstrip() for b in correction_blocks)

    parts = [preamble.rstrip("\n")]
    if out_blocks:
        parts.append("\n".join(out_blocks))
    out_text = "\n\n".join(p for p in parts if p) + "\n"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(log_path.parent), prefix=".log_tool-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out_text)
        os.replace(tmp, log_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return marked, already_marked, len(correction_blocks)


def rewrite(log_path: Path, source: str, new_blocks: list[str]) -> tuple[int, int]:
    """Drop existing blocks matching `source`, append `new_blocks`, write
    atomically. Returns (removed_count, appended_count)."""
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = plib.ERRORS_LOG_SEED
    preamble, blocks = split_blocks(text)
    survivors = [b for b in blocks if block_field(b, "source") != source]
    removed = len(blocks) - len(survivors)
    out_blocks = survivors + [b.rstrip() for b in new_blocks]

    parts = [preamble.rstrip("\n")]
    if out_blocks:
        parts.append("\n".join(out_blocks))
    out_text = "\n\n".join(p for p in parts if p) + "\n"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(log_path.parent), prefix=".log_tool-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out_text)
        os.replace(tmp, log_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return removed, len(new_blocks)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("append", "remove", "override"):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: log_tool.py append|remove|override --source=<source> [--log=<path>]",
              file=sys.stderr)
        return 2
    cmd = argv[0]
    source: str | None = None
    log_path = Path("errors/log.md")
    for arg in argv[1:]:
        if arg.startswith("--source="):
            source = _unquote(arg.split("=", 1)[1])
        elif arg.startswith("--log="):
            log_path = Path(arg.split("=", 1)[1])
        else:
            print(f"error: unknown argument '{arg}'", file=sys.stderr)
            return 2
    if not source:
        print("error: --source=<source> is required", file=sys.stderr)
        return 2

    if cmd == "remove":
        removed, _ = rewrite(log_path, source, [])
        print(f"log_tool: removed {removed} entr{'y' if removed == 1 else 'ies'} "
              f"for source '{source}' in {log_path}")
        return 0

    stdin_text = sys.stdin.read()
    _, new_blocks = split_blocks(stdin_text)

    if cmd == "override":
        problems = validate_entries(new_blocks, source, reject_override_key=True)
        if problems:
            for p in problems:
                print(f"error: {p}", file=sys.stderr)
            print("log_tool: nothing written", file=sys.stderr)
            return 2
        marked, already_marked, appended = apply_override(log_path, source, new_blocks)
        preserved = marked + already_marked
        print(f"log_tool: overrode {marked} entr{'y' if marked == 1 else 'ies'} "
              f"({preserved} preserved as overridden) → appended {appended} "
              f"for source '{source}' in {log_path}")
        return 0

    # cmd == "append"
    problems = validate_entries(new_blocks, source)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        print("log_tool: nothing written", file=sys.stderr)
        return 2
    removed, appended = rewrite(log_path, source, new_blocks)
    print(f"log_tool: replaced {removed} → appended {appended} "
          f"for source '{source}' in {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
