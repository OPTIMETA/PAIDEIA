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

import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paideia_lib as plib  # noqa: E402  (shared .course-meta / phase logic)

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
CACHE_TTL_S = 30 * 86400  # GC horizon: cache entries older than this are pruned


def pick_color(seed: str) -> str:
    h = int(hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:8], 16)
    r, g, b = NEON[h % len(NEON)]
    return f"\033[38;2;{r};{g};{b}m"


def top_miss(cwd: Path) -> str | None:
    wm = plib.latest_weakmap(cwd)
    if wm:
        try:
            text = wm.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        # The statusline's "Pk ↑" is the user's single focus pattern, so it must
        # track the weakmap's PRIORITY ranking — not whatever pattern happens to
        # be listed first. The "## Top 5 weaknesses" section is priority-ranked
        # (#1 = drill this first); the "## Error histogram" above it is merely
        # latest-per-pattern in log order. Read the Pk from the ranked section's
        # **bold headlines** only: a headline names a real pattern ("**P6 — …**"),
        # whereas the explanatory prose is littered with problem-ids ("mock-P5")
        # and §-anchors that a loose `P\d+` scan would mistake for a pattern.
        ranked = re.search(
            r"^##\s+Top\s+5\s+weaknesses.*?(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        if ranked:
            for headline in re.findall(r"\*\*([^*]+)\*\*", ranked.group(0)):
                m = re.search(r"(?<![\w-])P(\d+)\b", headline)
                if m:
                    return f"P{m.group(1)}"
        # A weakmap whose top entries are all §/topic-based (no Pk headline) —
        # fall back to the most-frequent graded error pattern below, not to an
        # arbitrary first token, which would surface a low-priority pattern.
    return plib.top_pattern(plib.read_errors_log(cwd))


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


def _gc_cache(now: float) -> None:
    """Prune cache entries past the TTL — sessions rotate constantly, and
    without this the per-(cwd, session) files accumulate forever."""
    try:
        for f in CACHE_DIR.glob("*.json"):
            try:
                if now - f.stat().st_mtime > CACHE_TTL_S:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _write_cache(cwd: Path, session: str, output: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _cache_path(cwd, session)
        p.write_text(
            json.dumps({"mtimes": _collect_mtimes(cwd), "output": output}),
            encoding="utf-8",
        )
        _gc_cache(time.time())
    except OSError:
        pass


def _render(cwd: Path, session: str) -> str:
    meta = plib.parse_meta(cwd)
    if not meta:
        return ""
    name = truncate(meta.get("COURSE_NAME", "course"))
    days = plib.days_until(meta.get("EXAM_DATE", ""))
    phase = plib.phase(cwd, days)
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
