# 🧩 Dev Lifecycle Skills for Claude

A collection of [Claude Agent Skills](https://code.claude.com/docs) that attack
the *uncertainty* tax on shipping software — the anxious questions between "done
coding" and "safely shipped" that no linter answers. Each skill pairs a
**read-only analysis engine** (pure Python 3 stdlib + `git`, `ripgrep` when
available) with a **workflow** that tells Claude how to act on the output.

Together they cover the full loop:

| Stage | Skill | The question it kills |
| ----- | ----- | --------------------- |
| 🛰️ **Understand** | [`repo-radar`](skills/repo-radar) | *"I'm new here — where do I even start?"* |
| 🔪 **Build** | [`commit-surgeon`](skills/commit-surgeon) | *"My working tree is a mess — how do I commit this cleanly?"* |
| 🧭 **Ship** | [`blast-radius`](skills/blast-radius) | *"What does this change break? Did I forget tests/docs?"* |
| 🎯 **Debug** | [`stack-to-repro`](skills/stack-to-repro) | *"Here's a crash — where is it and how do I reproduce it?"* |

Each is language-agnostic (Python, JS/TS, Go, Java, Ruby, Rust, PHP, C/C++, C#,
Kotlin, Swift) and never writes to your repo — the engines only read; Claude does
the edits deliberately, guided by what they find.

---

## 🛰️ repo-radar — onboarding autopilot

Drop into any unfamiliar codebase and get an instant guided tour: entry points,
the **core load-bearing modules ranked by reference-centrality × git churn**, the
hottest files, where tests live, and the config that defines the project — in a
suggested reading order. Turns a lost first day into a ten-minute orientation.

```bash
python3 skills/repo-radar/scripts/tour.py --md TOUR.md
```

## 🔪 commit-surgeon — messy tree → atomic commits

You made five unrelated changes in one sitting. This clusters the diff by
concern, infers a Conventional-Commit type and message per group, orders them for
review (`build → refactor → feat → fix → perf → test → docs → ci → style`), and
emits a runnable staging script. Mixed-concern files are flagged for `git add -p`.

```bash
python3 skills/commit-surgeon/scripts/plan_commits.py --md commit-plan.md --sh commit.sh
```

## 🧭 blast-radius — pre-merge impact analyzer

Before you merge, it maps the full blast radius: **who calls what you changed**
(reverse dependencies), which collateral surfaces are touched (tests, docs, API,
migrations, config, i18n), a 0–100 risk score, and an actionable ship-readiness
checklist. Catches the caller outside your diff and the test you forgot.

```bash
python3 skills/blast-radius/scripts/blast_radius.py --base origin/main --md report.md
```

## 🎯 stack-to-repro — crash → failing test

Paste a production/CI stack trace and it locates the **exact culprit frame inside
your repo** (skipping library noise), extracts the failing function, and
scaffolds a minimal red test that reproduces the crash — so you write the fix,
not the archaeology. Supports Python, JS/TS/Node, Java/Kotlin, Ruby, Go, PHP.

```bash
python3 skills/stack-to-repro/scripts/parse_trace.py trace.txt --md repro-brief.md
```

---

## Layout

```
.
├── README.md
├── LICENSE
├── .gitignore
└── skills/
    ├── repo-radar/
    │   ├── SKILL.md              # when to use it + the workflow Claude follows
    │   ├── scripts/tour.py        # ranking engine (churn × centrality)
    │   └── references/ranking.md
    ├── commit-surgeon/
    │   ├── SKILL.md
    │   └── scripts/plan_commits.py
    ├── blast-radius/
    │   ├── SKILL.md
    │   ├── scripts/blast_radius.py
    │   ├── references/methodology.md
    │   └── examples/example-report.md
    └── stack-to-repro/
        ├── SKILL.md
        ├── scripts/parse_trace.py
        └── references/trace-formats.md
```

Each skill is a self-contained directory: a `SKILL.md` (with YAML frontmatter
Claude uses to decide when to invoke it), a `scripts/` engine, and optional
`references/` and `examples/`.

## Install

Copy any (or all) of the skill directories into your project's or personal skills
folder so Claude Code discovers them:

```bash
# Project-scoped (shared with your team via the repo)
mkdir -p .claude/skills && cp -r skills/* .claude/skills/

# Personal (available in every project)
mkdir -p ~/.claude/skills && cp -r skills/* ~/.claude/skills/
```

Claude loads the right one automatically when a request matches — *"give me a
tour of this repo"*, *"split my changes into clean commits"*, *"what does this
change break?"*, *"reproduce this stack trace"* — or you can run any engine
standalone (they're just Python scripts) and wire them into CI or git hooks.

## Design principles

- **Read-only engines.** No skill mutates your repo. Analysis is separated from
  action; Claude makes edits deliberately, with the analysis as evidence.
- **Zero dependencies.** Python 3 stdlib + `git`. `ripgrep` is used if present,
  with a pure-Python fallback. Nothing to install.
- **Heuristic, honestly.** The engines are fast text/git heuristics, not
  compilers. Every skill states its blind spots; treat outputs as *leads to
  verify*, not proof.

## Limits

All four engines are heuristic and text/git-based. They can miss dynamic
dispatch, reflection, minified code, and cross-language boundaries, and can
over-report common names. They're built to *focus attention*, not to gate merges
or replace judgment. Each skill's `references/` documents its specific
assumptions and failure modes.

## License

MIT — see [`LICENSE`](LICENSE). Contributions and new skills welcome.
