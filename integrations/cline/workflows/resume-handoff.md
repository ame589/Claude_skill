# Workflow: resume another developer's session from a handoff bundle

You received a handoff bundle (a `.handoff/` directory or a
`handoff-<timestamp>.tar.gz`). Restore it faithfully — the previous session's
decisions are settled unless evidence contradicts them.

## 1. Verify before touching anything

```bash
python3 skills/session-handoff/scripts/handoff.py restore --bundle <bundle-path>
```

This checks that HEAD matches the commit the bundle was made at and that every
knowledge-source file still matches its sha256. Take problems seriously:

- **HEAD mismatch** → fetch and check out the branch/commit named in the output
  (the exact commands are in the bundle's HANDOFF.md), then re-verify.
- **Content drift on a knowledge source** → the findings in HANDOFF.md may
  describe a version of that document that no longer exists. STOP and surface
  this to the user before proceeding. Never `--force` on your own initiative.

## 2. Apply the work in progress

Only after verification passes:

```bash
python3 skills/session-handoff/scripts/handoff.py restore --bundle <bundle-path> --apply
```

This re-applies the uncommitted patch and restores untracked files.

## 3. Load the semantic state, then continue

Read `.handoff/HANDOFF.md` IN FULL before any other action. Then:

- Treat **Decisions made & why** as settled — do not re-litigate them; if you
  find evidence one is wrong, say so explicitly instead of silently diverging.
- Do not redo anything listed as finished in **Current step**.
- Start from step 1 of **Next steps**.
- Raise the **Open questions** with the user early rather than assuming.

Give the user a one-paragraph confirmation of where the session resumed from
and what you are about to do first.
