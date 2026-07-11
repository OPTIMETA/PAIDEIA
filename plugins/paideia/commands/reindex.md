---
description: Idempotent reindex of an existing course — rewrite retired coverage.md tier markers to canonical vocabulary and materialize errors/log.md nature/phase into the on-disk schema (header keys == data keys), in place and atomically, WITHOUT running analyze.
argument-hint: "[--fix to write; default is dry-run/report] [--log=errors/log.md]"
---

## Output language

User-facing prose, status messages, and this command's narrative are rendered in `$INTERFACE_LANG` (from `.course-meta`). File paths, slash command names (`/paideia:reindex`), tier markers (🔥🔥/🔥/🟡/⚪), YAML keys, `error_type` values, and tool identifiers stay in English regardless of `$INTERFACE_LANG`.

## What this does

Reindex answers one question: **can this course's index artifacts be brought into conformance with current canonical vocabulary — without re-running `/paideia:analyze`?**

Two jobs run in sequence:

### (A) coverage.md — retired marker (do NOT emit these: ✅✅/✅/🔴/🔴🔴) → canonical rewrite

`course-index/coverage.md` may carry retired markers (✅✅/✅/🔴/🔴🔴) written by an older analyze run. Reindex rewrites them to the canonical vocabulary atomically:

```
retired (do NOT emit): ✅✅ → 🔥🔥   ✅ → 🔥   🔴🔴 → ⚪   🔴 → 🟡
```

This mapping is the same normalization defined in `commands/analyze.md` Step 3 (`analyze.md:301`) and `skills/course-builder/SKILL.md`. Reindex is the analyze-free path to apply it.

**Byte-preserving contract:** substitution is scoped to the **Exam-tier column** and to **non-pipe prose/legend lines** (e.g. `Legend: ✅ = high exam priority`, `Aggregate: 3 sections at ✅`). Every other table cell — `§` numbers, section titles, HW coverage cell contents, `⚠weak` flags — and the table header/separator rows are preserved byte-for-byte, even if a data cell happens to contain a retired glyph (e.g. a section title `Checklist ✅ done`). `⚠weak` is never promoted or demoted. The Exam-tier column is located by the following priority order: (1) canonical `Exam tier` header (case-insensitive) — always wins; (2) non-canonical alias headers (`Strength`, `Emphasis`, `Priority`, `Weight`, `Tier`) — recognized when the canonical header is absent, fixing false-canonical exit-0 on Reverse-map tables that use an alias with a non-rightmost tier column; (3) headless fragment fallback — when no recognised header exists, the rightmost cell that actually carries a tier glyph (retired or canonical) is targeted, so a bare `Notes`/`L2` trailing column with no glyph is never mistakenly rewritten.

**Substitution order (retired markers — do NOT emit out of order):** longest retired key first (`✅✅` before `✅`, `🔴🔴` before `🔴`) to prevent double-substitution artifacts.

### (B) errors/log.md — nature/phase facet materialization

The `errors/log.md` header (the `<!-- … -->` schema block) documents `phase` and `nature` as optional keys inferred from `error_type` when absent. Reindex **materializes** those inferences into the on-disk data blocks so that header-documented keys equal data keys (header-data 1:1 contract).

**Inference maps** (imported from `paideia_lib.DEFAULT_PHASE` / `paideia_lib.DEFAULT_NATURE` — same maps `iter_error_entries` uses at read-time):

| `error_type` | default `phase` | default `nature` |
|---|---|---|
| `pattern-missed` | `transformation` | `misconception` |
| `wrong-variable` | `transformation` | `misconception` |
| `wrong-end-form` | `encoding` | `misconception` |
| `algebraic` | `execution` | `slip` |
| `sign` | `execution` | `slip` |
| `definition` | `comprehension` | `gap` |

**Explicit wins:** if a block already carries an explicit `phase:` or `nature:` field, it is never overwritten.

**Byte-preserving contract:** the required-6 keys (`problem_id`, `pattern`, `error_type`, `summary`, `source`, `date`) and the `overridden_by` audit marker are never modified. Only `phase:` and/or `nature:` lines are inserted where absent.

## Procedure

**Step 1 — course mode gate**

Check for `.course-meta` in the current directory. If absent, print (in `$INTERFACE_LANG`):

> reindex: no `.course-meta` found here — this command requires a course folder.
> Run `/paideia:init-course` to create one.

Stop. Do not touch any files.

**Step 2 — run the backend**

```bash
# Dry-run (default): report what would change, exit 0=clean exit 1=changes-needed
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/reindex.py"

# Apply in-place (--fix): atomic rewrite, exit 0=already-clean exit 1=rewrote exit 2=disk-failure
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/reindex.py" --fix

# Custom log path:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/reindex.py" --fix --log=errors/log.md
```

Parse the backend's stdout lines to compose the narrative below.

**Step 3 — narrate result (in `$INTERFACE_LANG`)**

Dry-run (no `--fix`):
- If coverage.md has retired marker lines: report the count, explain what would change, suggest `/paideia:reindex --fix`.
- If log has entries needing phase/nature materialization: report the count, suggest `/paideia:reindex --fix`.
- If both are already clean: "Course index is already in canonical form — no reindex needed."

After `--fix`:
- If rewrites were performed: confirm coverage.md marker lines rewritten and/or log entries materialized.
- If already clean: "Course index was already canonical — no changes made."
- On disk failure (exit 2): report the failure and suggest checking disk permissions.

## What this command does NOT do

- **Does not run `/paideia:analyze` or any sub-agent.** No converted files are read. No fan-out occurs. The entire operation reads and rewrites only `course-index/coverage.md` and `errors/log.md`.
- **Does not recalculate HW coverage cells.** Tier tokens are rewritten; the numeric HW density data is byte-preserved. If coverage data itself is stale, run `/paideia:analyze`.
- **Does not invent new tier vocabulary.** Only the four retired-to-canonical mappings above are applied.
- **Does not modify required-6 log values.** `problem_id`, `pattern`, `error_type`, `summary`, `source`, `date` are byte-preserved.
- **Does not preserve retired markers.** After `--fix`, `coverage.md` contains only canonical tier vocabulary (🔥🔥/🔥/🟡/⚪). Retired markers (do NOT emit: ✅✅/✅/🔴/🔴🔴) must not be preserved on write.
- **Does not overwrite explicit phase/nature.** Only entries that lack those fields receive inferred values.

## Idempotence guarantee

Running `/paideia:reindex --fix` twice on an already-reindexed course produces no change and exits 0. The backend exits 0 when both artifacts are already in canonical form. No confirmation prompt is shown for idempotent runs.

## Atomic write safety

Both coverage.md and errors/log.md rewrites use the same atomic pattern as `doctor.py --fix`:
`tempfile.mkstemp` in the same directory → write → `os.replace`. A crash or disk error mid-write leaves the original file intact. The temp file is cleaned up on failure.
