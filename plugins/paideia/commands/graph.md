---
description: Extract prerequisite concept graph from converted course materials and write course-index/concept-graph.md.
argument-hint: "[--force]"
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language.

Keep verbatim regardless of `INTERFACE_LANG`: file paths, slash command names, concept IDs (C1..Cn), pattern IDs (P1..Pk), tier markers (🔥🔥/🔥/🟡/⚪) and `⚠weak`, § / Ch section anchors, column headers (`Concept`, `id`, `§`, `Patterns`, `Tier`, `Type`, `Source`, `From`, `To`, `Confidence`, `Rationale`, `A`, `B`, `Relation`).

Load `skills/course-builder/SKILL.md`.
Load `skills/course-builder/concept-graph.md`.

Arguments: $ARGUMENTS

## Prerequisite check

Verify that `converted/` exists and contains at least one `.md` file. If empty, tell the user to run `/ingest` first and stop.

If `course-index/concept-graph.md` exists and `--force` is not passed, show the focus question and node count, then ask whether to overwrite. (Idempotent: re-running with `--force` overwrites without prompting.)

## Extraction pipeline

Follow PHASE A → B → C → D → E in order. Do not skip phases. Do not add optimization logic (no BKT, CP-SAT, Bandit, BLIM — PLOM exclusion, doc 04 §0.4).

### PHASE A — Candidate concept mining (sLLM tier, bulk repetition)

For each file in `converted/` (lectures, textbook, notes in document order):

1. Read the file text.
2. Emit candidate concepts with a minimal prompt (no explanation, comma-separated prerequisites only):

   ```
   You are an education expert. List the key concepts DEFINED in this text as a JSON array:
   [{"concept": "<name>", "defined_here": true|false, "section": "<§ or Ch>", "first_line": <int>, "refs": ["<concept>"]}, ...]
   Emit JSON only. No prose.
   ```

3. Collect all candidates across files. Track `def(X)` = the file/line of first full definition, and `ref(B→A)` = count of times file B mentions concept A.

### PHASE B — Normalisation and ID assignment

1. String-normalise candidates (lowercase, strip articles, collapse whitespace). Merge near-duplicates by edit distance ≤ 2 or exact synonym (e.g. "eigenvalue" = "eigen value").
2. Assign sequential IDs: `C1`, `C2`, … in order of first-definition appearance across files.
3. For each node, join:
   - `§`: the section anchor from the source file (use `source_path` header `<!-- SOURCE: ... §X.Y -->` if present)
   - `Patterns`: cross-reference `course-index/patterns.md` — list Pk IDs whose **Appears in** overlaps with this concept's §
   - `Source`: the relative path of the file where the concept is first defined
   - `Type`: `procedural` if the concept maps to ≥ 1 Pk that is a solution technique; otherwise `conceptual`

### PHASE C — Prerequisite edge proposal (structural priors first, LLM for ambiguous pairs only)

Apply RefD-style structural priors to propose edges. For each ordered pair (A, B) where A ≠ B:

- **Prior-positive edge A→B** (A is prerequisite of B) if:
  - `def(A) < def(B)` (A defined before B in document order), **AND**
  - `ref(B→A) > ref(A→B)` (B's file mentions A more than A's file mentions B)

Accept all prior-positive edges with `confidence: 0.75` without calling the LLM.

For pairs where the prior is ambiguous (neither dominates), or where `def(A)` ≈ `def(B)` (same §), call the reasoning LLM once per ambiguous pair:

```
Given two concepts in a course:
  Concept A: "<name>" defined in <§A>
  Concept B: "<name>" defined in <§B>
Decide: is A a prerequisite of B, B a prerequisite of A, or neither?
Respond JSON: {"from": "A"|"B"|null, "confidence": 0.0..1.0, "rationale": "<one sentence>"}
```

Discard edges with `confidence < 0.5`.

### PHASE D — DAG enforcement (Tarjan SCC → Kahn topo-sort)

1. Run Tarjan's SCC on the proposed edge set.
2. For each non-trivial SCC (size > 1):
   - If the concepts are near-synonyms (edit distance ≤ 2 or same root), merge them into the node with the lower-numbered Cx id and redirect edges.
   - Otherwise remove the lowest-confidence edge in the cycle to break it. Log the removed edge.
3. Verify the graph is now a DAG by running Kahn's topological sort. If any node is not reachable from the sort (still a cycle), repeat step 2.
4. The final edge set must produce a complete topological order across all nodes.

### PHASE E — Exam-signal join and write

1. For each node, join `Tier` from `course-index/coverage.md`:
   - Match by `§` value. Use the tier of the matching row. If the § is not in `coverage.md`, assign `⚪`.
2. Build the mermaid block for the `## Rendered graph` section (render-only, not parsed):
   - Use `flowchart TD`. One line per edge: `Cx["<concept> · <§> · <tier emoji>"] --> Cy`.
   - Bold `foundationalCracks` nodes by wrapping label in `**`: `Cx["**<concept>** · <§> · 🔥🔥"]`.
   - **Closing fence rule**: The mermaid block MUST be closed with **exactly one** ` ``` ` fence line. Emitting a second or trailing fence is a producer error. / mermaid 블록은 닫는 ` ``` `를 **정확히 1개**만 발행. 잉여 펜스 금지.
   - **Wikilink option (Obsidian interop)**: When `INTERFACE_LANG` is any value, the `Concept` cell in the `## Nodes` table MAY be wrapped in a wikilink: `[[<concept name>]]`. The parser (`parseConceptGraph`) is unaffected — it reads the `Concept` cell as a raw string and passes `zod .min(1)`, so `[[Eigenvalue]]` is a valid cell value. Do NOT add wikilinks inside mermaid labels — mermaid treats `[[` as a subgraph syntax and will break rendering. / `Concept` 셀은 `[[이름]]` 위키링크로 감쌀 수 있음(파서 무영향). mermaid 라벨에는 위키링크 금지.
3. Write `course-index/concept-graph.md` with the schema below.

**Language (reaffirms Output language header):** The `Focus question` sentence, `Rationale` cell prose in Prerequisite edges, and `Relation` cell prose in Cross-links must be in `$INTERFACE_LANG`. Column headers (`From`, `To`, `Confidence`, `Rationale`, `A`, `B`, `Relation`, `Concept`, `id`, `§`, `Patterns`, `Tier`, `Type`, `Source`), concept IDs (C1..Cn), pattern IDs (P1..Pk), tier markers (🔥🔥/🔥/🟡/⚪), and `§`/`Ch` anchors stay verbatim regardless of `$INTERFACE_LANG`.

**Node label language contract (mandatory — FND-018 fix):** The `Concept` cell prose in the `## Nodes` table MUST be emitted in `$INTERFACE_LANG`. This is canonical data, not a display-time translation: if `INTERFACE_LANG` is `en`, concept names in the `Concept` column must be in English (e.g. `Ladder operator`, not `사다리연산자`); if `ko`, they must be in Korean. The `id` column (C1..Cn), `§`, `Tier`, `Type`, `Source`, and `Patterns` columns are language-neutral and stay verbatim regardless of `$INTERFACE_LANG`. / `## Nodes` 표의 `Concept` 셀은 `$INTERFACE_LANG`로 방출 (en이면 영문, ko이면 한국어). `id`·`§`·`Tier` 등 기타 열은 언어 무관 고정.

## Output schema (§2.2, verbatim — table is the contract, mermaid is render-only)

```markdown
# Concept Graph — <course name>

<!-- SOURCE: course-index/concept-graph.md method: llm-concept-graph, model: <engine> -->

## Focus question

<One sentence that frames what the graph answers, e.g. "How do eigenvalues and diagonalization relate in finite-dimensional vector spaces?">

## Nodes

| Concept | id | § | Patterns | Tier | Type | Source |
|---|---|---|---|---|---|---|
| <concept name> | C1 | §X.Y | P4, P7 | 🔥🔥 | conceptual | converted/lectures/chNN.md |

## Prerequisite edges

| From | To | Confidence | Rationale |
|---|---|---|---|
| C1 | C5 | 0.90 | <one-sentence linking phrase> |

## Cross-links

| A | B | Relation |
|---|---|---|
| C1 | C9 | <relation phrase> |

## Rendered graph

\`\`\`mermaid
flowchart TD
  C1["<concept> · <§> · <tier emoji>"] --> C5["<concept> · <§> · <tier emoji>"]
\`\`\`
```

**Contract rule**: The parser (`parseConceptGraph` in `packages/paideia-core`) reads only the `## Nodes`, `## Prerequisite edges`, and `## Cross-links` tables. The `## Rendered graph` mermaid block is ignored by the parser — it exists for human readers only.

## Concept heatmap (render-only, optional)

**This section is render-only and is NOT parsed by `parseConceptGraph`.** It is produced by the `/paideia:graph` command after writing the contract tables, if `errors/log.md` contains at least one entry. / 이 섹션은 파서가 읽지 않는 렌더 전용 섹션이며, `errors/log.md` 엔트리가 0이면 생략.

Join key: node `id`↔`Patterns` (Pk column) and `§` ↔ `errors/log.md` `pattern:` (Pk) / `source:` (§ fragment). Count per node, split by `nature:` facet (slip/misconception/gap). PLOM 금지: 관측 카운트만, BKT/Bandit/가중 추정 금지.

```markdown
## Concept heatmap

> Error counts from errors/log.md joined by pattern (Pk) and § anchor.
> / errors/log.md의 오답을 pattern(Pk)·§ 앵커로 조인한 관측 카운트.

| id | Concept | Errors | Slip | Misconception | Gap |
|---|---|---|---|---|---|
| C1 | Eigenvalue | 3 | 1 | 2 | 0 |
| C5 | Diagonalization | 1 | 0 | 1 | 0 |
```

**Graceful downgrade**: If `errors/log.md` is absent or has 0 entries matching any node, omit the `## Concept heatmap` section entirely. Never emit an empty table. / errors/log.md 부재·매칭 0이면 섹션 자체 생략.

**i18n**: The blockquote description above should be in the course's `INTERFACE_LANG` (en prose vs. ko prose), but column headers (`id`, `Concept`, `Errors`, `Slip`, `Misconception`, `Gap`) are kept verbatim regardless of lang.

## Validation (§2.4)

Before writing, verify:
1. All edge `From` and `To` values match a node `id` in the `## Nodes` table.
2. The graph is acyclic (PHASE D guarantees this; re-check here).
3. Every `Tier` value is one of: 🔥🔥, 🔥, 🟡, ⚪.
4. Every `Confidence` value is a number in [0, 1].

If any check fails, fix the issue (remove bad edges, correct tiers) and log the fix. Do not write a file that fails validation.

## --rebuild flag (supplementary accuracy pass)

When `--rebuild` is given, after completing the standard PHASE A–E pipeline above, perform an additional cross-validation pass: read `converted/**/*.md` (one file at a time, sequentially — no parallel fan-out, to stay within window) and check for any concept mentions not captured in the extracted node set. Merge any additional concepts found: the PHASE A–E results take precedence for structure; `--rebuild` adds only concepts not already present.

**Fan-out vs sequential read distinction:** The standard PHASE A reads `converted/` files **sequentially** (one file at a time, in document order) — this is not a parallel fan-out and is the default behavior. `--rebuild` is a supplementary accuracy pass that performs an **additional** sequential cross-validation sweep after PHASE A–E completes. Do NOT perform **parallel fan-out** (spawning multiple concurrent read agents against `converted/`) without `--rebuild` — parallel fan-out is reserved for the rebuild pass to stay within the window constraint (FND-029). Sequential single-file reads in PHASE A are always permitted regardless of `--rebuild`.

## Engine caveats

- **codex**: no mid-run image reads — structural priors (PHASE C) from text only, sequential
- **ollama-cloud**: edge confirmation quality varies by cloud model (Sonnet-class recommended for PHASE C LLM pairs)

## Note on command numbering

This command is registered as entry 18 in `packages/corpus/src/registry.ts`. The document §2.8 refers to it as "17th" but `/paideia:drill` already occupies slot 17 in the live registry. The code is the authoritative source; this note documents the deviation.
