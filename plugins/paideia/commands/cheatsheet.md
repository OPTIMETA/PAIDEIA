---
description: Generate a one-page exam cheatsheet from course-index and errors/log.md. Outputs to cheatsheet/final.md. Optionally convert to PDF.
argument-hint: "[--pdf to also produce a printable PDF via pdf skill]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output, clarification questions, and narrative sections of any MD file you write (including the cheatsheet's prose) — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1, P2…), YAML keys, LaTeX, code, and the literal section anchors downstream tools regex on.

Load `skills/exam-drill/SKILL.md`. Read `course-index/patterns.md`, `course-index/coverage.md`, `course-index/summary.md`, and `errors/log.md`.

Arguments: $ARGUMENTS

Procedure:

1. **Collect highest-value items:**
   - Top 5 patterns by frequency of appearance (from `patterns.md`)
   - All formulas boxed in `derivations/*.md` (final results)
   - User's most-frequent error types (from `errors/log.md`) — with the correction, not the error
   - 🔴 blind-spot sections with one key formula each

2. **Structure the cheatsheet** (target: fits on 1 page @ 10pt):

   ```markdown
   # <Course name> — Cheatsheet

   _Generated <date>. For exam reference only._

   ## Core formulas
   <table or compact list of boxed results from derivations/>

   ## Pattern quick-ref
   | Pk | Recognition | Move |
   |---|---|---|
   ...top 8 patterns only

   ## Traps to remember (from my errors/log)
   - <correction 1>
   - <correction 2>
   ...max 5

   ## Blind-spot formulas (memorize these — no HW drilled them)
   <one formula per blind-spot section, boxed>
   ```

3. **Write to** `cheatsheet/final.md`.

4. **If `--pdf` in arguments:**
   - Load `skills/pdf/SKILL.md`
   - Convert cheatsheet/final.md to `cheatsheet/final.pdf` using reportlab
   - Use 2-column layout, 9pt font, no margins (for maximum density)
   - Remember: NO Unicode subscripts/superscripts in reportlab — use `<sub>`/`<super>` XML tags
   - **CJK fonts (required when `INTERFACE_LANG=ko`).** reportlab's built-in
     Type-1 fonts (Helvetica/Times) **cannot render Hangul** — every Korean
     glyph silently comes out blank, so a `ko` cheatsheet PDF would be empty of
     prose. Register a CJK-capable TrueType font first and use it for every
     style (`fontName=`). Probe these candidates in order and fall back to the
     first that exists:
     ```python
     from reportlab.pdfbase import pdfmetrics
     from reportlab.pdfbase.ttfonts import TTFont
     KFONT, candidates = "Helvetica", [
         "/System/Library/Fonts/AppleSDGothicNeo.ttc",            # macOS
         "/System/Library/Fonts/Supplemental/AppleGothic.ttf",    # macOS
         "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",       # Ubuntu (fonts-nanum)
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",# Noto CJK
     ]
     for cand in candidates:
         try:
             pdfmetrics.registerFont(TTFont("KFont", cand)); KFONT = "KFont"; break
         except Exception:
             continue
     ```
     If none is found on a `ko` course, tell the user (in `INTERFACE_LANG`) to
     `brew install font-nanum` / `sudo apt-get install fonts-nanum`, or keep the
     `.md` and read it directly — don't ship a blank-glyph PDF.
   - Use `pypandoc` if available as alternative: `pypandoc.convert_file('final.md', 'pdf', outputfile='final.pdf')` (its LaTeX engine needs a CJK-aware mainfont, e.g. `-V mainfont='Apple SD Gothic Neo'`, for Korean too)
   - After the PDF is written and verified, remove any scratch build script you created (e.g. a temporary `cheatsheet/build_pdf.py`) so it isn't left in the user's committed course folder.

5. **Print to chat** (in $INTERFACE_LANG):
   - Filename of the cheatsheet
   - Word count / rough page estimate
   - Closing: "Check what materials your exam allows. If none, at least scan this one more time and commit it to memory."

## Density tips

- Formulas only, no sentences. Everything derivable in your head doesn't belong here.
- Use abbreviations the user will recognize (no first-time notation).
- Group by when-you'll-need-it, not by pedagogical order.
- The "traps" section is disproportionately valuable — it's tailored to the user's specific mistakes.
