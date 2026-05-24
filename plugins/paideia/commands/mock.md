---
description: Generate a mock exam matched to the course's structure (inferred from course-index). Saves problem MD + hidden solution MD. User solves on paper, uploads PDF, runs /grade.
argument-hint: "<total minutes, default 90> [optional emphasize=§X,§Y]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs, LaTeX, tier markers, and the mock exam's structural labels (`# Mock Exam — <date>`, `**Duration**`, `**Total**`, `## P<n>`).

Load `skills/exam-drill/SKILL.md`. Read `course-index/summary.md`, `course-index/patterns.md`, `course-index/coverage.md`.

Arguments: $ARGUMENTS
(First token: minutes. Remaining: optional `emphasize=...` list.)

Procedure:

1. **Infer exam structure** from `coverage.md` and past HW:
   - Typical mid/final: 4–6 problems, 2 hours
   - **HW-weighted mix.** Problems are drawn in proportion to HW density of each section. Rough target:
     - ≥70% of points from 🔥🔥 Exam-primary sections (3+ HW)
     - ~25% from 🔥 Exam-likely (2 HW)
     - ≤5% from 🟡 Exam-possible (1 HW)
     - 0% from ⚪ Low-risk (no HW) — do not invent problems in sections the professor never tested.
   - If user passed `emphasize=§X,§Y`, bias toward those (override the HW weighting if they override explicitly).
   - Difficulty distribution: 1 warmup / N-2 standard / 1 hard (multi-pattern)

2. **Design the exam:**
   - For each problem, pick: target §, target pattern(s), point value, estimated time
   - Ensure patterns from ≥3 different parts of the course appear (tests integration)
   - Last problem should require chaining ≥2 patterns

3. **Save:**
   - Problems → `mock/exam_<ts>.md`
   - Solutions → `mock/exam_<ts>_sol.md` (do not display)

4. **Print to chat:**
   - The full exam (problem statements with point values and time suggestions)
   - Total points summing to 100 (or inferred weighting)
   - Closing line (in $INTERFACE_LANG): "Timer: $ARGUMENTS min. Solve on paper, upload as `answers/mock_<ts>.pdf`, then `/grade`."

5. **Do NOT** reveal which patterns are being tested in the problem statements. The user should identify them during solving.

## Exam format

```markdown
# Mock Exam — <date>

**Duration**: <minutes> min  **Total**: 100 pts

---

## P1 (<pts>, ~<min> min)

<problem>

## P2 (<pts>, ~<min> min)

<problem>

...
```

The `_sol.md` sibling has the full reference solution + pattern labels + typical point distribution. Only opens via `/grade`.
