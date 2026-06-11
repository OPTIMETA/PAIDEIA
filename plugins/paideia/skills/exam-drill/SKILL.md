---
name: exam-drill
description: Use when the user wants exam-focused drilling from the course's analyzed material. Generates twin variants of known problems (`/twin`), runs strategy-level blind drills on known problems (`/blind`), creates integration problems chaining multiple patterns (`/chain`), surfaces pattern cards (`/pattern`), and shows coverage/blind-spot maps (`/hwmap`). Reads from `course-index/patterns.md`, `course-index/coverage.md`, and `converted/solutions/*.md`. Works for any math/physics course that has been ingested and analyzed.
---

# Exam Drill

## Workflow philosophy (critical — do not break)

**The user does not type math into the CLI — it is too slow.** All interactions obey:

1. **Generation side (Claude → file).** Problems, variants, and clean reference derivations are written as markdown files to `quizzes/`, `twins/`, `chain/`, `derivations/`. The user views them; no math dialogue in the terminal.

2. **Answer side (user → PDF).** The user solves on paper, scans as PDF, uploads to `answers/<name>.pdf`. The `answer-processing` skill (auto-loaded by `/grade`) converts the PDF to markdown and grades.

3. **Strategy checks (when user is online)** — when a command asks the user to verify understanding without producing a full written solution, it asks only for the *strategy* in 3–5 lines of prose (written in `INTERFACE_LANG` from `.course-meta`, default `en`): which pattern(s), which variables are fixed/expanded, what form the answer takes. Strategy matching is stronger evidence of mastery than line-by-line algebra.

## Drill targeting philosophy (critical — do not break)

**HW density = exam probability.** The professor has already told you, through HW, where the exam points live. Every drill command **must bias toward HW-emphasized sections** (🔥🔥 Exam-primary > 🔥 Exam-likely > 🟡 Exam-possible). Sections with no HW (⚪ Low-risk) are **not** "blind spots waiting to bite" — they are the professor's signal of what is off the exam. Do not treat low-HW sections as high-risk.

Concretely:
- `/twin`, `/blind` default to the highest-HW-density problems when the user doesn't specify one.
- `/chain` composes patterns drawn from Exam-primary sections; avoid pulling patterns from ⚪ sections unless the user explicitly asks.
- `/mock` problem weighting follows HW density (see `commands/mock.md`).
- `/quiz all` samples ≥70% from 🔥🔥, ~25% from 🔥, ≤5% from 🟡, 0% from ⚪.
- If the user requests a ⚪ section drill, comply once but warn that exam probability is low.

## Prerequisites

This skill assumes `/ingest` and `/analyze` have been run. If `course-index/patterns.md` or `course-index/coverage.md` don't exist, tell the user to run those first.

## Files read

- `course-index/patterns.md` — recognition cards P1, P2, ...
- `course-index/coverage.md` — HW↔§ map, blind spots
- `course-index/summary.md` — topic tree
- `converted/homework/*.md` — original HW problems
- `converted/solutions/*.md` — HW solutions (ground truth for grading)
- `errors/log.md` — user's error history (append-only)

## Files written

- `quizzes/<topic>_<ts>.md` — problem statements (answers in `_answers.md` sibling)
- `twins/<origin>_<ts>.md` — variant problems
- `chain/<ts>.md` — integration problems
- `derivations/<topic>.md` — clean reference derivations (post-success)
- `errors/log.md` — append error entries

## Command patterns

### `/twin <problem-id>`

1. Locate `<problem-id>` in `converted/homework/` and `converted/solutions/`.
2. Identify patterns used via `course-index/patterns.md`.
3. Apply twin-recipe.md rules: hold pattern and topic invariant; vary system, numbers, direction, names.
4. Save problem to `twins/<id>_<ts>.md` and solution to `twins/<id>_<ts>_sol.md`. Do not reveal solution unless user either (a) uploads their answer PDF, or (b) describes a correct strategy.

### `/blind <problem-id>`

1. Present the problem verbatim from `converted/homework/`.
2. Ask for strategy (3–5 lines, in $INTERFACE_LANG):
   - which pattern(s) from `course-index/patterns.md`
   - what variables are fixed vs. varied
   - expected form of the final answer
3. Compare against `converted/solutions/`. Three checks: pattern / variable-choice / end-form.
4. On success, copy the relevant solution section into `derivations/<stem>-<n>.md`. On failure, flag the specific axis and log to `errors/log.md`.

### `/chain <N>`

1. Pick N patterns from different source problems (per `course-index/coverage.md`).
2. Design a problem that requires composing them sequentially in parts (a), (b), (c).
3. Bias toward user's weak zone (see `course-index/coverage.md` Critical column).
4. Save problem and solution; prompt for part-by-part strategy or PDF upload.

### `/pattern [§ or keyword or "all"]`

Read-only. Filter `course-index/patterns.md` by the query and return compact pattern cards.

### `/hwmap [§ or "blind"]`

Read-only. Project `course-index/coverage.md` by the query. `blind` lists all 🔴 and 🔴🔴 entries with drill recommendations.

## Twin recipe (invariance rules)

**Hold invariant:**
- The pattern(s) required — a twin that uses a different method is not a twin, it's a new problem.
- The number of reasoning steps (±1).
- The course topic/section being tested.
- The difficulty tier (recall / calculation / derivation / analysis).

**Vary:**
- Numerical values.
- Variable names.
- System/model specification (if course admits multiple — ideal gas → vdW, ODE → PDE of same order, matrix 3×3 → 4×4).
- Direction of the ask: "show X = Y" ↔ "given X = Y, verify Z" ↔ "compute X".

**Quality check before presenting:**
1. The target pattern is clearly required (not avoidable by a shortcut).
2. The answer differs from the original (if it matches, it's not a twin).
3. No filename or wording directly references the original problem ID.
4. Final answer exists and is not pathological.

## Error logging schema

When any drill reveals an error, append to `errors/log.md`:

```yaml
- problem_id: <HW#-P#, twin-id, or chain-ts>
  pattern: <Pk from patterns.md>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<one-line description>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts>>
  date: <ISO8601>
```

This is the **same canonical schema** as `skills/answer-processing/SKILL.md` Step 6 — keep every key, including `source:` (the statusline's mock-phase detection regexes on it). `/weakmap` (top-level command) consumes this log; this skill just produces entries.

## Cross-skill coordination

- `/grade` → loads `answer-processing` skill (PDF → MD → compare with `converted/solutions/`).
- `/ingest` or `/analyze` → loads `course-builder` skill.
- Any PDF read/write → loads `pdf` skill.
- All drill outputs (twins/, chain/, quizzes/) use plain markdown — no PDF creation inside drill commands. The user uploads answer PDFs; Claude doesn't make PDFs during drilling.

## Prose conventions

- Explanations in `INTERFACE_LANG` (en or ko) from `.course-meta`. Default `en` if the field is absent.
- Math in LaTeX (`$...$` inline, `$$...$$` display).
- Pattern IDs stay Latin (P1, P2, ...) regardless of language.
- Section IDs follow the course's convention from `course-index/summary.md` (§, Ch., Ch 3.1, etc.) regardless of language.
- File paths, slash command names, YAML keys, and section anchors downstream tools regex on (`## One-line verdict`, `## Page N`, `# Vision-OCR transcription`) stay in English regardless of language.
