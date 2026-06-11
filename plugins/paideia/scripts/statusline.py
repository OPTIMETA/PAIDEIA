#!/usr/bin/env python3
"""
PAIDEIA statusline - emits one line for Claude Code's statusline slot.

Format:  paideia · <COURSE_NAME> · D-N · <phase> · P<k> ↑
Color:   one neon color per session (hashed from session_id), truecolor ANSI.
Silent:  if CWD has no .course-meta, output nothing (Claude Code falls back).

Phases (artifact AND activity derived, not time-derived):
  setup  - course-index/patterns.md absent
  diag   - patterns exist, but no quiz problems yet, or no graded error yet
  drill  - quiz problems exist AND errors/log.md has at least one graded entry
  mock   - a mock exam has been graded (errors/log.md has a mock/ source)
  cram   - cheatsheet/final.{md,pdf} present
  cool   - D-0 (today == exam date) overrides all

Caching: output is memoized on disk under ~/.cache/paideia/, keyed by
(cwd, session_id), and invalidated when any watched file's mtime changes.
Claude Code re-renders the statusline every prompt, so without this cache
every turn would re-scan the course folder and re-parse the newest weakmap.

Input (stdin, JSON, per Claude Code's statusline contract):
  { "session_id": "...", "cwd": "...", "workspace": {"current_dir": "..."} }
"""
from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

NEON = [
    (57, 255, 20),     # neon green
    (255, 20, 147),    # hot pink
    (0, 255, 255),     # electric cyan
    (204, 255, 0),     # laser yellow
    (255, 0, 255),     # magenta
    (191, 0, 255),     # electric purple
    (255, 102, 0),     # neon orange
    (176, 255, 0),     # acid green
    (255, 49, 49),     # neon red
    (125, 249, 255),   # electric blue
    (255, 111, 97),    # neon coral
    (255, 153, 0),     # tangerine
]

CACHE_DIR = Path.home() / ".cache" / "paideia"

# Robust to schema drift: the canonical /grade entry uses `pattern:` but older
# /blind entries may have used `pattern_missed_initial:`. Accept both.
_PATTERN_RX = re.compile(r"\b(?:pattern|pattern_missed_initial)\s*:\s*(P\d+)")


def pick_color(seed: str) -> str:
    h = int(hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:8], 16)
    r, g, b = NEON[h % len(NEON)]
    return f"\033[38;2;{r};{g};{b}m"


def parse_meta(cwd: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    p = cwd / ".course-meta"
    if not p.exists():
        return meta
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(.+?)\s*$", line)
            if m:
                # Strip a trailing `# comment` from every value so a hand-edited
                # line like `COURSE_NAME: Complex Analysis  # main` doesn't leak
                # the annotation into the statusline. Mirrors doctor.parse_meta
                # and session_start.parse_meta — all three must agree.
                meta[m.group(1)] = m.group(2).split("#", 1)[0].strip()
    except OSError:
        pass
    return meta


def days_until(exam_date: str) -> int | None:
    try:
        d = datetime.datetime.strptime(exam_date.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    return (d - datetime.date.today()).days


def _quiz_problems_exist(cwd: Path) -> bool:
    """True iff at least one quiz PROBLEM file exists (excluding _answers siblings)."""
    for p in glob.glob(str(cwd / "quizzes" / "*.md")):
        if not p.endswith("_answers.md"):
            return True
    return False


def _read_errors_log(cwd: Path) -> str:
    log = cwd / "errors" / "log.md"
    if not log.exists():
        return ""
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_error_entries(log_text: str) -> bool:
    return bool(re.search(r"^\s*-\s+problem_id\s*:", log_text, re.MULTILINE))


def _mock_was_graded(log_text: str) -> bool:
    """Did at least one grade write back a mock-sourced entry?"""
    if re.search(r"^\s*source\s*:\s*(?:answers/converted/)?mock[/_]", log_text, re.MULTILINE):
        return True
    if re.search(r"^\s*problem_id\s*:\s*['\"]?mock[_\-]", log_text, re.MULTILINE):
        return True
    return False


def detect_phase(cwd: Path, days: int | None) -> str:
    if days == 0:
        return "cool"
    cheatsheet = cwd / "cheatsheet"
    if (cheatsheet / "final.pdf").exists() or (cheatsheet / "final.md").exists():
        return "cram"
    log_text = _read_errors_log(cwd)
    if _mock_was_graded(log_text):
        return "mock"
    if not (cwd / "course-index" / "patterns.md").exists():
        return "setup"
    if _quiz_problems_exist(cwd) and _has_error_entries(log_text):
        return "drill"
    return "diag"


def top_miss(cwd: Path) -> str | None:
    wms = sorted(glob.glob(str(cwd / "weakmap" / "weakmap_*.md")), reverse=True)
    if wms:
        try:
            text = Path(wms[0]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = _PATTERN_RX.search(text)
        if m:
            return m.group(1)
        m = re.search(r"\bP(\d+)\b", text)
        if m:
            return f"P{m.group(1)}"
    log_text = _read_errors_log(cwd)
    if log_text:
        counts: dict[str, int] = {}
        for m in _PATTERN_RX.finditer(log_text):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        if counts:
            return max(counts, key=counts.get)
    return None


def fmt_days(days: int | None) -> str | None:
    if days is None:
        return None
    if days == 0:
        return "D-0"
    if days > 0:
        return f"D-{days}"
    return f"D+{-days}"


def truncate(name: str, limit: int = 28) -> str:
    name = name.strip()
    if len(name) <= limit:
        return name
    return name[: limit - 1].rstrip() + "…"


def resolve_cwd(payload: dict) -> Path:
    for key in ("cwd",):
        v = payload.get(key)
        if v:
            return Path(v).expanduser()
    ws = payload.get("workspace") or {}
    v = ws.get("current_dir") or ws.get("cwd")
    if v:
        return Path(v).expanduser()
    return Path(os.getcwd())


def resolve_session(payload: dict) -> str:
    for key in ("session_id",):
        v = payload.get(key)
        if v:
            return str(v)
    sess = payload.get("session") or {}
    v = sess.get("id")
    if v:
        return str(v)
    return os.environ.get("USER", "paideia")


def _collect_mtimes(cwd: Path) -> dict[str, float]:
    """mtimes of every file whose contents affect the rendered statusline."""
    watch: dict[str, float] = {}
    singles = (
        ".course-meta",
        "course-index/patterns.md",
        "cheatsheet/final.md",
        "cheatsheet/final.pdf",
        "errors/log.md",
    )
    for rel in singles:
        p = cwd / rel
        if p.exists():
            try:
                watch[rel] = p.stat().st_mtime
            except OSError:
                pass
    dir_globs = (
        ("weakmap/weakmap_*.md", "weakmap:newest"),
        ("mock/*.md",            "mock:newest"),
        ("quizzes/*.md",         "quizzes:newest"),
    )
    for pattern, label in dir_globs:
        matches = glob.glob(str(cwd / pattern))
        if matches:
            try:
                watch[label] = max(Path(m).stat().st_mtime for m in matches)
            except OSError:
                pass
    return watch


def _cache_path(cwd: Path, session: str) -> Path:
    try:
        key_seed = f"{cwd.resolve()}|{session}"
    except OSError:
        key_seed = f"{cwd}|{session}"
    key = hashlib.sha1(key_seed.encode("utf-8", "replace")).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def _read_cache(cwd: Path, session: str) -> str | None:
    try:
        p = _cache_path(cwd, session)
        if not p.exists():
            return None
        cached = json.loads(p.read_text(encoding="utf-8"))
        if cached.get("mtimes") != _collect_mtimes(cwd):
            return None
        out = cached.get("output")
        return out if isinstance(out, str) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_cache(cwd: Path, session: str, output: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path(cwd, session)
        p.write_text(
            json.dumps({"mtimes": _collect_mtimes(cwd), "output": output}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _render(cwd: Path, session: str) -> str:
    meta = parse_meta(cwd)
    if not meta:
        return ""
    name = truncate(meta.get("COURSE_NAME", "course"))
    days = days_until(meta.get("EXAM_DATE", ""))
    phase = detect_phase(cwd, days)
    miss = top_miss(cwd)

    parts = ["paideia", name]
    d = fmt_days(days)
    if d:
        parts.append(d)
    parts.append(phase)
    if miss:
        parts.append(f"{miss} ↑")

    color = pick_color(session)
    reset = "\033[0m"
    return f"{color}{' · '.join(parts)}{reset}"


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    cwd = resolve_cwd(payload)
    session = resolve_session(payload)

    cached = _read_cache(cwd, session)
    if cached is not None:
        sys.stdout.write(cached)
        return 0

    output = _render(cwd, session)
    _write_cache(cwd, session, output)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
