---
name: session-handoff
description: >-
  Export the current working session — loaded documents, uncommitted work, and
  above all the accumulated knowledge (decisions, findings, dead ends, next
  steps) — as a verifiable handoff bundle another developer (or another Claude
  session) can resume from exactly where it stopped; and restore such a bundle
  on the receiving side. Use when the user wants to hand work off, pause and
  resume later, transfer a session's knowledge base, or resume from a received
  bundle. Triggers on: "handoff", "hand this off", "export this session",
  "another developer will continue", "resume from where I left", "passa il
  lavoro", "knowledge base export", "riprendi da questo punto", "restore
  handoff", "HANDOFF.md".
---

# Session Handoff

## What this does

A session accumulates two kinds of state. The **mechanical** state — repo
position, uncommitted changes, untracked files, the exact versions of every
document that was loaded — is captured by the engine, content-hashed so the
receiver can verify nothing drifted. The **semantic** state — what was decided
and why, what was ruled out, what was learned from the documents, what comes
next — exists only in the conversation, and it is the expensive part: losing it
means the next developer re-derives days of work. This skill's core job is
forcing that semantic state out of the conversation and into a `HANDOFF.md`
rigorous enough that a stranger can resume without asking a single question.

## When to use it

- The user says another developer (or a future session) will continue the work.
- A long elaboration session must pause and resume later without loss.
- The user received a handoff bundle and wants to pick the work up.

## Workflow — creating a handoff

### 1. Capture the mechanical state

```bash
python3 skills/session-handoff/scripts/handoff.py create --kb docs/ --kb specs/requirements.pdf --pack
```

Pass `--kb` once per document/directory that served as a knowledge source this
session — those files get hashed into the manifest so the receiver can detect
drift. `--pack` additionally produces a portable `handoff-<timestamp>.tar.gz`.
The engine snapshots branch/HEAD, writes all tracked changes to
`uncommitted.patch`, and copies untracked files into the bundle.

### 2. Fill the semantic sections — this is the real work

Open `.handoff/HANDOFF.md`. The auto sections are done; the ✍️ TODO sections are
yours, and you must fill them **from the conversation history**, not from the
files. Be exhaustive on:

- **Mission** — the goal in one paragraph, as the user stated it.
- **Current step** — the precise point reached, so nothing done gets redone.
- **Decisions & why** — every settled decision with rationale, **including
  rejected alternatives and dead ends**. A dead end not written down will be
  re-explored at full cost.
- **Key findings** — facts extracted from the documents/code that later steps
  depend on, each citing its source file from the manifest.
- **Next steps** — numbered, concrete, starting with the very next action.
- **Open questions** — what's unresolved and who can resolve it.

### 3. Apply the stranger test

Re-read the finished `HANDOFF.md` pretending you know nothing about this
session. Every term you invented, every file you reference, every assumption —
is it defined in the document? If resuming would require asking the original
author anything, the handoff is not done. Fix it now, while you still know the
answers.

### 4. Deliver

Commit and push the branch if the user agrees (the bundle references its exact
HEAD). Hand over either the `.handoff/` directory or the packed
`handoff-*.tar.gz`. Both contain everything.

## Workflow — resuming from a handoff

### 1. Verify before touching anything

```bash
python3 skills/session-handoff/scripts/handoff.py restore --bundle .handoff        # or the .tar.gz
```

This checks that HEAD matches the bundle's commit and that every
knowledge-source hash still matches. **Take verification problems seriously**: a
drifted document means the findings in HANDOFF.md may describe a version that no
longer exists — surface that to the user before proceeding.

### 2. Apply the work in progress

```bash
python3 skills/session-handoff/scripts/handoff.py restore --bundle .handoff --apply
```

Re-applies `uncommitted.patch` and restores untracked files. It refuses to apply
over a mismatched state unless `--force`d — prefer resetting to the bundle's
HEAD (the commands are in HANDOFF.md) over forcing.

### 3. Load the semantic state, then continue

Read `HANDOFF.md` in full. Treat **Decisions made** as settled — do not
re-litigate them unless you find evidence they're wrong (then say so explicitly).
Do not redo anything listed as finished. Start from step 1 of **Next steps**,
and raise the **Open questions** with the user early rather than assuming.

## Notes & limits

- The engine is deliberately conversation-blind: it cannot extract decisions or
  findings. Step 2 of creation is mandatory, and skipping it produces a bundle
  that restores files but loses the knowledge — the failure mode this skill
  exists to prevent.
- Untracked files larger than 5 MB are listed but not copied (noted in the
  bundle); move such artifacts via LFS or object storage and reference them.
- The bundle may contain document contents and diffs — treat it with the same
  confidentiality as the repo itself, and don't commit `.handoff/` unless the
  user wants the handoff versioned.
