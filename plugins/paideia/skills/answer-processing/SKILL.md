---
name: answer-processing
description: Use whenever the user uploads a hand-written or scanned answer PDF to be graded against a reference solution. Converts answer PDFs in `answers/*.pdf` to markdown in `answers/converted/*.md` using the pdf skill (OCR as needed), then performs strategy-based grading against `converted/solutions/*.md` or `quizzes/*_answers.md`. Invoked by `/grade`.
---

# Answer Processing

## When to load

- User uploads an answer PDF and asks to grade it
- `/grade` is invoked
- User says "I finished the quiz, here's my work"

## Core pipeline

```
answers/<quiz-name>.pdf      ← user uploads hand-written scan
      ↓ (pdf skill, OCR)
answers/converted/<quiz-name>.md
      ↓ (this skill)
grade report → stdout (compact) + errors/log.md (append)
```

## Step-by-step procedure

### Step 1: Locate the answer file

If `/grade` was called with an argument, use it as a hint. Otherwise find the most recently modified file in `answers/` (not `answers/converted/`).

### Step 2: Convert PDF to MD (if PDF)

**Use the `vision-ocr` skill** — delegates to a local VLM (Qwen3-VL 8B via ollama) for clean prose + LaTeX transcription (the script reads `INTERFACE_LANG` from `.course-meta` so the VLM keeps the handwriting in its original language), with pytesseract as automatic fallback.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py" answers/<name>.pdf answers/converted/<name>.md
```

The script handles model warmup, page-by-page inference, and tier fallback. See `.claude/skills/vision-ocr/SKILL.md`. The output header tells the grader which tier produced the text:

- `<!-- SOURCE: ..., qwen3-vl:8b @ 300dpi, N pages -->` → high-confidence
- `<!-- TIER: tesseract fallback -->` → degraded; treat results conservatively

### Step 3: Graceful handling of OCR noise

Hand-written math OCR will be imperfect. Expect:
- Greek letters misread as Latin ($\alpha \to a$, $\beta \to B$, $\pi \to T$ or $n$)
- Fractions rendered as flattened text ($\tfrac{dU}{dT} \to dUdT$ or similar)
- Subscripts/superscripts lost or inlined

**Do not grade on algebraic correctness of OCR output.** Instead, apply **strategy-based grading**:

### Step 4: Strategy extraction from noisy MD

Read the converted MD file. For each problem, identify:

1. **Which pattern(s) did the user invoke?** Look for:
   - Named theorems / techniques the user wrote out ("Maxwell relation", "Stokes theorem", "by induction")
   - Variables they held fixed (even if notation is mangled)
   - Key intermediate objects (a chosen potential, a change of variable, an ansatz)

2. **Did the reasoning reach the correct end form?** Even if algebra is wrong, the user's final expression structure (Does it have a log? A sqrt? A series? Correct variables?) tells you if the approach worked.

3. **Where did they stop?** Incomplete work is common; note which step is the last recognizable one.

### Step 5: Compare against reference solution

Open the reference (`converted/solutions/<hw>.md` for HW, `quizzes/<name>_answers.md` for quizzes, `twins/<id>_<ts>_sol.md` for twins, `chain/<ts>_sol.md` for chain).

For each problem/part, produce a verdict:

```
## P<n>
- Pattern match: ✅ / ⚠️ / ❌   [user invoked <Pk>, solution uses <Pk>]
- Variable choice: ✅ / ⚠️ / ❌  [user held <x> fixed, should be <y>]
- End form: ✅ / ⚠️ / ❌          [user's final: <form>, expected: <form>]
- Completeness: <last step user reached>
- Overall: <PASS | PARTIAL | FAIL>
- Note: <one line — what to study, which Pk to re-drill>
```

**Do not** report line-by-line algebra mistakes unless they are specifically about sign errors or notation bugs that matter on the exam (e.g., missing $-$ on $\kappa$ definition, conjugate vs. transpose confusion).

### Step 6: Log errors

**Canonical `errors/log.md` schema — single source of truth.** Every command that appends here (`/grade`, `/blind`, future drills) MUST use exactly these keys. Downstream readers (`statusline.py`, `weakmap`, `session_start.py`) pattern-match on `pattern:` and `problem_id:` lines; any drift silently hides entries.

For each non-✅ entry, append to `errors/log.md`:

```yaml
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<1 line>"
  source: answers/converted/<name>.md
  date: <ISO>
```

**Idempotent by `source:` — replace, don't pile up.** Re-grading the same
answer (fix the OCR, re-run `/grade`) or re-running `/blind` on the same
problem must NOT leave two copies of that attempt's errors in the log — the
`weakmap` histogram would then double-count and over-rank those patterns.
Before appending this grading's entries, **delete every existing list item
whose `source:` equals the current source** (the same answer file / `blind/<id>`
/ `chain/<ts>` you're about to write), then append the fresh block. The log
stays a record of the *latest* grading of each source, not a transcript of every
re-grade. (A genuinely new attempt belongs under a new `source:` — a new upload
gets a new filename, so this only collapses true re-grades of the same file.)

### Step 7: Render grade summary (chat output)

Compact table, no verbose explanations:

```
| Problem | Pattern | Vars | End form | Overall |
|---|---|---|---|---|
| P1 | ✅ | ✅ | ⚠️ | PARTIAL |
| P2 | ❌ | — | — | FAIL |
| P3 | ✅ | ✅ | ✅ | PASS |

Dominant issue: pattern-missed on P2 (used brute-force integration; should use residue theorem, P7).
Drill next: /blind <problem testing P7>, or /pattern P7 for quick review.
```

Keep this under 15 lines of output.

## Handling edge cases

### Empty or unreadable PDF
If OCR yields <100 chars total, ask the user (in `INTERFACE_LANG` from `.course-meta`, default `en`):
"OCR returned too little. PDF quality may be low or the handwriting too small. Options:
(a) re-scan brighter/larger and re-upload
(b) type the answer into `.md` and save it to `answers/converted/<name>.md`, then `/grade` again"

### User uploads .md directly
Skip PDF conversion. Read `answers/<name>.md` directly. Everything else is the same.

### Multi-page with disordered content
Hand-written work often has margin notes, arrows, struck-through attempts. OCR will render them chaotically. Note in the grade (in $INTERFACE_LANG): "Answer ordering ambiguous. My interpretation: <brief>. Let me know if different."

### User already in context
If the user pastes their work directly into chat (not as PDF), grade it from context. Still apply strategy-based grading.

## Anti-patterns (things NOT to do)

❌ Demand pixel-perfect algebra from OCR output
❌ Mark something wrong because OCR mangled a Greek letter
❌ Require the user to retype their solution in LaTeX
❌ Produce 3-page grade reports (stay compact)
❌ Reveal the reference solution before grading (user might be asking "did I get it right" as a first pass)

## Integration

- Called by `/grade`
- Uses `pdf` skill for OCR
- Reads `course-index/patterns.md` (pattern IDs) and `converted/solutions/` or equivalent
- Writes to `errors/log.md` and `answers/converted/`
