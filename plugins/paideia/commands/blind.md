---
description: Strategy-level blind drill on a known HW or example problem. User describes approach in prose (no math typing); Claude verifies against solution then saves clean reference to derivations/.
argument-hint: <problem-id, e.g. "hw4-p3" or "example-5.2">
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output, clarification questions, and narrative sections of any MD file you write — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1, P2…), YAML keys (`pattern:`, `error_type:`, `problem_id:`, `source:`, `date:`, `summary:`), LaTeX, code, and the literal section anchors downstream tools regex on (`## One-line verdict`, `## Page N`, `# Vision-OCR transcription`).

Load `skills/exam-drill/SKILL.md`. Read `course-index/patterns.md`.

Target: $ARGUMENTS

Procedure:

1. **Load problem statement ONLY** from `converted/homework/<n>.md` or `converted/textbook/<ch>.md` (for textbook examples). Do NOT open the solution yet.

   **Confirm a reference solution exists first — before spending the user's effort.** A blind drill grades the user's strategy against the known solution, so without one there is nothing to check. Verify (do NOT read its contents yet) that the matching solution is ingested: `converted/solutions/<n>_sol.md` for a homework problem (e.g. `3.3` → `converted/solutions/hw3_sol.md`), or the worked-example section inside `converted/textbook/<ch>.md` for a textbook example. If it is missing, **stop here without requesting a strategy** and tell the user (in $INTERFACE_LANG): no reference solution for this problem is ingested, so a blind strategy-check can't be verified. Offer the concrete next steps — add the solution to `materials/solutions/` and run `/paideia:ingest`, or pick a problem that has a solution (list which `converted/solutions/*_sol.md` exist), or drill it instead with `/paideia:twin <id>` or `/paideia:quiz` (neither needs a pre-existing per-problem solution). Never fabricate a solution to grade against.

2. **Present the problem verbatim** to the user.

3. **Request strategy** (3–5 lines in $INTERFACE_LANG prose, no math typing). The 3 axes to ask about:
   ```
   Strategy only — no equations needed.
   1) Which pattern(s) will you use? (Pk number from course-index/patterns.md)
   2) Which variables held fixed; which expanded?
   3) What form do you expect the final answer to take?
   ```

   Render those three axes in $INTERFACE_LANG.

4. **Wait for response.** Do NOT proceed until the user answers.

5. **Load solution** from `converted/solutions/<n>_sol.md` (or the worked-example section of `converted/textbook/<ch>.md` for an example) — the same file confirmed present in Step 1. Compare 3 axes:

   a. **Pattern identification** — correct Pk(s)?
   b. **Variable choice** — correct hold-fixed set?
   c. **End-form prediction** — matches actual answer structure?

6. **Feedback protocol:**
   - ✅ all three → confirm, then copy the relevant part of the solution into `derivations/blind-<id>.md` for permanent reference
   - ❌ on any axis → point out specifically which axis failed, WITHOUT revealing correct answer. Ask for revision.
   - After 2 failed attempts on same axis → give a one-line hint referencing the relevant pattern name.

7. **Log errors** if user needed revision. Use the **canonical schema from `skills/answer-processing/SKILL.md` Step 6** — same keys `/grade` writes, so statusline and weakmap see `/blind` errors too. Write through the deterministic writer (replaces any prior entries for this drill's source, so re-running `/blind` on the same problem never double-counts):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_tool.py" append --source="blind/<id>" <<'YAML'
   - problem_id: <id>
     pattern: <Pk>
     error_type: pattern-missed | wrong-variable | wrong-end-form
     summary: "<1 line>"
     source: blind/<id>
     date: <ISO>
   YAML
   ```
   Map strategy axis → `error_type`: pattern axis → `pattern-missed`, variable axis → `wrong-variable`, end-form axis → `wrong-end-form`. Never hand-edit `errors/log.md` appends.

8. **Close** (in $INTERFACE_LANG):
   "To check retention on the same type, do one variant via `/twin <id>`."

## Why strategy-based, not full-derivation

Exam pattern recognition is the bottleneck — if the user can articulate the correct strategy in 30 seconds, they'll execute it in 10 minutes on the exam. The strategy check IS the drill. Execution is practiced via paper + `/grade`.
