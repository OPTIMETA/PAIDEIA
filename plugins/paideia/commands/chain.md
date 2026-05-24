---
description: Generate an exam-style integration problem chaining N patterns from different parts of the course. User solves on paper, uploads PDF, runs /grade.
argument-hint: <N patterns to chain, default 2>
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs, LaTeX, and YAML keys (`pattern:`, `error_type:`, `chain_problem`, etc.).

Load `skills/exam-drill/SKILL.md`. Read `course-index/patterns.md`, `course-index/coverage.md`.

N (pattern count): $ARGUMENTS (default 2, max 4)

Procedure:

1. **Select N patterns** with constraints:
   - From ≥ N different source problems (span HW/example origins; don't pick 2 patterns both from HW1)
   - At least one pattern from the user's weak zone (per `coverage.md` Critical column)
   - At least one pattern marked ✅✅ Strong (user has machinery)
   - Patterns must be composable (pattern A's output = pattern B's input)

2. **Design the problem** as a multi-part question:
   - Part (a): establishes context, requires pattern 1
   - Part (b): uses result from (a), requires pattern 2
   - Part (c): ties together, requires pattern 3 (if N=3)
   - Final answer should synthesize

3. **Save:**
   - Problem → `chain/exam_<ts>.md`
   - Solution → `chain/exam_<ts>_sol.md` (hidden)

4. **Print:**
   - Full problem
   - Estimated time (N × 6 min + 5 min setup)
   - Do NOT reveal which patterns are used
   - Closing (in $INTERFACE_LANG): "Solve on paper, upload as `answers/chain_<ts>.pdf`, then `/grade`. At the end of your solution, also write down 'which pattern you used' — that's the core of the recognition drill."

5. **When user submits:**
   - `/grade` converts PDF → MD → checks:
     - Did they identify all N patterns?
     - Did they use them in the correct order?
     - Does the final synthesis match?
   - Log pattern-identification errors to `errors/log.md` with field `chain_problem`.

## Why multi-pattern chaining

Real exam problems rarely test one pattern in isolation. Chaining tests two skills:
1. **Pattern decomposition** — breaking a complex problem into pattern-sized pieces
2. **Pattern sequencing** — recognizing that pattern A's output is pattern B's input

Both are bottlenecks that single-pattern drills (`/quiz`, `/twin`, `/blind`) don't test.
