---
description: Import an Exam Radar (OPTIMETA Alt plugin) export and fold its lecture-emphasis exam signal into the course index — radar.md, a lecture-emphasis column on coverage.md, and a gold-zone weakmap.
argument-hint: "[paste the Exam Radar copy, or leave empty to read materials/radar.md]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and the narrative parts of generated MDs — must be in that language. Keep in English regardless: file paths, slash command names, the `<!-- exam-radar:v1 ... -->` marker, table column headers (`Topic`, `Exam prob`, `Zone`, `Lecture emphasis`, `§`, `Title`, `HW coverage`, `Exam tier`), tier markers (🔥🔥/🔥/🟡/⚪), the 🎙 signal flag, pattern IDs (P1..Pk), and § / Ch anchors — downstream tools (`weakmap`, `hwmap`, `analyze`) regex on them.

Load `skills/alt-import/SKILL.md` and `skills/course-builder/SKILL.md` (the latter for the `coverage.md` schema you will annotate).

Arguments (the pasted Exam Radar export, may be multi-line): $ARGUMENTS

## What this is

Exam Radar is OPTIMETA's Alt plugin. It reads your lecture **recordings** and ranks topics by how much the professor **emphasized them out loud** — a second signal of exam probability, independent of PAIDEIA's HW density. Its 학습 로드맵 → 복사 button emits a fixed markdown form. This command folds that signal into `course-index/`.

HW density stays the primary exam-tier signal. Lecture emphasis is layered on as a **second opinion**: it corroborates where the two agree and flags blind spots where they diverge. It never silently rewrites the HW-based tier.

## Step 0 — Get the export

1. If `$ARGUMENTS` contains the export (look for `<!-- exam-radar:v1`), use it.
2. Else if `materials/radar.md` exists, read that.
3. Else: tell the user — "Exam Radar에서 **학습 로드맵 → 복사** 후 `/paideia:alt` 뒤에 붙여넣거나, `materials/radar.md`로 저장하세요." — then stop.
4. Validate the marker. No `<!-- exam-radar:v1` → not an Exam Radar export; stop. Version `> 1` → warn that this command parses v1 and may ignore new fields, then proceed best-effort.

## Pipeline

Follow `skills/alt-import/SKILL.md` end to end:

1. **Parse** the export (meta + the three zones, each topic as `{name} · 시험확률 {N}%` with optional `· 🎙`).
2. Write **`course-index/radar.md`** — the canonical lecture-emphasis store.
3. If **`course-index/coverage.md`** exists, **merge**: add a `Lecture emphasis` column to the reverse map, append a divergence section, and fold emphasis into drill priority — **without changing the HW-based `Exam tier`**. If it doesn't exist, skip and tell the user to run `/paideia:analyze` first.
4. Seed a **gold-zone weakmap** — write a new `weakmap/weakmap_<ts>.md` treating the gold zone as user-declared weaknesses (lecture-hot + self-weak).

## Idempotence

- `radar.md` — overwrite (snapshot of the latest Exam Radar state). Warn if it was hand-edited (`<!-- SOURCE: Exam Radar` header absent).
- `coverage.md` — the merge is re-runnable: replace the prior `Lecture emphasis` column and the `Lecture vs HW` / `From Exam Radar` sections rather than duplicating them.
- `weakmap/` — never overwrite; always a new timestamped file.

## Chat output

Print, prose in `INTERFACE_LANG`, identifiers verbatim:

```
Exam Radar 반영 완료 (<course>, <D-N>).

- course-index/radar.md     ← 토픽 <N>개 (골드존 <G> · 이미 다진 것 <S> · 버려도 안전 <D>)
- course-index/coverage.md  ← Lecture emphasis 열 추가, 발산 <X>건
- weakmap/weakmap_<ts>.md   ← 골드존 <G>개를 약점으로 등록

발산 (강의 vs HW):
  🎙 강조했으나 HW 없음:  <§/토픽 …>   ← 구두-only 출제 가능, 판단 필요
  HW 빈출이나 강의선 조용: <§ …>        ← 묵묵히 중요

다음:
  /paideia:weakmap         — 합쳐진 약점 우선순위
  /paideia:quiz <gold §>   — 골드존부터 드릴
```
