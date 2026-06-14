# paideia (plugin)

Exam-formation plugin for math / physics / engineering courses. Local-first by construction — no SaaS, no cloud upload of your materials, no subscription.

PAIDEIA graph/trace artifacts are source-grounded views over course files, attempts, error-ledger entries, and review actions. They do not visualize model internal thoughts or hidden activations.

See the repo root `README.md` for the full manifesto, install steps, and workflow walk-through.

## Quick reference

```
tutorial ─▶ ingest ──▶ analyze ──▶ drill ──▶ grade ──▶ weakmap ──▶ cheatsheet
   ▲                                                                  │
   └──────────────────── attempt/error feedback loop ─────────────────┘
```

| Command | Purpose |
|---------|---------|
| `/paideia:init-course` | Bootstrap a fresh course folder (deps check, dir skeleton, metadata prompt, background `ollama pull`) |
| `/paideia:tutorial [smoke]` | Create a 15-minute synthetic, attempt-first tutorial harness with `tutorial/{tutorial,attempt,rubric,verify}.md` |
| `/paideia:ingest` | Every PDF → markdown via the vision pipeline (parallel agents, LaTeX-faithful) |
| `/paideia:analyze` | Build `course-index/{summary,patterns,coverage}.md` |
| `/paideia:hwmap hot` | Surface 🔥🔥 Exam-primary sections ranked by HW density |
| `/paideia:pattern <§\|Pk\|keyword>` | Show pattern cards |
| `/paideia:derive <target>` | Clean reference derivation to `derivations/` |
| `/paideia:quiz <topic\|§\|weakmap> [N]` | N practice problems, answers hidden |
| `/paideia:blind <problem-id>` | Strategy-check on a known problem |
| `/paideia:twin <problem-id>` | Variant — same pattern, new surface |
| `/paideia:chain <N>` | Multi-pattern integration problem |
| `/paideia:mock <minutes>` | Full mock exam, HW-density weighted |
| `/paideia:grade [path]` | OCR answer PDF, strategy-grade, update the source-idempotent error ledger |
| `/paideia:weakmap [concept]` | Priority-ranked weakness report |
| `/paideia:cheatsheet [--pdf]` | Error-driven one-pager |

## Dependencies

- `ollama` + `qwen3-vl:8b` (Tier-1 OCR — runs locally, ~6 GB model)
- `tesseract-ocr` + `poppler-utils` (Tier-2 OCR fallback)
- Python: `pypdf pdfplumber pytesseract pdf2image pillow reportlab`

All checked and offered for install by `/paideia:init-course`.
