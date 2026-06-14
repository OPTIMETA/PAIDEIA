---
description: "Create a 15-minute synthetic, attempt-first tutorial harness. Writes tutorial/tutorial.md, attempt.md, rubric.md, verify.md, plus a tiny local fixture so users can test PAIDEIA without real course or student data."
argument-hint: "[smoke]"
---

You are creating PAIDEIA's hands-on tutorial harness in the user's current working directory. The goal is not to show a polished answer first. The goal is to make the user produce observable attempt/error evidence, then verify that attempt against a tiny rubric.

## Output language

Read `INTERFACE_LANG` from `.course-meta` if present (default `en`). All user-facing prose in chat should use that language. Keep file paths, command names, YAML keys, and LaTeX in English.

## Safety and scope

- Use **synthetic toy material only**. Do not import, invent, or imply real student records.
- Do not call external services, OCR, network, telemetry, or model APIs.
- Do not overwrite an existing `tutorial/attempt.md` that has user work in it. If it exists and is non-empty, ask before replacing it.
- PAIDEIA does not claim to inspect model internals, hidden activations, or a student's cognition. The tutorial is an artifact-grounded workflow check.

## What to create

Create a local tutorial sandbox under `tutorial/` and tiny source material under `materials/` / `converted/`:

```text
tutorial/tutorial.md       # what to do in the next 10 minutes
tutorial/attempt.md        # the user's first attempt; starts as a worksheet
tutorial/rubric.md         # small verification rubric
tutorial/verify.md         # pending until attempt.md has real work
materials/lectures/tutorial-generating-functions.md
materials/homework/tutorial-hw.md
materials/solutions/tutorial-hw-sol.md
converted/lectures/tutorial-generating-functions.md
converted/homework/tutorial-hw.md
converted/solutions/tutorial-hw-sol.md
errors/log.md              # source-idempotent ledger seed if missing
course-index/context-graph.md
reviews/actions.md
```

The synthetic concept is an index shift in generating functions. It is deliberately small enough to smoke-test in 15 minutes.

## Execution

Run this from the course folder with the Bash tool:

```bash
set -euo pipefail

mkdir -p tutorial materials/{lectures,homework,solutions} converted/{lectures,homework,solutions} \
  course-index errors reviews

if [ -s tutorial/attempt.md ] && ! grep -q "TODO: write your attempt here" tutorial/attempt.md; then
  echo "tutorial/attempt.md already contains work. Move or rename it before re-running /paideia:tutorial."
  exit 1
fi

cat > materials/lectures/tutorial-generating-functions.md <<'EOF'
# Synthetic lecture: index shifts in generating functions

This file is fabricated for PAIDEIA's tutorial smoke test. It contains no real student data.

A generating function packages a sequence $(a_n)_{n\ge 0}$ as

$$A(x)=\sum_{n\ge 0} a_n x^n.$$

The common move is an index shift:

$$\sum_{n\ge 1} a_{n-1}x^n = x\sum_{m\ge 0}a_mx^m = xA(x).$$

The error to watch for: dropping the leading factor of $x$ when changing from $n$ to $m=n-1$.
EOF

cat > materials/homework/tutorial-hw.md <<'EOF'
# Synthetic HW: index shift smoke test

This file is fabricated for PAIDEIA's tutorial smoke test. It contains no real student data.

## Problem T1

Let $(a_n)$ satisfy $a_0=1$ and $a_n = 2a_{n-1}$ for $n\ge 1$. Let

$$A(x)=\sum_{n\ge 0}a_nx^n.$$

Use the recurrence to derive a closed form for $A(x)$.
EOF

cat > materials/solutions/tutorial-hw-sol.md <<'EOF'
# Synthetic solution key: index shift smoke test

This file is fabricated for PAIDEIA's tutorial smoke test.

## Problem T1

Start from

$$A(x)=a_0+\sum_{n\ge1}a_nx^n=1+\sum_{n\ge1}2a_{n-1}x^n.$$

Shift $m=n-1$:

$$\sum_{n\ge1}2a_{n-1}x^n=2x\sum_{m\ge0}a_mx^m=2xA(x).$$

So

$$A(x)=1+2xA(x),\qquad A(x)=\frac{1}{1-2x}.$$

Rubric-critical evidence: the shifted term must become $2xA(x)$, not $2A(x)$.
EOF

cp materials/lectures/tutorial-generating-functions.md converted/lectures/tutorial-generating-functions.md
cp materials/homework/tutorial-hw.md converted/homework/tutorial-hw.md
cp materials/solutions/tutorial-hw-sol.md converted/solutions/tutorial-hw-sol.md

cat > tutorial/tutorial.md <<'EOF'
# PAIDEIA 15-minute hands-on tutorial harness

This is a synthetic smoke test. It uses generated toy files only — no real course material, no real student data, no OCR, no network.

## Goal

Check the PAIDEIA loop end-to-end:

1. Read a tiny source concept.
2. Write your own attempt before seeing the verification.
3. Verify the attempt against a small rubric.
4. Record the next review action from observable attempt/error evidence.

## Source files

- Lecture: `converted/lectures/tutorial-generating-functions.md`
- Problem: `converted/homework/tutorial-hw.md`
- Reference solution, hidden until after your attempt: `converted/solutions/tutorial-hw-sol.md`

## Instructions — 10 minutes

1. Read the lecture and problem files.
2. Open `tutorial/attempt.md`.
3. Fill in the attempt section without opening `converted/solutions/tutorial-hw-sol.md` first.
4. In your attempt, explicitly write the shifted sum after substituting `m=n-1`.
5. Then ask PAIDEIA to verify the attempt using `tutorial/rubric.md`.

## Success condition

The tutorial is useful only if `attempt.md` contains observable evidence: the exact shifted expression, the closed form, and any confusion. If `verify.md` can only say “looks good” without quoting the attempt, the harness failed.
EOF

cat > tutorial/attempt.md <<'EOF'
# Tutorial attempt — write here first

<!-- TODO: write your attempt here before opening the reference solution. -->

## Problem T1

Given $a_0=1$, $a_n=2a_{n-1}$, and $A(x)=\sum_{n\ge0}a_nx^n$:

1. Write $A(x)$ split into the $a_0$ term and the $n\ge1$ sum.
2. Substitute the recurrence.
3. Shift the index with $m=n-1$.
4. Solve for $A(x)$.

## My attempt

- Split:
- Recurrence substitution:
- Index shift evidence:
- Closed form:
- Confidence / confusion:
EOF

cat > tutorial/rubric.md <<'EOF'
# Tutorial verification rubric

Verify only after `tutorial/attempt.md` contains a real attempt. Do not reveal the reference solution before the attempt.

## Required evidence

| Criterion | Pass condition | Common miss |
|---|---|---|
| Attempt exists | `tutorial/attempt.md` has non-placeholder work in `My attempt` | blank worksheet |
| Split | Includes `A(x)=1+...` or equivalent | omits $a_0$ |
| Recurrence | Replaces $a_n$ by $2a_{n-1}$ for $n\ge1$ | applies recurrence at $n=0$ |
| Index shift | Shows the shifted term as `2xA(x)` or equivalent | writes `2A(x)` and loses the factor $x$ |
| Closed form | Solves to `1/(1-2x)` | algebra stops before solving |
| Evidence quote | `verify.md` quotes the user's attempt for every pass/fail | verdict without source evidence |

## Review action rule

- If the index shift fails, add/open a review action for `/paideia:derive index-shift` or another index-shift drill.
- If the attempt passes, next action is `/paideia:quiz tutorial-index-shift 1` or starting the real course bootstrap.
EOF

cat > tutorial/verify.md <<'EOF'
# Tutorial verification — pending

Status: PENDING_ATTEMPT

`tutorial/attempt.md` has been seeded as a worksheet. Fill it in first, then verify against `tutorial/rubric.md`.

When verification runs, this file should include:

- pass/fail/partial for each rubric row
- quote from `tutorial/attempt.md` as evidence
- any error ledger entry to add
- next review action
EOF

if [ ! -f errors/log.md ]; then
cat > errors/log.md <<'EOF'
# Error ledger

<!-- Source-idempotent YAML entries. Keep the latest grading per source. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts> | tutorial/attempt.md>
  date: <ISO8601>
-->
EOF
fi

cat > course-index/context-graph.md <<'EOF'
# Course Context Graph — tutorial seed

PAIDEIA's graph artifacts are source-grounded views over course files, attempts, errors, and review actions. They do not visualize model internal thoughts or hidden activations.

## Nodes

| Node ID | Type | Label | Source |
|---|---|---|---|
| tut-sec-index-shift | concept | Generating-function index shift | converted/lectures/tutorial-generating-functions.md |
| tut-problem-t1 | problem | Synthetic HW Problem T1 | converted/homework/tutorial-hw.md |
| tut-attempt-t1 | attempt | User attempt for Problem T1 | tutorial/attempt.md |
| tut-rubric-t1 | rubric | Verification rubric for Problem T1 | tutorial/rubric.md |
| tut-review-index-shift | review_action | Redo index-shift drill if factor x is missing | reviews/actions.md |

## Edges

| From | Relation | To | Evidence |
|---|---|---|---|
| tut-problem-t1 | tests | tut-sec-index-shift | converted/homework/tutorial-hw.md |
| tut-attempt-t1 | verified_by | tut-rubric-t1 | tutorial/rubric.md |
| tut-rubric-t1 | may_trigger | tut-review-index-shift | tutorial/rubric.md |
EOF

cat > reviews/actions.md <<'EOF'
# Review actions

Review actions are local, editable study artifacts derived from observable attempt/error evidence. They are not telemetry and not a student profile.

```yaml
- action_id: tutorial-index-shift
  triggered_by: tutorial/attempt.md
  command: "/paideia:derive index-shift"
  reason: "Use if the attempt drops the factor x during the m=n-1 shift."
  status: open-if-needed
```
EOF

printf 'created tutorial harness:\n  tutorial/tutorial.md\n  tutorial/attempt.md\n  tutorial/rubric.md\n  tutorial/verify.md\n  course-index/context-graph.md\n  reviews/actions.md\n'
```

## After creating the files

Print a compact next-step block in `INTERFACE_LANG`:

- Open `tutorial/tutorial.md`.
- Fill `tutorial/attempt.md` before reading `converted/solutions/tutorial-hw-sol.md`.
- Then ask PAIDEIA to verify the attempt against `tutorial/rubric.md`.

If the user asks you to verify immediately and `attempt.md` is still blank, refuse to pass the smoke test and tell them the harness is waiting for a real attempt.
