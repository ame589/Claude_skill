---
name: blast-radius
description: >-
  Map the full impact ("blast radius") of a code change before merging: which
  callers, tests, docs, API/schema surfaces, migrations, config and i18n files
  it touches, plus a risk score and a ship-readiness checklist — then fill the
  gaps it finds. Use this before opening a PR, before merging, when reviewing a
  diff, when asked "what does this change affect / did I forget anything / is
  this safe to ship", or when a change touches shared/public code. Triggers on:
  "impact analysis", "what does this break", "blast radius", "ship readiness",
  "pre-merge check", "reverse dependencies", "who calls this", "am I forgetting
  tests/docs".
---

# Blast Radius

## What this does

Shipping is slow because of *uncertainty*, not typing. Before a change goes out,
a developer has to answer a nervous checklist: which callers depend on what I
changed? Did I update the tests, the docs, the changelog? Is there an API or
migration surface that will break a consumer? This skill answers that
mechanically from git + a reverse-dependency search, then helps close every gap
it finds — turning a vague "looks fine" into an evidence-backed ship decision.

## When to use it

- Right before opening a PR or merging.
- When the user asks "what does this affect", "what will this break", "did I
  forget anything", "is this safe to ship", "who calls this function".
- When reviewing someone else's diff and you need the impact surface fast.
- Whenever a change touches shared, exported, or public code.

## Workflow

Follow these steps in order. Do not skip step 1 — the report is the ground truth
everything else builds on.

### 1. Generate the impact report

Run the analyzer against the change under review. Pick the scope that matches
what the user is shipping:

```bash
# Uncommitted + staged work (default — "what am I about to commit")
python3 blast-radius/scripts/blast_radius.py --md blast-radius-report.md

# Everything on this branch vs the base (best for pre-PR / pre-merge)
python3 blast-radius/scripts/blast_radius.py --base origin/main --md blast-radius-report.md

# Only staged
python3 blast-radius/scripts/blast_radius.py --staged
```

The script needs only Python 3 and git; it uses `ripgrep` if present and falls
back to a pure-Python search otherwise. It prints a Markdown report and can also
emit JSON with `--json report.json` for programmatic use.

### 2. Read the report to the user, highest risk first

Lead with the **overall risk badge and score**, then the **ship-readiness
checklist**. Do not bury the risk. If the score is HIGH, say so plainly and say
why (fan-out, API surface, migration, missing tests).

### 3. Close every gap the checklist flags

The checklist is a to-do list, not a report to admire. For each flagged item,
take the concrete action:

- **`[MISSING TEST]`** → Write the missing test(s) for the changed symbols,
  matching the repo's existing test framework and conventions. Then re-run the
  analyzer to confirm the flag clears.
- **`[REVIEW DOCS]` / doc drift** → Open the docs/README sections that describe
  the changed public symbols and update them to match the new behavior.
- **`[BREAKING?]` (API/schema)** → Determine whether the change is
  backward-compatible. If not, recommend a semver bump, add a deprecation path
  where feasible, and draft a short consumer migration note.
- **`[IRREVERSIBLE]` (migration)** → Confirm a rollback/rollforward plan and
  data-safety of the migration before it merges. Never wave this through.
- **`[DEPLOY]` (config/build)** → Verify env parity and that deploy steps
  account for the config change.
- **`[i18n]`** → Ensure every locale is updated, not just the default.
- **`[CHANGELOG]`** → Add the entry.

### 4. Verify the reverse-dependency list

For each changed code file, walk the "who calls what you changed" section.
For every caller listed, confirm the call site is still correct after your
change (signature, return type, side effects, nullability). This is where
silent breakage hides. Callers that need updating but aren't in the diff are
your highest-priority follow-ups.

### 5. Re-run and give a verdict

After closing gaps, re-run step 1. Then give a one-paragraph verdict: the final
risk level, what you changed to lower it, and any residual risk the user must
sign off on (e.g. an intentional breaking change). If nothing residual remains,
say it's ready to ship and why.

## Interpreting the risk score

- **🟢 LOW (<35)** — Localized change, callers accounted for, collateral present.
- **🟡 MEDIUM (35–64)** — Real fan-out or a missing surface. Close the gaps before merge.
- **🔴 HIGH (≥65)** — Wide fan-out, API/migration surface, or missing tests on
  externally-called code. Treat as ship-blocking until justified.

The score is a heuristic prior, not a gate. Your judgment on the actual call
sites (step 4) overrides it in both directions.

## Notes & limits

- Symbol extraction and reference search are heuristic and text-based. Treat the
  reverse-dependency list as *leads to verify*, not proof. It can miss dynamic
  dispatch, reflection, and string-built calls; it can over-report common names.
- The analyzer never writes to the repo — it only reads git and files. All fixes
  in steps 3–4 are your normal edits, done deliberately.
- For a deeper explanation of scoring and heuristics, see
  `references/methodology.md`.
