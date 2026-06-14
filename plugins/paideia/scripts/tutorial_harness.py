#!/usr/bin/env python3
"""PAIDEIA tutorial harness.

Stdlib-only CLI for seeding and verifying the synthetic attempt-first tutorial.
It intentionally works over local markdown/JSON artifacts only: no network, no model
calls, no telemetry, and no claims about hidden model or student cognition.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class AttemptState(str, Enum):
    PENDING_ATTEMPT = "PENDING_ATTEMPT"
    ATTEMPT_READY = "ATTEMPT_READY"
    CANNOT_VERIFY = "CANNOT_VERIFY"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    PASS = "PASS"


ROOT_FILES = {
    "materials/lectures/tutorial-generating-functions.md": """# Synthetic lecture: index shifts in generating functions

This file is fabricated for PAIDEIA's tutorial smoke test. It contains no real student data.

A generating function packages a sequence $(a_n)_{n\\ge 0}$ as

$$A(x)=\\sum_{n\\ge 0} a_n x^n.$$

The common move is an index shift:

$$\\sum_{n\\ge 1} a_{n-1}x^n = x\\sum_{m\\ge 0}a_mx^m = xA(x).$$

The error to watch for: dropping the leading factor of $x$ when changing from $n$ to $m=n-1$.
""",
    "materials/homework/tutorial-hw.md": """# Synthetic HW: index shift smoke test

This file is fabricated for PAIDEIA's tutorial smoke test. It contains no real student data.

## Problem T1

Let $(a_n)$ satisfy $a_0=1$ and $a_n = 2a_{n-1}$ for $n\\ge 1$. Let

$$A(x)=\\sum_{n\\ge 0}a_nx^n.$$

Use the recurrence to derive a closed form for $A(x)$.
""",
    "materials/solutions/tutorial-hw-sol.md": """# Synthetic solution key: index shift smoke test

This file is fabricated for PAIDEIA's tutorial smoke test.

## Problem T1

Start from

$$A(x)=a_0+\\sum_{n\\ge1}a_nx^n=1+\\sum_{n\\ge1}2a_{n-1}x^n.$$

Shift $m=n-1$:

$$\\sum_{n\\ge1}2a_{n-1}x^n=2x\\sum_{m\\ge0}a_mx^m=2xA(x).$$

So

$$A(x)=1+2xA(x),\\qquad A(x)=\\frac{1}{1-2x}.$$

Rubric-critical evidence: the shifted term must become $2xA(x)$, not $2A(x)$.
""",
    "tutorial/tutorial.md": """# PAIDEIA 15-minute hands-on tutorial harness

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
5. Then run `python3 plugins/paideia/scripts/tutorial_harness.py verify --root .`.

## Success condition

The tutorial is useful only if `attempt.md` contains observable evidence: the exact shifted expression, the closed form, and any confusion. If `verify.md` can only say “looks good” without quoting the attempt, the harness failed.
""",
    "tutorial/attempt.md": """# Tutorial attempt — write here first

<!-- TODO: write your attempt here before opening the reference solution. -->

## Problem T1

Given $a_0=1$, $a_n=2a_{n-1}$, and $A(x)=\\sum_{n\\ge0}a_nx^n$:

1. Write $A(x)$ split into the $a_0$ term and the $n\\ge1$ sum.
2. Substitute the recurrence.
3. Shift the index with $m=n-1$.
4. Solve for $A(x)$.

## My attempt

- Split:
- Recurrence substitution:
- Index shift evidence:
- Closed form:
- Confidence / confusion:
""",
    "tutorial/rubric.md": """# Tutorial verification rubric

Verify only after `tutorial/attempt.md` contains a real attempt. Do not reveal the reference solution before the attempt.

## Required evidence

| Criterion | Pass condition | Common miss |
|---|---|---|
| Attempt exists | `tutorial/attempt.md` has non-placeholder work in `My attempt` | blank worksheet |
| Split | Includes `A(x)=1+...` or equivalent | omits $a_0$ |
| Recurrence | Replaces $a_n$ by $2a_{n-1}$ for $n\\ge1$ | applies recurrence at $n=0$ |
| Index shift | Shows the shifted term as `2xA(x)` or equivalent | writes `2A(x)` and loses the factor $x$ |
| Closed form | Solves to `1/(1-2x)` | algebra stops before solving |
| Evidence quote | `verify.md` quotes the user's attempt for every pass/fail | verdict without source evidence |

## Review action rule

- If the index shift fails, add/open a review action for `/paideia:derive index-shift` or another index-shift drill.
- If the attempt passes, next action is `/paideia:quiz tutorial-index-shift 1` or starting the real course bootstrap.
""",
    "tutorial/verify.md": """# Tutorial verification — pending

Status: PENDING_ATTEMPT

`tutorial/attempt.md` has been seeded as a worksheet. Fill it in first, then verify against `tutorial/rubric.md`.

When verification runs, this file should include:

- pass/fail/partial for each rubric row
- quote from `tutorial/attempt.md` as evidence
""",
    "errors/log.md": """# Error ledger

<!-- Source-idempotent YAML entries. Keep the latest grading per source. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts> | tutorial/attempt.md>
  date: <ISO8601>
-->
""",
    "reviews/actions.md": """# Review actions

Review actions are local, editable study artifacts derived from observable attempt/error evidence. They are not telemetry and not a student profile.
""",
}

COPIED_FILES = {
    "converted/lectures/tutorial-generating-functions.md": "materials/lectures/tutorial-generating-functions.md",
    "converted/homework/tutorial-hw.md": "materials/homework/tutorial-hw.md",
    "converted/solutions/tutorial-hw-sol.md": "materials/solutions/tutorial-hw-sol.md",
}

PLACEHOLDER_MARKERS = (
    "TODO: write your attempt here",
    "- Split:",
    "- Recurrence substitution:",
    "- Index shift evidence:",
    "- Closed form:",
    "- Confidence / confusion:",
)


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    quote: str
    explanation: str


def rel(path: str) -> Path:
    return Path(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def attempt_body(text: str) -> str:
    match = re.search(r"^## My attempt\s*$", text, flags=re.MULTILINE)
    return text[match.end() :] if match else text


def meaningful_attempt_text(text: str) -> str:
    body = attempt_body(text)
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        if line in PLACEHOLDER_MARKERS:
            continue
        if line.startswith("-") and line.rstrip(":") in {m.rstrip(":") for m in PLACEHOLDER_MARKERS}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def classify_attempt(root: Path) -> AttemptState:
    attempt = root / "tutorial/attempt.md"
    if not attempt.exists():
        return AttemptState.PENDING_ATTEMPT
    text = read_text(attempt)
    return AttemptState.ATTEMPT_READY if meaningful_attempt_text(text) else AttemptState.CANNOT_VERIFY


def find_quote(text: str, patterns: Iterable[str]) -> str:
    lines = [ln.strip() for ln in attempt_body(text).splitlines() if ln.strip()]
    for pat in patterns:
        rx = re.compile(pat, flags=re.IGNORECASE)
        for line in lines:
            if rx.search(line):
                return line[:240]
    for line in lines:
        if not any(marker in line for marker in PLACEHOLDER_MARKERS):
            return line[:240]
    return ""


def compact_math(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def score_attempt(text: str) -> list[Criterion]:
    flat = compact_math(text)
    split = bool(re.search(r"A\(x\)\s*=\s*(a_?0|1)\s*\+", text, re.I)) or "a(x)=1+" in flat
    recurrence = bool(re.search(r"2\s*a_?\{?n-?1\}?", text, re.I)) or "2a_{n-1}" in flat or "2a_n-1" in flat
    good_shift = bool(re.search(r"2\s*x\s*A\(x\)", text, re.I)) or "2xa(x)" in flat or "2*x*a(x)" in flat
    bad_shift = bool(re.search(r"(?<!x)2\s*A\(x\)", text, re.I)) or "=2a(x)" in flat
    closed = "1/(1-2x)" in flat or "\\frac{1}{1-2x}" in flat or "\frac{1}{1-2x}" in flat
    return [
        Criterion("split", split, find_quote(text, [r"A\(x\).*\+", r"split"]), "Includes the a0 term separately."),
        Criterion("recurrence", recurrence, find_quote(text, [r"2\s*a", r"recurrence"]), "Substitutes a_n = 2a_{n-1} for n>=1."),
        Criterion("index_shift", good_shift and not bad_shift, find_quote(text, [r"2\s*x\s*A\(x\)", r"2xA\(x\)", r"shift"]), "Shifted term keeps the leading factor x."),
        Criterion("closed_form", closed, find_quote(text, [r"1\s*/\s*\(\s*1\s*-\s*2\s*x\s*\)", r"frac\{1\}\{1-2x\}", r"closed"]), "Solves for A(x)."),
    ]


def final_state(criteria: list[Criterion]) -> AttemptState:
    passed = sum(1 for c in criteria if c.passed)
    if passed == len(criteria):
        return AttemptState.PASS
    if passed == 0:
        return AttemptState.FAIL
    return AttemptState.PARTIAL


def source_quote(path: Path, fallback: str) -> str:
    if path.exists():
        for line in read_text(path).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("<!--"):
                return line[:240]
    return fallback


def build_graph(root: Path, verify_state: AttemptState, criteria: list[Criterion] | None = None) -> dict:
    criteria = criteria or []
    attempt_quote = next((c.quote for c in criteria if c.quote), "Attempt worksheet seeded; no user evidence yet.")
    nodes = [
        {"id": "tutorial-course", "type": "course", "label": "Synthetic PAIDEIA tutorial course", "source_path": "tutorial/tutorial.md", "evidence_quote": source_quote(root / "tutorial/tutorial.md", "Synthetic tutorial course")},
        {"id": "tut-sec-index-shift", "type": "concept", "label": "Generating-function index shift", "source_path": "converted/lectures/tutorial-generating-functions.md", "evidence_quote": "The common move is an index shift:"},
        {"id": "tut-problem-t1", "type": "problem", "label": "Synthetic HW Problem T1", "source_path": "converted/homework/tutorial-hw.md", "evidence_quote": "Use the recurrence to derive a closed form for $A(x)$."},
        {"id": "tut-attempt-t1", "type": "attempt", "label": f"User attempt for Problem T1 ({verify_state.value})", "source_path": "tutorial/attempt.md", "evidence_quote": attempt_quote},
        {"id": "tut-rubric-t1", "type": "rubric", "label": "Verification rubric for Problem T1", "source_path": "tutorial/rubric.md", "evidence_quote": "Shows the shifted term as `2xA(x)` or equivalent"},
        {"id": "tut-error-index-shift", "type": "error", "label": "Index shift error if factor x is missing", "source_path": "errors/log.md", "evidence_quote": "source: tutorial/attempt.md"},
        {"id": "tut-review-index-shift", "type": "review_action", "label": "Redo index-shift drill when needed", "source_path": "reviews/actions.md", "evidence_quote": "/paideia:derive index-shift"},
    ]
    edges = [
        {"from": "tutorial-course", "relation": "contains", "to": "tut-sec-index-shift", "source_path": "tutorial/tutorial.md", "evidence_quote": "Read a tiny source concept."},
        {"from": "tut-problem-t1", "relation": "tests", "to": "tut-sec-index-shift", "source_path": "converted/homework/tutorial-hw.md", "evidence_quote": "Use the recurrence to derive a closed form for $A(x)$."},
        {"from": "tut-attempt-t1", "relation": "answers", "to": "tut-problem-t1", "source_path": "tutorial/attempt.md", "evidence_quote": attempt_quote},
        {"from": "tut-attempt-t1", "relation": "verified_by", "to": "tut-rubric-t1", "source_path": "tutorial/rubric.md", "evidence_quote": "Verify only after `tutorial/attempt.md` contains a real attempt."},
        {"from": "tut-rubric-t1", "relation": "may_log", "to": "tut-error-index-shift", "source_path": "tutorial/rubric.md", "evidence_quote": "If the index shift fails"},
        {"from": "tut-error-index-shift", "relation": "triggers", "to": "tut-review-index-shift", "source_path": "reviews/actions.md", "evidence_quote": "/paideia:derive index-shift"},
    ]
    return {"schema_version": 1, "generated_by": "plugins/paideia/scripts/tutorial_harness.py", "state": verify_state.value, "nodes": nodes, "edges": edges}


def write_graph(root: Path, state: AttemptState, criteria: list[Criterion] | None = None) -> None:
    write_text(root / "course-index/context-graph.json", json.dumps(build_graph(root, state, criteria), indent=2, ensure_ascii=False) + "\n")


def init(root: Path) -> int:
    attempt = root / "tutorial/attempt.md"
    if attempt.exists() and meaningful_attempt_text(read_text(attempt)):
        print("tutorial/attempt.md already contains work; move or rename it before re-running init.", file=sys.stderr)
        return 1
    for rel_path, text in ROOT_FILES.items():
        dest = root / rel_path
        if dest.exists() and rel_path == "tutorial/attempt.md" and meaningful_attempt_text(read_text(dest)):
            continue
        if dest.exists() and rel_path == "errors/log.md":
            continue
        if dest.exists() and rel_path == "reviews/actions.md":
            continue
        write_text(dest, text)
    for dest_rel, src_rel in COPIED_FILES.items():
        write_text(root / dest_rel, read_text(root / src_rel))
    write_graph(root, AttemptState.PENDING_ATTEMPT)
    print("created tutorial harness")
    return 0


def replace_source_block(path: Path, marker: str, block: str) -> None:
    existing = read_text(path) if path.exists() else ""
    start = f"<!-- BEGIN {marker} -->"
    end = f"<!-- END {marker} -->"
    wrapped = f"{start}\n{block.rstrip()}\n{end}\n"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", flags=re.DOTALL)
    if pattern.search(existing):
        new = pattern.sub(wrapped, existing)
    else:
        sep = "\n" if existing.endswith("\n") or not existing else "\n\n"
        new = existing + sep + wrapped
    write_text(path, new)


def update_error_log(root: Path, state: AttemptState, criteria: list[Criterion]) -> None:
    if state not in {AttemptState.FAIL, AttemptState.PARTIAL}:
        return
    today = _dt.date.today().isoformat()
    failed = [c.name for c in criteria if not c.passed]
    summary = "Tutorial attempt missing: " + ", ".join(failed)
    block = f"""- problem_id: tutorial-t1
  pattern: index-shift
  error_type: pattern-missed
  summary: "{summary}"
  source: tutorial/attempt.md
  date: {today}"""
    path = root / "errors/log.md"
    if not path.exists():
        write_text(path, ROOT_FILES["errors/log.md"])
    replace_source_block(path, "paideia-tutorial tutorial/attempt.md", block)


def update_review_action(root: Path, state: AttemptState, criteria: list[Criterion]) -> None:
    index = next((c for c in criteria if c.name == "index_shift"), None)
    if state not in {AttemptState.FAIL, AttemptState.PARTIAL} or (index and index.passed):
        return
    block = """```yaml
- action_id: tutorial-index-shift
  kind: ReviewAction
  triggered_by: tutorial/attempt.md
  command: "/paideia:derive index-shift"
  reason: "Observable attempt evidence missed the factor x during the m=n-1 shift."
  status: open
```"""
    path = root / "reviews/actions.md"
    if not path.exists():
        write_text(path, ROOT_FILES["reviews/actions.md"])
    replace_source_block(path, "paideia-tutorial-review-action tutorial/attempt.md", block)


def render_verify(state: AttemptState, criteria: list[Criterion]) -> str:
    lines = ["# Tutorial verification", "", f"Status: {state.value}", "", "Source: `tutorial/attempt.md`", ""]
    if state == AttemptState.CANNOT_VERIFY:
        lines += [
            "The attempt worksheet is still blank or placeholder-only, so PAIDEIA cannot verify it.",
            "No reference answer is revealed here; fill `tutorial/attempt.md` first.",
            "",
        ]
        return "\n".join(lines)
    lines += ["## Rubric results", ""]
    for c in criteria:
        mark = "PASS" if c.passed else "FAIL"
        quote = c.quote or "NO EVIDENCE QUOTE FOUND"
        lines += [f"- {c.name}: {mark}", f"  - Evidence quote: `{quote}`", f"  - Check: {c.explanation}"]
    if state in {AttemptState.FAIL, AttemptState.PARTIAL}:
        lines += ["", "## Follow-up", "", "A source-idempotent entry should exist in `errors/log.md`, and an open ReviewAction candidate should exist in `reviews/actions.md` if the index shift failed."]
    else:
        lines += ["", "## Follow-up", "", "Attempt passes the tutorial rubric. Suggested next action: `/paideia:quiz tutorial-index-shift 1` or start a real course bootstrap."]
    return "\n".join(lines) + "\n"


def verify(root: Path, emit_json: bool = False) -> int:
    state = classify_attempt(root)
    if state == AttemptState.PENDING_ATTEMPT:
        write_text(root / "tutorial/verify.md", render_verify(AttemptState.CANNOT_VERIFY, []))
        write_graph(root, AttemptState.CANNOT_VERIFY)
        payload = {"state": AttemptState.CANNOT_VERIFY.value, "criteria": []}
        print(json.dumps(payload, indent=2) if emit_json else AttemptState.CANNOT_VERIFY.value)
        return 2
    if state == AttemptState.CANNOT_VERIFY:
        write_text(root / "tutorial/verify.md", render_verify(state, []))
        write_graph(root, state)
        payload = {"state": state.value, "criteria": []}
        print(json.dumps(payload, indent=2) if emit_json else state.value)
        return 2
    attempt = read_text(root / "tutorial/attempt.md")
    criteria = score_attempt(attempt)
    state = final_state(criteria)
    write_text(root / "tutorial/verify.md", render_verify(state, criteria))
    update_error_log(root, state, criteria)
    update_review_action(root, state, criteria)
    write_graph(root, state, criteria)
    payload = {"state": state.value, "criteria": [{"name": c.name, "passed": c.passed, "quote": c.quote} for c in criteria]}
    print(json.dumps(payload, indent=2) if emit_json else state.value)
    return 0 if state == AttemptState.PASS else 1


def graph_check(root: Path) -> int:
    path = root / "course-index/context-graph.json"
    errors: list[str] = []
    if not path.exists():
        errors.append("missing course-index/context-graph.json")
    else:
        try:
            graph = json.loads(read_text(path))
        except json.JSONDecodeError as exc:
            print(f"graph-check FAIL: invalid JSON: {exc}", file=sys.stderr)
            return 1
        required_types = {"course", "concept", "problem", "attempt", "rubric", "error", "review_action"}
        node_types = {n.get("type") for n in graph.get("nodes", [])}
        missing = required_types - node_types
        if missing:
            errors.append("missing node types: " + ", ".join(sorted(missing)))
        node_ids = {n.get("id") for n in graph.get("nodes", [])}
        for n in graph.get("nodes", []):
            for field in ("id", "type", "label", "source_path", "evidence_quote"):
                if not n.get(field):
                    errors.append(f"node {n.get('id', '<unknown>')} missing {field}")
            src = n.get("source_path")
            if src and not (root / src).exists():
                errors.append(f"node {n.get('id')} source_path missing: {src}")
        for e in graph.get("edges", []):
            for field in ("from", "relation", "to", "source_path", "evidence_quote"):
                if not e.get(field):
                    errors.append(f"edge {e.get('from', '<unknown>')}->{e.get('to', '<unknown>')} missing {field}")
            if e.get("from") not in node_ids or e.get("to") not in node_ids:
                errors.append(f"edge references unknown node: {e}")
            src = e.get("source_path")
            if src and not (root / src).exists():
                errors.append(f"edge source_path missing: {src}")
    if errors:
        for err in errors:
            print(f"graph-check FAIL: {err}", file=sys.stderr)
        return 1
    print("graph-check PASS")
    return 0


CLAIM_PATTERNS = (
    "visualize model internal thoughts",
    "visualizes model internal thoughts",
    "hidden activations",
    "student cognition graph",
    "graph of student cognition",
    "chain of model cognition",
    "faithful model cognition",
    "model's thoughts",
    "student's thoughts",
)
NEGATION_RE = re.compile(r"\b(no|not|never|does not|do not|don't|cannot|can't|without|rather than|not model-internal|source-grounded)\b", re.I)


def sentence_allowed(sentence: str) -> bool:
    return bool(NEGATION_RE.search(sentence))


def guardrail_check(root: Path) -> int:
    errors: list[str] = []
    for path in root.rglob("*.md"):
        if ".git" in path.parts:
            continue
        try:
            text = read_text(path)
        except UnicodeDecodeError:
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        for sentence in sentences:
            lower = sentence.lower()
            if any(claim in lower for claim in CLAIM_PATTERNS) and not sentence_allowed(sentence):
                errors.append(f"{path.relative_to(root)}: {sentence.strip()[:180]}")
    if errors:
        for err in errors:
            print(f"guardrail-check FAIL: overclaiming graph/cognition language: {err}", file=sys.stderr)
        return 1
    print("guardrail-check PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PAIDEIA stdlib tutorial harness")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "graph-check", "guardrail-check"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".", help="course root")
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--root", default=".", help="course root")
    verify_p.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "init":
        return init(root)
    if args.command == "verify":
        return verify(root, emit_json=args.json)
    if args.command == "graph-check":
        return graph_check(root)
    if args.command == "guardrail-check":
        return guardrail_check(root)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
