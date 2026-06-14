---
description: "Create and verify a 15-minute synthetic, attempt-first tutorial harness. Uses the stdlib-only tutorial_harness.py CLI to seed tutorial files, enforce attempt-before-answer verification, emit context-graph.json, and update errors/review actions from observable attempt evidence."
argument-hint: "[smoke|verify|graph-check|guardrail-check]"
---

You are operating PAIDEIA's hands-on tutorial harness in the user's current working directory. The goal is not to show a polished answer first. The goal is to make the user produce observable attempt/error evidence, then verify that attempt against a tiny rubric.

## Output language

Read `INTERFACE_LANG` from `.course-meta` if present (default `en`). All user-facing prose in chat should use that language. Keep file paths, command names, JSON/YAML keys, and LaTeX in English.

## Safety and scope

- Use **synthetic toy material only**. Do not import, invent, or imply real student records.
- Do not call external services, OCR, network, telemetry, or model APIs.
- Use the repository script `plugins/paideia/scripts/tutorial_harness.py`; it is stdlib-only and local-first.
- Do not overwrite an existing `tutorial/attempt.md` that has user work in it. The harness refuses to overwrite non-placeholder attempts.
- PAIDEIA graph artifacts are source-grounded views over course files, attempts, errors, and review actions. They do not visualize model internal thoughts, hidden activations, or a student's cognition.

## What the harness creates

```text
tutorial/tutorial.md       # what to do in the next 10 minutes
tutorial/attempt.md        # the user's first attempt; starts as a worksheet
tutorial/rubric.md         # small verification rubric
tutorial/verify.md         # PENDING_ATTEMPT until attempt.md has real work
materials/lectures/tutorial-generating-functions.md
materials/homework/tutorial-hw.md
materials/solutions/tutorial-hw-sol.md
converted/lectures/tutorial-generating-functions.md
converted/homework/tutorial-hw.md
converted/solutions/tutorial-hw-sol.md
errors/log.md              # source-idempotent ledger seed if missing
course-index/context-graph.json
reviews/actions.md
```

The synthetic concept is an index shift in generating functions. It is deliberately small enough to smoke-test in 15 minutes.

## Commands

Run from the course folder:

```bash
python3 plugins/paideia/scripts/tutorial_harness.py init --root .
```

After the user fills `tutorial/attempt.md`, verify:

```bash
python3 plugins/paideia/scripts/tutorial_harness.py verify --root . --json
```

The verifier has an explicit attempt state machine:

- `PENDING_ATTEMPT`: tutorial was seeded and verification has not run yet.
- `ATTEMPT_READY`: internal readiness state when `attempt.md` has non-placeholder work.
- `CANNOT_VERIFY`: `attempt.md` is blank/placeholder-only; no answer is leaked.
- `FAIL`: real attempt exists but no rubric criteria pass.
- `PARTIAL`: real attempt exists and some criteria pass.
- `PASS`: all tutorial rubric criteria pass.

Additional machine checks:

```bash
python3 plugins/paideia/scripts/tutorial_harness.py graph-check --root .
python3 plugins/paideia/scripts/tutorial_harness.py guardrail-check --root .
```

## Verification behavior

`verify` reads `tutorial/attempt.md`, writes `tutorial/verify.md`, and updates `course-index/context-graph.json`.

Rubric scoring is evidence-first:

- split evidence for `A(x)=1+...`
- recurrence substitution evidence for `2a_{n-1}`
- index-shift evidence for `2xA(x)` rather than `2A(x)`
- closed-form evidence for `1/(1-2x)`
- every pass/fail row in `verify.md` includes a quote from `tutorial/attempt.md`

If the attempt is blank or placeholder-only, the harness returns `CANNOT_VERIFY` and does not reveal the reference answer in `verify.md`.

If verification is `FAIL` or `PARTIAL`, the harness updates `errors/log.md` idempotently with a canonical source entry for `tutorial/attempt.md`. If the index shift fails, it also opens a `ReviewAction` candidate in `reviews/actions.md` for `/paideia:derive index-shift`.

## Graph contract

`course-index/context-graph.json` must be machine-checkable by `graph-check` and include nodes for:

- `course`
- `concept`
- `problem`
- `attempt`
- `rubric`
- `error`
- `review_action`

Every node and edge must include `source_path` and `evidence_quote`. These are source-grounded artifact references, not a model-thought or cognition graph.

## After creating the files

Print a compact next-step block in `INTERFACE_LANG`:

- Open `tutorial/tutorial.md`.
- Fill `tutorial/attempt.md` before reading `converted/solutions/tutorial-hw-sol.md`.
- Then run `python3 plugins/paideia/scripts/tutorial_harness.py verify --root . --json`.

If the user asks you to verify immediately and `attempt.md` is still blank, report `CANNOT_VERIFY` and tell them the harness is waiting for a real attempt.
