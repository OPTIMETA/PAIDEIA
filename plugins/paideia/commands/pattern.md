---
description: Show solution pattern cards from course-index/patterns.md, filtered by topic or keyword.
argument-hint: <§ number, keyword, Pk id, or "all">
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs (P1, P2…), and the pattern-card field labels (`Recognition:`, `Move:`, `Seen in:`, `Topic:`).

Read `course-index/patterns.md`. If missing, tell the user to run `/analyze` first.

Query: $ARGUMENTS

Procedure:

1. **Filter patterns:**
   - If query starts with `§` or `Ch` or similar: return patterns whose Topic field includes that section
   - If query matches `P\d+` (e.g., `P7`): return that single pattern plus cross-references
   - If query is a keyword (e.g., `maxwell`, `fourier`, `induction`): return patterns matching name/recognition/move text (case-insensitive)
   - If query is `all` or empty: return the full list, grouped by part/topic

2. **For each matching pattern**, render as a compact card:

   ```
   [Pk] <name>
   Recognition: <signal>
   Move: <operation, 1-2 lines>
   Seen in: <problem IDs>
   Topic: <§ numbers>
   ```

3. **End with a prompt** (in $INTERFACE_LANG):
   "Any pattern here that would be hard to recognize at first sight? Tell me its number — we'll drill just that one with `/blind <problem>`."

Keep total output under 40 lines. This is a recognition tool, not a tutorial. If the user wants depth on one pattern, they'll ask.
