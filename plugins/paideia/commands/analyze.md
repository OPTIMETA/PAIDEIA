---
description: Analyze converted course materials to produce the course knowledge base — patterns.md, coverage.md, summary.md.
argument-hint: "[weak-zone topics, comma-separated] [--files=<glob>] [--since=<YYYY-MM-DD>] [--lectures-only] [--resume] [--force]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and narrative parts of the generated index MDs — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1..Pk), tier markers (🔥🔥/🔥/🟡/⚪) and the `⚠weak` flag, § / Ch section anchors, and table column headers (`Problem`, `Primary §`, `Secondary §`, `Patterns`, `HW coverage`, `Exam tier`, etc.) — `weakmap`, `hwmap`, and `quiz` regex on them.

Load `skills/course-builder/SKILL.md`.

Arguments: $ARGUMENTS

Non-flag tokens (comma-separated, excluding any `--` prefixed tokens) are the user's declared weak zones. Tokens beginning with `--` are control flags parsed in Step 0.5 below — exclude them from the weak-zone list.

Prerequisite check: verify that `converted/` contains files. If empty, tell the user to run `/ingest` first.

Follow the course-builder Phase 2 analyze pipeline:

## Step 0 — Discovery & fan-out plan

List all files matching `converted/lectures/*.md`, `converted/textbook/*.md`, `converted/homework/*.md`, and `converted/solutions/*.md`. Count the total as N.

Output in $INTERFACE_LANG (keep the token identifier verbatim):

```
Analyzing N files (0/N)...
```

**Fan-out (mandatory — single-pass over the full converted directory is forbidden):**

Spawn one `general-purpose` Task sub-agent **per file**, in parallel, up to the workflow concurrency ceiling (currently ~10 parallel agent slots) at once; batches sized to that ceiling. If N exceeds the ceiling, process in sequential batches, waiting for each batch to complete before launching the next — maximize parallelism within each batch. Each agent reads only its own single file and returns a **partial index** (structured summary) — it must not re-read or transcribe the full original text back to the parent.

**First-batch cap (mandatory — batch-1 must provably commit inside the standard window):** The first batch is intentionally smaller than the full ceiling. Set batch-1 size = min(FIRST_BATCH_CAP, N), where FIRST_BATCH_CAP is 3–4 files. This ensures that fan-out + Reduce + all three `.partial` writes + all three renames provably complete and commit a valid course-index inside the standard window — batch-1 must provably commit a valid course-index inside the standard window; subsequent batches widen to the ceiling (~10). Choosing a ceiling-sized first batch risks a SIGTERM (exit 143) with zero committed files if the Reduce + write phase is reached near the window boundary (as observed in FND-002: "assembling section headers" → SIGTERM, 0 files committed). The small first batch eliminates this risk while the subsequent batches widen to recover throughput.

**Batch-1 emit-time self-check (mandatory):** Before streaming the batch-1 header, compute `b = min(4, N)` (FIRST_BATCH_CAP upper bound is 4). Verify that the actual file count you are about to spawn is ≤ b. If the computed file list length exceeds b, truncate it to the first b files (applying selection priority below) and carry the remainder into batch-2. Emitting a batch-1 header with a file range `1..b` where b > min(4, N) is a **contract violation** — it indicates the self-check was bypassed.

- **en:** Batch-1 must contain ≤ min(4, N) files. Streaming a batch-1 header with more than 4 files (when N ≥ 4) is a contract violation.
- **ko:** 배치-1은 반드시 min(4, N)개 이하 파일이어야 합니다. N ≥ 4일 때 4개 초과 배치-1 헤더 방출은 계약 위반입니다.

**Standard vs golden window note:** The standard deployment window (approximately 290 s) is narrower than the e2e-golden window (approximately 560–600 s). Keeping batch-1 small (≤ 4 files) ensures at least one committed course-index survives in the narrower window. Full-course completion (all N files, `partial=false`) requires either `--resume` repetition or the wider golden window; this is a measurement-condition constraint, not a code defect.

**First-batch file selection priority (recommended — rich first-batch patterns):** When selecting the min(FIRST_BATCH_CAP, N) files for batch-1, prefer `converted/solutions/*.md` and `converted/homework/*.md` files over `converted/lectures/*.md` files. Solutions and homework files contain problem IDs and recurring technique instances; including at least one solutions/homework file in batch-1 increases the probability that `patterns.md` accumulates ≥1 recurring pattern card (≥2 distinct `problem_id` occurrences) after batch-1's Reduce. A batch-1 consisting entirely of lecture-only files risks producing a `patterns.md` with 0 pattern cards (lecture notes rarely contain ≥2 problem IDs), making the committed course-index not rich. This is a **recommended ordering**, not a hard constraint — if the course contains only lectures (e.g. `--lectures-only` flag), proceed with lecture files in document order.

Before spawning the first batch, output a batch-progress header:

```
Batch 1/K (files 1..b)
```

where b = min(4, N) (verified by the emit-time self-check above) and K = ceil((N − b) / ceiling) + 1. At the start of each subsequent batch M output:

```
Batch M/K (files a..b)
```

Stream this header immediately before spawning each batch's agents.

**Batch-commit (mandatory — run after every batch completes, before spawning the next):**

After all agents in batch M return (succeeded or marked FAILED), and before spawning batch M+1, execute the Reduce phase (Steps 1–3) on the **cumulative** partial indexes from batches 1..M and write the three output files atomically:

1. **Pre-write orphan cleanup.** Before writing any scratch file, delete any orphan `.partial` scratch files (`summary.md.partial`, `patterns.md.partial`, `coverage.md.partial`) left next to the final paths by a prior interrupted run. Orphan scratchfiles are created when a prior invocation wrote the `.partial` but was interrupted before rename; deleting them before writing new scratchfiles prevents stale data confusion and eliminates GUI file-tree clutter (FND-002/010).
2. **Write the three `.partial` scratch files.** Write `course-index/summary.md.partial`, `course-index/patterns.md.partial`, `course-index/coverage.md.partial` — fully formed files conforming to all anchor contracts.
3. **Rename in deterministic order.** Rename each `.partial` to its final path — all three `.partial` writes MUST complete, then all three renames MUST complete, **before** streaming the batch-commit progress line or spawning the next batch. Rename in deterministic order: `summary.md.partial` → `summary.md`, then `patterns.md.partial` → `patterns.md`, then `coverage.md.partial` → `coverage.md`. Never write the final path directly — a reader must never observe a torn or empty file. Never leave a `.partial` orphan on the final path side: a batch-commit that has written a `.partial` but not renamed is **incomplete** — on the next invocation it is treated as not-yet-committed (see Resume, Step 0.6).
4. **Post-rename orphan confirmation.** After all three renames complete, confirm that no orphan `.partial` scratch files remain in `course-index/`. If any remain (e.g. from a partial-failure or duplicate write), delete them before streaming the batch-commit progress line. Rename consumes the scratch source, but defensive cleanup handles edge cases (partial failure, duplicate writes).
5. In `coverage.md` (the `.partial` before rename), prepend the metadata comment immediately before `## Reverse map …`:

   ```
   <!-- COVERAGE: files=<A>/<N>, partial=<true|false>, since=<date|->, subset=<glob|-> -->
   ```

   where A = count of files successfully processed so far across batches 1..M (the same "already-processed count" slot referred to as A in Step 0.6 Resume and Step 0.75). If A < N set `partial=true`; on the last batch when A = N set `partial=false`.

6. After completing all three renames, stream one progress line to chat (in `$INTERFACE_LANG`, keeping token identifiers verbatim):

   - **en:** `Batch M/K committed (A files/N on disk)`
   - **ko:** `배치 M/K 커밋 완료 (A/N 파일 디스크 저장됨)`

The batch-commit Reduce is **cumulative**: each re-run merges all partial indexes from batches 1..M using the same merge rules as Step 0.5 (preserve entries outside the current set). Do NOT re-read any converted source file during batch-commit Reduce — use only the partial-index JSON/MD returned by the sub-agents collected so far. This is the same constraint as Steps 2 and 3 below; it prevents context explosion regardless of how many batches have run.

This per-batch commit means an interrupt after batch M always leaves a valid, parseable partial index on disk for batches 1..M. The full-run Steps 1–3 at the end of the document are the **final** execution of this same Reduce, producing `partial=false`.

**Partial-index return schema** (each sub-agent returns JSON or fixed-header MD conforming to this shape):

```json
{
  "file": "<relative path>",
  "sections": [
    { "anchor": "§1.1", "title": "Example title" }
  ],
  "key_moves": [
    { "name": "short move name", "problem_id": "hw2-p1", "section": "§1.1" }
  ],
  "problems": [
    { "id": "hw2-p1", "primary_§": "§1.1", "secondary_§": ["§2.3"], "patterns": ["P6"] }
  ]
}
```

**Sub-agent prompt template** (fill in bracketed values):

```
You are a course-index extraction agent for a <domain> course.

Your task: read the single file at <abs_path> and return a partial index.
Do NOT read any other file. Do NOT re-emit the original text or prose summaries.

Read only its own file: use the Read tool exactly once on <abs_path>.

Return ONLY a JSON object (no prose, no markdown outside the JSON fence) conforming
to this schema:

{
  "file": "<rel_path>",
  "sections": [ { "anchor": "§X.Y or ChN", "title": "section title" } ],
  "key_moves": [ { "name": "move name", "problem_id": "hwN-pM", "section": "§X.Y" } ],
  "problems": [ { "id": "hwN-pM", "primary_§": "§X.Y", "secondary_§": ["§A.B"], "patterns": ["Pk"] } ]
}

Rules:
- sections: every numbered section or slide heading found, in document order.
- key_moves: recurring solution techniques you observe (name + example problem_id + section).
- problems: every distinct problem ID found, with its primary and secondary section tags.
- patterns: pattern IDs if labelled (e.g. "P6"), otherwise omit the field.
- If the file contains no problems (e.g. a lecture note), return empty arrays for key_moves and problems.
- Do not invent content not present in the file.
- Do not refuse or stop partway — always return what you found, even if partial.
- **Return the JSON only. Do NOT restate section bodies, equations, or prose. `title` ≤ ~8 words. Cap `sections`/`key_moves`/`problems` at what is materially distinct; omit empty optional fields entirely (do not emit `null`/`[]` for absent `patterns`).**
```

`<domain>` should be whatever the course is about (quantum mechanics, linear algebra, discrete math, real analysis, E&M, etc.) — infer from the materials or ask the user once if unclear.

**Alternative (chunk-incremental aggregation):** If the fan-out count would exceed available agent slots, process files in chunks sized to the concurrency ceiling (currently ~8–10), accumulating a running merged partial index after each chunk completes. Either parallel fan-out or chunk-incremental aggregation is required; a single sequential pass over the full `converted/` directory is not permitted.

As each sub-agent or chunk completes, stream a progress line to chat (in $INTERFACE_LANG, keeping the token identifier verbatim):

```
(k/N) <filename> done
```

The batch-progress header `Batch M/K (files a..b)` (streamed at each batch start, as described above) and the per-file `(k/N)` lines together give the user clear visibility into both batch-level and file-level progress.

If a sub-agent stops or returns malformed output, mark that file FAILED, continue with the remaining files, and note the failure in the Step 4 summary.

## Step 0.5 — Subset & incremental selection

**Applied after discovery (Step 0 scan) and before fan-out.** Control flags from `$ARGUMENTS` (the `--`-prefixed tokens) filter the discovered file list. Four flags are supported (`--resume` is a mode switch, not a subset filter — see Step 0.6):

- **`--files=<glob>`**: intersect the `converted/**` scan result with the provided glob. Files outside the glob are excluded from this run; count them as "outside subset" (see Summary footnote below). The glob is matched against relative paths from the course root (e.g. `--files=lectures/L2{2,3,4}.md`). Neither idempotence nor forced-reconvert logic is altered for matched files.

- **`--since=<YYYY-MM-DD>`**: include only `converted/` files whose modification time (`mtime`) is on or after that date (incremental re-analysis). If the date string cannot be parsed as a valid `YYYY-MM-DD`, ignore it and proceed with the full file list, printing one notice in both languages:
  - **en:** "Could not parse `--since` value; ignoring and analyzing all files."
  - **ko:** "`--since` 값을 파싱할 수 없습니다. 무시하고 전체 파일을 분석합니다."

- **`--lectures-only`**: restrict selection to `converted/lectures/*.md` only (exclude homework, solutions, textbook files). If `--files=` is also present, apply both as an AND intersection.

When none of these three flags are present, proceed with the full discovered file list (original behavior).

**Partial-index integrity warning (subset/incremental runs):** When a subset or incremental selection is active, the three output files (`summary.md`, `patterns.md`, `coverage.md`) represent **a partial index over the selected file range only**. If existing `course-index/*.md` files are present, **do not overwrite them with a narrowed result** — instead, **merge**: preserve existing section anchors and pattern cards that fall outside the selected file range, and update only the entries covered by files in this run. Append a footnote to the Summary chat output (not as a table column; the golden table headers are unchanged):

  - **en:** "M files outside the selected subset were not re-analyzed; the index reflects a partial re-run."
  - **ko:** "M개 파일이 선택 범위 밖이라 재분석되지 않았습니다. 인덱스는 부분 재실행 결과입니다."

(where M = total discovered files − files selected for this run; omit the footnote when M = 0).

## Step 0.6 — Resume (idempotent continue)

### Trigger

`--resume` is present in `$ARGUMENTS`, **or** (automatic) `course-index/coverage.md` exists and its `<!-- COVERAGE: files=A/N, partial=true … -->` comment carries `partial=true`.

`--force` and `--resume` are mutually exclusive: `--force` discards all prior state and regenerates from scratch; `--resume` reads existing state and continues from where it left off. If both flags are provided, `--resume` takes precedence and `--force` is ignored. Output a one-line notice (both languages):

- **en:** "Both `--force` and `--resume` specified; `--resume` takes precedence — continuing from partial index."
- **ko:** "`--force`와 `--resume`이 함께 지정되었습니다. `--resume`이 우선 적용됩니다 — 부분 인덱스에서 재개합니다."

### Already-complete guard (idempotent)

If `course-index/coverage.md` exists and its COVERAGE comment shows `partial=false, files=N/N`, output a one-line message and exit without spawning any agents:

- **en:** "course-index/ is already complete (`files=N/N, partial=false`). Nothing to do."
- **ko:** "course-index/가 이미 완료 상태입니다 (`files=N/N, partial=false`). 재분석할 파일이 없습니다."

### Reconstruct the processed set (no re-read of converted sources)

Read the existing `course-index/summary.md`, `course-index/patterns.md`, and `course-index/coverage.md` to reconstruct the *processed set*:

- From `coverage.md`: parse the `<!-- COVERAGE: files=A/N, … -->` comment to learn A (already processed) and N (total).
- From `coverage.md` Forward map: collect every file path or problem ID that identifies a processed source file.
- From `patterns.md`: collect existing `### Pk.` pattern card IDs (P1..Pk) and their `**Appears in.**` problem IDs to identify covered files.
- From `summary.md`: collect existing `§` anchors to identify covered lecture files.

Do NOT re-read any converted source file (`converted/**/*.md`) during this reconstruction — use only the existing `course-index/` index files. This is the same constraint as Steps 2 and 3 (prevents context explosion).

### Fan-out only not-yet-processed files

From the Step 0 discovery list (full `converted/` scan), subtract the processed set to produce the **not-yet-processed** file list. Apply the same batch rules as Step 0 (first-batch cap of 3–4 files for batch-1, then ceiling ~10 for subsequent batches).

### Merge — do NOT overwrite

After each batch of not-yet-processed files completes its Reduce, **merge** the new partial index into the existing `course-index/` files using the Step 0.5 merge rules (preserve entries outside the current set):

- Existing `§` anchors, topic-tree entries, and scope paragraph in `summary.md` are preserved; new sections are appended.
- Existing `### Pk.` pattern cards keep their current IDs (P1..Pk). New patterns are assigned the next available sequential IDs continuing from the highest existing Pk — do NOT renumber existing cards (downstream `hwmap`, `weakmap`, `quiz` regex anchor on the existing Pk numbers).
- Existing coverage rows in `coverage.md` are preserved; new rows are added.
- Use the same `.partial` → rename atomic write sequence as Step 0 batch-commit (all three files, deterministic rename order).

### COVERAGE comment update

On each batch-commit during resume, recalculate `files=A/N` (A = cumulative processed count across all prior runs + current resume batches). Set `partial=true` while A < N. On the final batch when A = N, set `partial=false`. The COVERAGE comment must be updated on every batch-commit so an interrupt during resume still leaves a valid, parseable partial state.

### Orphan cleanup on resume entry

On resume entry (before spawning any not-yet-processed fan-out agents), scan `course-index/` for orphan `.partial` scratch files (`summary.md.partial`, `patterns.md.partial`, `coverage.md.partial`). These indicate a prior invocation wrote a scratch but was interrupted before the rename. Delete any found orphans before proceeding with the resume fan-out. Output one progress line (in `$INTERFACE_LANG`):

- **en:** `Cleaned N orphan .partial scratch file(s) from a prior interrupted run; resuming.`
- **ko:** `직전 중단 실행의 orphan .partial 스크래치 N개를 정리하고 재개합니다.`

(where N = count of deleted orphans; omit this line entirely if N = 0.)

Orphan scratchfiles are **not reused** — they may represent incomplete or torn partial indexes. Deleting them is always safe because the final path state (or absence thereof) is the sole source of truth for resume progress.

### i18n

All chat output in this step is gated on `$INTERFACE_LANG` (en · ko). Token identifiers (`course-index/`, `summary.md`, `patterns.md`, `coverage.md`, `--resume`, `--force`, `files=A/N`, `partial`, `P1..Pk`) stay verbatim in both languages.

## Step 0.85 — Orphan scratch cleanup on interrupt/resume

This step documents the **active cleanup** obligation that prevents orphan `.partial` scratch files from accumulating across interrupted runs.

**On every batch-commit (mandatory):**
1. Before writing new `.partial` scratch files for the current batch, delete any pre-existing orphan `.partial` files in `course-index/` (from prior interrupted runs or duplicate writes).
2. After all three renames complete for the current batch, confirm no `.partial` files remain in `course-index/`. If any are found, delete them.

**On resume entry (before first batch fan-out):**
- Scan `course-index/` for orphan `.partial` scratch files. Delete any found and emit the i18n progress line (see Step 0.6 Orphan cleanup on resume entry above).

**Committed state invariant:** After any batch-commit completes, `course-index/` MUST contain:
- The three final files (`summary.md`, `patterns.md`, `coverage.md`) — all renamed from their `.partial` scratch, fully parseable.
- Zero `.partial` files — all scratch files deleted or renamed.

A batch-commit that leaves **only** `.partial` files (with no final counterparts) is an **incomplete** batch-commit. A batch-commit that leaves `.partial` files alongside final files is an **incomplete cleanup** — the `.partial` files must be removed.

This invariant is the acceptance gate that `run-loop3-analyze.mjs` checks post-commit: `ls course-index/*.partial` must return empty. It is also the invariant that eliminates GUI file-tree clutter (FND-002/010 related: `.partial` files were visible as inert grey items in the shell file tree because the view filter did not exclude them by extension).

## Step 0.75 — Partial-commit guarantee (loop contract anchor)

The Reduce phase (Steps 1–3) must be entered even if not all fan-out agents have completed. The batch-commit mechanism defined in **Step 0** above is the enforcement point of this guarantee. As soon as each batch completes, the Reduce phase writes the accumulated index to disk (`.partial`→rename) **before** the next batch is spawned; the last committed batch therefore always survives an interrupt. Do not wait indefinitely for lagging agents — if a sub-agent does not return by the time its batch window closes, mark it FAILED and proceed to the batch-commit with whatever partial indexes were collected.

The three output files must be in a parseable state conforming to their anchor contracts (§ headers, table headers, `### Pk.` pattern card format) whenever they exist on disk — a reader must never observe a torn or empty file. This holds for **every batch-commit**, not only the final one.

**Atomic writes:** Write each of the three output files to a `.partial` scratch path first (`summary.md.partial`, `patterns.md.partial`, `coverage.md.partial`), then rename to the final path (Step 0 batch-commit, step 2). Never write the final path directly — applies to every batch-commit, not only the final write. The convention is `.partial`→rename on all three files in each batch-commit cycle, exactly as specified in Step 0. All three `.partial` writes MUST complete, then all three renames MUST complete (in deterministic order: summary → patterns → coverage), **before** streaming the batch-commit progress line or spawning the next batch. A `.partial` that is written but not renamed is an **incomplete** batch-commit — on the next invocation (including `--resume`) it is treated as not-yet-committed. Never leave a `.partial` orphan on the final path side.

**Committed-state gate (after every batch-commit, mandatory):** After completing all three renames, verify that:
1. The three final paths (`summary.md`, `patterns.md`, `coverage.md`) **all exist** in `course-index/`.
2. Zero `.partial` files remain in `course-index/` — delete any remaining orphan scratch files.

If final files exist but orphan `.partial` files are also present, delete the `.partial` files and proceed. A batch-commit where `.partial` files exist alongside final files is a partial-failure cleanup state; removing the `.partial` files restores the committed invariant. Emit an orphan-cleanup line (in `$INTERFACE_LANG`):

- **en:** `Cleaned N orphan .partial scratch file(s) from a prior interrupted run; resuming.`
- **ko:** `직전 중단 실행의 orphan .partial 스크래치 N개를 정리하고 재개합니다.`

(where N = count of deleted orphans; omit this line when N = 0).

**Partial-run metadata comment (mandatory on every batch-commit):** This is the same comment written by **Step 0** batch-commit, step 3 — it is written on **every** batch-commit (partial and final), not only on subset runs. Prepend the following HTML comment to `coverage.md` immediately before the `## Reverse map …` header:

```
<!-- COVERAGE: files=<A>/<N>, partial=<true|false>, since=<date|->, subset=<glob|-> -->
```

where A = files successfully processed so far, N = total discovered. Written on **every batch-commit** and always present when `coverage.md` exists: `partial=true` while A < N, `partial=false` on the final batch when A = N. The acceptance gate reads this line to confirm `files=A/N` and the `partial` flag, so it must never be omitted. It is nonetheless parser-safe — `parseCoverage` skips non-`|`-prefixed lines, so this comment is **never** treated as a tier row.

## Step 1 (Reduce) — Generate `course-index/summary.md`

**This Reduce is re-run after every batch (Step 0 batch-commit); on the final batch it produces the complete index with `partial=false`.** Each re-run operates only on the cumulative partial indexes from batches 1..M collected so far — do NOT re-read any converted source file.

Merge the `sections` arrays from all partial indexes. De-duplicate entries with the same anchor (file-order wins). Sort by document order (file order, then section order within file). Cross-reference lecture and textbook section numbering if both are present.

Build `summary.md` from the merged section list:

- One-paragraph scope statement (inferred from the merged section titles — do NOT re-read any converted file).
- Topic tree with `§` anchors cross-referencing source files.
- Difficulty ordering based on section progression.

**Language:** Write the scope paragraph and any narrative topic-tree titles in `$INTERFACE_LANG`; keep `§`/`Ch` anchors, table headers, `Pk`/tier markers, and file paths verbatim (per Output language above).

Required structure (anchors must be verbatim for downstream tools):

```markdown
## Scope
<scope paragraph>

## Topic tree
- §X …
  - §X.Y …
```

## Step 2 (Reduce) — Generate `course-index/patterns.md`

Aggregate `key_moves` from all partial indexes. Group by move name. A pattern qualifies if it appears in ≥2 distinct `problem_id` values across all files. Assign sequential IDs P1, P2, … (sorted by frequency descending, then alphabetically by name).

Target 15–30 patterns. Each pattern card must use this exact format (anchors are verbatim — `hwmap`, `weakmap`, and `quiz` regex on them):

```markdown
### Pk. <short name>
**Recognition.** <signal>
**Move.** <operation>
**Appears in.** <problem IDs>
**Topic.** <§ numbers>
```

**Language:** `Recognition`/`Move`/`Topic` prose in `$INTERFACE_LANG`; the anchors `### Pk.`/`**Recognition.**`/`**Move.**`/`**Appears in.**`/`**Topic.**` and all IDs stay verbatim.

Moves that appear in only 1 problem are "one-off techniques" — list them in a final section of `patterns.md` after all numbered patterns.

Do NOT re-read any converted file during this step. Use only the aggregated partial indexes from Step 0.

## Step 3 (Reduce) — Generate `course-index/coverage.md`

Aggregate `problems` from all partial indexes. Build:

- **Forward map** (problem → §): from `primary_§` and `secondary_§` fields.
- **Reverse map** (§ → problems): group `problems` by `primary_§`, count distinct `problem_id` values as HW density.

For the reverse map, assign the **exam tier from HW density** — the single canonical vocabulary from `skills/course-builder/SKILL.md`, which `hwmap`, `weakmap`, and `alt` regex on (do NOT emit ✅/🔴 "coverage strength" markers; that vocabulary is retired):

- 🔥🔥 Exam-primary (3+ HW instances)
- 🔥 Exam-likely (2 instances)
- 🟡 Exam-possible (1 instance)
- ⚪ Low-risk (0 instances — reference only)

Flag any section that falls in the user's declared weak zones (from `$ARGUMENTS`) with a trailing ` ⚠weak` after its tier (e.g. `⚪ Low-risk ⚠weak`). The flag never upgrades the tier — it only feeds drill-priority ranking.

Required file structure (headers and table headers are verbatim — parsers anchor on them):

```markdown
## Reverse map: section → exam-probability (from HW density)

| § | Title | HW coverage | Exam tier |
|---|---|---|---|
| §X.Y | … | hwN-pM, … | 🔥🔥 Exam-primary |
…

## Forward map: problem → sections
…
```

End the file with a "Recommended drill priority" section ranking the top 6 items by HW density first, `⚠weak` as the tie-breaker within a tier.

**Language:** Section titles and the `Recommended drill priority` prose in `$INTERFACE_LANG`; tier vocabulary (🔥🔥/🔥/🟡/⚪), `⚠weak`, table headers (`§`, `Title`, `HW coverage`, `Exam tier`), and `§`/hw-id stay verbatim.

**Marker normalization:** If a pre-existing `coverage.md` (or partial-merge input) carries retired markers (✅/✅✅/🔴/🔴🔴), emit the row with the canonical tier (✅✅→🔥🔥, ✅→🔥, 🔴→🟡, 🔴🔴→⚪) so the written file contains **only** canonical vocabulary — do NOT preserve retired markers on write.

Do NOT re-read any converted file during this step. Use only the aggregated partial indexes from Step 0.

## Step 4: Print summary

After writing all three files, print to chat:

Print the block below, with prose written in $INTERFACE_LANG. Token-level identifiers (`course-index/`, `summary.md`, `patterns.md`, `coverage.md`, `P1..P<N>`, `/hwmap`, `/pattern`, `/blind`, `§<weak-§>`, `<hw-id>`) stay verbatim either way. Include a FAILED line for any files that could not be processed:

```
course-index/ generated.

- summary.md:  <X> sections, <Y> subsections
- patterns.md: <N> recurring patterns (P1..P<N>), <M> one-off techniques
- coverage.md: <A> 🔥🔥 exam-primary, <B> 🔥 exam-likely, <C> 🟡, <D> ⚪ (+<W> ⚠weak flags)
- sub-agents:  <N> files processed, <F> FAILED

Top 3 drill targets (HW-dense first, ⚠weak breaks ties):
  1. <§X> — <title>  [recommend: /blind <hw-id>]
  2. <§Y> — <title>  [recommend: /quiz <§Y> 3]
  3. <§Z> — <title>  [recommend: /twin <hw-id>]

Next steps:
  /hwmap hot          — full exam-tier map with drill anchors per §
  /pattern §<weak-§>  — pattern cards for the weak section
  /blind <hw-id>      — drill the HW closest to the weakness
```

## Idempotence

If `course-index/*.md` already exists and `--resume` is active (or `partial=true` is detected), the resume path (Step 0.6) applies — the existing index is **merged/continued**, not overwritten. No confirmation prompt is shown in this path.

If `course-index/*.md` already exists and neither `--resume` nor `partial=true` applies, warn (in $INTERFACE_LANG): "I'll overwrite the existing index. Back up any hand-edited content first." Wait for confirmation unless `--force` in arguments.
