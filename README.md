# 🧭 blast-radius — a Claude skill

> Know exactly what your change touches **before** you ship it.

`blast-radius` is a [Claude Agent Skill](https://code.claude.com/docs) that maps
the full impact — the *blast radius* — of a code change before it merges, then
helps you close every gap it finds.

The slow part of shipping isn't writing the code. It's the anxious checklist
before you hit merge: *Which callers depend on what I changed? Did I update the
tests, the docs, the changelog? Is there an API or migration surface that will
break a consumer downstream?* Today that review is manual, inconsistent, and
easy to rush. `blast-radius` answers it mechanically from `git` + a
reverse-dependency search, scores the risk, and turns "looks fine to me" into an
evidence-backed ship decision — shrinking the review loop that sits between
"done coding" and "safely shipped."

## Why it's useful

- **Faster time-to-market.** Removes the guesswork that stalls PRs and the
  hidden breakage that causes rollbacks.
- **Catches what humans forget.** Missing tests, stale docs, un-updated locales,
  irreversible migrations, callers that live *outside* your diff.
- **Language-agnostic.** Heuristic symbol + reference analysis works across
  Python, JS/TS, Go, Java, Ruby, Rust, PHP, C/C++, C#, Kotlin, Swift.
- **Zero dependencies, read-only.** Pure Python 3 stdlib + `git` (uses `ripgrep`
  if present). It never writes to your repo — it only reads.

## What it produces

1. An **overall risk score** (0–100) with a 🟢/🟡/🔴 band.
2. A **ship-readiness checklist** of concrete, actionable gaps.
3. A **reverse-dependency map**: for every symbol you changed, who calls it —
   with callers outside your diff highlighted as follow-ups.
4. A **collateral map** of the tests / docs / API / migration / config / i18n
   surfaces the change touches.

Claude then works the checklist top-to-bottom — writing the missing tests,
updating the drifted docs, drafting the migration note — and re-runs to confirm
the risk is closed.

## Layout

```
.
├── README.md
├── .gitignore
└── blast-radius/
    ├── SKILL.md                 # the skill: when to use it + the workflow Claude follows
    ├── scripts/
    │   └── blast_radius.py       # the analysis engine (stdlib-only)
    ├── references/
    │   └── methodology.md        # how scoring & heuristics work
    └── examples/
        └── example-report.md     # a sample run
```

## Install

Drop the `blast-radius/` directory into your project's or personal skills
folder so Claude Code can discover it:

```bash
# Project-scoped (shared with your team via the repo)
mkdir -p .claude/skills && cp -r blast-radius .claude/skills/

# Personal (available in every project)
mkdir -p ~/.claude/skills && cp -r blast-radius ~/.claude/skills/
```

Claude loads it automatically when a request matches — e.g. *"what does this
change break?"*, *"is this safe to ship?"*, *"who calls this function?"*, or
*"run a pre-merge check."*

## Run it directly

The engine also works standalone, without Claude:

```bash
# Uncommitted + staged work
python3 blast-radius/scripts/blast_radius.py --md report.md

# Everything on this branch vs. the base — best before a PR
python3 blast-radius/scripts/blast_radius.py --base origin/main --md report.md

# Machine-readable output for CI
python3 blast-radius/scripts/blast_radius.py --base origin/main --format json --json report.json
```

Wire it into CI to post the report on every PR, or into a pre-push hook to catch
a wide blast radius before it leaves your machine.

## Limits

Symbol extraction and reference search are heuristic and text-based. Treat the
reverse-dependency list as *leads to verify*, not proof: it can miss dynamic
dispatch, reflection, and string-built calls, and can over-report very common
names. It's a review aid that focuses attention — not a compiler and not a merge
gate. See [`blast-radius/references/methodology.md`](blast-radius/references/methodology.md)
for the full details.

## License

MIT — see [`LICENSE`](LICENSE). Contributions welcome.
