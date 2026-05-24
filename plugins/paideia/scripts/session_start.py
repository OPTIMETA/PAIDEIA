#!/usr/bin/env python3
"""
PAIDEIA SessionStart hook - prints a 2-3 line reminder when Claude Code opens
a session inside a paideia course folder, so the agent starts each turn with
the right context loaded: exam D-N, current phase, top-miss pattern.

Silent (exit 0, no output) when CWD has no .course-meta. Wired by
/paideia:init-course into .claude/settings.json under hooks.SessionStart.
"""
from __future__ import annotations

import datetime
import glob
import re
import sys
from pathlib import Path

_PATTERN_RX = re.compile(r"\b(?:pattern|pattern_missed_initial)\s*:\s*(P\d+)")

# i18n: keyed by message id, each value is a {"en": ..., "ko": ...} dict.
# `format()` placeholders are filled in by the caller.
_MSG: dict[str, dict[str, str]] = {
    "exam_day":    {"en": " - exam day",                "ko": " - 시험 당일"},
    "exam_past":   {"en": " - D+{n} (past exam)",       "ko": " - D+{n} (시험 지남)"},
    "top_miss":    {"en": "  top-miss pattern: {p} - /paideia:blind or /paideia:pattern {p}",
                    "ko": "  최다 실수 패턴: {p} - /paideia:blind 또는 /paideia:pattern {p}"},
    "next_setup":  {"en": "  next: fill materials/ then /paideia:ingest → /paideia:analyze",
                    "ko": "  다음: materials/ 채우고 /paideia:ingest → /paideia:analyze"},
    "next_diag":   {"en": "  next: run a diagnostic with /paideia:quiz all 20",
                    "ko": "  다음: /paideia:quiz all 20 으로 diagnostic 돌리기"},
    "next_drill":  {"en": "  next: /paideia:weakmap, then /paideia:quiz weakmap",
                    "ko": "  다음: /paideia:weakmap 후 /paideia:quiz weakmap"},
    "next_mock":   {"en": "  next: /paideia:cheatsheet --pdf to start the summary",
                    "ko": "  다음: /paideia:cheatsheet --pdf 로 요약 시작"},
    "next_cram":   {"en": "  next: re-read /paideia:weakmap; don't learn anything new",
                    "ko": "  다음: /paideia:weakmap 재열람, 새로운 건 배우지 말 것"},
}


def t(key: str, lang: str, **kw: object) -> str:
    """Return the localized message for `key`, defaulting to English on missing lang."""
    bundle = _MSG.get(key, {})
    template = bundle.get(lang) or bundle.get("en", key)
    return template.format(**kw) if kw else template


def parse_meta(cwd: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    p = cwd / ".course-meta"
    if not p.exists():
        return meta
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(.+?)\s*$", line)
            if m:
                meta[m.group(1)] = m.group(2)
    except OSError:
        pass
    return meta


def days_until(exam_date: str) -> int | None:
    try:
        d = datetime.datetime.strptime(exam_date.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    return (d - datetime.date.today()).days


def latest_weakmap_verdict(cwd: Path) -> str | None:
    wms = sorted(glob.glob(str(cwd / "weakmap" / "weakmap_*.md")), reverse=True)
    if not wms:
        return None
    try:
        text = Path(wms[0]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"##\s*One-line verdict\s*\n+\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return None


def top_pattern_from_errors(cwd: Path) -> str | None:
    log = cwd / "errors" / "log.md"
    if not log.exists():
        return None
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    counts: dict[str, int] = {}
    for m in _PATTERN_RX.finditer(text):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def current_phase(cwd: Path) -> str:
    cheat = cwd / "cheatsheet"
    if (cheat / "final.pdf").exists() or (cheat / "final.md").exists():
        return "cram"
    log = cwd / "errors" / "log.md"
    if log.exists():
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^\s*source\s*:\s*(?:answers/converted/)?mock[/_]", text, re.MULTILINE):
                return "mock"
        except OSError:
            pass
    if not (cwd / "course-index" / "patterns.md").exists():
        return "setup"
    has_quiz = any(
        not p.endswith("_answers.md") for p in glob.glob(str(cwd / "quizzes" / "*.md"))
    )
    if has_quiz and log.exists():
        try:
            if re.search(r"^\s*-\s+problem_id\s*:", log.read_text(errors="replace"), re.MULTILINE):
                return "drill"
        except OSError:
            pass
    return "diag"


def format_d(days: int | None, lang: str) -> str:
    if days is None:
        return ""
    if days == 0:
        return t("exam_day", lang)
    if days > 0:
        return f" - D-{days}"
    return t("exam_past", lang, n=-days)


def main() -> int:
    cwd = Path.cwd()
    meta = parse_meta(cwd)
    if not meta:
        return 0

    name = meta.get("COURSE_NAME", "course")
    lang = meta.get("INTERFACE_LANG", "en").strip().lower()
    if lang not in {"en", "ko"}:
        lang = "en"
    days = days_until(meta.get("EXAM_DATE", ""))
    phase = current_phase(cwd)
    verdict = latest_weakmap_verdict(cwd)
    top_miss = top_pattern_from_errors(cwd)

    lines = [f"[paideia] {name}{format_d(days, lang)} · phase={phase}"]

    if verdict:
        lines.append(f"  weakmap verdict: {verdict}")
    elif top_miss:
        lines.append(t("top_miss", lang, p=top_miss))
    else:
        phase_key = {
            "setup": "next_setup",
            "diag":  "next_diag",
            "drill": "next_drill",
            "mock":  "next_mock",
            "cram":  "next_cram",
        }.get(phase)
        if phase_key:
            lines.append(t(phase_key, lang))

    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
