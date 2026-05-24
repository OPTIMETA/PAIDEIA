---
name: vision-ocr
description: Use whenever a hand-written or scanned answer PDF needs transcription to markdown for /grade. Three tiers — Claude native vision (default, no extra install), local Qwen3-VL 8B via ollama (opt-in privacy mode), pytesseract fallback. The engine is selected via `OCR_ENGINE` in `.course-meta` (written by /paideia:init-course) and can be overridden per-call with `/paideia:grade --ocr=<engine>`.
---

# Vision-OCR

## When to load

- `/grade` needs to convert `answers/*.pdf` → `answers/converted/*.md`
- Any hand-written / scanned document whose previous tesseract pass was garbled
- `answer-processing` skill's step-2 conversion

## Engine choice

`.course-meta` holds a single line `OCR_ENGINE: <engine>` written by `/paideia:init-course`. The grade command reads it and dispatches. Users can override per-call with `/paideia:grade --ocr=<engine> [path]`.

| Engine | Default? | How it runs | When to pick it |
|---|---|---|---|
| `claude` | **Yes** | `pdftoppm` → Claude reads each PNG via the Read tool → synthesizes markdown inline. No external model. No subprocess. | The out-of-the-box path. Nothing to install. Highest fidelity on messy handwriting because Claude vision handles mixed-script (English/Korean) prose with LaTeX well. |
| `ollama` | opt-in | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py --engine=ollama --lang=$INTERFACE_LANG <pdf> <md>` — local Qwen3-VL 8B, with an automatic tesseract fall-back if ollama is unreachable. | You want the PDF to never leave the machine *and* you don't want to burn Claude tokens on OCR. Requires one-time `ollama pull qwen3-vl:8b` (~6 GB). |
| `tesseract` | opt-in | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py --engine=tesseract --lang=$INTERFACE_LANG <pdf> <md>` — pytesseract `eng` (en) or `eng+kor` (ko). | Zero cloud + no GPU/VRAM budget. Lowest fidelity on handwriting; fine for typed scans. |

All three emit `answers/converted/<stem>.md` with a `<!-- SOURCE: ... -->` / `<!-- TIER: ... -->` header comment that lets `/grade` caveat the confidence.

## Tier 0 — Claude native vision (default)

**Pipeline (driven by the `/grade` command, not this script):**

```
answers/<stem>.pdf
  ↓ pdftoppm -r 200 -png <pdf> <tmpdir>/page   # rasterize to PNG per page
  ↓ Claude reads <tmpdir>/page-1.png, page-2.png, ... via the Read tool
  ↓ Claude synthesizes clean MD following the prompt contract below
answers/converted/<stem>.md
   └── header:  <!-- SOURCE: <stem>.pdf, claude-vision (native), N pages -->
```

The grade command handles the orchestration — rasterize, Read each page, synthesize into one markdown file in a single pass. No standalone driver script is required.

## Tier 1 — Ollama Qwen3-VL 8B (opt-in)

```
answers/<stem>.pdf
  ↓ pdf2image @ 300dpi
  ↓ resize to ≤1200px wide (VLMs dislike huge inputs)
  ↓ base64 JPEG per page
  ↓ [Tier 1a] ollama qwen3-vl:8b
  ↓    (on timeout / ollama down)
  ↓ [Tier 1b] pytesseract (eng or eng+kor, from --lang)  ← auto-fallback inside the same script
answers/converted/<stem>.md
   └── header:  <!-- SOURCE: <stem>.pdf, qwen3-vl:8b @ 300dpi, N pages -->
                <!-- TIER: tesseract fallback -->  (only when 1a bombed)
```

**Entrypoint:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py" --engine=ollama <input.pdf> <output.md>
```

`${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py` is the single source of truth. It:
1. Warms up the VLM with a 1-token `/api/generate` so the first real page isn't stalled by model load.
2. Sends each page as a JPEG-encoded base64 image with a language-aware, LaTeX-first prompt (prose-language rule selected by `INTERFACE_LANG`).
3. Sets `keep_alive: "15m"` so the model stays in memory across pages within a session.
4. On any exception (timeout, connection refused) falls back to pytesseract and marks the file.

## Tier 2 — Tesseract explicit

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/vision_ocr.py" --engine=tesseract <input.pdf> <output.md>
```

Skips ollama entirely. Header: `<!-- TIER: tesseract (explicit) -->`.

## Prompt contract (must preserve across Tier 0 + Tier 1)

Whether synthesized by Claude inline (Tier 0) or by Qwen3-VL through this script (Tier 1), the transcription prompt must:

- Keep prose in its original language (English, Korean, etc.) — do not translate
- Emit math as `$...$` / `$$...$$`
- Preserve problem numbering (P1, (1), (a), ...)
- NOT grade or interpret — just transcribe
- Write `[?]` for ambiguous glyphs instead of guessing
- Skip crossed-out work
- Return markdown only, no `<think>`, no commentary

If you edit the prompt, keep these six clauses — they're what separates useful transcription from hallucination.

## Dependencies

**All engines need:**
- `poppler` binaries (`pdftoppm`, used by pdf2image). `brew install poppler` / `apt-get install poppler-utils`.

**Tier 0 (claude):** nothing beyond Claude Code itself.

**Tier 1 (ollama) extras:**
- `ollama` CLI + model `qwen3-vl:8b` (~6.1 GB). `brew install ollama && ollama serve & && ollama pull qwen3-vl:8b`.
- Python: `pdf2image`, `pytesseract`, `pillow`.

**Tier 2 (tesseract) extras:**
- `tesseract` + `tesseract-lang` (or `tesseract-ocr-kor` on Debian). Python: `pdf2image`, `pytesseract`, `pillow`.

## Performance notes

- **Tier 0 (claude):** depends on Claude's per-image processing; typically a few seconds per page with no model-load stall.
- **Tier 1 (ollama) on Mac M-series:** first page ~2–5 min (model load + decode); subsequent pages ~20–60 s.
- A 2-page hand-written answer typically takes 3–7 min total on Tier 1, a few seconds on Tier 0, and <10 s on Tier 2 (but fidelity falls off a cliff).
- 300dpi input is downscaled to 1200px before encoding — keeps the base64 payload under ~500 KB on Tier 1.

## Failure modes + fixes

| Symptom | Cause | Fix |
|---|---|---|
| Tier 0 produces garbage | Scan too dim / skewed / low-res | Re-scan at 300dpi with the page flat, re-run |
| Tier 1 `timed out` on page 1 | first-load stall on cold ollama | re-run; warmup + `keep_alive` should help on 2nd try |
| Tier 1 empty response / `<think>...` leaks | prompt contract violated | re-check prompt; add "Return ONLY markdown, no <think>" |
| Tier 1 base64 error / 413 | image too large | drop `MAX_IMG_WIDTH` from 1200 → 1000 |
| Tier 1 ollama 404 | `qwen3-vl:8b` not pulled | `ollama pull qwen3-vl:8b` |
| Tier 1 tesseract fallback kept firing | ollama server not running | `ollama serve &` |

## Anti-patterns

- ❌ Don't pass base64 via `curl -d <arg>` — ARG_MAX overflow. Use stdlib `urllib` with POST body.
- ❌ Don't send PNG to Qwen3-VL — JPEG q=90 is 5–10× smaller with no impact on VLM accuracy.
- ❌ Don't ask any tier to grade or solve. That's `/grade`'s job; OCR must stay pure transcription.
- ❌ Don't trust Tier 1b (silent tesseract fallback) without reading the header — the file comment tells `/grade` to caveat its verdict.

## Integration

- Called by `/grade` via `answer-processing` skill step 2
- Called by `/ingest` (future) for hand-written lecture notes, if any appear in `materials/`
- Writes to `answers/converted/` only; does not modify originals in `answers/`
