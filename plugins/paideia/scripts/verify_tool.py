#!/usr/bin/env python3
"""
verify_tool — LaTeX/SymPy equivalence checker for OPTIMETA-OS grade pipeline.

Contract (stdin → stdout):
  in:  {"checks": [{"id": "<id>", "gold": "<latex>", "cand": "<latex>",
                    "relation": "eq"}]}
  out: {"available": true,
        "results": [{"id": "<id>", "result": "pass|fail|timeout|unparsable"}]}
       — or, when math-verify is not installed:
       {"available": false, "reason": "math-verify not installed", "results": []}

Exit codes:
  0 — normal execution (available=true, results written)
  2 — usage error: stdin is not valid JSON or missing the "checks" key
  3 — math-verify not installed (honest downgrade; caller hides symbolic mode)

Asymmetry rule: verify(gold, cand) — gold is ALWAYS parsed first. This is
locked here so callers cannot accidentally swap operands.  (03 §1.6 D5)

Per-check timeout: 5 seconds (TIMEOUT_SECONDS).  Enforced by math-verify's own
SIGALRM-based guard (`parse(parsing_timeout=5)` / `verify(timeout_seconds=5)`); a
computation that exceeds it returns "timeout".  That guard uses `signal.alarm()`,
which is valid ONLY on the main thread, so parse/verify run directly on the main
thread with no worker-thread wrapper.  This is safe because verify_tool is a
1-shot subprocess (Rust spawns `python3` per call).  Running math-verify in a
worker thread would raise ValueError in math-verify 0.9.0
("parse function doesn't support threaded environment due to usage of
signal.alarm()") and mis-report every step as "unparsable" — the exact bug this
version fixes.

Vendored as OPTIMETA-original (not from PAIDEIA upstream). Provenance: 03 §1.6.
"""
from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# Optional import — honest downgrade if math-verify is absent (03 §1.6, 08 §2.3)
# ---------------------------------------------------------------------------
try:
    from math_verify import verify as _mv_verify  # type: ignore[import-untyped]
    from math_verify import parse as _mv_parse   # type: ignore[import-untyped]
    # TimeoutException is a *BaseException* (not Exception) in math-verify 0.9.0,
    # so a plain `except Exception` never swallows it.  That is precisely what
    # lets a genuine SIGALRM timeout map to "timeout" while every other
    # parse/verify failure maps to "unparsable".  Import defensively: on version
    # skew, fall back to a sentinel that is never raised, so a timeout degrades
    # honestly to "unparsable" instead of crashing the process.
    try:
        from math_verify.errors import TimeoutException as _MVTimeout  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — version-skew fallback
        class _MVTimeout(BaseException):  # type: ignore[no-redef]
            """Sentinel — never raised; keeps `except _MVTimeout` a valid clause."""
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

TIMEOUT_SECONDS: int = 5


# ---------------------------------------------------------------------------
# Core equivalence check
# ---------------------------------------------------------------------------

def _check_one(gold_latex: str, cand_latex: str) -> str:
    """Return "pass" | "fail" | "timeout" | "unparsable".

    Runs on the MAIN thread.  math-verify's built-in timeout uses signal.alarm()
    and raises ValueError in any non-main thread (math-verify 0.9.0); as a 1-shot
    subprocess this script always owns the main thread, so no worker-thread
    wrapper is used and the SIGALRM guard (TIMEOUT_SECONDS) is what bounds the
    computation.  gold is always parsed first per the asymmetry rule (03 §1.6 D5).

    Verdict mapping:
      • empty extraction (parse() → [], e.g. bare tokens, "[?]", garbage) →
        "unparsable".  NB parse() returns a *list*, never None, so emptiness
        (truthiness), not `is None`, is the correct signal — collapsing this into
        "fail" would mis-tag unverifiable student steps (03 §1.6).
      • SIGALRM timeout after TIMEOUT_SECONDS → "timeout".
      • any other parse/verify exception → "unparsable" (deferred to the LLM).
    """
    # raise_on_error=True so a real timeout surfaces as TimeoutException (a
    # BaseException, hence not caught by `except Exception`) instead of being
    # silently swallowed into an empty list / False.
    try:
        gold_expr = _mv_parse(gold_latex, parsing_timeout=TIMEOUT_SECONDS, raise_on_error=True)
        cand_expr = _mv_parse(cand_latex, parsing_timeout=TIMEOUT_SECONDS, raise_on_error=True)
    except _MVTimeout:
        return "timeout"
    except Exception:  # noqa: BLE001 — any parse failure → unparsable (defer to LLM)
        return "unparsable"

    # Empty extraction is the honest "cannot verify" signal, NOT a mismatch.
    if not gold_expr or not cand_expr:
        return "unparsable"

    try:
        equivalent = _mv_verify(
            gold_expr, cand_expr, timeout_seconds=TIMEOUT_SECONDS, raise_on_error=True
        )
    except _MVTimeout:
        return "timeout"
    except Exception:  # noqa: BLE001 — any verify failure → unparsable (defer to LLM)
        return "unparsable"
    return "pass" if equivalent else "fail"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Validate stdin FIRST — a usage error (exit 2) is always reported
    # regardless of whether math-verify is installed, so callers get a clear
    # signal about malformed input rather than a misleading downgrade message.
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise ValueError("empty stdin")
        data = json.loads(raw)
        checks = data["checks"]
        if not isinstance(checks, list):
            raise TypeError("checks must be a list")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        sys.stderr.write(
            'Usage: stdin must be JSON {"checks":[{"id":…,"gold":…,"cand":…}]}\n'
        )
        sys.stderr.write(f"Error: {exc}\n")
        return 2

    # Honest downgrade: report unavailability AFTER stdin is validated.
    if not _AVAILABLE:
        json.dump(
            {"available": False, "reason": "math-verify not installed", "results": []},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 3

    # Process each check
    results = []
    for item in checks:
        item_id = str(item.get("id", ""))
        gold = str(item.get("gold", ""))
        cand = str(item.get("cand", ""))
        # relation is accepted as metadata but verify() always checks equivalence
        result = _check_one(gold, cand)
        results.append({"id": item_id, "result": result})

    json.dump({"available": True, "results": results}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
