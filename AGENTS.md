# Casting project instructions

Casting chooses the harness and model. It owns the model catalog, policy,
availability inventory, scoring, and explanation. It never launches a process
and never reads PWC task storage.

The first goal is the standalone core from
https://github.com/shreyansqt/pwc/issues/7#issuecomment-5294907115.
Use PWC commit `daf1738` as the behavior baseline. Preserve the top-level
`preferences` block, the SHA-256 bucket rule, hard filters, capability gates,
cost order, expiry, and explanations. Do not change PWC during the core task.

Work directly on `main`. Do not create a pull request unless the user asks for one.

# Self-learning conventions

This repo is operated by agents and is expected to get smarter with every
session: work done once should never need to be re-derived.

Knowledge lands in three places:

- **AGENTS.md (this file)** — durable instructions: domain facts, environment
  quirks, calibrated values, workflow rules. When a session uncovers something
  a future session would otherwise rediscover the hard way, propose an edit
  here.
- **docs/** — reference material too long for instructions: findings,
  investigation write-ups, external API notes, maintenance logs. One topic per
  file; link from AGENTS.md when an instruction needs the detail.
- **skills/** — repeatable workflows, one directory per skill with a
  `SKILL.md` (frontmatter: `name` + `description`, then instructions). Extract
  a skill when a workflow has recurred, not on first use. Harnesses discover
  this directory through the committed symlinks `.claude/skills` and
  `.agents/skills` — add a skill here and every harness picks it up; never
  create per-harness copies.

Rules:

1. **End every substantive session with a learning review.** Before wrapping
   up, check: did this session produce a fact, fix, or workflow a future
   session will need? Present concrete proposals (specific edits, not "should
   I update the docs?"). If nothing is worth saving, say so in one line.
2. **Propose, never auto-write.** Every update to AGENTS.md, docs/, or
   skills/ is shown to the user and approved one item at a time. The analysis
   is automatic; the writes never are.
3. **Prefer updating over adding.** Check whether an existing instruction,
   doc, or skill already covers the topic and update it instead of adding a
   near-duplicate. Delete what has turned out to be wrong.
4. **Don't save what is already recorded** — in code, git history, or
   upstream documentation. Save what is specific to this project, this
   hardware, this account, this user.
5. **The work queue is GitHub issues** (milestones for larger arcs). Anything
   worth doing later becomes an issue so any future session can pick it up
   with context; close issues with a comment saying what was actually done.
