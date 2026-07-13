# Workflow: export this session as a resumable handoff bundle

You are creating a handoff so another developer (or another AI session — Cline
or Claude Code) can resume this work exactly where it stopped. Follow every
step; the bundle is worthless if step 2 is skipped.

## 1. Capture the mechanical state

Run, passing `--kb` once for each file/directory that served as a knowledge
source in this session (specs, docs, datasets):

```bash
python3 skills/session-handoff/scripts/handoff.py create --kb <path> [--kb <path> ...] --pack
```

This snapshots branch/HEAD, writes uncommitted changes to a patch, copies
untracked files, and sha256-hashes every knowledge source into
`.handoff/manifest.json`, plus a portable `handoff-<timestamp>.tar.gz`.

## 2. Fill the semantic sections of `.handoff/HANDOFF.md` — the real work

Open `.handoff/HANDOFF.md` and replace every `✍️ TODO(author)` section using
THIS CONVERSATION as the source, not the files:

- **Mission** — the goal, as the user stated it.
- **Current step** — the precise point reached, so nothing gets redone.
- **Decisions made & why** — every settled decision with rationale, INCLUDING
  rejected alternatives and dead ends (unwritten dead ends get re-explored at
  full cost).
- **Key findings** — facts later steps depend on, each citing its source file.
- **Next steps** — numbered, concrete, starting with the very next action.
- **Open questions & risks** — what's unresolved and who can resolve it.

## 3. Stranger test

Re-read the finished HANDOFF.md as if you knew nothing about this session. If
resuming would require asking the original author anything, fix the document
now. Only then tell the user the bundle is ready and where it is
(`.handoff/` and `handoff-<timestamp>.tar.gz`).

## 4. Deliver

Ask the user whether to commit/push the branch (the bundle references its exact
HEAD — the receiver needs that commit reachable). The tar.gz is what travels.
