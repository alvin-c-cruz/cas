---
name: cycle
description: Use when the user types /cycle, or wants to run their standard page-improvement loop — analyze a page, make changes, then retrospect — with a checkpoint between steps where they choose to proceed, pause, or fix findings.
---

# /cycle — Analyze → Retro driver

Drives the user's recurring workflow as one sequenced loop with a human-in-the-loop
**checkpoint** between steps. The actual work is done by the existing skills
(`/analyze-page`, `/retro`); this skill's job is to run them in order and stop for a
decision between them.

The sequence:

```
/analyze-page <url>  →  CHECKPOINT  →  /retro  →  done
```

(The CHECKPOINT is where "do debugging / make changes" happens.)

## The CHECKPOINT (the core of this skill)

After a step finishes and you have relayed its result, do NOT roll into the next
step. Ask the user, via an AskUserQuestion with these options:

1. **Proceed to the next step** — continue the sequence.
2. **Pause — I'll do something else** — stop driving. The user works freely
   (debug, edit, anything). The cycle is *suspended, not ended*: when they later
   say "resume" / "next" / "continue", pick up at the step after the one that was
   just completed.
3. **Fix the findings/bugs now** — for each finding the user wants fixed: report
   it and get explicit approval **before** editing (CLAUDE.md: discuss bugs before
   fixing; never fix inline), then fix under TDD. When fixes are done, return to
   THIS checkpoint and ask again (a fix may warrant re-running the prior step).

(The user can always type "stop" / "end" to exit the cycle entirely — "Other".)

## Steps

1. **Analyze.** Get the page URL (ask if not supplied). Invoke `/analyze-page <url>`.
   Relay its report. → **CHECKPOINT.**
2. **Retro.** Invoke `/retro`. Relay the retrospective and surface its
   "Proposed changes (need approval)" section. The cycle ends here.

## Resuming after a pause

State lives in this conversation — track which step was last completed. On
"resume"/"next", continue from the next step. If the context was summarized and
the position is unclear, ask: "We were at the checkpoint after <step> — proceed to
<next step>?" rather than guessing.

## Notes
- This skill only *sequences*; it does not re-implement any step. Bugs found during
  `/analyze-page` follow the normal report-then-approve-then-TDD-fix rule — the cycle
  never auto-fixes.
- Running tests is not part of this loop. If the user wants a test pass, they can
  invoke `/run-tests` themselves during a Pause, then resume.
- Each underlying skill keeps its own behavior (e.g. `/retro` still proposes—not
  applies—CLAUDE.md/settings/source/map changes).
