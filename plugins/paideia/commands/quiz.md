---
description: Generate N practice problems on a topic. Saves problem MD + hidden answer MD. User solves on paper, uploads answer PDF, then runs /grade. First arg `weakmap` → auto-load latest weakmap report and target its top weaknesses.
argument-hint: <topic | § | "weakmap"> [N=5]
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and narrative parts of the generated quiz MD — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1, P2…), LaTeX, tier markers, and the per-problem footer template's keyword shape (a one-line italic citation of `§<section>` and `P<k>`).

Load `skills/exam-drill/SKILL.md`. Also load `course-index/summary.md`, `course-index/patterns.md`, `course-index/coverage.md` if they exist.

Arguments: $ARGUMENTS
(First word: topic, § number, or the literal `weakmap`. Second word if present: number of problems, default 5.)

Prerequisite: if `course-index/` is empty, run `/analyze` first — problems generated without the index will be unfocused.

Procedure:

0. **Weakmap mode.** If the first arg is `weakmap`:
   - Find the latest `weakmap/weakmap_*.md` (by mtime). If missing, tell the user to run `/weakmap` first and abort.
   - Parse its "Top 5 weaknesses" and "User-declared weaknesses" sections to collect a target set of (§, Pk) pairs.
   - Design the N-problem mix so every top weakness is covered at least once; user-declared items take priority. Spread remaining slots over top-ranked error patterns.
   - Filename override: save to `quizzes/weakmap_<ts>.md` (+ `_answers.md`). Cite which weakness entry each problem targets in the footer.
   - Skip step 1 below. Continue from step 2 with this weakness-driven mix.

1. **Resolve topic.** Map the argument to a specific set of sections and patterns via `coverage.md` and `patterns.md`. If ambiguous, ask the user to pick.
   - **Special case `all`.** When the user passes `all` (broad diagnostic), weight section selection by HW density: draw ~70% of problems from 🔥🔥 Exam-primary sections, ~25% from 🔥 Exam-likely, ≤5% from 🟡, 0% from ⚪. Never sample ⚪ low-risk sections unless the user explicitly names them — the professor's HW already signaled what's off the exam.
   - **Specific § or topic.** If the user names a ⚪ low-risk section, comply but warn once (in $INTERFACE_LANG): "No HW touched this §, so exam probability is low. Still want to drill it?"

2. **Design the problem mix** (N problems):
   - 1 warmup (definition recall, fastest pattern application)
   - N-3 standard (single-pattern derivation or computation) — prefer patterns that recur across multiple HW problems in the target sections
   - 1 applied (pattern used in a specific system / numerical case)
   - 1 conceptual trap (tests a common student error — sign, wrong variable held fixed, wrong pattern chosen)

3. **Save.**
   - Problems → `quizzes/<topic>_<ts>.md`
   - Answers → `quizzes/<topic>_<ts>_answers.md` (do not display)
   - Each problem cites the § and pattern being tested (at the end of the problem, not in title — don't spoil).

4. **Print to chat** (in $INTERFACE_LANG):
   - Filename of the quiz (so user knows where it is)
   - All N problem statements, numbered
   - Closing line: "Solve on paper, scan, upload as `answers/<topic>_<ts>.pdf`, then `/grade`."

5. **Do NOT ask the user to type answers in chat.** If they start typing an answer, remind them of the PDF-upload workflow.

## Problem format (each problem in the MD)

```markdown
## P<n>  (<points if applicable>)

<problem statement, including any figures referenced>

<blank line for working>

---
*(setup: §<section>, tests pattern: P<k>)*  ← at very bottom, small
```

If `INTERFACE_LANG=ko`, render the bottom italic footer in Korean (e.g., `*(문제 설정: §<section>, 테스트 패턴: P<k>)*`). The `§<section>` and `P<k>` tokens themselves stay unchanged either way.

The footer citation is for the user to self-reference after — during the test they ignore it.
