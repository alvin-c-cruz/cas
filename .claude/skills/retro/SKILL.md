---
name: retro
description: Use when the user types /retro or asks for a retrospective on recent work. Gathers branch diff, recent commits, changed files, and the test-failure baseline, then runs the retro agent to extract durable lessons, update the persistent memory store, and reconcile the backlog/bug-tracker.
---

# /retro — Work Retrospective + System Learning

Runs a structured retrospective on recently completed work and improves the project's long-term
memory so mistakes are not repeated. The heavy lifting is done by the **`retro` subagent**
(`.claude/agents/retro.md`); this skill's job is to collect the context it needs and hand off.

Optional argument: a scope hint (`branch`, `session`, `backlog`, `tests`). Default = all.

## Steps

**1. Gather git context** (read-only):

```powershell
git branch --show-current
git log main..HEAD --oneline
git diff main...HEAD --stat
git status --short
```

If the current branch IS `main`, use the last ~10 commits instead:
`git log -10 --oneline` and `git diff HEAD~10 --stat`.

**2. Read the baseline.** Read `C:\Users\user\.claude\projects\C--envs-cas\memory\project-preexisting-test-failures.md`
so the agent can tell new regressions from known-baseline failures. (Already in context via
`MEMORY.md`, but pass the file path explicitly.)

**3. Invoke the retro agent.** Launch the `retro` subagent (subagent_type: `retro`) with a prompt
containing: the current branch, the commit list, the `--stat` diff, the changed-file list, the
baseline file path, and any session notes you can summarize from this conversation (decisions,
mistakes, rule frictions). Tell it which scope was requested.

**4. Relay the result.** The agent returns a structured retrospective. Present it to the user
verbatim-ish, then surface the **"Proposed changes (need approval)"** section prominently — those
are diffs the agent deliberately did NOT apply (CLAUDE.md / settings.json / app/ / tests / its own
definition). Ask the user whether to apply each.

## Notes

- The agent auto-writes lessons to the memory store and reconciles backlog/bug-tracker on its own —
  that does not need confirmation (it is the point of the retro).
- The agent will NOT edit application source or fix bugs; bugs go to `project-bug-tracker.md` as
  follow-ups.
- Pairs with `/guard` (the proactive pre-push regression check). `/retro` is reflective and runs
  after work; `/guard` is preventive and runs before a push.
