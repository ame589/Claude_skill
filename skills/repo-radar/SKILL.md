---
name: repo-radar
description: >-
  Generate an instant guided tour of an unfamiliar codebase: entry points, the
  core load-bearing modules (ranked by reference-centrality × git churn), the
  hottest files, where tests live, and the key config — in a suggested reading
  order. Use this when onboarding onto a new/unknown repo, when the user asks
  "where do I start / how is this codebase organized / what are the important
  files / give me a tour / help me understand this project", or before making a
  change in code you don't know yet. Triggers on: "onboard", "give me a tour",
  "where do I start", "explain this codebase", "codebase overview", "what are
  the important files", "how is this project structured", "unfamiliar repo".
---

# Repo Radar

## What this does

The expensive part of joining a project is the first day spent guessing which of
2,000 files actually matter. This skill answers that statistically: it ranks the
codebase by how load-bearing each file is — combining how many other files
reference it (centrality) with how often it changes (churn) and whether it's a
recognizable entry point — then lays out a reading order, the test layout, and
the config that defines the project's shape. It turns "where do I start?" into a
ten-minute orientation.

## When to use it

- Onboarding onto a new or unfamiliar repository.
- The user asks for a tour, an overview, "where do I start", or "what matters
  here".
- Before you (or the user) modify code in an area neither of you knows yet —
  orient first, edit second.

## Workflow

### 1. Generate the tour

```bash
python3 skills/repo-radar/scripts/tour.py --md TOUR.md
# fewer/more items per section:
python3 skills/repo-radar/scripts/tour.py --top 20
```

Needs only Python 3 and git; uses `ripgrep` if present for the centrality pass
(much faster on large repos). Churn comes from `git log`, so a repo with history
gives a far richer signal than a fresh clone with one commit.

### 2. Walk the user through it, in order

Present the tour the way it's laid out — this order is deliberate:

1. **Read these first** — the config/manifest files that reveal language,
   dependencies, build, and entry commands.
2. **Start here** — the entry points where execution begins.
3. **Core modules** — the ranked load-bearing files; read them top-down to build
   a mental model before touching anything.
4. **Hottest files** — where change concentrates, so where bugs and active
   feature work most likely live.
5. **Where tests live** — how to run and where to add coverage.

### 3. Go deeper on the top modules

For the top few core modules, open them and give the user a one- or two-line
summary of each file's responsibility and how they connect. This is where you
convert the statistical ranking into an actual architectural narrative — the
ranking finds *what* matters; you explain *why*.

### 4. Point to the first useful task

Close by suggesting a concrete on-ramp: a good first file to modify, the command
to run the app/tests, and any obvious gap (missing README section, thin test
coverage on a hot file) the newcomer could pick up.

## Interpreting the ranking

- **Centrality** (in-degree via basename references) approximates "imported by
  many" — high centrality means changing it ripples widely.
- **Churn** (commit count) means "actively worked on" — high churn is where the
  living complexity is.
- **Entry bonus** lifts recognizable `main`/`index`/`app`/`cli`/`server` files so
  the reading order starts where execution does.

A file high on both centrality and churn is the beating heart of the codebase —
read it first and change it carefully.

## Notes & limits

- Centrality is a **text-based proxy** (basename references), not a true import
  graph; it can over-count common names and miss re-exports or dynamic imports.
  Very generic stems (`index`, `main`, `utils`) are damped deliberately.
- Churn needs git history; on a shallow or brand-new repo it's near-zero and the
  ranking leans entirely on centrality.
- This is a map, not the territory. It surfaces what *matters*; the README and
  the team still own the *why*. Use it to aim your reading, then read.
