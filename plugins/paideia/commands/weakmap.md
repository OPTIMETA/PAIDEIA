---
description: Priority-ranked weakness report. No arg → fresh report from latest errors per pattern. With concept arg → patch latest report by adding the user-declared weakness, save as new timestamped file.
argument-hint: "[concept text (optional)]"
---

Arguments: $ARGUMENTS

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and the narrative portions of the report MD — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1, P2…), YAML keys, tier markers (🔥🔥/🔥/🟡/⚪), the report's literal section anchors (`# Weakmap — <ts>`, `## Error histogram`, `## Top 5 weaknesses`, `## User-declared weaknesses`, `## Exam-hot zones not yet drilled`, `## One-line verdict`) and the table column headers (`Pattern/topic`, `Latest error type`, `Date`, `§`) — downstream tools regex on these.

## Purpose

Use when the user notices "I think I'm weak at this point" while studying — they record it with `/weakmap <concept>` and it accumulates in the report. Called without arguments, it takes a fresh snapshot from the latest error log.

## Storage rules

- Report directory: `weakmap/`
- File name: `weakmap/weakmap_<YYYY-MM-DD_HHmm>.md`
- Top heading: `# Weakmap — <YYYY-MM-DD HH:mm>`
- **Never overwrite.** Always save a new timestamped file (preserve history).
- "Latest report" = the file in `weakmap/` with the most recent mtime.

## Branches

### Case A — no argument (fresh snapshot)

1. Read `errors/log.md`. Group YAML entries by `pattern`.
2. **Within each pattern, keep only the entry with the most recent `date`.** Older errors may have already been corrected, so "current weakness snapshot" = latest only.
3. Cross-reference with `course-index/coverage.md`'s reverse map — the 🔥 exam tiers and any `⚠weak` flags.
4. (If present) the prior weakmap's "User-declared weaknesses" section is **not** re-included. A no-argument call is an error-log-driven re-snapshot, so user-declared stays empty in this mode.
5. Write to `weakmap/weakmap_<ts>.md` in the format below and print a chat summary.

### Case B — with argument (concept patch)

"Read the latest report → append the new concept to user-declared (cumulative: A, B + C) → rewrite the whole report against {A, B, C} → save under a new timestamp."

1. Read the latest weakmap file. If none, treat Case A as having run and start from an empty report.
2. Extract the existing "User-declared weaknesses" list → `[A, B, …]`.
3. Treat the whole `$ARGUMENTS` as a new concept `C`. Dedupe. Final list `[A, B, C]`.
4. Map each concept to `course-index/patterns.md` and `course-index/summary.md` → identify related §, Pk, suggested drills.
5. Also run the Case A steps 1–3 (latest-error snapshot) so the final report reflects **both** error data and user-declared data.
6. Save to `weakmap/weakmap_<ts>.md` under a new timestamp.

## Report format

```markdown
# Weakmap — <YYYY-MM-DD HH:mm>

## Error histogram (latest per pattern)

| Pattern/topic | Latest error type | Date | § |
|---|---|---|---|
...one row per pattern, latest first.

## Top 5 weaknesses (priority ranked)

1. **<pattern or topic>** — <one-line summary>
   → Recommended: `/<command> <target>`

(Recommendation rules by error_type:)
- `pattern-missed` / `wrong-variable` → `/blind <problem>` or `/derive <concept>`
- `algebraic` / `sign` → `/quiz <topic> 3`
- `definition` → 5-min re-read of the relevant § in `converted/lectures/`
- `wrong-end-form` → `/pattern <Pk>` recognition drill

## User-declared weaknesses

(Populated only in Case B. Empty in Case A.)

- **<concept A>** — relevant §<x>, P<k>. Recommended: `/<command>`
- **<concept B>** — …
- **<concept C (newly added)>** — …

## Exam-hot zones not yet drilled

§ marked 🔥🔥 / 🔥 (Exam-primary, Exam-likely) in `coverage.md` but with no entry in `errors/log.md`:
- §X, §Y

→ A high-HW-density section with nothing in the error log means either (a) the user already has it, or (b) they haven't tried. Run `/blind <hw-id>` to find out fast.

(⚪ Low-risk sections are excluded from this section. No HW → low exam probability → not a weakmap priority.)

## One-line verdict

<the single thing to drill first right now>
```

## Chat output

- One line with the file path that was saved.
- Do NOT paste the full report. Output only **Top 5 + one-line verdict** as a summary (≤30 lines).
- Close with (in $INTERFACE_LANG): "Add new weak points with `/weakmap <concept>`; generate problems from this report with `/quiz weakmap`."
