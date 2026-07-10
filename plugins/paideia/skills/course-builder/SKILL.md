---
name: course-builder
description: Use whenever the user wants to ingest a new course's materials (lecture notes, textbook chapters, HW problems, HW solutions) and build the course-specific knowledge base — patterns.md (recurring solution techniques), coverage.md (HW-to-section map with 🔥 exam tiers + ⚠weak flags), and summary.md (topic tree). Invoked by `/ingest` and `/analyze` slash commands. Designed to be domain-general across math and physics courses (calculus, linear algebra, real/complex analysis, classical mechanics, E&M, thermodynamics, quantum, etc.).
---

# Course Builder

## Overview

This skill turns raw course materials into a structured knowledge base that downstream drilling commands (`/twin`, `/blind`, `/chain`, `/pattern`, `/hwmap`) can query. It is **domain-general** — the same pipeline works for a Linear Algebra course as for a Quantum Mechanics course.

Two-phase pipeline:

```
Phase 1: /ingest
  materials/**/*.pdf  →  converted/**/*.md      (via pdf skill)
  materials/**/*.md   →  (copied as-is)

Phase 2: /analyze
  converted/** + materials/*.md  →  course-index/patterns.md
                                     course-index/coverage.md
                                     course-index/summary.md
```

## When to load

- User runs `/ingest` or `/analyze`
- User mentions adding new course materials
- User asks "what does this course cover" or "what are the key techniques"
- Downstream commands (`/twin`, `/blind`, `/pattern`, `/hwmap`) need `course-index/` data that doesn't exist yet

## Phase 1: Ingest

### Discovery
Scan `materials/` recursively. Classify each file by path and extension:
- `materials/lectures/*.pdf|.md` — lecture notes
- `materials/textbook/*.pdf|.md` — textbook chapters
- `materials/homework/*.pdf|.md` — HW problem sets (rename for consistency: `hw1.pdf`, `hw2.pdf`, ...)
- `materials/solutions/*.pdf|.md` — HW solutions (`hw1_sol.pdf`, etc.) or worked examples

Ambiguous location (e.g., a PDF in `materials/` root)? Ask user once to categorize, then remember.

### Conversion

**All `.pdf` files in `materials/**` go through the vision pipeline.** `pdfplumber` was tried as a fast path and proved unreliable on course materials — even prose-heavy textbook pages silently word-salad when they mix equations or multi-column figures. Routing everything uniformly through vision is simpler than maintaining per-category heuristics with fallbacks. Full pipeline in `skills/pdf/VISION.md`; the short form:

1. Load `skills/pdf/SKILL.md` and `skills/pdf/VISION.md`.
2. Render each PDF to PNG at `dpi=160` (via `pdf2image`) into `converted/<category>/_pages/<stem>/`.
3. Resize all rendered PNGs to ≤1800 px on the long edge **before** any agent starts reading — this is the hard 2000 px many-image limit; violating it wastes entire agent runs.
4. Spawn one parallel `general-purpose` agent per PDF. Each agent reads its own pages **sequentially** (not in parallel batches — same dimension limit) and transcribes to clean LaTeX markdown (`$...$` / `$$...$$`). Unreadable symbols get `[?]`.
5. Write `converted/<category>/<stem>.md` with provenance: `<!-- SOURCE: materials/<category>/<stem>.pdf, extracted <YYYY-MM-DD>, method: vision -->`.
6. After all agents finish, delete the `_pages/` scratch dirs.

For each `.md` already in `materials/`: copy to `converted/<category>/<stem>.md` unchanged with a `method: passthrough` provenance comment.

### Idempotence
If `converted/X.md` exists and is newer than source, skip unless user passes `--force`. Log skip count.

### Output
After ingest completes, print a summary table:

| Category | Converted | Skipped (already done) | Failed |
|---|---|---|---|
| lectures | N | M | F |
| textbook | ... | ... | ... |
| homework | ... | ... | ... |
| solutions | ... | ... | ... |

And (in `INTERFACE_LANG` from `.course-meta`, default `en`): "Next: run `/analyze` to generate the patterns / coverage indexes."

## Phase 2: Analyze

This is the core generalization. Given `converted/**/*.md` (or a subset selected via `--files=`, `--since=`, or `--lectures-only`), produce three index files. Fan-out agents run in parallel batches sized to the concurrency ceiling (~10 slots); a single sequential pass is forbidden. When a subset is active, the index reflects a partial re-run — existing entries outside the subset are preserved (merged, not overwritten). The Reduce phase is entered as soon as any batch completes: after **each** batch, the accumulated index is written atomically to disk (`.partial` then rename for all three files) before the next batch spawns, so an interrupt always preserves the last committed batch on disk.

### `course-index/summary.md`

Topic tree of the course. Structure:
```markdown
# Course Summary

## Scope
Inferred from lecture notes: <one paragraph>.

## Topic tree
- §1 <topic>
  - §1.1 <subtopic> — covered in: lectures/ch01.md, textbook/ch01.md
  - §1.2 ...
- §2 <topic>
  ...

## Difficulty ordering (inferred from lecture progression)
Early → foundational definitions. Middle → core theorems. Late → applications/advanced.
```

**How to build.** Parse section headers (`##`, `###`) from lecture notes, in order. Cross-reference with textbook headers. Use section numbers if present; if not, auto-number by order of appearance.

### `course-index/patterns.md`

Recurring solution techniques extracted from HW solutions and worked examples.

**How to extract.** For each solution (`converted/solutions/*.md` and examples in lecture notes):
1. Identify the "key move" — the step where a reusable technique is applied (e.g., "integration by parts", "change of variable", "Cauchy's integral formula", "Lagrange multipliers", "separation of variables", "Green's function", "diagonalization").
2. Check whether the same move appears in 2+ other problems. If yes, it's a pattern.
3. Number patterns P1, P2, ... in order of first appearance.

Format each pattern card:
```markdown
### Pk. <short name>

**Recognition signal.** <1-2 lines: what triggers this pattern>

**Move.** <1-3 lines: the operation>

**Appears in.** <HW problem IDs, textbook example numbers>

**Topic.** <§ numbers from summary.md>
```

Target pattern count: 15–30 (too few misses important ones; too many becomes noise). If you find <10, the course is too small or you missed patterns — re-scan. If you find >40, merge similar patterns.

### `course-index/coverage.md`

Bidirectional map between HW/example problems and course sections.

**Core premise (do not break).** HW coverage is a **signal of exam probability**, not a completeness metric. The professor has already told you, via HW, where the exam will be drawn from: sections with heavy HW emphasis are where the exam points live. Sections with no HW are unlikely to produce problems worth drilling — they become reference-only.

Structure:
```markdown
## Forward map: problem → sections

| Problem | Primary § | Secondary § | Patterns |
|---|---|---|---|
| HW1-P1 | §2.3 | §2.1 | P1, P3 |
| ...

## Reverse map: section → exam-probability (from HW density)

| § | Title | HW coverage | Exam tier |
|---|---|---|---|
| §2 | ... | HW1-P1, HW2-P3, HW3-P1 | 🔥🔥 Exam-primary |
| §1 | ... | HW1-P2, HW2-P1           | 🔥 Exam-likely |
| §4 | ... | HW3-P5                    | 🟡 Exam-possible |
| §5 | ... | —                         | ⚪ Low-risk (reference only) |
```

Exam tiers (based on HW problem count targeting the section):
- 🔥🔥 **Exam-primary** — 3+ HW instances. Highest exam probability. Drill hardest.
- 🔥 **Exam-likely** — 2 HW instances. High exam probability.
- 🟡 **Exam-possible** — 1 HW instance. Moderate probability; warm-pass review.
- ⚪ **Low-risk** — no HW coverage. Treat as reference; do not spend drill time here unless the user explicitly asks.

A section in the user's declared weak zones gets a trailing ` ⚠weak` flag after its tier (e.g. `⚪ Low-risk ⚠weak`). The flag never upgrades the tier — it is a drill-priority tie-breaker only.

**This 🔥/⚪ + ⚠weak vocabulary is the only one.** Earlier drafts used ✅✅/✅/🟡/🔴/🔴🔴 "coverage strength" markers in `coverage.md`; that scheme is retired — `hwmap`, `weakmap`, `chain`, and `alt` regex on the 🔥 tiers and would not see 🔴 rows.

**Do not invert this.** Sections with no HW are NOT "blind spots that the exam will bite" — they are sections the professor chose not to test, by omission. Drilling them steals time from exam-primary sections.

### Summary of analysis output

At end of analyze, print to chat:
- Number of patterns extracted
- Number of sections in summary
- Count of 🔥🔥 / 🔥 / 🟡 / ⚪ sections
- Top 3 **exam-primary** sections and their recommended drills (most HW-dense first)

## Domain-general hints

When analyzing, watch for common **mathematical** patterns (applicable broadly):
- Integration techniques (substitution, parts, partial fractions, contour)
- Linear algebra moves (diagonalization, Gram-Schmidt, rank-nullity)
- Series manipulations (telescoping, generating functions, asymptotics)
- Induction structures (strong, transfinite, well-ordering)
- Function-space methods (orthogonality, completeness, eigenexpansions)

And common **physics** patterns:
- Conservation laws invocation (energy, momentum, charge, angular momentum)
- Symmetry arguments (Noether, parity, gauge)
- Perturbation theory (regular, singular, Rayleigh-Schrödinger)
- Boundary condition matching (continuity of ψ, ψ', field components)
- Change of reference frame (Galilean, Lorentz, rotating)
- Maxwell-style relations (any variable-swap via second mixed derivative)

These are hints — only add a pattern if it actually appears ≥2 times in the user's solutions.

## Files produced (summary)

After a full ingest + analyze run, the `paideia` directory contains:

```
converted/                    ← all PDFs as MD
course-index/
├── summary.md               ← topic tree
├── patterns.md              ← P1..Pk recognition cards
└── coverage.md              ← HW↔§ map, 🔥 exam tiers + ⚠weak flags
```

All downstream commands (`/twin`, `/blind`, `/chain`, `/pattern`, `/hwmap`) read from these three index files, not from the raw materials. This makes re-analysis cheap (edit index manually if needed) and keeps commands domain-agnostic.
