---
description: Bootstrap a fresh course folder — create directory skeleton, check deps (Python, tesseract; optionally ollama), prompt for interface language (en/ko) + course metadata + OCR engine, and write CLAUDE.md + .course-meta. Run once per course in the course folder's CWD.
argument-hint: (no args; fully interactive)
---

You are bootstrapping the user's current working directory into a fresh paideia workspace. Everything you create lives in the **user's CWD**, not in the plugin. The plugin itself (skills, commands, `vision_ocr.py`) is auto-loaded — your job is the per-course state.

## Execution plan

Run these steps sequentially. Use the Bash tool. Keep chat output compact — the user is watching progress.

### Step 0 — Interface language (ask the user, always in English)

This prompt is **always shown in English** because we do not yet know the user's preference. After Step 0, all subsequent prompts and output in this command — and all future paideia commands and generated MD narrative — must follow the chosen language.

Print exactly:

```
Choose interface language for this course (paideia will use it for all
future prompts, drill instructions, and generated MD narrative):

  1) en — English          (default)
  2) ko — 한국어

  Press Enter without input: en
```

Wait for the answer. Normalize `1`/`english`/`en`/empty → `en`; `2`/`korean`/`ko`/`한국어` → `ko`. Remember as `INTERFACE_LANG`. It goes into `.course-meta` in Step 6.

**From this point on, every user-facing string in this command — prompts, confirmations, the final next-steps block — must be written in $INTERFACE_LANG.** Steps 3, 5, and 11 provide both `en` and `ko` literal blocks; pick the matching one.

### Step 1 — Python deps

Check + offer to install `pypdf pdfplumber pytesseract pdf2image pillow reportlab`:

```bash
python3 -c "import pypdf, pdfplumber, pytesseract, pdf2image, PIL, reportlab" 2>&1 || \
  echo "MISSING_PYTHON_DEPS"
```

If missing: offer `python3 -m pip install --break-system-packages --user pypdf pdfplumber pytesseract pdf2image pillow reportlab`. Run only with user's OK.

### Step 2 — System binaries

```bash
command -v pdftoppm   >/dev/null 2>&1 && echo "poppler: ok"    || echo "poppler: MISSING"
command -v tesseract  >/dev/null 2>&1 && echo "tesseract: ok"  || echo "tesseract: MISSING"
command -v ollama     >/dev/null 2>&1 && echo "ollama: ok (optional)" || echo "ollama: not installed (optional — only needed for --ocr=ollama)"
tesseract --list-langs 2>&1 | grep -q '^kor$' && echo "tesseract-kor: ok" || echo "tesseract-kor: MISSING"
```

`poppler` and `tesseract` (+ Korean trained data) are required by all three OCR engines; `ollama` is strictly optional. For missing required items, print the install command (don't auto-run — these often need sudo/brew):
- macOS: `brew install poppler tesseract tesseract-lang`
- Ubuntu: `sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-kor`

### Step 3 — OCR engine choice (ask the user, in $INTERFACE_LANG)

Ask the user which OCR engine they want as the default for `/paideia:grade`. Use the block matching `INTERFACE_LANG`:

**If `INTERFACE_LANG=en`:**

```
Pick an OCR engine (override later with `/paideia:grade --ocr=<engine>`):

  1) claude    — Claude native vision (default, no extra install, highest handwriting accuracy)
  2) ollama    — local Qwen3-VL 8B (nothing leaves the machine, ~6GB initial download)
  3) tesseract — pytesseract only (lightest and fastest, lowest handwriting accuracy)

  Press Enter without input: claude
```

**If `INTERFACE_LANG=ko`:**

```
OCR 엔진을 선택해 주세요 (나중에 `/paideia:grade --ocr=<engine>`로 덮어쓸 수 있습니다):

  1) claude    — Claude 네이티브 비전 (기본값, 추가 설치 불필요, 필기 정확도 가장 높음)
  2) ollama    — 로컬 Qwen3-VL 8B (외부 전송 전혀 없음, 최초 ~6GB 다운로드 필요)
  3) tesseract — pytesseract eng+kor 만 사용 (가장 가볍고 빠름, 필기 정확도는 낮음)

  입력 없이 Enter 시: claude
```

Wait for the answer. Normalize to `claude`, `ollama`, or `tesseract`. Remember the value as `OCR_ENGINE`; it goes into `.course-meta` in Step 6.

### Step 3a — Ollama daemon + qwen3-vl:8b pull (only if user picked `ollama`)

Skip this step entirely if `OCR_ENGINE` is `claude` or `tesseract`.

If `OCR_ENGINE=ollama` and `ollama` binary is not present, stop and tell the user to install ollama first (`brew install ollama` / see `https://ollama.com/install.sh`), then re-run `/paideia:init-course`.

If `OCR_ENGINE=ollama` and ollama is present:

```bash
# Daemon check
curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 \
  && echo "daemon: up" || echo "daemon: down — run 'ollama serve &' in a separate shell"
```

If daemon is up AND model missing, kick off pull in background so it overlaps with the metadata prompts (Step 5):

```bash
if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "qwen3-vl:8b"; then
  LOG=$(mktemp -t paideia-ollama-pull.XXXXXX.log)
  ( ollama pull qwen3-vl:8b > "$LOG" 2>&1 ) &
  echo "BACKGROUND_PULL_PID=$!"
  echo "LOG=$LOG"
fi
```

Remember the PID and LOG path. Report (in $INTERFACE_LANG):

- `en`: "ollama model background pull started (PID, ~6 GB, runs in parallel with the metadata prompts)."
- `ko`: "ollama 모델 백그라운드 pull 시작 (PID, ~6 GB, 메타데이터 입력과 병렬 진행)."

### Step 3b — Symbolic grading availability (ask the user, in $INTERFACE_LANG)

Probe whether symbolic (SymPy) grading is already reachable by running:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --json 2>/dev/null \
  | python3 -c "import sys,json; print('VERIFY_REACHABLE=' + str(json.load(sys.stdin).get('verify_reachable', False)))"
```

**If `VERIFY_REACHABLE=True`:** Report one line (in $INTERFACE_LANG) and proceed:
- en: `"Symbolic (SymPy) grading is available — /paideia:grade will use symbolic+llm verification."`
- ko: `"기호(SymPy) 검산 가용 — /paideia:grade 가 symbolic+llm 검증을 사용합니다."`

**If `VERIFY_REACHABLE=False`:** Apply TTY-branch gate (T-VERIFY-HEADLESS-BUNDLE D1). Determine session interactivity first: the session is **non-interactive** when stdin is not a TTY (`test -t 0` is false) OR when running under `-p` / headless mode.

**Non-interactive path (headless / stdin not a TTY):** Do NOT display the `[Y/n]` prompt. Run auto-provisioner:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --ensure-verify
```
After `--ensure-verify` completes, re-run the probe above. Report result in $INTERFACE_LANG:
- en (success): `"Symbolic (SymPy) grading installed — /paideia:grade will use symbolic+llm verification."`
- ko (success): `"기호(SymPy) 검산 설치 완료 — /paideia:grade 가 symbolic+llm 검증을 사용합니다."`
- en (failure): `"Install failed — grading will use LLM-only. You can retry later with /paideia:doctor --install-verify."`
- ko (failure): `"설치 실패 — LLM 단독 채점으로 진행합니다. 나중에 /paideia:doctor --install-verify 로 재시도 가능."`

Installation failure does **not** block the rest of the bootstrap — continue to Step 4 regardless.

**Interactive path (TTY session):** Show the opt-out prompt (default = install; user must say `n` to skip):

**If `INTERFACE_LANG=en`:**

```
Symbolic (SymPy) grading is not installed. Install now so grading uses the
deterministic SymPy backstop? [Y/n]
(installs math-verify stack via /paideia:doctor --install-verify; ~30s.
Decline to keep LLM-only grading — you can enable later.)
```

**If `INTERFACE_LANG=ko`:**

```
기호(SymPy) 검산이 미설치입니다. 지금 설치해 결정론 SymPy 백스톱으로 채점할까요? [Y/n]
(/paideia:doctor --install-verify 로 math-verify 스택 설치, ~30초.
거부 시 LLM 단독 채점 유지 — 나중에 활성화 가능.)
```

Wait for the answer. Normalize `n`/`no`/`아니오`/`아니요` → skip; **all other input including empty → install** (capital `Y` is the default).

**If user chooses to install:**
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --install-verify
```
After the install completes, re-run the probe above. Report result in $INTERFACE_LANG:
- en (success): `"Symbolic (SymPy) grading installed — /paideia:grade will use symbolic+llm verification."`
- ko (success): `"기호(SymPy) 검산 설치 완료 — /paideia:grade 가 symbolic+llm 검증을 사용합니다."`
- en (failure): `"Install failed — grading will use LLM-only. You can retry later with /paideia:doctor --install-verify."`
- ko (failure): `"설치 실패 — LLM 단독 채점으로 진행합니다. 나중에 /paideia:doctor --install-verify 로 재시도 가능."`

Installation failure does **not** block the rest of the bootstrap — continue to Step 4 regardless.

**If user skips (answered `n`/`no`/`아니오`/`아니요`):**
- en: `"Skipped — grading will use LLM-only until you run /paideia:doctor --install-verify."`
- ko: `"건너뜀 — /paideia:doctor --install-verify 실행 전까지 LLM 단독 채점을 사용합니다."`

### Step 4 — Directory skeleton

Create these directories in the user's CWD (idempotent):

```bash
mkdir -p materials/{lectures,textbook,homework,solutions} \
         converted/{lectures,textbook,homework,solutions} \
         course-index quizzes mock twins chain derivations cheatsheet weakmap \
         answers/converted errors

# Seed errors/log.md if missing (append-only log; /grade and /weakmap depend on it).
# This text must stay identical to paideia_lib.ERRORS_LOG_SEED (doctor --fix and
# log_tool.py restore/extend the same seed).
[ -f errors/log.md ] || cat > errors/log.md <<'EOF'
# Error log

<!-- Append-only YAML entries. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  phase: reading | comprehension | transformation | execution | encoding   # optional (F2) — inferred from error_type when absent
  nature: slip | misconception | gap   # optional (F3) — inferred from error_type when absent
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts>>
  date: <ISO8601>
  overridden_by: <source>   # optional — present only on entries superseded by a human override
Only the six keys problem_id/pattern/error_type/summary/source/date are required; phase/nature/overridden_by are optional.
Write entries via scripts/log_tool.py (idempotent per source) — do not hand-edit appends.
-->
EOF
```

### Step 5 — Course metadata (ask the user, in $INTERFACE_LANG)

Ask four short questions. Use the phrasing matching `INTERFACE_LANG`:

**If `INTERFACE_LANG=en`:**
1. `COURSE_NAME` (e.g., Complex Analysis MATH 405)
2. `EXAM_DATE` (YYYY-MM-DD)
3. `EXAM_TYPE` (midterm/final/qualifier)
4. `USER_WEAK_ZONES` (comma-separated topics, or `unknown`)

**If `INTERFACE_LANG=ko`:**
1. `COURSE_NAME` (예: Complex Analysis MATH 405)
2. `EXAM_DATE` (YYYY-MM-DD)
3. `EXAM_TYPE` (midterm/final/qualifier)
4. `USER_WEAK_ZONES` (쉼표로 구분된 토픽, 또는 `unknown`)

Wait for responses before continuing.

### Step 6 — Write .course-meta

```bash
cat > .course-meta <<EOF
COURSE_NAME: <answer1>
EXAM_DATE: <answer2>
EXAM_TYPE: <answer3>
USER_WEAK_ZONES: <answer4>
OCR_ENGINE: <engine-from-step-3>
INTERFACE_LANG: <lang-from-step-0>
EOF
```

`INTERFACE_LANG` is read by `session_start.py`, `statusline.py`, `vision_ocr.py`, and every paideia slash command to decide which language to use for all user-facing prose.

### Step 7 — CLAUDE.md (project-level rules)

If `CLAUDE.md` doesn't exist in CWD, write the paideia template (see `CLAUDE.md.template` below). If it exists, **do not overwrite** — ask the user if they want to append the paideia section instead.

Substitute all 6 placeholders (`$COURSE_NAME`, `$EXAM_DATE`, `$EXAM_TYPE`, `$WEAK_ZONES`, `$OCR_ENGINE`, `$INTERFACE_LANG`) into the template's metadata block before writing. The list must stay in sync with the metadata block in the `CLAUDE.md.template` section below.

### Step 8 — Statusline + SessionStart wiring

Write a project-scoped `.claude/settings.json` that points two Claude Code slots at the plugin:

1. **statusLine** → `scripts/statusline.py` (live `paideia · <COURSE> · D-N · <phase> · P<k> ↑` readout, random neon color per session, silent outside this folder).
2. **hooks.SessionStart** → `scripts/session_start.py` (2–3 line reminder on new session / resume so the first turn already knows D-N, phase, and top-miss pattern).

**Important:** `${CLAUDE_PLUGIN_ROOT}` is expanded inside hooks but **not** inside statusline commands (per Claude Code's statusline docs). To keep the two slots symmetric and failure-mode-identical — either both work or both fail together when the plugin is moved — we resolve both script paths to **absolute paths now, at bootstrap time**, and write those literal paths into the JSON.

```bash
mkdir -p .claude

# Resolve the plugin script paths to absolute paths at bootstrap time.
# $CLAUDE_PLUGIN_ROOT is set inside plugin slash commands; fall back to unset for
# dev / unusual installs.
STATUSLINE_SRC=""
SESSION_START_SRC=""
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py" ]    && STATUSLINE_SRC="${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py"
  [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/session_start.py" ] && SESSION_START_SRC="${CLAUDE_PLUGIN_ROOT}/scripts/session_start.py"
fi

# Make sure both scripts are executable (plugins sometimes lose the x-bit during install/unzip).
[ -n "$STATUSLINE_SRC" ]    && chmod +x "$STATUSLINE_SRC"    2>/dev/null || true
[ -n "$SESSION_START_SRC" ] && chmod +x "$SESSION_START_SRC" 2>/dev/null || true

if [ -z "$STATUSLINE_SRC" ] && [ -z "$SESSION_START_SRC" ]; then
  echo "wiring: could not locate plugin scripts (CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-unset}). Skipping."
elif [ -f .claude/settings.json ]; then
  echo "wiring: .claude/settings.json already exists — leaving as is. To enable, merge into it:"
  [ -n "$STATUSLINE_SRC" ]    && echo "  statusLine: { \"type\": \"command\", \"command\": \"$STATUSLINE_SRC\" }"
  [ -n "$SESSION_START_SRC" ] && echo "  hooks.SessionStart: [{ hooks: [{ \"type\": \"command\", \"command\": \"python3 $SESSION_START_SRC\" }] }]"
else
  # JSON is assembled by python, not a bash heredoc, for two reasons:
  # 1. Per-slot presence — if exactly one script resolved, only that slot is
  #    written. (The old heredoc emitted both slots unconditionally, so a
  #    missing script produced a broken `"command": ""` entry.)
  # 2. Space-safe quoting — the command strings are shell lines, so script
  #    paths get shlex-quoted; an install path containing spaces survives.
  #    shlex.quote adds quotes only when needed, so normal paths stay bare.
  # Statusline is invoked via its shebang (no `python3` wrapper, Claude Code
  # runs it with a minimal env). SessionStart runs in a richer hook env so we
  # explicitly call `python3` for portability.
  python3 - "$STATUSLINE_SRC" "$SESSION_START_SRC" <<'PY'
import json, shlex, sys
sl, ss = sys.argv[1], sys.argv[2]
data = {}
if sl:
    data["statusLine"] = {"type": "command", "command": shlex.quote(sl)}
if ss:
    data["hooks"] = {"SessionStart": [{
        "matcher": "startup|resume",
        "hooks": [{"type": "command", "command": f"python3 {shlex.quote(ss)}"}],
    }]}
with open(".claude/settings.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"wiring: statusLine      → {sl or '(script missing — slot omitted)'}")
print(f"wiring: SessionStart    → {ss or '(script missing — slot omitted)'}")
PY
  echo "  (if nothing appears after this, fully quit and relaunch Claude Code —"
  echo "   both slots are read at app startup, not on /plugin reload)"
fi
```

Both slots silently no-op if `.course-meta` is missing, so there is no harm in leaving them wired when the user cd's elsewhere. If the plugin is later moved/reinstalled at a different path, re-run `/paideia:init-course` (or hand-edit `.claude/settings.json`) so the absolute paths match the new location.

### Step 9 — git init

If `.git` doesn't exist:

```bash
git init -q
cat > .gitignore <<'EOF'
.claude/cache/
# Original answer scans: large, personal, and already OCR'd into answers/converted/.
answers/*.pdf
# Archived answer scans from /paideia:grade (moved out of answers/ after grading).
answers/_archive/
answers/converted/.tmp-*/
cheatsheet/final.pdf
.DS_Store
*.pyc
__pycache__/
# Do NOT ignore errors/log.md — it's the learning record; commit every entry.
# Do NOT ignore answers/converted/*.md — OCR output is slow to regenerate.
# Do NOT ignore quizzes/*_answers.md, mock/*_sol.md, twins/*_sol.md, chain/*_sol.md —
#   these are generated reference solutions; keep them versioned so you can diff
#   against a re-roll and cross-reference graded errors later.
EOF
git add -A
git commit -q -m "paideia: initial setup" 2>/dev/null || true
```

### Step 10 — Wait for background pull (if any)

If Step 3a spawned a background pull:

```bash
wait <PID>
```

Report pull status (success or point to `$LOG`).

### Step 11 — Print next steps

Format the block below exactly as shown — the first paragraph is the **mandatory restart notice**. `statusLine` in `.claude/settings.json` is only read at Claude Code startup; `/plugin reload` and new turns will NOT pick it up. If Step 8 actually wrote a new `settings.json` (i.e., one did not already exist), the restart is **required** for the statusline to appear. If Step 8 skipped writing (file already existed), restart is optional.

Print the block matching `INTERFACE_LANG`:

**If `INTERFACE_LANG=en`:**

```
✅ <COURSE_NAME> ready. (OCR: <OCR_ENGINE>, lang: en)

⚠️  Fully **quit and relaunch** Claude Code to enable the statusline.
    (statusLine settings are read only at app startup — /plugin reload
    will NOT pick them up.) After relaunch, opening Claude Code in this
    folder will show a neon line at the top:
    "paideia · <COURSE_NAME> · D-N · setup · …"

Next steps (after relaunch):
  1. Drop PDFs/MDs into materials/{lectures,textbook,homework,solutions}/
  2. /paideia:ingest        ← PDFs → MDs
  3. /paideia:analyze       ← build patterns, coverage
  4. /paideia:hwmap hot     ← see 🔥🔥 exam hotzones
```

**If `INTERFACE_LANG=ko`:**

```
✅ <COURSE_NAME> 준비 완료. (OCR: <OCR_ENGINE>, lang: ko)

⚠️  statusline 적용을 위해 Claude Code를 **완전히 종료 후 재시작**해 주세요.
    (statusLine 설정은 앱 시작 시에만 읽힙니다 — /plugin reload 로는 반영 안 됩니다.)
    재시작 후 이 폴더에서 Claude Code를 여시면 상단에
    "paideia · <COURSE_NAME> · D-N · setup · …" 형태의 네온색 한 줄이 뜹니다.

다음 단계 (재시작 후):
  1. materials/{lectures,textbook,homework,solutions}/ 에 PDF/MD 드롭
  2. /paideia:ingest        ← PDFs → MDs
  3. /paideia:analyze       ← patterns, coverage 생성
  4. /paideia:hwmap hot     ← 🔥🔥 시험 핫존 확인
```

## CLAUDE.md.template

Below is the template to write at Step 7. Substitute `$COURSE_NAME`, `$EXAM_DATE`, `$EXAM_TYPE`, `$WEAK_ZONES`, `$OCR_ENGINE`, `$INTERFACE_LANG` verbatim. (Step 8 wires the statusline; Step 9 handles git.)

```markdown
# Course Cram — Project Context

## Purpose

This project is a general-purpose exam preparation workspace for any math or physics course.
Given raw course materials (lecture notes, textbook chapters, HW problems, HW solutions — in
PDF or markdown), it builds a structured knowledge base and provides drilling tools for exam prep.

## Course metadata

```
COURSE_NAME: $COURSE_NAME
EXAM_DATE: $EXAM_DATE
EXAM_TYPE: $EXAM_TYPE
USER_WEAK_ZONES: $WEAK_ZONES
OCR_ENGINE: $OCR_ENGINE
INTERFACE_LANG: $INTERFACE_LANG
```

## Directory map

materials/ converted/ course-index/ quizzes/ mock/ twins/ chain/ derivations/ cheatsheet/
weakmap/ answers/ errors/ — see the paideia plugin README for full semantics.

## Workflow philosophy

1. **User does not type math in the CLI.** Claude produces MD files. User reads.
2. **User produces PDF scans** of hand-written work in `answers/`.
3. **Claude OCRs locally** via the engine set in `OCR_ENGINE` (`claude` = native vision, `ollama` = local Qwen3-VL, `tesseract` = pytesseract) and **strategy-grades**.
4. **HW density = exam probability.** Drill `🔥🔥` (3+ HW) sections first; `⚪` (no HW) = reference only.

## Slash commands

All commands are namespaced `/paideia:<name>`. See the plugin's README for the full list.

## Conventions

- Citations: every explanation cites `converted/<file>.md` §.
- Pattern IDs: reference by `Pk` from `course-index/patterns.md`.
- Never reveal solutions before the user attempts.
- Prose in `$INTERFACE_LANG` (en or ko), LaTeX math (`$...$` inline, `$$...$$` display). File paths, slash command names, pattern IDs (P1, P2…), YAML keys, and section anchors regex'd by other tools (e.g. `## One-line verdict`, `## Page N`) always stay in English regardless of language.
- Errors logged in `errors/log.md` on every failed attempt (YAML schema).
- Keep drill output ≤ 40 lines, grade reports ≤ 15 lines.
```
