---
name: commit-surgeon
description: >-
  Split a messy working tree with several unrelated changes into a clean,
  reviewable sequence of atomic commits, each with an inferred Conventional
  Commit message. Use this when the user has a pile of uncommitted work spanning
  multiple concerns and wants it committed sensibly, asks to "split / organize /
  clean up my changes / commits", wants "atomic commits" or "one commit per
  concern", or is preparing a tidy PR history. Triggers on: "split my changes",
  "atomic commits", "organize commits", "my working tree is a mess", "commit
  this properly", "conventional commits", "separate these changes".
---

# Commit Surgeon

## What this does

Big, mixed commits are where code review goes to die — a reviewer can't approve a
bug fix without also vetting the unrelated refactor and doc tweak riding along.
This skill reads your working tree, groups the changes by concern, proposes an
ordered set of atomic commits with sensible Conventional-Commit messages, and
hands you a script to apply them. Clean history, faster review, easier reverts —
without you hand-staging file by file.

## When to use it

- The user has accumulated unrelated changes and wants them committed cleanly.
- The user asks to split / organize / tidy commits, or wants "atomic commits".
- You're about to open a PR and the history is one undifferentiated blob.

## Workflow

### 1. Plan the split

```bash
python3 skills/commit-surgeon/scripts/plan_commits.py --md commit-plan.md --sh commit.sh
```

This inspects tracked and untracked changes, clusters files by concern
(src / test / docs / config / ci / style) and by module, infers a commit type
(`feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `style`,
`chore`) from file type and change keywords, and writes:
- `commit-plan.md` — the proposed commits, in review order, and
- `commit.sh` — a runnable staging+commit script.

It is read-only; nothing is committed until you act.

### 2. Review the plan with the user — this is the important step

Present the proposed commits. The type/scope/message are **inferred heuristics**;
correct them where the intent is wrong (only you and the user know that the
"refactor" was actually the bug fix). Pay special attention to any **⚠️
mixed-concern** files: a single file carrying both a feature and a fix should be
split with `git add -p` so each hunk lands in the right commit — do that
manually rather than through the file-level script.

### 3. Apply

Either run the generated script:

```bash
bash commit.sh
```

…or, when files are mixed, stage hunk-by-hunk yourself (`git add -p`) following
the plan's grouping, committing each concern with its message. Refine any
message before committing — never ship an inferred subject you haven't read.

### 4. Verify the history

```bash
git log --oneline --stat
```

Confirm each commit is self-contained (builds/tests would pass at that commit if
practical) and that no unrelated change leaked across a boundary. Reorder or
`git commit --amend`/`git rebase -i` if needed.

## Conventions

- Messages follow **Conventional Commits** (`type(scope): subject`). Scope is the
  module directory; it's omitted for root-level changes.
- Commit order is chosen for reviewability: `build → refactor → feat → fix →
  perf → test → docs → ci → style → chore`, so structural changes land before
  the features that use them.
- A feature and its tests in the same module are grouped into one commit by
  design — an atomic commit includes its own tests.

## Notes & limits

- Grouping is at **file granularity**, which is safe and reversible. True
  hunk-level splitting (two concerns in one file) is flagged, not automated —
  use `git add -p` there.
- Inference is keyword/heuristic based; it cannot read intent. Always review
  types and messages before committing.
- The generated script runs `git reset` first to unstage everything, then stages
  each group cleanly. Read it before running.
