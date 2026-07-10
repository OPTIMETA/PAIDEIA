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
Workspace repairs (directories, log seed, settings.json) run **only in course
mode** (`.course-meta` present): in global mode `--fix` restores the +x bits
and nothing else, so running it in an arbitrary folder never scaffolds a
course skeleton there.

Invoked by the /paideia:doctor slash command, which reads the JSON/text and
narrates the result in the course's INTERFACE_LANG.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paideia_lib as plib  # noqa: E402  (shared .course-meta parsing)

OLLAMA_MODEL = "qwen3-vl:8b"

# FND-003: 검산 의존성 단일 출처 상수 (check_verify / check_antlr4 / install_verify_deps 공유).
# 핀 버전은 08 §2.3 문서와 동기화. fix_cmd 조립도 이 상수에서만.
VERIFY_INSTALL_SPEC = [
    "math-verify==0.9.0",
    "latex2sympy2_extended==1.11.0",
    "sympy",
    "antlr4-python3-runtime>=4.13",
]

# Python deps, graded by what actually needs them. The old flat REQUIRED_PY
# hard-failed on pdfplumber/pypdf — libraries the vision pipeline deliberately
# abandoned — which contradicted the plugin's own routing decision.
#   core:     pdf2image + PIL — every render path (/ingest, /grade) needs these.
#   ocr:      pytesseract — required by OCR_ENGINE=ollama (its fallback tier)
#             and =tesseract; merely useful otherwise.
#   optional: reportlab (/cheatsheet --pdf only), pypdf + pdfplumber (ad-hoc
#             merge/split/text-dump work outside the vision pipeline).
#   verify:   math-verify/sympy/latex2sympy2_extended — optional symbolic mode.
#             Absent → StudyView/GradeView hide symbolic mode and fall back to
#             strategy grading (03 §1.6 "정직한 강등"). Never a blocker.
CORE_PY = ["pdf2image", "PIL"]
OCR_PY = ["pytesseract"]
OPTIONAL_PY = ["reportlab", "pypdf", "pdfplumber"]
VERIFY_PY = ["sympy", "math_verify", "latex2sympy2_extended"]  # 03 §1.6 probe set
# antlr4-python3-runtime: latex2sympy2_extended의 런타임 의존 (05-5 §A-3).
# VERIFY_PY와 별도 프로브 — 패키지명이 "antlr4" 임포트와 다름(antlr4-python3-runtime).
ANTLR4_PY = ["antlr4"]  # pip install antlr4-python3-runtime
# FND-024: poppler 폴백용 래스터라이저 (BSD-3-Clause/Apache-2.0, AGPL 미포함).
# 존재 시 poppler 부재를 FAIL → WARN으로 강등.
RENDER_FALLBACK_PY = ["pypdfium2"]  # pip install pypdfium2

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

VALID_ENGINES = plib.VALID_ENGINES
VALID_LANGS = plib.VALID_LANGS

# Writable paths that downstream commands depend on (only the ones that should
# already exist; `--fix` creates the rest, then this re-checks).
WRITABLE_PATHS = [".", "converted", "answers/converted", "errors"]

# Seed for errors/log.md — canonical text lives in paideia_lib, identical to
# what init-course Step 4 writes, so /grade and /weakmap find the schema they
# expect.
ERRORS_LOG_SEED = plib.ERRORS_LOG_SEED

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
# .course-meta parsing — single source of truth in paideia_lib
# --------------------------------------------------------------------------- #

parse_meta = plib.parse_meta


def engine_of(meta: dict[str, str]) -> str | None:
    e = meta.get("OCR_ENGINE", "").lower()
    return e if e in VALID_ENGINES else None


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #

def _py_missing(mods: list[str]) -> list[str]:
    missing = []
    for mod in mods:
        rc, _ = run([sys.executable, "-c", f"import {mod}"], timeout=20)
        if rc != 0:
            missing.append(mod)
    return missing


def check_python(engine: str | None) -> list[Result]:
    """Three graded results instead of one flat FAIL — severity follows what
    the missing module actually blocks (mirrors the OCR-binary grading)."""
    pip = "python3 -m pip install --break-system-packages --user"
    results: list[Result] = []

    core_missing = _py_missing(CORE_PY)
    if core_missing:
        results.append(Result(
            "python_core", "Python deps (core)", FAIL,
            L(f"missing: {', '.join(core_missing)} — every ingest/grade render path needs these",
              f"누락: {', '.join(core_missing)} — 모든 ingest/grade 렌더 경로가 사용"),
            L(f"{pip} pdf2image pillow", f"{pip} pdf2image pillow"),
        ))
    else:
        results.append(Result("python_core", "Python deps (core)", OK))

    ocr_missing = _py_missing(OCR_PY)
    if ocr_missing:
        sev = _ocr_severity(engine, {"ollama", "tesseract"})
        note_en = "pytesseract missing — needed by OCR_ENGINE=ollama (fallback tier) and =tesseract"
        note_ko = "pytesseract 누락 — OCR_ENGINE=ollama(폴백 티어)·tesseract 에 필요"
        if sev == WARN:
            note_en += " (optional for OCR_ENGINE=claude)"
            note_ko += " (OCR_ENGINE=claude 에선 선택)"
        results.append(Result(
            "python_ocr", "Python deps (pytesseract)", sev,
            L(note_en, note_ko),
            L(f"{pip} pytesseract", f"{pip} pytesseract"),
        ))
    else:
        results.append(Result("python_ocr", "Python deps (pytesseract)", OK))

    opt_missing = _py_missing(OPTIONAL_PY)
    if opt_missing:
        results.append(Result(
            "python_optional", "Python deps (optional)", WARN,
            L(f"missing: {', '.join(opt_missing)} — reportlab: /cheatsheet --pdf; "
              "pypdf/pdfplumber: ad-hoc PDF ops only (the vision pipeline doesn't use them)",
              f"누락: {', '.join(opt_missing)} — reportlab: /cheatsheet --pdf 전용; "
              "pypdf/pdfplumber: 임시 PDF 작업 전용 (비전 파이프라인은 미사용)"),
            L(f"{pip} {' '.join(opt_missing)}", f"{pip} {' '.join(opt_missing)}"),
        ))
    else:
        results.append(Result("python_optional", "Python deps (optional)", OK))

    return results


def check_poppler() -> Result:
    """poppler(pdftoppm) 존재 확인.

    FND-024: poppler 부재라도 pypdfium2 폴백 래스터라이저(BSD/Apache)가 존재하면
    FAIL → WARN으로 강등하고 폴백 안내를 포함. 둘 다 없으면 FAIL 유지.
    """
    if has_bin("pdftoppm"):
        return Result("poppler", "poppler (pdftoppm)", OK)
    pdfium_missing = _py_missing(RENDER_FALLBACK_PY)
    if not pdfium_missing:
        # poppler 없음이나 pypdfium2 폴백 가능 → WARN
        return Result(
            "poppler", "poppler (pdftoppm)", WARN,
            L(
                "not found — pypdfium2 fallback renderer active (PDF rendering will work, "
                "but install poppler for best quality)",
                "없음 — pypdfium2 폴백 렌더러 활성 (PDF 렌더링 가능하나 "
                "품질 최적화를 위해 poppler 설치 권장)",
            ),
            install_hint("brew install poppler", "sudo apt-get install poppler-utils"),
        )
    return Result(
        "poppler", "poppler (pdftoppm)", FAIL,
        L(
            "not found — every OCR engine renders pages with it; "
            "install pypdfium2 as a fallback or poppler for primary rendering",
            "없음 — 모든 OCR 엔진이 페이지 렌더링에 사용; "
            "pypdfium2 폴백 또는 poppler 기본 설치 필요",
        ),
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


def check_verify() -> Result:
    """Probe sympy + math_verify + latex2sympy2_extended (03 §1.6, gate 4).

    Absence is always WARN, never FAIL: symbolic mode is silently hidden and
    strategy grading is used instead (honest downgrade).  Install hint pins
    the versions documented in 08 §2.3 via VERIFY_INSTALL_SPEC (단일 출처).
    """
    missing = _py_missing(VERIFY_PY)
    if not missing:
        return Result("verify_deps", "verify deps (sympy / math-verify)", OK)
    detail_en = (
        f"missing: {', '.join(missing)} — symbolic step verification unavailable; "
        "StudyView/GradeView will hide symbolic mode and use strategy grading only. "
        "Run `/paideia:doctor --install-verify` to install with one click."
    )
    detail_ko = (
        f"누락: {', '.join(missing)} — 기호 단계 검증 불가; "
        "StudyView/GradeView 가 symbolic 모드를 숨기고 전략 채점만 사용. "
        "`/paideia:doctor --install-verify` 로 원클릭 설치."
    )
    # fix_cmd 조립: VERIFY_INSTALL_SPEC 단일 출처 (antlr4 포함)
    _pip = "python3 -m pip install --break-system-packages --user"
    _specs = " ".join(f'"{s}"' for s in VERIFY_INSTALL_SPEC)
    fix_cmd = f"{_pip} {_specs}"
    return Result(
        "verify_deps",
        "verify deps (sympy / math-verify)",
        WARN,
        L(detail_en, detail_ko),
        L(fix_cmd, fix_cmd),
    )


def check_antlr4() -> Result:
    """Probe antlr4-python3-runtime — latex2sympy2_extended 런타임 의존 (05-5 §A-3).

    latex2sympy2_extended 는 ANTLR4 파서를 런타임에 사용한다. antlr4-python3-runtime이
    없으면 verify_math.py의 LaTeX 파싱이 실패한다.
    Absence는 WARN (softVerify=off이면 미사용 경로). install hint는 VERIFY_INSTALL_SPEC 단일 출처.
    """
    missing = _py_missing(ANTLR4_PY)
    if not missing:
        return Result("antlr4_runtime", "antlr4-python3-runtime", OK)
    detail_en = (
        "antlr4-python3-runtime missing — verify_math.py LaTeX parsing unavailable; "
        "2nd Verification (softVerify) will silently skip. "
        "Run `/paideia:doctor --install-verify` to install with one click."
    )
    detail_ko = (
        "antlr4-python3-runtime 누락 — verify_math.py LaTeX 파싱 불가; "
        "2차 검증(softVerify)이 조용히 건너뜀. "
        "`/paideia:doctor --install-verify` 로 원클릭 설치."
    )
    # fix_cmd 조립: VERIFY_INSTALL_SPEC 단일 출처 (antlr4 포함)
    _pip = "python3 -m pip install --break-system-packages --user"
    _specs = " ".join(f'"{s}"' for s in VERIFY_INSTALL_SPEC)
    fix_cmd = f"{_pip} {_specs}"
    return Result(
        "antlr4_runtime",
        "antlr4-python3-runtime",
        WARN,
        L(detail_en, detail_ko),
        L(fix_cmd, fix_cmd),
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

    def _script_path(cmd: str) -> str:
        """Last argv token of a shell command — shlex-parsed so quoted paths
        with spaces resolve, and a bare `python3 <path>` wrapper is skipped."""
        try:
            toks = shlex.split(cmd)
        except ValueError:
            toks = cmd.split()
        return toks[-1] if toks else ""

    sl = (data.get("statusLine") or {}).get("command", "")
    if sl:
        slp = Path(_script_path(sl))
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
        tok = _script_path(cmd)
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

    results: list[Result] = check_python(engine)
    results += [
        check_poppler(),
        check_tesseract(engine),
        check_tesseract_kor(engine),
    ]
    results += check_ollama(engine)
    results.append(check_verify())  # 03 §1.6 symbolic mode probe — always after ollama
    results.append(check_antlr4())  # 05-5 §A-3: latex2sympy2_extended 런타임 의존

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
# FND-003: --install-verify: 동의 기반 검산 의존성 설치
# --------------------------------------------------------------------------- #

def install_verify_deps() -> dict[str, str]:
    """VERIFY_INSTALL_SPEC 패키지를 `python3 -m pip install --user --break-system-packages`로
    설치한다. `--install-verify` 플래그가 명시될 때만 호출된다(동의 게이트).

    반환: L(en, ko) action 딕트 (성공/실패 정직 보고).

    설계 근거:
    - `sys.executable`로 자기참조 → 새 프로그램 스폰 아님, PROGRAM_ALLOWLIST 불변.
    - `--user --break-system-packages`: verify_tool.py / grade.md 가 시스템 python3를
      스폰하는 경로와 일치. venv 부트스트랩은 스폰 경로 불일치로 채택 안 함.
    - `--fix` 단독은 이 함수를 호출하지 않는다 (기존 "never runs pip" 불변식 유지).
    """
    cmd = [sys.executable, "-m", "pip", "install", "--user",
           "--break-system-packages", *VERIFY_INSTALL_SPEC]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return L(
                "installed verify deps: " + ", ".join(VERIFY_INSTALL_SPEC),
                "검산 의존성 설치 완료: " + ", ".join(VERIFY_INSTALL_SPEC),
            )
        else:
            stderr_snippet = (result.stderr or "")[:200]
            return L(
                f"FAILED to install verify deps (exit {result.returncode}): {stderr_snippet}",
                f"검산 의존성 설치 실패 (exit {result.returncode}): {stderr_snippet}",
            )
    except subprocess.TimeoutExpired:
        return L(
            "FAILED to install verify deps: pip timed out after 300 s",
            "검산 의존성 설치 실패: pip 300초 초과",
        )
    except Exception as exc:  # noqa: BLE001
        return L(
            f"FAILED to install verify deps: {exc}",
            f"검산 의존성 설치 실패: {exc}",
        )


# --------------------------------------------------------------------------- #
# --fix: permission-free repairs only
# --------------------------------------------------------------------------- #

def _extract_header_comment(text: str) -> str:
    """Return the '<!-- … -->' block from text, or '' if absent."""
    start = text.find("<!--")
    if start == -1:
        return ""
    end = text.find("-->", start)
    if end == -1:
        return ""
    return text[start:end + 3]


def _normalize_log_header(log: Path) -> list[dict[str, str]]:
    """If log's header comment drifts from ERRORS_LOG_SEED, replace it.

    Only the '<!-- … -->' preamble is rewritten; data entries (everything
    after the closing '-->') are preserved byte-for-byte. Write is atomic
    (tmp + os.replace). Returns a list of zero or one action dicts.
    """
    import tempfile
    try:
        text = log.read_text(encoding="utf-8")
    except OSError:
        return []

    canonical_header = _extract_header_comment(ERRORS_LOG_SEED)
    live_header = _extract_header_comment(text)

    if live_header == canonical_header:
        return []  # already correct — nothing to do

    if not live_header:
        # No header comment at all: prepend seed header before any entries.
        after_preamble = text
    else:
        # Replace existing header in-place; keep everything after the old '-->'
        end = text.find("-->") + 3
        after_preamble = text[end:]

    # Rebuild: canonical preamble (ERRORS_LOG_SEED, which ends with '-->\n') +
    # the original post-'-->' bytes. The old '-->' line's own trailing newline
    # is already supplied by the seed's trailing '\n', so strip exactly ONE
    # leading newline from the retained data — not all of them. lstrip('\n')
    # would collapse the blank-line separator that a fresh seed+append keeps
    # between '-->' and the first '- problem_id:' entry (\n\n), producing a
    # body layout that differs from a freshly seeded file; stripping a single
    # newline preserves that exact separator, so normalization is a pure header
    # replacement (the entry region is byte-identical before and after).
    if after_preamble.startswith("\n"):
        after_preamble = after_preamble[1:]
    new_text = ERRORS_LOG_SEED + after_preamble

    try:
        fd, tmp_path = tempfile.mkstemp(dir=log.parent, prefix=".log_hdr_fix_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            os.replace(tmp_path, log)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return [L(f"FAILED to normalize errors/log.md header ({e})",
                  f"errors/log.md 헤더 정규화 실패 ({e})")]

    return [L("normalized errors/log.md header to canonical seed",
              "errors/log.md 헤더를 정본 시드로 정규화")]


def apply_fixes(cwd: Path) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []

    # Workspace repairs are gated on course mode. Without this guard,
    # `/paideia:doctor --fix` run in an arbitrary folder (home dir, another
    # project) would scaffold all 18 course directories + errors/log.md +
    # .claude/settings.json right there — creating a course skeleton is
    # init-course's job, done deliberately, not a side effect of a diagnostic.
    course_mode = (cwd / ".course-meta").is_file()

    if course_mode:
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

        # 2. seed or normalize-header errors/log.md
        log = cwd / "errors" / "log.md"
        if not log.is_file():
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(ERRORS_LOG_SEED, encoding="utf-8")
                actions.append(L("seeded errors/log.md", "errors/log.md 시드 생성"))
            except OSError as e:
                actions.append(L(f"FAILED to seed errors/log.md ({e})",
                                 f"errors/log.md 시드 실패 ({e})"))
        else:
            # Normalize header comment when it drifts from canonical seed.
            # Data entries (lines after '-->') are preserved byte-for-byte;
            # only the '<!-- … -->' preamble is replaced. Atomic write (tmp +
            # os.replace) so a crash mid-write never corrupts the log.
            actions += _normalize_log_header(log)
    else:
        actions.append(L(
            "skipped workspace repairs — no .course-meta here (global mode); "
            "use /paideia:init-course to create a course folder",
            "워크스페이스 복구 건너뜀 — .course-meta 없음(글로벌 모드); "
            "코스 폴더 생성은 /paideia:init-course 사용"))

    # 3. restore +x on plugin scripts (safe in both modes — targets the plugin
    #    install, not CWD) + 4. rewrite settings.json wiring (course mode only)
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
        if course_mode and statusline.is_file() and session_start.is_file():
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
    # shlex.quote adds quotes only when the path needs them (spaces etc.), so
    # existing unquoted-but-identical configs don't churn.
    want_sl = shlex.quote(str(statusline))
    want_ss = f"python3 {shlex.quote(str(session_start))}"
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
    # verify_reachable: True only when BOTH verify_deps AND antlr4_runtime are OK.
    # init-course/grade read this single field to decide "symbolic grading reachable"
    # without parsing individual check entries — decouples callers from check key names.
    _verify_ok = all(
        r.status == OK
        for r in results
        if r.key in ("verify_deps", "antlr4_runtime")
    )
    payload = {
        "course_mode": course_mode,
        "overall": overall_status(results),
        "ocr_engine": meta.get("OCR_ENGINE"),
        "interface_lang": meta.get("INTERFACE_LANG"),
        "verify_reachable": _verify_ok,
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
    ap.add_argument("--install-verify", action="store_true",
                    help="install symbolic-verification deps (math-verify, sympy, antlr4) "
                         "via `python3 -m pip install --user --break-system-packages`; "
                         "requires explicit consent — --fix alone never runs pip")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--lang", default=None, help="override INTERFACE_LANG (en|ko)")
    args = ap.parse_args(argv)

    cwd = Path.cwd()

    fixes: list[dict[str, str]] | None = None
    if args.fix:
        fixes = apply_fixes(cwd)
    # --install-verify: 동의 명시 플래그 시에만 pip 실행 (--fix 단독은 pip 미실행).
    if args.install_verify:
        if fixes is None:
            fixes = []
        fixes.append(install_verify_deps())

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
