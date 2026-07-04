---
description: Diagnose the paideia install + course workspace (Python, poppler, tesseract, Ollama/Qwen3-VL, course folders, .course-meta, writable paths, statusline wiring) and optionally auto-repair the permission-free issues. Run when a command won't work or right after cloning.
argument-hint: "[--fix to auto-repair safe issues]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language. Keep in English regardless: file paths, slash command names, OCR engine names (`claude`, `ollama`, `tesseract`), package names, and shell commands the user must copy-paste.

## What this does

`doctor` answers one question: **can paideia actually run here?** It checks the install (Python deps, poppler, tesseract + `kor` langdata, Ollama daemon + `qwen3-vl:8b`) and, when run inside a course folder, the workspace too (the directory skeleton, `.course-meta`, `errors/log.md`, writable paths, and the statusline / SessionStart wiring in `.claude/settings.json`).

It runs in two modes automatically:
- **Course mode** — `.course-meta` is present in CWD → full check. OCR-dependency severity is graded against `OCR_ENGINE`: poppler is required for every engine, but tesseract only blocks `ollama`/`tesseract`, and the Ollama daemon/model only block `ollama`. Python deps are graded the same way — `pdf2image`/`pillow` are core (blocking), `pytesseract` blocks only `ollama`/`tesseract`, and `reportlab`/`pypdf`/`pdfplumber` are warn-level (cheatsheet PDF / ad-hoc PDF ops only).
- **Global mode** — no `.course-meta` → system dependencies only, then points the user at `/paideia:init-course`. This is the "cloned but can't run" first line of defense.

## Procedure

Arguments: `$ARGUMENTS`

1. **Run the diagnostic.** Use the script in the plugin (it reads `INTERFACE_LANG` and `OCR_ENGINE` from `.course-meta` on its own):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py"
   ```

   If the user passed `--fix`, add it — `CLAUDE_PLUGIN_ROOT` must be in the environment (it is, inside a slash command) so the wiring repair can resolve absolute script paths:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --fix
   ```

   The script's exit code encodes overall status: `0` = all clear, `1` = usable with warnings, `2` = blocking issues.

2. **Relay the report** in `$INTERFACE_LANG`. The script already prints localized lines with copy-paste fix commands — surface them as-is; do not re-translate the shell commands. Lead with the bottom-line status (✓ all clear / ⚠ warnings / ✗ blocking).

3. **What `--fix` does and does not do.** Make this explicit if blocking issues remain after a `--fix` run:
   - **Auto-repaired** (no permissions needed): missing course directories, `errors/log.md` seed, `+x` bit on plugin scripts, and the absolute paths in `.claude/settings.json`. The workspace repairs (directories, log seed, settings.json) apply **only in course mode** — in global mode (no `.course-meta`) `--fix` restores the `+x` bits and nothing else, so it never scaffolds a course skeleton into an arbitrary folder.
   - **Never auto-run** — printed as commands for the user to run themselves: `brew` / `apt` / `pip` installs (these need sudo/brew), and any `.course-meta` value fixes (doctor will not guess `COURSE_NAME`, `EXAM_DATE`, etc.).

4. **If the wiring was repaired** (statusline / SessionStart paths rewritten), remind the user — as `/paideia:init-course` does — that `statusLine` is read **only at Claude Code startup**: they must fully **quit and relaunch** for the statusline to reappear (`/plugin reload` and new turns will not pick it up).

5. **Next step.** If blocking issues remain, list exactly which copy-paste commands to run, then suggest re-running `/paideia:doctor` (or `/paideia:doctor --fix`) to confirm green. If global mode and otherwise healthy, point to `/paideia:init-course`.

Keep output compact — this is a triage tool. Show the failing lines and their fixes first; collapse the passing checks into a single "N checks passed" line unless the user asks for detail.
