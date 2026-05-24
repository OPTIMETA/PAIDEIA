---
description: Generate a twin variant of a known HW/example problem. Same technique, new surface. User solves on paper, uploads PDF, runs /grade.
argument-hint: <problem-id, e.g. "hw4-p3" or "example-5.2">
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs, LaTeX, and YAML keys.

Load `skills/exam-drill/SKILL.md` and `skills/exam-drill/twin-recipe.md`. Read `course-index/patterns.md`.

Target: $ARGUMENTS

Procedure:

1. **Locate original.** Search `converted/homework/` and `converted/solutions/` for the problem-id. If not found, also check `converted/lectures/*.md` and `converted/textbook/*.md` for worked examples.

2. **Identify pattern(s) used.** Cross-reference with `course-index/patterns.md`.

3. **Apply twin-recipe.md rules.** Hold pattern, topic, step count invariant. Vary system, numbers, names, direction.

4. **Save two files:**
   - Problem → `twins/<id>_<ts>.md`
   - Solution → `twins/<id>_<ts>_sol.md` (hidden)

5. **Print to chat** (in $INTERFACE_LANG):
   - The twin problem statement (do NOT reference the original problem ID in the output)
   - Instruction: "Solve on paper, upload as `answers/twin_<id>_<ts>.pdf`, then `/grade`. Or just describe the strategy in 3–5 lines."

6. **If user responds with strategy text** (not PDF):
   - Match 3 axes: pattern / variable-choice / end-form
   - If all ✅: confirm, optionally copy the sol.md content into `derivations/twin-<id>.md`
   - If any ❌: flag specifically, ask for revision

7. **Quality check** before presenting:
   - ✅ Pattern genuinely required
   - ✅ Answer differs from original
   - ✅ Origin problem ID not leaked
   - ✅ Well-posed
