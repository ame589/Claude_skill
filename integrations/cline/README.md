# Using these skills with Cline

The engines in this repo are agent-agnostic: pure Python 3 + git, invoked from a
terminal. What differs between agents is only the *trigger + workflow* layer —
Claude Code reads `SKILL.md` files, while [Cline](https://cline.bot) uses
**rules** (`.clinerules/`) and **workflows** (`.clinerules/workflows/*.md`,
invoked with `/name`). This directory provides that layer for Cline.

The handoff **bundle format is the interop contract**: `HANDOFF.md` +
`uncommitted.patch` + `manifest.json` (sha256) + `untracked/` in a directory or
tar.gz. A bundle created from a Claude Code session can be resumed in Cline and
vice versa — the tools on both ends run the same `handoff.py`.

## Install

From your project root (with this repo's `skills/` present, e.g. vendored or
copied in):

```bash
mkdir -p .clinerules/workflows
cp integrations/cline/workflows/*.md .clinerules/workflows/
```

## Use

- `/handoff.md` — export the current Cline session as a resumable bundle.
- `/resume-handoff.md` — resume from a bundle another developer sent you.

Cline's own [Memory Bank](https://docs.cline.bot) pattern solves the *same
problem within one project's lifetime*; the handoff bundle differs in being a
**verifiable, portable snapshot** — hashed sources, an exact commit anchor, and
the uncommitted work itself — that crosses machines, developers, and agents.

> Note: agent ecosystems move fast. If Cline gains native support for the open
> `SKILL.md` format, prefer pointing it at `skills/` directly and drop these
> shims.
