#!/usr/bin/env python3
"""
PAIDEIA doctor — diagnose a course workspace and the install it depends on, so
someone who cloned the plugin but can't get a command to run has one place to
look. Checks Python deps, poppler, tesseract (+kor), Ollama/Qwen3-VL, the course
directory skeleton, `.course-meta`, writable paths, and the statusline /
SessionStart wiring.

This is the single source of truth for "can paideia actually run here?". The
severity of each OCR dependency is graded against the course's OCR_ENGINE —
poppler is required by every engine (the default `claude` path renders pages
with `pdftoppm`), but tesseract only matters for `ollama` (its fallback) and
`tesseract`, and the Ollama daemon/model only matter for `ollama`.

Usage:
    python3 doctor.py            # diagnose only; exit 0=ok 1=warn 2=fail
    python3 doctor.py --fix      # apply permission-free repairs, then re-check
    python3 doctor.py --json     # machine-readable report on stdout

`--fix` only touches things that never need sudo: it creates missing course
directories, seeds `errors/log.md`, restores the +x bit on plugin scripts, and
rewrites the absolute paths in `.claude/settings.json` (using CLAUDE_PLUGIN_ROOT
from the environment). It never runs brew / apt / pip and never guesses
`.course-meta` values — those are printed as copy-paste commands instead.

Invoked by the /paideia:doctor slash command, which reads the JSON/text and
narrates the result in the course's INTERFACE_LANG.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

OLLAMA_MODEL = "qwen3-vl:8b"

REQUIRED_PY = ["pypdf", "pdfplumber", "pytesseract", "pdf2image", "PIL", "reportlab"]

# The exact directory set created by /paideia:init-course Step 4. Kept in sync so
# `--fix` recreates precisely what bootstrap would have.
COURSE_DIRS = [
    "materials/lectures", "materials/textbook", "materials/homework", "materials/solutions",
    "converted/lectures", "converted/textbook", "converted/homework", "converted/solutions",
    "course-index", "quizzes", "mock", "twins", "chain", "derivations", "cheatsheet",
    "weakmap", "answers/converted", "errors",
]

META_KEYS = [
    "COURSE_NAME", "EXAM_DATE", "EXAM_TYPE", "USER_WEAK_ZONES", "OCR_ENGINE", "INTERFACE_LANG",
]

VALID_ENGINES = {"claude", "ollama", "tesseract"}
VALID_LANGS = {"en", "ko"}

# Writable paths that downstream commands depend on (only the ones that should
# already exist; `--fix` creates the rest, then this re-checks).
WRITABLE_PATHS = [".", "converted", "answers/converted", "errors"]

# Seed for errors/log.md — identical to init-course Step 4 so /grade and /weakmap
# find the schema they expect.
ERRORS_LOG_SEED = """# Error log

<!-- Append-only YAML entries. Schema:
- problem_id: <id>
  pattern: <Pk>
  error_type: pattern-missed | wrong-variable | wrong-end-form | algebraic | sign | definition
  summary: "<1 line>"
  source: <answers/converted/<name>.md | blind/<id> | chain/<ts>>
  date: <ISO8601>
-->
"""

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
_ICON = {OK: "✓", WARN: "⚠", FAIL: "✗", SKIP: "·"}


def L(en: str, ko: str) -> dict[str, str]:
    return {"en": en, "ko": ko}


def pick(d: dict[str, str] | None, lang: str) -> str:
    if not d:
        return ""
    return d.get(lang) or d.get("en", "")


class Result:
    """One diagnostic line. `detail`/`fix` are {en,ko} dicts (fix optional)."""

    def __init__(self, key: str, label: str, status: str,
                 detail: dict[str, str] | None = None,
                 fix: dict[str, str] | None = None):
        self.key = key
        self.label = label
        self.status = status
        self.detail = detail or {}
        self.fix = fix

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "detail": self.detail, "fix": self.fix,
        }


# --------------------------------------------------------------------------- #
# small shell / env helpers
# --------------------------------------------------------------------------- #

def os_family() -> str:
    s = platform.system()
    if s == "Darwin":
        return "macos"
    if s == "Linux":
        return "linux"
    return "other"


def has_bin(name: str) -> bool:
    from shutil import which
    return which(name) is not None


def run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def install_hint(macos: str, ubuntu: str) -> dict[str, str]:
    """Build an OS-aware install line; show both when the OS is unknown."""
    fam = os_family()
    if fam == "macos":
        body = macos
    elif fam == "linux":
        body = ubuntu
    else:
        body = f"macOS: {macos}\n    Ubuntu: {ubuntu}"
    return L(body, body)


# --------------------------------------------------------------------------- #
# .course-meta parsing (mirrors session_start.parse_meta)
# --------------------------------------------------------------------------- #

def parse_meta(cwd: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    p = cwd / ".course-meta"
    if not p.exists():
        return meta
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(.+?)\s*$", line)
            if m:
                # strip trailing "# comment" the way session_start does for lang
                meta[m.group(1)] = m.group(2).split("#", 1)[0].strip()
    except OSError:
        pass
    return meta


def engine_of(meta: dict[str, str]) -> str | None:
    e = meta.get("OCR_ENGINE", "").lower()
    return e if e in VALID_ENGINES else None


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #

def check_python() -> Result:
    missing = []
    for mod in REQUIRED_PY:
        rc, _ = run([sys.executable, "-c", f"import {mod}"], timeout=20)
        if rc != 0:
            missing.append(mod)
    if not missing:
        return Result("python_deps", "Python deps", OK)
    pkgs = "pypdf pdfplumber pytesseract pdf2image pillow reportlab"
    return Result(
        "python_deps", "Python deps", FAIL,
        L(f"missing: {', '.join(missing)}", f"누락: {', '.join(missing)}"),
        L(f"python3 -m pip install --break-system-packages --user {pkgs}",
          f"python3 -m pip install --break-system-packages --user {pkgs}"),
    )


def check_poppler() -> Result:
    if has_bin("pdftoppm"):
        return Result("poppler", "poppler (pdftoppm)", OK)
    return Result(
        "poppler", "poppler (pdftoppm)", FAIL,
        L("not found — every OCR engine renders pages with it",
          "없음 — 모든 OCR 엔진이 페이지 렌더링에 사용"),
        install_hint("brew install poppler", "sudo apt-get install poppler-utils"),
    )


def _ocr_severity(engine: str | None, needs: set[str]) -> str:
    """FAIL if the active engine needs this dep, WARN otherwise (still useful as
    a fallback). In global mode (engine is None) downgrade to WARN."""
    if engine is None:
        return WARN
    return FAIL if engine in needs else WARN


def check_tesseract(engine: str | None) -> Result:
    sev = _ocr_severity(engine, {"ollama", "tesseract"})
    if has_bin("tesseract"):
        return Result("tesseract", "tesseract", OK)
    note_en = "not found"
    note_ko = "없음"
    if sev == WARN:
        note_en += " (optional for OCR_ENGINE=claude; needed if you switch engines)"
        note_ko += " (OCR_ENGINE=claude 에선 선택; 엔진 변경 시 필요)"
    return Result(
        "tesseract", "tesseract", sev,
        L(note_en, note_ko),
        install_hint("brew install tesseract tesseract-lang",
                     "sudo apt-get install tesseract-ocr tesseract-ocr-kor"),
    )


def check_tesseract_kor(engine: str | None) -> Result:
    if not has_bin("tesseract"):
        return Result("tesseract_kor", "tesseract kor langdata", SKIP,
                      L("skipped — tesseract not installed",
                        "건너뜀 — tesseract 미설치"))
    sev = _ocr_severity(engine, {"ollama", "tesseract"})
    _, out = run(["tesseract", "--list-langs"], timeout=15)
    if re.search(r"^kor$", out, re.MULTILINE):
        return Result("tesseract_kor", "tesseract kor langdata", OK)
    return Result(
        "tesseract_kor", "tesseract kor langdata", sev,
        L("'kor' trained data missing — Korean handwriting OCR will fail",
          "'kor' 학습 데이터 없음 — 한국어 필기 OCR 실패"),
        install_hint("brew install tesseract-lang",
                     "sudo apt-get install tesseract-ocr-kor"),
    )


def check_ollama(engine: str | None) -> list[Result]:
    """Daemon + model. Only FAIL when the course actually uses ollama; otherwise
    SKIP (it is strictly optional)."""
    relevant = engine == "ollama"
    if not has_bin("ollama"):
        if relevant:
            return [Result(
                "ollama", f"ollama + {OLLAMA_MODEL}", FAIL,
                L("OCR_ENGINE=ollama but the ollama binary is not installed",
                  "OCR_ENGINE=ollama 인데 ollama 바이너리 미설치"),
                install_hint("brew install ollama",
                             "curl -fsSL https://ollama.com/install.sh | sh"),
            )]
        return [Result("ollama", f"ollama + {OLLAMA_MODEL}", SKIP,
                       L("not installed (optional — only for OCR_ENGINE=ollama)",
                         "미설치 (선택 — OCR_ENGINE=ollama 전용)"))]

    sev = FAIL if relevant else WARN
    results: list[Result] = []
    # daemon
    daemon_up = False
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            daemon_up = r.status == 200
    except Exception:
        daemon_up = False
    if not daemon_up:
        results.append(Result(
            "ollama_daemon", "ollama daemon", sev,
            L("not responding on :11434", "11434 포트 응답 없음"),
            L("ollama serve &", "ollama serve &"),
        ))
        # can't reliably check model if daemon is down
        results.append(Result("ollama_model", f"{OLLAMA_MODEL}", SKIP,
                              L("skipped — daemon down", "건너뜀 — 데몬 꺼짐")))
        return results
    results.append(Result("ollama_daemon", "ollama daemon", OK))
    # model
    _, out = run(["ollama", "list"], timeout=15)
    if any(line.split()[:1] == [OLLAMA_MODEL] for line in out.splitlines() if line.strip()):
        results.append(Result("ollama_model", f"{OLLAMA_MODEL}", OK))
    else:
        results.append(Result(
            "ollama_model", f"{OLLAMA_MODEL}", sev,
            L("model not pulled (~6 GB)", "모델 미다운로드 (~6 GB)"),
            L(f"ollama pull {OLLAMA_MODEL}", f"ollama pull {OLLAMA_MODEL}"),
        ))
    return results


def check_course_dirs(cwd: Path) -> Result:
    missing = [d for d in COURSE_DIRS if not (cwd / d).is_dir()]
    if not missing:
        return Result("course_dirs", "course directories", OK)
    return Result(
        "course_dirs", "course directories", FAIL,
        L(f"{len(missing)} missing: {', '.join(missing)}",
          f"{len(missing)}개 누락: {', '.join(missing)}"),
        L("/paideia:doctor --fix   (or re-run /paideia:init-course)",
          "/paideia:doctor --fix   (또는 /paideia:init-course 재실행)"),
    )


def check_meta(cwd: Path, meta: dict[str, str]) -> Result:
    problems_en: list[str] = []
    problems_ko: list[str] = []
    for k in META_KEYS:
        if k not in meta or not meta[k]:
            problems_en.append(f"missing {k}")
            problems_ko.append(f"{k} 누락")
    # value validation (only when present)
    eng = meta.get("OCR_ENGINE", "").lower()
    if eng and eng not in VALID_ENGINES:
        problems_en.append(f"OCR_ENGINE='{meta['OCR_ENGINE']}' invalid")
        problems_ko.append(f"OCR_ENGINE='{meta['OCR_ENGINE']}' 잘못됨")
    lang = meta.get("INTERFACE_LANG", "").lower()
    if lang and lang not in VALID_LANGS:
        problems_en.append(f"INTERFACE_LANG='{meta['INTERFACE_LANG']}' invalid")
        problems_ko.append(f"INTERFACE_LANG='{meta['INTERFACE_LANG']}' 잘못됨")
    ed = meta.get("EXAM_DATE", "")
    if ed and not re.match(r"^\d{4}-\d{2}-\d{2}$", ed):
        problems_en.append(f"EXAM_DATE='{ed}' not YYYY-MM-DD")
        problems_ko.append(f"EXAM_DATE='{ed}' YYYY-MM-DD 아님")
    if not problems_en:
        return Result("course_meta", ".course-meta", OK)
    return Result(
        "course_meta", ".course-meta", FAIL,
        L("; ".join(problems_en), "; ".join(problems_ko)),
        L("edit .course-meta by hand (doctor will not guess these values)",
          ".course-meta 직접 수정 (doctor는 값을 추측하지 않음)"),
    )


def check_errors_log(cwd: Path) -> Result:
    if (cwd / "errors" / "log.md").is_file():
        return Result("errors_log", "errors/log.md", OK)
    return Result(
        "errors_log", "errors/log.md", FAIL,
        L("missing — /grade and /weakmap append here",
          "없음 — /grade·/weakmap 이 기록하는 파일"),
        L("/paideia:doctor --fix", "/paideia:doctor --fix"),
    )


def check_writable(cwd: Path) -> Result:
    bad = []
    for rel in WRITABLE_PATHS:
        p = cwd / rel
        if p.exists() and not os.access(p, os.W_OK):
            bad.append(rel)
    if not bad:
        return Result("writable", "writable paths", OK)
    return Result(
        "writable", "writable paths", FAIL,
        L(f"not writable: {', '.join(bad)}", f"쓰기 불가: {', '.join(bad)}"),
        install_hint(f"chmod u+w {' '.join(bad)}", f"chmod u+w {' '.join(bad)}"),
    )


def _settings_paths(cwd: Path) -> Path:
    return cwd / ".claude" / "settings.json"


def check_wiring(cwd: Path) -> Result:
    """statusLine + SessionStart in .claude/settings.json must point at scripts
    that actually exist and are executable. This catches the 'plugin moved /
    reinstalled at a new path' failure mode that init-course warns about."""
    sp = _settings_paths(cwd)
    if not sp.is_file():
        return Result(
            "wiring", "statusline/hook wiring", WARN,
            L(".claude/settings.json absent — no statusline / SessionStart reminder",
              ".claude/settings.json 없음 — statusline·SessionStart 미작동"),
            L("/paideia:doctor --fix   (needs the plugin loaded)",
              "/paideia:doctor --fix   (플러그인 로드 상태 필요)"),
        )
    try:
        data = json.loads(sp.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return Result("wiring", "statusline/hook wiring", FAIL,
                      L(".claude/settings.json is not valid JSON",
                        ".claude/settings.json JSON 파싱 실패"),
                      L("/paideia:doctor --fix", "/paideia:doctor --fix"))

    problems_en: list[str] = []
    problems_ko: list[str] = []

    sl = (data.get("statusLine") or {}).get("command", "")
    if sl:
        slp = Path(sl)
        if not slp.is_file():
            problems_en.append("statusLine path does not exist")
            problems_ko.append("statusLine 경로 없음")
        elif not os.access(slp, os.X_OK):
            problems_en.append("statusLine script not executable")
            problems_ko.append("statusLine 스크립트 실행권한 없음")

    # hooks.SessionStart[].hooks[].command — typically "python3 /abs/path.py"
    ss_cmds: list[str] = []
    for blk in (data.get("hooks", {}).get("SessionStart") or []):
        for h in blk.get("hooks", []):
            if h.get("command"):
                ss_cmds.append(h["command"])
    for cmd in ss_cmds:
        # last whitespace-separated token is the script path
        tok = cmd.split()[-1] if cmd.split() else ""
        if tok and not Path(tok).is_file():
            problems_en.append("SessionStart script path does not exist")
            problems_ko.append("SessionStart 스크립트 경로 없음")

    if not problems_en:
        return Result("wiring", "statusline/hook wiring", OK)
    return Result(
        "wiring", "statusline/hook wiring", FAIL,
        L("; ".join(problems_en) + " (plugin likely moved)",
          "; ".join(problems_ko) + " (플러그인 이동 추정)"),
        L("/paideia:doctor --fix   (rewrites paths from CLAUDE_PLUGIN_ROOT)",
          "/paideia:doctor --fix   (CLAUDE_PLUGIN_ROOT 기준 경로 재작성)"),
    )


def run_checks(cwd: Path) -> tuple[list[Result], dict[str, str], bool]:
    """Returns (results, meta, course_mode)."""
    meta = parse_meta(cwd)
    # Course mode keys on the file's *existence*, not on whether it parsed any
    # keys — an empty or corrupted .course-meta means the user is in a course
    # folder with a broken setup, which check_meta should flag, not silently
    # demote to global mode.
    course_mode = (cwd / ".course-meta").is_file()
    engine = engine_of(meta)

    results: list[Result] = [
        check_python(),
        check_poppler(),
        check_tesseract(engine),
        check_tesseract_kor(engine),
    ]
    results += check_ollama(engine)

    if course_mode:
        results.append(check_course_dirs(cwd))
        results.append(check_meta(cwd, meta))
        results.append(check_errors_log(cwd))
        results.append(check_writable(cwd))
        results.append(check_wiring(cwd))
    else:
        results.append(check_writable(cwd))

    return results, meta, course_mode


# --------------------------------------------------------------------------- #
# --fix: permission-free repairs only
# --------------------------------------------------------------------------- #

def apply_fixes(cwd: Path) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []

    # 1. course directories
    for d in COURSE_DIRS:
        p = cwd / d
        if not p.is_dir():
            try:
                p.mkdir(parents=True, exist_ok=True)
                actions.append(L(f"created {d}/", f"{d}/ 생성"))
            except OSError as e:
                actions.append(L(f"FAILED to create {d}/ ({e})",
                                 f"{d}/ 생성 실패 ({e})"))

    # 2. seed errors/log.md
    log = cwd / "errors" / "log.md"
    if not log.is_file():
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(ERRORS_LOG_SEED, encoding="utf-8")
            actions.append(L("seeded errors/log.md", "errors/log.md 시드 생성"))
        except OSError as e:
            actions.append(L(f"FAILED to seed errors/log.md ({e})",
                             f"errors/log.md 시드 실패 ({e})"))

    # 3. restore +x on plugin scripts + 4. rewrite settings.json wiring
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if root:
        statusline = Path(root) / "scripts" / "statusline.py"
        session_start = Path(root) / "scripts" / "session_start.py"
        for s in (statusline, session_start, Path(root) / "scripts" / "doctor.py"):
            if s.is_file() and not os.access(s, os.X_OK):
                try:
                    s.chmod(s.stat().st_mode | 0o111)
                    actions.append(L(f"chmod +x {s.name}", f"{s.name} 실행권한 부여"))
                except OSError:
                    pass
        if statusline.is_file() and session_start.is_file():
            _rewrite_wiring(cwd, statusline, session_start, actions)
    else:
        actions.append(L(
            "skipped wiring fix — CLAUDE_PLUGIN_ROOT unset (run via /paideia:doctor)",
            "wiring 복구 건너뜀 — CLAUDE_PLUGIN_ROOT 미설정 (/paideia:doctor 로 실행)"))

    return actions


def _rewrite_wiring(cwd: Path, statusline: Path, session_start: Path,
                    actions: list[dict[str, str]]) -> None:
    """Write/repair .claude/settings.json with absolute script paths. Mirrors
    init-course Step 8: literal absolute paths, statusline via shebang,
    SessionStart via `python3 <path>`. Preserves any unrelated keys already in
    an existing settings.json."""
    sp = _settings_paths(cwd)
    sp.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if sp.is_file():
        try:
            data = json.loads(sp.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = {}
    want_sl = str(statusline)
    want_ss = f"python3 {session_start}"
    changed = False

    if (data.get("statusLine") or {}).get("command") != want_sl:
        data["statusLine"] = {"type": "command", "command": want_sl}
        changed = True

    hooks = data.setdefault("hooks", {})
    ss_block = [{
        "matcher": "startup|resume",
        "hooks": [{"type": "command", "command": want_ss}],
    }]
    # compare just the command string to avoid churning on cosmetic diffs
    cur = ""
    for blk in (hooks.get("SessionStart") or []):
        for h in blk.get("hooks", []):
            cur = h.get("command", "") or cur
    if cur != want_ss:
        hooks["SessionStart"] = ss_block
        changed = True

    if changed:
        try:
            sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            actions.append(L("rewrote .claude/settings.json paths",
                             ".claude/settings.json 경로 재작성"))
        except OSError as e:
            actions.append(L(f"FAILED to write settings.json ({e})",
                             f"settings.json 쓰기 실패 ({e})"))


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #

def overall_status(results: list[Result]) -> str:
    if any(r.status == FAIL for r in results):
        return FAIL
    if any(r.status == WARN for r in results):
        return WARN
    return OK


def exit_code(status: str) -> int:
    return {FAIL: 2, WARN: 1, OK: 0}[status]


def print_text(results: list[Result], lang: str, course_mode: bool,
               fixes: list[dict[str, str]] | None) -> None:
    out = sys.stdout
    mode = "course" if course_mode else "global (no .course-meta)"
    out.write(f"paideia doctor — {mode}\n")
    for r in results:
        out.write(f"{_ICON[r.status]} {r.label}\n")
        det = pick(r.detail, lang)
        if det and r.status != OK:
            out.write(f"    {det}\n")
        if r.fix and r.status in (WARN, FAIL):
            out.write(f"    → {pick(r.fix, lang)}\n")
    if fixes is not None:
        out.write("\n--fix applied:\n" if lang == "en" else "\n--fix 적용:\n")
        if not fixes:
            out.write("    (nothing to repair)\n" if lang == "en" else "    (복구할 항목 없음)\n")
        for a in fixes:
            out.write(f"    • {pick(a, lang)}\n")
    st = overall_status(results)
    tail = {OK: "all clear", WARN: "usable, with warnings", FAIL: "blocking issues"}
    tail_ko = {OK: "이상 없음", WARN: "사용 가능 (경고 있음)", FAIL: "차단 이슈 있음"}
    label = tail[st] if lang == "en" else tail_ko[st]
    out.write(f"\n{_ICON[st]} {label}\n")
    if not course_mode and st != OK:
        out.write(("Run /paideia:init-course in a course folder to set up the rest.\n")
                  if lang == "en" else
                  ("코스 폴더에서 /paideia:init-course 로 나머지를 설정하세요.\n"))


def print_json(results: list[Result], meta: dict[str, str], course_mode: bool,
               fixes: list[dict[str, str]] | None) -> None:
    payload = {
        "course_mode": course_mode,
        "overall": overall_status(results),
        "ocr_engine": meta.get("OCR_ENGINE"),
        "interface_lang": meta.get("INTERFACE_LANG"),
        "checks": [r.to_dict() for r in results],
    }
    if fixes is not None:
        payload["fixes"] = fixes
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--fix", action="store_true",
                    help="apply permission-free repairs, then re-check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--lang", default=None, help="override INTERFACE_LANG (en|ko)")
    args = ap.parse_args(argv)

    cwd = Path.cwd()

    fixes: list[dict[str, str]] | None = None
    if args.fix:
        fixes = apply_fixes(cwd)

    results, meta, course_mode = run_checks(cwd)

    lang = (args.lang or meta.get("INTERFACE_LANG", "en")).lower()
    if lang not in VALID_LANGS:
        lang = "en"

    if args.json:
        print_json(results, meta, course_mode, fixes)
    else:
        print_text(results, lang, course_mode, fixes)

    return exit_code(overall_status(results))


if __name__ == "__main__":
    sys.exit(main())
