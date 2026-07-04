---
description: "Grade user's answer PDF (hand-written, scanned) against reference solution. OCR engine is selectable: claude (default, no extra install), ollama (Qwen3-VL local), or tesseract. Then strategy-based grade."
argument-hint: "[--ocr=claude|ollama|tesseract] [optional path to answer file; default = most recent in answers/]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output, grade-table commentary, the OCR quality escape-hatch menu — must be in that language. Keep in English regardless: file paths, slash command names (`/paideia:grade`, `/paideia:blind`, …), pattern IDs (P1, P2…), YAML keys, LaTeX, OCR engine names (`claude`, `ollama`, `tesseract`), and the grade table's column headers (`P#`, `Pattern`, `Vars`, `End form`, `Overall`). `vision_ocr.py` reads `INTERFACE_LANG` from `.course-meta` on its own to set the VLM's prose-language rule and the tesseract `lang=` code, so the bash invocations below don't need to pass it explicitly.

Load `skills/vision-ocr/SKILL.md`, `skills/pdf/SKILL.md`, and `skills/answer-processing/SKILL.md`.

Arguments: $ARGUMENTS

If `$ARGUMENTS` contains `--ocr=<engine>`, that overrides the default for this call. Otherwise read `OCR_ENGINE` from `.course-meta` in CWD (one line of the form `OCR_ENGINE: <engine>`). If `.course-meta` is absent or the key is missing, default to `claude`.

Target answer file: the non-flag positional in `$ARGUMENTS`. If no positional, find the most recently modified file in `answers/` (not `answers/converted/`).

Follow the answer-processing skill pipeline:

1. **Identify.** Is target a `.pdf` or `.md`?
   - `.pdf` → proceed to step 2
   - `.md` → skip step 2, go to 3

2. **Convert PDF → MD.** Dispatch on the selected OCR engine:

   ### 2a. `claude` (default) — native Claude vision, no external model

   ```bash
   STEM=$(basename "answers/<stem>.pdf" .pdf)
   TMPDIR="answers/converted/.tmp-${STEM}"
   mkdir -p "$TMPDIR"
   pdftoppm -r 200 -png "answers/${STEM}.pdf" "$TMPDIR/page"

   # Downsize to max 1800px width to keep Read-tool image payloads small.
   # Without this, 200-DPI letter-size pages are ~1700–2200px wide and each page
   # eats ~0.5–1.0 MB of image tokens — fine for 1–2 pages, brutal for 10+.
   # Mirrors the resize step used by /paideia:ingest for lecture/homework scans.
   python3 - "$TMPDIR" <<'PY'
   import sys, pathlib
   from PIL import Image
   MAX_W = 1800
   for p in sorted(pathlib.Path(sys.argv[1]).glob("page-*.png")):
       img = Image.open(p)
       if img.width > MAX_W:
           ratio = MAX_W / img.width
           img.resize((MAX_W, int(img.height * ratio))).save(p, optimize=True)
   PY
   ```

   This produces `$TMPDIR/page-1.png`, `$TMPDIR/page-2.png`, ... (each ≤1800px wide). Now **use the Read tool on each PNG in order** and synthesize clean markdown yourself, following the transcription prompt contract from `skills/vision-ocr/SKILL.md`:

   - Prose stays in its original language (English, Korean, etc.) — do not translate.
   - Math as `$...$` / `$$...$$`.
   - Preserve problem numbering (P1, (1), (a), ...).
   - Do NOT interpret or grade — pure transcription.
   - `[?]` for ambiguous glyphs.
   - Skip crossed-out work.
   - Markdown only.

   Write the synthesized result to `answers/converted/<stem>.md` with header:

   ```markdown
   # Vision-OCR transcription

   <!-- SOURCE: <stem>.pdf, claude-vision (native), N pages -->

   ## Page 1

   <transcription>

   ## Page 2

   <transcription>
   ```

   Clean up: `rm -rf "$TMPDIR"`.

   ### 2b. `ollama` — local Qwen3-VL 8B

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py" --engine=ollama \
     "answers/<stem>.pdf" "answers/converted/<stem>.md"
   ```

   Uses `qwen3-vl:8b` via ollama. The script reads `INTERFACE_LANG` from `.course-meta` in CWD so the prose-language rule in the VLM prompt matches the course's language. Auto-falls back to tesseract on any exception (timeout / ollama down / model missing). Tier is recorded in the file header. See `skills/vision-ocr/SKILL.md` for details.

   ### 2c. `tesseract` — explicit, skip ollama

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py" --engine=tesseract \
     "answers/<stem>.pdf" "answers/converted/<stem>.md"
   ```

   Pure pytesseract (`eng` if the course's `INTERFACE_LANG=en`, `eng+kor` if `ko` — also read from `.course-meta`). Fastest, lowest fidelity on handwriting.

3. **Identify reference solution.** Based on the answer filename stem:
   - `hw3.pdf` → `converted/solutions/hw3_sol.md` (or `converted/solutions/hw3.md`)
   - `diagnostic.pdf` → `quizzes/diagnostic_answers.md`
   - `mock_<ts>.pdf` (or `exam_<ts>.pdf`) → `mock/exam_<ts>_sol.md`. The scan is
     usually timestamped later than the exam, so the `<ts>` rarely matches —
     if there is no exact match, fall back to the most recent `mock/exam_*_sol.md`.
   - `<topic>_<ts>.pdf` → `quizzes/<topic>_<ts>_answers.md` (this generic rule
     fires only after the `mock_`/`twin_`/`chain_` prefixes above are ruled out)
   - `twin_<id>_<ts>.pdf` → `twins/<id>_<ts>_sol.md`; if the `<ts>` doesn't
     match exactly, fall back to the most recent `twins/<id>_*_sol.md`.
   - `chain_<ts>.pdf` → `chain/<ts>_sol.md`; same as mock, the scan `<ts>`
     rarely matches the generated one, so fall back to the most recent
     `chain/*_sol.md`.
   If cannot resolve, ask the user to specify.

4. **Strategy-based grading per problem:**
   - Pattern match (did the user invoke the right pattern from `course-index/patterns.md`?)
   - Variable choice (did they hold the right things fixed?)
   - End form (does their final expression structure match?)
   - Completeness (where did they stop?)

5. **Render compact grade table** (≤ 15 lines in chat):
   ```
   | P# | Pattern | Vars | End form | Overall |
   |---|---|---|---|---|
   ```
   Plus one closing line (in $INTERFACE_LANG): "Dominant issue: <type>. Next drill: /<command> <target>."

6. **Log errors.** Build the YAML block for every non-✅ entry (canonical schema from answer-processing SKILL.md Step 6), then write it in ONE call through the deterministic writer — it replaces any prior entries for the same source (idempotent re-grades) and schema-validates before writing:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_tool.py" append \
     --source="answers/converted/<stem>.md" <<'YAML'
   - problem_id: <id>
     ...
   YAML
   ```

   Never hand-edit `errors/log.md` appends. If a re-grade produced zero errors, run `log_tool.py remove --source="answers/converted/<stem>.md"` instead so stale entries clear.

7. **Do NOT** print the full reference solution. The user can open it themselves if they want to study.

8. **Archive the graded PDF.** After the grade table and the `errors/log.md` append both succeed, move the original PDF out of `answers/` so the next `/paideia:grade` invocation doesn't keep re-picking the same "most recently modified" file when the user uploads a newer scan:

   ```bash
   if [ -f "answers/${STEM}.pdf" ]; then
     mkdir -p answers/_archive
     TS=$(date +%Y%m%d-%H%M%S)
     mv "answers/${STEM}.pdf" "answers/_archive/${STEM}_${TS}.pdf"
     echo "archived: answers/${STEM}.pdf → answers/_archive/${STEM}_${TS}.pdf"
   fi
   ```

   `answers/_archive/` is in `.gitignore` (scans are bulky + personal); the converted `answers/converted/${STEM}.md` stays put and IS committed, so the grade trail is preserved in version control. Skip this archive for the `.md`-only path (step 1's `.md` branch) — there's no original PDF to move.

## OCR quality escape hatch

Inspect the `<!-- SOURCE: ... -->` / `<!-- TIER: ... -->` header comment in `answers/converted/<stem>.md` first.

- **Tier 0 (`claude-vision`)** or **Tier 1 (`qwen3-vl:8b`) succeeded:** grade normally. Quality is usually good enough for strategy matching even on messy handwriting.
- **Tier 1b fallback (`tesseract` auto-fallback)** was used, **Tier 2 (`tesseract` explicit)**, the MD is <100 chars, or mostly garbled — print the menu below in $INTERFACE_LANG, keeping slash commands and paths verbatim:
  ```
  OCR quality is low (grading reliability degraded).
  Options:
    (a) /paideia:grade --ocr=claude <pdf>   ← retry with Claude vision (no extra install)
    (b) re-scan brighter / larger, then /paideia:grade again
    (c) type the answer into .md and save it to `answers/converted/<stem>.md`, then /paideia:grade
    (d) skip grading and use /paideia:blind <problem-id> to verbalize the strategy instead
  ```

## When both .pdf and .md exist

If `answers/<stem>.pdf` AND `answers/converted/<stem>.md` both exist and the `.md` is recent (edited within 1 hour), use the `.md` directly (user likely manually cleaned OCR output).
