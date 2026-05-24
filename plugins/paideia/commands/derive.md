---
description: Save a clean reference derivation of a target equation or theorem to derivations/. Draws from course materials (textbook, lecture notes) rather than testing the user.
argument-hint: <equation or theorem name>
---

## Output language

Read `INTERFACE_LANG` from `.course-meta` (default `en`). All user-facing prose — chat output and narrative sections of the generated derivation MD — must be in that language. Keep in English regardless: file paths, slash command names, pattern IDs, LaTeX, and any literal section anchors downstream tools regex on.

Load `skills/course-builder/SKILL.md` for material locations. Also read `course-index/summary.md` to resolve the target.

Target: $ARGUMENTS

Procedure:

1. **Locate the derivation** in `converted/textbook/*.md` and `converted/lectures/*.md`. If present in both, prefer the textbook (usually cleaner).
2. **If not in materials**, derive it from first principles using standard techniques for the course's domain. Cite which earlier results you're using.
3. **Format as a clean reference markdown file** with:
   - Starting definitions/assumptions clearly stated
   - Each step with a one-line explanation of why
   - Boxed final result
   - Short physical / mathematical interpretation at the end
   - Typical pitfalls (common student errors) listed at bottom
4. **Save to** `derivations/<slug>.md`. Slug is lowercase-hyphenated from the target name.
5. **Print** (in $INTERFACE_LANG): "Saved `derivations/<slug>.md`. Open and read; ask if any step is unclear."

Do NOT quiz or prompt the user — this command is a pure reference-writer. The user explicitly set this up so they can read rather than type.

## Format convention (align with existing `derivations/` files if any)

The skeleton below uses English labels; if `INTERFACE_LANG=ko`, translate the bold labels ("Goal", "Starting point", "Step 1 — ...", "Result", "Interpretation", "Pitfalls", "Reference") to natural Korean equivalents. Keep LaTeX, file paths, and equation content unchanged.

```markdown
# <Target name>

**Goal.** <statement of what we want to derive>

**Starting point.** <definition / law / axiom / earlier result>

---

### Step 1 — <step description>

$$<step equation>$$

<why this step>

### Step 2 — ...

...

---

**Result.**
$$\boxed{\;<final>\;}$$

**Interpretation.** <1-2 sentences on what this means physically/mathematically>

**Pitfalls.**
- <common error 1>
- <common error 2>

**Reference.** <source section in converted/>
```

Preserve LaTeX, use `$...$` and `$$...$$`. No emojis except the final $\blacksquare$ or ∎ at the result.
