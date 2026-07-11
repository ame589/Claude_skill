---
name: stack-to-repro
description: >-
  Turn a production or CI stack trace into a minimal failing test that
  reproduces the crash, then fix it. Locates the exact culprit frame inside the
  repo, extracts the failing function, scaffolds a red test, and drives it to
  green. Use this whenever the user pastes a stack trace, exception, traceback,
  panic, or error log and wants it debugged/reproduced/fixed, or asks "why is
  this crashing / where does this error come from / write a test for this bug".
  Triggers on: "stack trace", "traceback", "exception", "this is crashing",
  "reproduce this bug", "repro", "panic:", "NullPointerException", "unhandled
  rejection", "why does this fail in prod".
---

# Stack-to-Repro

## What this does

The slowest part of fixing a production bug is *reproducing* it: reading the
trace, finding the real culprit among library noise, understanding the failing
function, and writing a test that goes red for the right reason. This skill does
the mechanical part in one shot — trace in, red test out — so you spend your time
on the fix, not the archaeology. A reproduced bug is a fixed bug; an
unreproduced one is a guess.

## When to use it

- The user pastes a stack trace, traceback, exception, panic, or error log.
- The user asks to reproduce, debug, or "write a failing test for" a crash.
- A CI failure or Sentry/Rollbar-style report needs to become a local red test.

## Workflow

### 1. Capture the trace, then parse it

Save the trace the user gave you to a file (or pipe it in) and run:

```bash
python3 skills/stack-to-repro/scripts/parse_trace.py trace.txt --md repro-brief.md
# or inline:
python3 skills/stack-to-repro/scripts/parse_trace.py --text "<the trace>"
# or piped:
cat trace.txt | python3 skills/stack-to-repro/scripts/parse_trace.py -
```

The parser supports Python, JS/TS/Node, Java/Kotlin, Ruby, Go, and PHP. It needs
only Python 3 and git.

### 2. Confirm the culprit

The brief names the **culprit frame** — the deepest *application* frame (it
skips library frames) — with `file:line`, the enclosing function, and its source.
Sanity-check it: does that function plausibly raise the reported exception? If
the deepest in-repo frame is flagged as outside the repo, the bug is likely in
how your code *calls* a library — inspect the nearest 🏠 in-repo frame instead.

### 3. Turn the skeleton into a real red test

The brief includes a suggested test-file path and a language-appropriate
skeleton. Replace the `...`/TODO inputs with the **actual arguments and state
from the failing call site** (read the culprit function and its callers to
recover them). The goal is a test that fails with the *same* exception type and
message as the trace. Run it and confirm it is **red for the right reason** — a
test that fails for a different reason is not a reproduction.

### 4. Fix, then confirm green

Only now change the production code. Re-run the test: it must go green. Then run
the surrounding suite so the fix didn't break a neighbor. If the project also
has the `blast-radius` skill, run it on your fix to see what else the change
touches.

### 5. Leave the test behind

Keep the reproduction test in the suite — it is now a regression guard. Name it
so its origin is obvious (e.g. `test_repro_<bug>`), and reference the original
error in a comment.

## Notes & limits

- Frame parsing and function extraction are heuristic. Always eyeball the culprit
  before trusting it; minified/obfuscated JS and deeply async traces can mislead
  the "deepest frame" pick.
- The tool is read-only — it never edits code. Steps 3–5 are your normal edits.
- If no in-repo frame is found, the crash originates in a dependency; focus on
  the boundary where your code hands data to that dependency.
- See `references/trace-formats.md` for the exact frame grammars supported.
