#!/usr/bin/env python3
"""
PAIDEIA SessionStart hook - prints a 2-3 line reminder when Claude Code opens
a session inside a paideia course folder, so the agent starts each turn with
the right context loaded: exam D-N, current phase, top-miss pattern.

Silent (exit 0, no output) when CWD has no .course-meta. Wired by
/paideia:init-course into .claude/settings.json under hooks.SessionStart.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paideia_lib as plib  # noqa: E402  (shared .course-meta / phase logic)

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
    "next_cool":   {"en": "  exam is today - top 3 of the weakmap only; learn nothing new",
                    "ko": "  시험 당일 - weakmap 상위 3개만 재확인, 새 학습 금지"},
}


def t(key: str, lang: str, **kw: object) -> str:
    """Return the localized message for `key`, defaulting to English on missing lang.

    Uses `or` (not `is None`): an explicitly empty translation value also
    falls through to the English bundle. That's intentional here — a blank
    line at session start would be more confusing than a silent en fallback.
    """
    bundle = _MSG.get(key, {})
    template = bundle.get(lang) or bundle.get("en", key)
    return template.format(**kw) if kw else template


def latest_weakmap_verdict(cwd: Path) -> str | None:
    wm = plib.latest_weakmap(cwd)
    if wm is None:
        return None
    try:
        text = wm.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"##\s*One-line verdict\s*\n+\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return None


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
    meta = plib.parse_meta(cwd)
    if not meta:
        return 0

    name = meta.get("COURSE_NAME", "course")
    lang = plib.interface_lang(meta)
    days = plib.days_until(meta.get("EXAM_DATE", ""))
    # Same phase machine as the statusline (plib.phase), so the banner and the
    # status bar can never disagree — including `cool` on exam day.
    phase = plib.phase(cwd, days)
    verdict = latest_weakmap_verdict(cwd)
    top_miss = plib.top_pattern(plib.read_errors_log(cwd))

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
            "cool":  "next_cool",
        }.get(phase)
        if phase_key:
            lines.append(t(phase_key, lang))

    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
