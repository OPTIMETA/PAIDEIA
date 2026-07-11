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

Badge consumer: grade.md step 4c writes answers/converted/<stem>.verify.json by
mapping this stdout `results[]` directly — the badge `checks[].result` and
GRADE_RECORD_JSON `steps[].sympy.result` both source from the same single call here.
(T-VERIFY-HEADLESS-BUNDLE C1)

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

Fallback extraction layers (T-VERIFY-PARSER-FALLBACK):
  math-verify's default extraction requires anchored LaTeX context ($...$, boxed,
  or numeric) to yield a non-empty list.  Bare tokens (e.g. x**2-1, \\hbar,
  p_1+p_2, \\hat T(a)\\hat U) produce an empty list and were previously reported
  as "unparsable", even when the ground-truth relationship is verifiable.

  The fallback layers activate ONLY when the primary extraction returns empty for
  at least one operand — the anchored/primary path is always tried first and always
  wins if non-empty (zero regression risk on existing anchored inputs).

  Layer 1 — LaTeX-wrap re-extraction:
    Applied when the input contains LaTeX metacharacters (\\, ^, _) but does NOT
    already contain a $ delimiter (which would indicate malformed or already-wrapped
    input).  The input is wrapped as $...$  and re-presented to _mv_parse.
    Rescues: \\hbar, \\hat T(a)\\hat U, p_1+p_2, etc.
    Both operands go through this layer together; if either remains empty after
    wrapping, this layer does not produce a verdict (falls through to layer 2).
    The resulting expressions are compared via _mv_verify (same path as anchored).

  Layer 2 — SymPy algebraic fallback:
    Applied only when neither operand contains LaTeX metacharacters (pure algebraic
    ASCII like x**2-1, (x-1)*(x+1), 2*x, 3*x).  Uses
    sympy.parsing.sympy_parser.parse_expr with standard_transformations +
    implicit_multiplication_application, then checks simplify(g - c) == 0.
    Rescues: x**2-1 == (x-1)*(x+1), p_1+p_2 == p_2+p_1 (via layer 1 first).
    Requires sympy (math-verify pulls it in as a dep); if unavailable, this
    layer is silently skipped (honest unparsable, no crash).

  Garbage → still "unparsable":
    A string like \\invalid_command_xyz_$$ has a $ in it → layer 1 skipped;
    layer 2 also skipped (has LaTeX metachar \\); sympify fails → unparsable.
    The fallback never promotes garbage to "pass".

  Result set unchanged: "pass" | "fail" | "timeout" | "unparsable".
  No new result tokens are added; 4c badge and GRADE_RECORD_JSON contracts are
  unaffected.

Vendored as OPTIMETA-original (not from PAIDEIA upstream). Provenance: 03 §1.6.
"""
from __future__ import annotations

import json
import re
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

# ---------------------------------------------------------------------------
# Optional sympy import for layer-2 algebraic fallback (T-VERIFY-PARSER-FALLBACK)
# math-verify already depends on sympy, so this import normally succeeds whenever
# _AVAILABLE is True.  Guard defensively so a sympy-free environment still works
# (fallback is silently disabled — unparsable verdict, no crash).
# ---------------------------------------------------------------------------
try:
    from sympy.parsing.sympy_parser import (  # type: ignore[import-untyped]
        parse_expr,
        standard_transformations,
        implicit_multiplication_application,
    )
    import sympy as _sympy  # type: ignore[import-untyped]
    _SYMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SYMPY_AVAILABLE = False

TIMEOUT_SECONDS: int = 5

# Matches LaTeX metacharacters that suggest the string is (or should be) LaTeX
# rather than pure algebraic ASCII.  Used in layer-1 fallback gate.
_LATEX_META_RE = re.compile(r"[\\^_]")


def _has_dollar(s: str) -> bool:
    """True if s contains a $ character (already-anchored or malformed input)."""
    return "$" in s


def _has_latex_meta(s: str) -> bool:
    """True if s contains \\, ^, or _ (LaTeX metacharacters)."""
    return bool(_LATEX_META_RE.search(s))


def _mv_parse_safe(s: str, **kwargs):  # type: ignore[return]
    """Call _mv_parse, returning [] on any non-timeout exception."""
    try:
        return _mv_parse(s, **kwargs)
    except Exception:  # noqa: BLE001
        return []


def _sympify_safe(s: str):  # type: ignore[return]
    """Try sympy parse_expr; return None on any failure."""
    if not _SYMPY_AVAILABLE:
        return None
    _T = standard_transformations + (implicit_multiplication_application,)
    try:
        return parse_expr(s, transformations=_T)
    except Exception:  # noqa: BLE001
        return None


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
      • anchored extraction succeeds (parse() → non-empty) for both → verify via
        _mv_verify; "pass"/"fail"/"timeout" per result.
      • empty extraction after primary attempt → fallback layers (see module
        docstring); still defers to "unparsable" if all layers exhausted.
      • SIGALRM timeout after TIMEOUT_SECONDS → "timeout" (BaseException path).
      • any other parse/verify exception → "unparsable" (deferred to the LLM).

    DO NOT add a worker-thread wrapper here.  DO NOT change the gold-first
    asymmetry.  DO NOT change the raise_on_error=True / except _MVTimeout /
    except BaseException layering — all three are load-bearing for thread safety
    and correct timeout propagation (03 §1.6 D5, math-verify 0.9.0 contract).
    """
    # ── Primary path: anchored/math-verify extraction ────────────────────────
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

    if gold_expr and cand_expr:
        # Both extracted — compare via math-verify (canonical path, no fallback).
        try:
            equivalent = _mv_verify(
                gold_expr, cand_expr, timeout_seconds=TIMEOUT_SECONDS, raise_on_error=True
            )
        except _MVTimeout:
            return "timeout"
        except Exception:  # noqa: BLE001
            return "unparsable"
        return "pass" if equivalent else "fail"

    # ── Fallback layers: at least one operand extracted nothing ───────────────
    # Layer 1 — LaTeX-wrap re-extraction (T-VERIFY-PARSER-FALLBACK)
    # Gate: input must have LaTeX metacharacters (suggesting it IS LaTeX) and must
    # NOT already contain a $ (which would imply malformed anchoring or
    # intentional non-LaTeX content that parse() already saw and rejected).
    # Both operands are evaluated together so we never mix mv and sympy results.
    if _has_latex_meta(gold_latex) or _has_latex_meta(cand_latex):
        # Apply wrap only where it makes sense (LaTeX meta + no embedded $)
        def _wrap_if_eligible(s: str, existing_expr):  # type: ignore[return]
            if existing_expr:               # primary already gave us something
                return existing_expr
            if _has_latex_meta(s) and not _has_dollar(s):
                return _mv_parse_safe("$" + s + "$", parsing_timeout=TIMEOUT_SECONDS)
            return []

        gold_w = _wrap_if_eligible(gold_latex, gold_expr)
        cand_w = _wrap_if_eligible(cand_latex, cand_expr)

        if gold_w and cand_w:
            try:
                equivalent = _mv_verify(
                    gold_w, cand_w, timeout_seconds=TIMEOUT_SECONDS, raise_on_error=True
                )
            except _MVTimeout:
                return "timeout"
            except Exception:  # noqa: BLE001
                return "unparsable"
            return "pass" if equivalent else "fail"
        # One or both still empty after wrap attempt → fall through

    # Layer 2 — SymPy algebraic fallback (T-VERIFY-PARSER-FALLBACK)
    # Gate: both operands must be pure algebraic ASCII (no LaTeX metacharacters).
    # This catches x**2-1, (x-1)*(x+1), etc. that have no \, ^, _.
    # Do NOT mix with the LaTeX-wrap path: if either string has LaTeX metachar,
    # it already went through layer 1 above; sympify would likely fail on it anyway.
    if not _has_latex_meta(gold_latex) and not _has_latex_meta(cand_latex):
        g_sym = _sympify_safe(gold_latex)
        c_sym = _sympify_safe(cand_latex)
        if g_sym is not None and c_sym is not None:
            try:
                return "pass" if _sympy.simplify(g_sym - c_sym) == 0 else "fail"
            except Exception:  # noqa: BLE001
                return "unparsable"

    # All fallbacks exhausted — defer to the LLM.
    return "unparsable"


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
