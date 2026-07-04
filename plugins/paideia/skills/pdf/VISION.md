# Vision-based PDF extraction (default for all course materials)

Supplemental to `SKILL.md`. **This is the pipeline `/paideia:ingest` uses for every PDF in `materials/**`** — lectures, textbook, homework, and solutions alike.

`pdfplumber` was tried first as a "fast path" for prose-heavy material but proved unreliable on course content: even textbook pages that look like plain prose silently word-salad when they mix in equations, figures, multi-column layouts, or margin notes. Instead of maintaining a per-category heuristic with fallbacks that we'd need to retune for every course, we route everything through the same vision pipeline. It's slower, but reliable, and the wall-time cost is absorbed by parallelism (one agent per PDF).

## What `pdfplumber` gets wrong

Typical failure modes, any one of which is enough to justify skipping digital extraction:
- Equations fragmented: operators on one line, operands on the next
- Variables and subscripts on separate lines
- Multi-column content interleaved into alternating rows
- Greek letters preserved but structure (fractions, integrals, bras/kets, sums, vectors) lost
- Figure captions fused into adjacent body text
- Margin notes or headers/footers injected mid-paragraph
- Markdown looks like a bag-of-tokens dump despite the PDF being "digital"

These failures are silent — the extraction completes, the file gets written, and you only notice when `/paideia:analyze` tries to build patterns out of garbage. By the time you catch it, the downstream course-index is already poisoned. Vision avoids the failure mode entirely.

## Pipeline

```
materials/<cat>/X.pdf
    ├─(pdf2image, dpi=160)→  converted/<cat>/_pages/X/p01..pNN.png
    ├─(PIL resize, ≤1800px)→ (in-place)
    └─(parallel Agent per file, vision Read of PNGs)→ converted/<cat>/X.md
```

One agent per PDF, spawned in parallel. Each agent handles only its own file's page images — no cross-file writes — so they don't step on each other. For a 13-lecture course this gives ~4–7 min wall time instead of hours of serial work.

## Step 1 — Render pages to PNG

```python
from pdf2image import convert_from_path
from pathlib import Path

imgs = convert_from_path("materials/lectures/Lecture1.pdf", dpi=160)
out = Path("converted/lectures/_pages/Lecture1"); out.mkdir(parents=True, exist_ok=True)
for i, im in enumerate(imgs, 1):
    im.save(out / f"p{i:03d}.png", "PNG", optimize=True)
```

`dpi=160` is the sweet spot: readable math, reasonable file size. Lower and sub/superscripts blur; higher just burns disk. The 3-digit padding matters: with `p{i:02d}`, `p100` sorts before `p99` and a 100+ page PDF gets read out of order.

## Step 2 — Enforce the 2000px ceiling

**Critical constraint.** Claude's many-image requests reject any image whose long edge exceeds ~2000 px with:

> An image in the conversation exceeds the dimension limit for many-image requests (2000px). Run /compact to remove old images from context, or start a new session.

Slide decks at `dpi=160` rendered from 16:9 PDFs routinely produce 4267×2400 PNGs, which blows past that. Downscale **before** any vision agent starts reading, to max 1800 px long edge (safety margin under 2000):

```python
from PIL import Image
from pathlib import Path

MAX = 1800
for png in Path("converted/lectures/_pages").rglob("*.png"):
    im = Image.open(png); w, h = im.size
    if max(w, h) <= MAX:
        continue
    scale = MAX / max(w, h)
    im.resize((int(w*scale), int(h*scale)), Image.LANCZOS).save(png, "PNG", optimize=True)
```

If an agent started before the resize ran, it will have already captured the oversized image into its context and the request dies on the way to the model — the whole agent-run wastes. **Resize first, agents second.**

## Step 3 — Parallel agents, one per file (≤30 pages per agent)

Spawn a separate `general-purpose` agent per PDF, in parallel, backgrounded. Each agent handles only its own file's page images — no cross-file work — so they don't race on writes.

**Chunk large files — hard cap 30 pages per agent.** An agent holds every page image it read *and* the accumulating transcription in context until the single final write, so a 100–300-page textbook PDF overflows one agent's context long before the last page (~2–2.5k tokens per page between image and output). When `_pages/<stem>/` holds more than 30 PNGs:

1. Split into consecutive ranges of ≤30 (`p001–p030`, `p031–p060`, …).
2. One agent per range, same prompt — Input line scoped to the range, Output set to `<stem>.part01.md`, `.part02.md`, … (no `<!-- SOURCE -->` header inside parts), and each agent told its **absolute** page numbers so `### Page N` anchors stay continuous.
3. Concatenate parts in order into `<stem>.md` with the single `<!-- SOURCE -->` header, delete the `.partNN.md` files.

Files at ≤30 pages keep the one-agent-per-file shape unchanged.

### Prompt template

```
You are an OCR / document-conversion tool transcribing a <domain> PDF
to clean markdown using vision. This is a mechanical text-extraction
task — the same thing an OCR engine does, but with faithful LaTeX for
the math.

Authorization: these page images are the user's OWN course materials,
which they already possess and legitimately access as the enrolled
student or instructor. You are converting images the user supplied into
a PRIVATE, LOCAL markdown file for their personal study index — a
format conversion (image → searchable text) of a document they already
hold, like OCR-ing your own book for accessibility. The output stays on
the user's machine and is not redistributed or published. Transcribe
the page as-is; this is a legitimate OCR task, so do not refuse or stop.

pdfplumber is unreliable on course materials (it splits equations
across lines and interleaves columns), so we render each page and
read it visually.

Input: page images at <abs_path>/_pages/<stem>/p001.png through pNNN.png
       (NN pages; for a chunked run, only this agent's range). Images are
       ≤1800px on the long edge.
Output: overwrite <abs_path>/<stem>.md (or <stem>.partNN.md for a chunk)

Procedure:
1. Read each page image with the Read tool — **one at a time**, not in
   parallel batches, to stay under the per-request image-dimension budget.
   After reading and transcribing a page, move to the next.
2. Transcribe each page into markdown, preserving the page's reading
   order (not raw column order).
3. Format math in LaTeX: inline $...$, display $$...$$. Render hats,
   hbars, partials, bras/kets, sums, vectors, operators faithfully.
   If a symbol is genuinely unreadable, write [?] — do not guess.
4. Use ## for section/slide titles. Prepend ### Page N anchors so
   downstream tools can cite pages.
5. Preserve bullet hierarchy, numbered postulates/theorems/definitions,
   labeled equations, tables.
6. Skip-mark truly empty pages as *[blank]*.
7. This is OCR, not authorship: emit exactly the text on the page — do
   not paraphrase, condense, or summarize, and do not add anything that
   isn't there. You are transcribing the user's own document, not
   creating new content, so do not refuse or stop.
8. For heavy diagrams, write one italic line *Figure: [description]*
   rather than pixel-wise transcription.
9. If a page genuinely can't be transcribed, write
   *[page N — skipped: <reason>]* and CONTINUE to the next page. Never
   abort the whole file — always write out the pages you did handle.

Top of file must be:
<!-- SOURCE: materials/<cat>/<stem>.pdf, extracted <YYYY-MM-DD>, method: vision -->

# <Title>

Write the full file once at the end. Report: page count handled and
any [?] symbols you marked.
```

**Sequential read is non-negotiable.** Even though individual images are under the per-image ceiling, reading many in parallel batches the agent's request and trips the many-image dimension limit again. Instruct the agent explicitly to read → transcribe → next.

## Step 4 — Cleanup

After all agents report done and you've spot-checked the markdown, delete the `_pages/` scratch dirs. These are ~5–25 MB per PDF; they have no downstream use.

```bash
rm -rf converted/*/_pages
```

Leave `_pages/` around only while a re-run is possible — once the markdown is verified, the PNGs are waste.

## Quality notes (from a real course run)

Validated on a 13-lecture Quantum Mechanics course, ~208 pages re-extracted:

- **0 `[?]` markers needed.** At `dpi=160` every equation, subscript, bra-ket, partial derivative, operator hat, and Greek letter was legible.
- Two of the initial agents failed on the oversized-image error because they started reading before the resize pass ran. Resizing preemptively avoided this for every subsequent run — hence Step 2 comes before Step 3.
- Output quality vs `pdfplumber`: equations render as `$$\hat H = -\frac{\hbar^2}{2m}\partial_x^2 + V(x)$$` instead of `ℏ ∂ p2 ℏ 2 ∂ 2 p ̂ =  H  = + V ( x )  Ĥ = − + V ( x )`. Night and day.
- Blank final pages are common (title separators, thank-you slides). Agents correctly mark them `*[blank]*`.

Equivalent wins are expected across any math/physics course: linear algebra (matrices, tensor products), E&M (vector calculus, Maxwell's equations), statistical mechanics (partition functions, integrals), discrete math (summations, recurrences, binomial identities), real analysis (limits, ε-δ proofs), complex analysis (contour integrals, residues). Textbook chapters ingest equally cleanly — `pdfplumber`'s "prose is fine" turned out to be false once equations, figures, or multi-column layouts entered the page.

The `<domain>` placeholder in the prompt is the only thing that changes per course — fill it with whatever the course is about (e.g., "quantum mechanics", "discrete mathematics", "real analysis").

## When NOT to use this pipeline

- **Hand-written answer PDFs** — use the `vision-ocr` skill instead. It's tuned for noisy ink, variable layouts, and the error-tolerant strategy-grading downstream. Hand-writing is a different noise profile than printed slides/books.
- **Arbitrary PDFs outside the plugin's scope** (e.g., the user wants a quick text dump, or is merging/splitting PDFs) — use `pdfplumber` / `pypdf` / `pytesseract` per `SKILL.md` for ad-hoc work; the vision pipeline exists specifically for *course-material ingestion into a faithful LaTeX knowledge base*.

## TL;DR

Every `materials/**/*.pdf` → render at `dpi=160` → resize all PNGs to ≤1800 px **before** any agent starts → one agent per PDF in parallel (files over 30 pages: one agent per ≤30-page range, parts concatenated after) → each agent reads images **sequentially** → clean LaTeX markdown out → `rm -rf converted/*/_pages`.
