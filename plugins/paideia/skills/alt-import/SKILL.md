---
name: alt-import
description: Parse an Exam Radar (OPTIMETA Alt plugin) export and fold its lecture-emphasis exam-probability signal into the PAIDEIA course index — write course-index/radar.md, annotate course-index/coverage.md with a lecture-emphasis column and divergence flags, and seed a gold-zone weakmap. Invoked by /paideia:alt. The export form is fixed (exam-radar:v1 marker).
---

# alt-import

Exam Radar is OPTIMETA's Alt plugin. From lecture-recording transcripts it extracts the topics a professor **verbally emphasized**, ranks them by exam probability, and lets the user triage each into one of three zones. Its 복사 button emits a fixed markdown form. This skill ingests that form.

PAIDEIA already has one exam-probability signal — **HW density** (`course-index/coverage.md`). Exam Radar adds a second, independent one — **lecture emphasis**. The two corroborate where they agree and expose blind spots where they diverge.

**Premise (do not break).** HW density remains the primary `Exam tier`. Lecture emphasis is layered on as annotation and a second opinion — it is surfaced, never substituted. As with a user-declared weak zone, a single lecture signal does **not** auto-upgrade an HW-based tier (mirror `course-builder`'s rule). What it does is flag divergences for the user to judge.

---

## 1. The export format (`exam-radar:v1`)

```
# Exam Radar 작전 — <course>
<!-- exam-radar:v1 source=alt -->

- 코스: <course>
- 시험까지: <D-N>
- 토픽: 총 <N>개 (골드존 <G> · 버려도 안전 <D>)
- 버려도 안전 비중: 전체의 <P>%

## 지금 할 것 — 골드존 (시험확률 높음 · 아직 약함)
1. <topic> · 시험확률 <p>%[ · 🎙]
...

## 이미 다진 것 (잘 알거나 시험에 덜 나옴)
- <topic> · 시험확률 <p>%
...

## 버려도 안전 (안 해도 되는 것)
- <topic> · 시험확률 <p>%
...
```

Parse rules:
- **Detect** by the `<!-- exam-radar:v1` marker. Parse the `vN` integer; if `> 1`, warn and parse the v1 fields best-effort (ignore unknown ones).
- **Meta**: read `- 코스:`, `- 시험까지:` (D-N), and the count line.
- **Zones**: three `## ` headings →
  - `지금 할 것 — 골드존` → zone **`gold`** (high exam-prob, low self-confidence).
  - `이미 다진 것` → zone **`strong`** (already known or low exam-prob).
  - `버려도 안전` → zone **`skip`** (safe to drop).
- **Each topic line**: `<name> · 시험확률 <p>%`, optionally ` · 🎙` (the professor verbally stressed it). The leading `1.` / `-` is just list markup. Parse `name`, integer `p` (0–100), and the `🎙` flag.
- Be lenient on whitespace and the leading marker. A zone with `(없음)` / `(아직 없음 …)` is empty.

---

## 2. Write `course-index/radar.md` (canonical store)

This mirrors how `coverage.md` stores the HW signal. Overwrite on re-import.

```markdown
<!-- SOURCE: Exam Radar (Alt), exam-radar:v1, course=<course>, <D-N>, imported <YYYY-MM-DD> -->
# Lecture-emphasis signal — <course>

Imported from Exam Radar. Exam probability here is **lecture emphasis** (professor's spoken stress + repetition across recordings), independent of HW density in `coverage.md`.

| Topic | Exam prob | Zone | Lecture signal |
|---|---|---|---|
| <topic> | <p>% | gold | 🎙 |
| <topic> | <p>% | strong | — |
| <topic> | <p>% | skip | — |
...one row per topic, exam-prob descending within each zone, gold → strong → skip.

## Now (gold zone)
High exam probability, still weak — drill these first:
- <topic> (<p>%)[ 🎙]

## Safe to drop
Low lecture emphasis — reference only:
- <topic> (<p>%)
```

If `course-index/` doesn't exist yet, create it. `radar.md` stands on its own even before `/paideia:analyze` has run.

---

## 3. Merge into `course-index/coverage.md` (if it exists)

If `coverage.md` is missing, **skip this step** and tell the user to run `/paideia:analyze` first — `radar.md` already captured the import.

Otherwise:

1. **Map** each Exam Radar topic to a reverse-map section (`§`) by title match — case- and spacing-insensitive, substring allowed (e.g. "Gram-Schmidt" ↔ "§3.2 Gram-Schmidt orthogonalization"). Keep the best match; leave the rest unmatched.

2. **Add/refresh a `Lecture emphasis` column** on the reverse-map table (`§ | Title | HW coverage | Exam tier | Lecture emphasis`). Value from the topic's exam-prob:
   - `🎙🎙` — gold zone or ≥ 70%
   - `🎙` — 40–69%
   - `·` — < 40%, or no Exam Radar topic mapped to that §

3. **Do not change the `Exam tier`.** It is HW-derived and stays. Lecture emphasis is the new column only.

4. **Append a divergence section** — this is the payoff of having two signals:

   ```markdown
   ## Lecture vs HW — divergences (judge these)

   ### 🎙 Stressed in lecture, but no HW
   §/topic the professor emphasized (🎙🎙) yet `coverage.md` marks ⚪ Low-risk:
   - <§ or topic> — verbal-only exam point? decide; if it matters, `/paideia:derive` or `/paideia:quiz` it.

   ### HW-dense, but quiet in lecture
   § marked 🔥🔥/🔥 with `·` lecture emphasis:
   - <§> — quietly important; the professor tests it without spending lecture time on it.
   ```

   Respect the premise: the ⚪→ "judge this" line is a *prompt for the user*, not an automatic tier upgrade.

5. **Unmatched topics** — append so nothing is lost:

   ```markdown
   ## From Exam Radar (no HW section match)
   - <topic> · <p>%[ · 🎙]
   ```

6. **Drill priority** — in `coverage.md`'s "Recommended drill priority", use lecture emphasis as a **booster/tie-breaker** (a 🎙🎙 + thin/blind item ranks above an equal one without emphasis), without reordering across HW tiers.

Re-runs replace the `Lecture emphasis` column and the `Lecture vs HW` / `From Exam Radar` sections in place — never duplicate them.

---

## 4. Seed a gold-zone weakmap

The gold zone = **high exam probability + low self-confidence** = a weakness the user effectively declared, corroborated by lecture emphasis. Treat it exactly like `/paideia:weakmap` Case B (user-declared weaknesses).

- Write a **new** `weakmap/weakmap_<YYYY-MM-DD_HHmm>.md` (never overwrite — preserve history).
- Use the weakmap report format (see `commands/weakmap.md`). Put gold-zone topics under `## User-declared weaknesses`, each tagged `(from Exam Radar gold zone)`, mapped to related `§`/`Pk` (via `course-index/`), with a recommended drill (`/paideia:blind` / `/paideia:quiz` / `/paideia:derive`).
- Also run the weakmap Case A latest-error snapshot so the report stays consistent. If `errors/log.md` and `course-index/` are absent, write a minimal report (gold zone only) and note that `/paideia:analyze` will enrich it.

---

## 5. Notes

- Lecture-emphasis exam-prob and HW-density exam-prob are **different axes**; never average them into one number. Keep them as separate columns/files so the user can see both and reason about divergence.
- Exam Radar topics are lecture-derived, so they overlap heavily with `summary.md` sections — but the user may have edited section numbering. Always do best-effort matching and surface the unmatched rather than forcing a map.
