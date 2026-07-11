# Methodology

How `blast_radius.py` turns a diff into an impact map and a risk score.

## 1. Scope resolution

The diff scope is chosen by flag:

| Invocation            | Scope                                              |
| --------------------- | ------------------------------------------------- |
| _(none)_              | `git diff HEAD` + unstaged — everything uncommitted |
| `--staged`            | `git diff --staged` — index only                  |
| `--base <ref>`        | `<ref>...HEAD` plus any uncommitted work          |

Diffs are taken with `--unified=0` so only changed lines are considered when
extracting symbols (context lines never introduce a "changed" symbol).

## 2. File classification

Each changed path is bucketed by extension, name, and path segment into:
`code`, `test`, `docs`, `api`, `migration`, `config`, `i18n`, or `other`.
Order matters — a file under `tests/` that ends in `.md` is a test, not docs.
This drives both the collateral map and the checklist.

## 3. Symbol extraction

For `code` files, added lines (`+`) are matched against a set of per-language
regexes that capture declaration names: functions, methods, classes, structs,
enums, traits, interfaces, exported consts, and types across Python, JS/TS, Go,
Java, Ruby, Rust, PHP, C/C++, C#, Kotlin, Swift.

Two filters cut noise:
- Names shorter than 3 characters are dropped.
- A `NOISE_SYMBOLS` set removes ubiquitous names (`main`, `get`, `handler`,
  `data`, …) that would produce meaningless reverse-dependency lists.

This is deliberately heuristic. It favors *recall of the surfaces worth
checking* over precise parsing, because the output is a review aid, not a
compiler.

## 4. Reverse-dependency search

For each surviving symbol, the repo is searched for word-boundary references
(`\bSYMBOL\b`) using `ripgrep` when available, else a stdlib walker that skips
`.git`, `node_modules`, `.venv`, `dist`, `build`. The file that defined the
symbol and any file already in the diff are excluded, so the result is
"who *outside this change* depends on what I touched."

Known blind spots: dynamic dispatch, reflection, dependency injection,
string-constructed calls, and cross-language boundaries (e.g. a symbol called
from a template or a config file of an unscanned type).

## 5. Scoring

Per code file:

```
risk = min(100, 10 + fan_out * 8 + symbol_count * 3)
```

where `fan_out` is the number of external referencing files. API and migration
files are floored at 70 because they are externally visible or hard to reverse.

Overall score is the max per-file risk, bumped by +15 if the checklist found a
`MISSING` collateral surface. Bands: `<35` low, `35–64` medium, `≥65` high.

The score is a prior meant to direct attention, not a merge gate. A high score
on a deliberate, well-migrated breaking change is fine; a low score never
excuses skipping the call-site review.

## 6. Checklist generation

The checklist cross-references the collateral map against the code changes:

- Changed code file with no same-stem test in the diff → `MISSING TEST`.
- Externally-called symbols changed with no tests/docs touched → `MISSING
  TEST` / `REVIEW DOCS`.
- Any API, migration, config, or i18n file present → the matching caution.
- Repo has a `CHANGELOG` but the diff doesn't touch it → `CHANGELOG`.

Every item is phrased as an action so it can be worked top-to-bottom.
