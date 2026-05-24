---
description: Analyze converted course materials to produce the course knowledge base — patterns.md, coverage.md, summary.md.
argument-hint: "[optional weak-zone topics to emphasize, comma-separated]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and narrative parts of the generated index MDs — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1..Pk), tier markers (🔥🔥/🔥/🟡/⚪, ✅✅/✅/🟡/🔴/🔴🔴), § / Ch section anchors, and table column headers (`Problem`, `Primary §`, `Secondary §`, `Patterns`, `HW coverage`, `Exam tier`, etc.) — `weakmap`, `hwmap`, and `quiz` regex on them.

Load `skills/course-builder/SKILL.md`.

Arguments (user's declared weak zones, comma-separated): $ARGUMENTS

Prerequisite check: verify that `converted/` contains files. If empty, tell the user to run `/ingest` first.

Follow the course-builder Phase 2 analyze pipeline:

## Step 1: Generate `course-index/summary.md`

Parse section headers from `converted/lectures/*.md` in file-order. Build a topic tree. Cross-reference with `converted/textbook/*.md` (if present — textbooks often use different numbering).

If the course uses its own section numbering (§ X.Y, Ch N.M, Chapter X §Y, Lecture N), use it. Otherwise auto-number.

Include in `summary.md`:
- One-paragraph scope statement (inferred from all lecture notes combined)
- Topic tree with cross-references to source files
- Difficulty ordering based on progression

## Step 2: Generate `course-index/patterns.md`

Scan `converted/solutions/*.md` and any example-problems in lecture notes. Identify recurring solution moves.

Target 15–30 patterns. Each pattern card:
```markdown
### Pk. <short name>
**Recognition.** <signal>
**Move.** <operation>
**Appears in.** <problem IDs>
**Topic.** <§ numbers>
```

A pattern must appear in ≥2 distinct problems to qualify. Otherwise note it as a "one-off technique" in a separate final section of `patterns.md` rather than a numbered pattern.

## Step 3: Generate `course-index/coverage.md`

Build forward map (problem → §) and reverse map (§ → problems).

For the reverse map, assign strength:
- ✅✅ Strong (3+ instances)
- ✅ Covered (2 instances)
- 🟡 Thin (1 instance)
- 🔴 Blind (0 instances)
- 🔴🔴 Critical Blind (0 instances AND in user's declared weak zone from `$ARGUMENTS`)

End the file with a "Recommended drill priority" section ranking the top 6 items by `(weakness × exam-probability × no-coverage)` heuristic.

## Step 4: Print summary

After writing all three files, print to chat:

Print the block below, with prose written in $INTERFACE_LANG. Token-level identifiers (`course-index/`, `summary.md`, `patterns.md`, `coverage.md`, `P1..P<N>`, `/hwmap`, `/pattern`, `/blind`, `§<weak-§>`, `<hw-id>`) stay verbatim either way:

```
course-index/ generated.

- summary.md:  <X> sections, <Y> subsections
- patterns.md: <N> recurring patterns (P1..P<N>), <M> one-off techniques
- coverage.md: <A> strongly covered, <B> thin, <C> blind, <D> CRITICAL blind

Top 3 blind spots:
  1. <§X> — <title>  [recommend: /derive <key-concept>]
  2. <§Y> — <title>  [recommend: /quiz <§Y>]
  3. <§Z> — <title>  [recommend: /derive <key-concept>]

Next steps:
  /hwmap blind        — review all blind spots
  /pattern §<weak-§>  — pattern cards for the weak section
  /blind <hw-id>      — drill the HW closest to the weakness
```

## Idempotence

If `course-index/*.md` already exists, warn (in $INTERFACE_LANG): "I'll overwrite the existing index. Back up any hand-edited content first." Wait for confirmation unless `--force` in arguments.
