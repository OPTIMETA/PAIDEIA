---
description: "Grade user's answer PDF (hand-written, scanned) against reference solution. OCR engine is selectable: claude (default, no extra install), ollama (Qwen3-VL local), or tesseract. Then strategy-based grade."
argument-hint: "[--ocr=claude|ollama|tesseract] [optional path to answer file; default = most recent in answers/]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output, grade-table commentary, the OCR quality escape-hatch menu — must be in that language. Keep in English regardless: file paths, slash command names (`/paideia:grade`, `/paideia:blind`, …), pattern IDs (P1, P2…), YAML keys, LaTeX, OCR engine names (`claude`, `ollama`, `tesseract`), and the grade table's column headers (`P#`, `Pattern`, `Vars`, `SymPy`, `End form`, `Overall`). `vision_ocr.py` reads `INTERFACE_LANG` from `.course-meta` on its own to set the VLM's prose-language rule and the tesseract `lang=` code, so the bash invocations below don't need to pass it explicitly.

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
   - `diagnostic*.pdf` (e.g. `diagnostic.pdf`, `diagnostic_<ts>.pdf`) →
     `quizzes/diagnostic_<ts>_answers.md` — exact `<ts>` match first; otherwise
     fall back to the most recent `quizzes/diagnostic_*_answers.md` (scans get
     renamed by phone apps, so like mock/chain the fallback is the common path;
     `/paideia:quiz all` saves under the `diagnostic` stem for exactly this rule)
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

4b-pre. **Preflight: symbolic verify availability check.** Before step decomposition, call `verify_tool.py` with a trivial probe (`{"checks":[]}`).

   **If exit 0 (math-verify present):** proceed with `verify_mode: "symbolic+llm"` — no prompt, no action needed.

   **If exit 3 (math-verify absent):** offer a single one-time consent in `$INTERFACE_LANG` **before any grading calculation begins**:

   > (en) "Deterministic verification is not installed. Enable it now for this and future grades? [Y/n] (installs math-verify stack via `/paideia:doctor --install-verify`; this happens BEFORE any grading begins, not mid-run.)"
   > (ko) "결정론 검산이 미설치입니다. 이번 채점부터 켤까요? [Y/n] (`/paideia:doctor --install-verify` 로 math-verify 스택 설치; **채점 시작 전** 단계에서만 실행되며 채점 도중이 아닙니다.)"

   Wait for user response. Normalize `n`/`no`/`아니오`/`아니요` → skip; **all other input including empty → install** (capital `Y` is the default).

   **If user answers Y (or empty/other):**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --install-verify
   ```
   After the install completes, re-probe: call `verify_tool.py` again with `{"checks":[]}`.
   - If re-probe exits 0: proceed with `verify_mode: "symbolic+llm"` for **this grade run**.
   - If re-probe still exits 3 (install failed): output one line in `$INTERFACE_LANG`:
     > (en) "Install failed — proceeding with LLM-only grading. Try `/paideia:doctor --install-verify` later."
     > (ko) "설치 실패 — LLM 단독 채점으로 진행합니다. 나중에 `/paideia:doctor --install-verify` 로 재시도."
     Then proceed with `verify_mode: "llm-only"`.

   **If user answers n/no/아니오/아니요 (skip):** output one line in `$INTERFACE_LANG`:
   > (en) "Deterministic verification skipped — proceeding with LLM-only grading. Enable anytime with `/paideia:doctor --install-verify`."
   > (ko) "결정론 검산 건너뜀 — LLM 단독 채점으로 진행합니다. 언제든 `/paideia:doctor --install-verify` 로 활성화 가능."
   Then proceed with `verify_mode: "llm-only"`.

   **no-mid-run-install rule:** Installation is only permitted at this 4b-pre preflight stage — BEFORE step decomposition and grading calculations begin. Once step verification has started (4b), if exit 3 is encountered then, skip symbolic verification for that step and continue with LLM verdict only; do NOT attempt to install mid-run. This preserves result consistency within a single grade run. This preflight output appears above the grade table.

4b. **Step decomposition + per-step verify (checkable steps).**

   Decompose the reference solution and the student's work into a step sequence `s_1..s_n`. Assign each step a `role` (one of: `setup`, `algebra`, `substitution`, `result`, `justification`) and a boolean `checkable` flag. `checkable: true` means the step contains an algebraic equality that SymPy can verify symbolically.

   For every `checkable` step, collect the check tuples `{id, gold, cand, relation}` and call **verify_tool.py in ONE call**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_tool.py" <<'JSON'
   {"checks":[{"id":"s1","gold":"<gold_latex>","cand":"<student_latex>","relation":"eq"},…]}
   JSON
   ```

   - `verify_tool.py` reads from stdin and writes `{"results":[{"id":"s1","result":"pass"|"fail"|"timeout"|"unparsable"},…]}` to stdout.
   - **Exit 3** = math-verify absent → skip symbolic verification entirely, fall back to LLM-only strategy grading (honest demotion, analogous to OCR-tier demotion above). Do NOT install math-verify mid-run; note the demotion in the grade table.
   - Any other non-zero exit → treat all results as `"unparsable"`.

   **Reconciliation rule (SymPy overrides LLM for checkable steps):**
   - `result = "pass"` → step verdict = `"correct"` (overrides LLM)
   - `result = "fail"` → step verdict = `"wrong"` (overrides LLM)
   - `result = "timeout"` or `"unparsable"` → keep LLM verdict unchanged

   This mirrors the `reconcileStep` rule in `paideia-core/src/reconcile.ts` (W3). The canonical computation is the TS pure function; this prompt instruction is its LLM-facing reflection.

   Non-`checkable` steps are assessed by strategy grading only (pattern match, variable choice, end form, completeness — step 4 below).

5. **Render compact grade table** (≤ 15 lines in chat):

   If `verify_mode == "llm-only"`, output the demotion badge line **above the table** (in $INTERFACE_LANG):
   - en: `"⚠ Symbolic verification off — LLM-only grading (enable: /paideia:doctor --install-verify)."`
   - ko: `"⚠ 기호 검산 꺼짐 — LLM 단독 채점 (활성화: /paideia:doctor --install-verify)."`

   Then render the table with the `SymPy` column included (column header stays in English regardless of $INTERFACE_LANG):
   ```
   | P# | Pattern | Vars | SymPy | End form | Overall |
   |---|---|---|---|---|---|
   ```

   SymPy column values (derived from `steps[].sympy.result` in the GRADE_RECORD_JSON — no duplicate source):
   - `verify_mode == "symbolic+llm"`: for checkable steps, `✓` (pass override) / `✗` (fail override) / `–` (timeout or unparsable, LLM verdict retained); for non-checkable steps, `·`.
   - `verify_mode == "llm-only"`: entire column is `n/a` for every row.

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

6b. **Emit machine-readable grade record.**

   Immediately after the `errors/log.md` append in step 6 (and before step 7), emit a machine-readable grade record to stdout using the following **exact** marker fence. The store reads this fence from the transcript to write `drill_attempts` and `decisions` (W4 T-GradeLedgerWrite).

   ```
   <!-- GRADE_RECORD_JSON -->
   ```json
   {
     "problem_id": "<stem of the answer file>",
     "ocr_tier": "<tier string from the TIER header>",
     "verify_mode": "<symbolic+llm | llm-only>",
     "pattern_expected": ["<P#>", …],
     "steps": [
       {
         "idx": 1,
         "latex": "<step expression>",
         "role": "setup|algebra|substitution|result|justification",
         "checkable": true|false,
         "sympy": { "checked": true, "relation": "eq", "gold_ref": "<gold>", "result": "pass|fail|timeout|unparsable" },
         "verdict": "correct|wrong|unclear",
         "confidence": 0.0–1.0,
         "error_type": <one of "pattern-missed"|"wrong-variable"|"wrong-end-form"|"algebraic"|"sign"|"definition", or JSON null for correct steps>,
         "note": "<optional>"
       }
     ],
     "first_wrong_step_idx": <integer or null>,
     "final_answer": { "latex": "<student>", "gold": "<reference>", "equivalent": true|false },
     "partial_credit": { "scale": "0-5", "score": <integer 0-5>, "rubric_hits": [] },
     "verdict": "PASS|PARTIAL|FAIL",
     "dominant_error": <error_type token in quotes, or JSON null>,
     "human_review": false
   }
   ```
   <!-- /GRADE_RECORD_JSON -->
   ```

   Rules:
   - `steps[].error_type` reuses the 6-type canonical enum (same tokens as `errors/log.md`, `init-course.md`, and `answer-processing/SKILL.md`): `pattern-missed`, `wrong-variable`, `wrong-end-form`, `algebraic`, `sign`, `definition`. For correct steps use the JSON literal `null` (unquoted). The quoted string `"null"` is NOT a valid token — emit `"error_type": null`, never `"error_type": "null"`. This keeps weakmap histograms from `errors/log.md` and from grade records aligned. Same rule for `dominant_error`.
   - `first_wrong_step_idx`: 1-based index of the earliest `"wrong"` step after reconciliation, or `null` if all steps are correct (ProcessBench all-correct signal, 03 §1.4).
   - `verify_mode`: `"symbolic+llm"` if verify_tool.py ran without exit 3; `"llm-only"` if exit 3 (math-verify absent).
   - `sympy` key is **absent** for non-checkable steps or when `verify_mode="llm-only"`.
   - The `verify_mode` value (`"symbolic+llm"` or `"llm-only"`) is derived from the 4b-pre preflight: it reflects `verify_reachable` as reported by `doctor --json`, and is consumed here and in step 5's SymPy column and demotion badge.
   - This marker and its schema are a **new additive anchor** (`<!-- GRADE_RECORD_JSON -->`). It does NOT replace the 6-key `errors/log.md` contract, `PATTERN_RX`, existing anchors, or `log_tool.py` idempotency — those remain unchanged.
   - No new Python or JS dependencies: `verify_tool.py` is the W1-vendored tool reused as-is.

### Human override — correcting a misgrade (오채점 정정)

**en:** If the user disputes a verdict ("this was an OCR misread" / "that error classification is wrong"), re-assess the problem and record the correction with `override` instead of `append`. The original verdict is preserved in the log with `overridden_by: <source>` — the audit trail is never destroyed.

**ko:** 사용자가 채점에 이의를 제기하면 ("OCR 오독이었다", "오류 분류가 틀렸다"), 해당 문항을 재평가한 뒤 `append` 대신 `override`로 기록하세요. 원본 평결은 `overridden_by: <source>` 표식과 함께 로그에 **보존**됩니다 — 감사추적이 파괴되지 않습니다.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/log_tool.py" override \
     --source="answers/converted/<stem>.md" <<'YAML'
   - problem_id: <id>
     pattern: <Pk>
     error_type: <corrected-type>
     summary: "<corrected 1-line description>"
     source: answers/converted/<stem>.md
     date: <ISO8601>
   YAML
   ```

   **en:** Rules:
   - Use `override` when changing the verdict (different `error_type`, different `pattern`, or new problem discovered). The original entry gets `overridden_by:` and stays in the log. The correction becomes the current verdict.
   - Use `remove` only when re-grading produced **zero** errors (the problem is now fully correct) — that clears stale entries entirely.
   - Do NOT include `overridden_by:` in the stdin block — the tool assigns it. Passing it is a validation error.

   **ko:** 규칙:
   - 평결을 바꿀 때 (`error_type` 변경, `pattern` 변경, 새 오류 발견) → `override` 사용. 원본 엔트리에 `overridden_by:` 가 붙고 로그에 남습니다. 정정본이 현행 평결이 됩니다.
   - 재채점 결과 오류가 **없어진** 경우에만 `remove` 사용 — 기존 엔트리를 완전히 삭제합니다.
   - stdin 블록에 `overridden_by:`를 직접 쓰지 마세요 — 도구가 자동 부여합니다. 포함하면 유효성 오류로 거부됩니다.

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
