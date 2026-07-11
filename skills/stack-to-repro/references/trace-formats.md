# Supported trace formats

`parse_trace.py` recognizes frames from these languages. Each row shows the
grammar the parser keys on and where the innermost (culprit) frame sits.

| Language     | Frame grammar (example)                                   | Innermost frame |
| ------------ | --------------------------------------------------------- | --------------- |
| Python       | `File "app/svc.py", line 42, in charge`                   | **last** listed |
| JS / TS / Node | `at charge (app/svc.js:42:13)` / `at app/svc.js:42:13`  | **first** listed |
| Java / Kotlin | `at com.acme.Svc.charge(Svc.java:42)`                    | **first** listed |
| Ruby         | `app/svc.rb:42:in 'charge'`                               | **first** listed |
| Go           | `main.charge(...)` then `\tapp/svc.go:42 +0x1a`           | **first** listed |
| PHP          | `#0 app/svc.php(42): Svc->charge()`                       | **first** listed |

## How the culprit is chosen

Python prints the outermost caller first and the crash site last, so the parser
takes the **last** in-repo frame. Every other supported runtime prints the crash
site first, so it takes the **first** in-repo frame. Library frames (paths that
don't resolve inside the repo) are skipped when choosing the culprit but are
still shown in the full list for context.

## Path resolution

A frame's file is matched to the repo in three escalating ways:

1. Absolute path that lives under the repo root.
2. Path relative to the repo root that exists.
3. Unique basename match via a recursive search (traces often carry only a
   partial or build-time path). Ambiguous basenames are left unresolved rather
   than guessed.

Unresolved frames are marked as out-of-repo — usually dependencies or framework
internals.

## Exception extraction

The exception type and message are read from the last non-empty line that
matches a `*Error` / `*Exception` / `panic:` / `Uncaught *` shape. This is what
the generated test asserts on, so a reproduction is only valid when your red
test raises the **same** type.

## Known blind spots

- Minified / bundled JavaScript without source maps: paths won't resolve to
  source files.
- Deeply asynchronous stacks (promise chains, goroutines, thread pools) may
  interleave frames from multiple logical call paths.
- Reflection, dynamic dispatch, and eval'd code produce frames the extractor
  can't tie back to a static function.
