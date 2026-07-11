# Ranking methodology

How `tour.py` decides what a newcomer should read first.

## Signals

For every source file the tool computes three signals:

| Signal        | Source                              | Proxy for                          |
| ------------- | ----------------------------------- | ---------------------------------- |
| **centrality** | count of other files referencing its basename (ripgrep/regex) | "imported by many" — how load-bearing it is |
| **churn**      | number of commits touching it (`git log --name-only`) | "actively worked on" — where complexity lives |
| **entry-ness** | filename ∈ {main, index, app, server, cli, __main__, …} or under `cmd/`, `bin/` | where execution starts |

## Score

Both centrality and churn are normalized to `[0, 1]` against the repo's maximum,
then combined:

```
score = 0.45 * centrality_norm
      + 0.35 * churn_norm
      + 0.20  (if the file is an entry point)
```

Test files are forced to score `0` so they never crowd the "core modules"
reading list — they get their own section instead.

Centrality is weighted highest because "what does everything depend on" is the
best single predictor of what you must understand to be productive. Churn breaks
ties toward the code that is actually moving.

## Noise control

- Files under `node_modules`, `dist`, `build`, `vendor`, `target`, `.venv`,
  `__pycache__`, and other build/dep dirs are skipped entirely.
- Very generic basenames (`index`, `main`, `test`, `utils`) are damped in the
  centrality pass so they don't score artificially high from name collisions.
- Only recognized source extensions are considered; docs and assets are ignored
  for ranking but config manifests are surfaced separately as "read first".

## Why it's a proxy, not a graph

True centrality would parse each language's import system and build a directed
dependency graph. That's accurate but language-specific and heavy. The
basename-reference heuristic is language-agnostic and good enough to *aim*
attention — which is the goal. It can over-count when a stem is a common English
word and under-count re-exports or dynamically constructed imports. Treat the
ranking as a fast prior, then read the top files to confirm.

## Churn depends on history

Churn is only meaningful with git history. On a shallow clone (`--depth 1`) or a
brand-new repo, every file has churn ≈ 1 and the ranking falls back almost
entirely to centrality. For the richest tour, run against a full clone.
