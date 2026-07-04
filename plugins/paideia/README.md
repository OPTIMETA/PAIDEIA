# paideia (plugin)

Exam-formation plugin for math / physics / engineering courses. Local-first by construction: every artifact it builds — patterns, coverage, error log, weakmaps, cheatsheets — lives on your disk as plain markdown, in your own git history, with no SaaS database and nothing to export. Processing follows your session: the default OCR/ingest path reads page images with Claude vision through the Claude Code session you're already in; an opt-in local Qwen3-VL engine exists for when page images must never leave the machine.

See the repo root `README.md` for the full manifesto, install steps, and workflow walk-through.

## Quick reference

```
ingest ──▶ analyze ──▶ drill ──▶ grade ──▶ weakmap ──▶ cheatsheet
   ▲                                                        │
   └────────────────── feedback loop ───────────────────────┘
```

| Command | Purpose |
|---------|---------|
| `/paideia:init-course` | Bootstrap a fresh course folder (deps check, dir skeleton, metadata + language + OCR-engine prompts) |
| `/paideia:doctor [--fix]` | Diagnose install + workspace; `--fix` repairs the permission-free issues (course mode only) |
| `/paideia:ingest [--force]` | Every PDF → markdown via the vision pipeline (parallel agents, ≤30 pages each, LaTeX-faithful) |
| `/paideia:analyze [hints]` | Build `course-index/{summary,patterns,coverage}.md` |
| `/paideia:hwmap hot` | Surface 🔥🔥 Exam-primary sections ranked by HW density |
| `/paideia:pattern <§\|Pk\|keyword>` | Show pattern cards |
| `/paideia:derive <target>` | Clean reference derivation to `derivations/` |
| `/paideia:quiz <topic\|§\|weakmap> [N]` | N practice problems, answers hidden |
| `/paideia:blind <problem-id>` | Strategy-check on a known problem |
| `/paideia:twin <problem-id>` | Variant — same pattern, new surface |
| `/paideia:chain <N>` | Multi-pattern integration problem |
| `/paideia:mock <minutes>` | Full mock exam, HW-density weighted |
| `/paideia:grade [--ocr=<engine>] [path]` | OCR answer PDF via the engine from `.course-meta` — Claude vision (default) / local Qwen3-VL / tesseract — then strategy-grade |
| `/paideia:weakmap [concept]` | Priority-ranked weakness report |
| `/paideia:cheatsheet [--pdf]` | Error-driven one-pager |
| `/paideia:alt [paste]` | Import an Exam Radar (Alt) export — lecture-emphasis signal beside HW density |

## Dependencies

Severity is graded by `/paideia:doctor` against the course's `OCR_ENGINE`:

- **Always required:** `poppler-utils` (every engine renders pages with `pdftoppm`); Python `pdf2image` + `pillow`.
- **`--ocr=claude` (default):** nothing else — Claude vision runs inside your existing Claude Code session.
- **`--ocr=ollama` (opt-in privacy mode):** `ollama` + `qwen3-vl:8b` (~6 GB, fully local) + `tesseract` and Python `pytesseract` for its automatic fallback tier.
- **`--ocr=tesseract`:** `tesseract` (+ `kor` langdata for Korean) and Python `pytesseract`.
- **Optional:** Python `reportlab` (only `/paideia:cheatsheet --pdf`), `pypdf`/`pdfplumber` (ad-hoc PDF ops; the ingest pipeline itself doesn't use them).

All checked — and the safe ones offered for install — by `/paideia:init-course`; re-check any time with `/paideia:doctor`.
