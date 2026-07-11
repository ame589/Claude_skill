#!/usr/bin/env python3
"""
plan_commits.py — Split a messy working tree into clean, atomic commits.

You made five unrelated changes in one sitting; now they need to land as a
reviewable sequence, not one giant blob. This tool inspects the diff, clusters
changed files by concern, infers a Conventional-Commit type and message for each
cluster, and emits:
  * a human-readable commit plan, and
  * a runnable shell script that stages and commits each group in order.

Clustering is at FILE granularity (robust and reversible). Files that mix two
concerns are flagged so you can split them by hand with `git add -p`.

Dependency-free (stdlib + git). Read-only unless you run the emitted script.

Usage:
    python3 plan_commits.py                     # plan the current working tree
    python3 plan_commits.py --md plan.md --sh commit.sh
    python3 plan_commits.py --format json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #

def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout
    except FileNotFoundError:
        sys.exit("error: git not found on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: git {' '.join(args)} failed:\n{e.stderr}")


def changed_files() -> list[tuple[str, str]]:
    """Return [(status, path)] for every changed/untracked file."""
    out = git("status", "--porcelain=1", "--untracked-files=all")
    files: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status = line[:2].strip() or "??"
        path = line[3:].strip()
        # Handle rename "old -> new"
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        files.append((status, path))
    return files


def file_diff(path: str) -> str:
    """Best-effort added/removed content for a single path (for keyword mining)."""
    # Tracked changes:
    d = git("diff", "HEAD", "--", path)
    if d.strip():
        return d
    # Untracked file: show its content as additions.
    p = Path(path)
    if p.exists() and p.is_file():
        try:
            return "\n".join("+" + l for l in p.read_text(errors="ignore").splitlines()[:400])
        except OSError:
            return ""
    return ""


# --------------------------------------------------------------------------- #
# Concern inference
# --------------------------------------------------------------------------- #

TEST_HINTS = ("test", "spec", "__tests__", "e2e")
DOC_EXTS = {".md", ".mdx", ".rst", ".adoc", ".txt"}
DOC_DIRS = ("doc", "docs", "documentation")
CONFIG_EXTS = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".json", ".lock"}
CONFIG_NAMES = {"dockerfile", "makefile", ".gitignore", ".dockerignore",
                "package.json", "pyproject.toml", "go.mod", "cargo.toml",
                "requirements.txt", "gemfile", "docker-compose.yml"}
CI_HINTS = (".github/", ".gitlab-ci", "jenkinsfile", ".circleci", ".travis")
STYLE_HINTS = (".prettierrc", ".eslintrc", ".editorconfig", ".ruff", "black")

FIX_WORDS = re.compile(r"\b(fix|bug|patch|hotfix|resolve|crash|npe|null|error|exception|regression)\b", re.I)
FEAT_WORDS = re.compile(r"\b(add|new|feature|implement|introduce|support|enable)\b", re.I)
REFACTOR_WORDS = re.compile(r"\b(refactor|rename|extract|inline|cleanup|simplify|restructure|move)\b", re.I)
PERF_WORDS = re.compile(r"\b(perf|performance|optimi[sz]e|cache|faster|latency|throughput)\b", re.I)


@dataclass
class Change:
    path: str
    status: str
    concern: str           # test|docs|config|ci|style|build|src
    module: str            # top-level dir / grouping key
    added: int = 0
    removed: int = 0
    keywords: set = field(default_factory=set)


def classify_concern(path: str) -> str:
    p = path.lower()
    name = os.path.basename(p)
    ext = os.path.splitext(name)[1]
    if any(h in p for h in CI_HINTS):
        return "ci"
    if any(h in name for h in STYLE_HINTS):
        return "style"
    if any(h in p for h in TEST_HINTS):
        return "test"
    if ext in DOC_EXTS or any(f"/{d}/" in f"/{p}" for d in DOC_DIRS):
        return "docs"
    if ext in CONFIG_EXTS or name in CONFIG_NAMES:
        return "config"
    return "src"


def normalize_stem(path: str) -> str:
    """File stem with test_/spec_ prefixes and _test/_spec/.test suffixes stripped,
    so a test file maps to the module it exercises."""
    stem = Path(path).stem
    stem = re.sub(r"^(test_|spec_)", "", stem)
    stem = re.sub(r"(_test|_spec|\.test|\.spec|Test|Spec)$", "", stem)
    return stem or Path(path).stem


def top_module(path: str) -> str:
    parts = Path(path).parts
    # Skip common wrapper dirs (including test roots) to find a meaningful key.
    skip = {"src", "lib", "app", "pkg", "internal", "packages",
            "tests", "test", "spec", "__tests__", "e2e"}
    for part in parts[:-1]:
        if part.lower() not in skip and not part.startswith("."):
            return part
    # No meaningful directory — group by the (test-normalized) file name so a
    # feature and its test share a scope and land together.
    return normalize_stem(path)


def mine_keywords(diff: str) -> set[str]:
    kws: set[str] = set()
    for rx, tag in ((FIX_WORDS, "fix"), (FEAT_WORDS, "feat"),
                    (REFACTOR_WORDS, "refactor"), (PERF_WORDS, "perf")):
        if rx.search(diff):
            kws.add(tag)
    return kws


def count_changes(diff: str) -> tuple[int, int]:
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return added, removed


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #

@dataclass
class CommitGroup:
    kind: str              # conventional-commit type
    scope: str
    files: list[str]
    message: str
    rationale: str
    mixed_flags: list[str] = field(default_factory=list)


def build_changes() -> list[Change]:
    changes: list[Change] = []
    for status, path in changed_files():
        diff = file_diff(path)
        added, removed = count_changes(diff)
        changes.append(Change(
            path=path,
            status=status,
            concern=classify_concern(path),
            module=top_module(path),
            added=added,
            removed=removed,
            keywords=mine_keywords(diff),
        ))
    return changes


def infer_kind(concern: str, keywords: set[str]) -> str:
    if concern == "docs":
        return "docs"
    if concern == "test":
        return "test"
    if concern == "ci":
        return "ci"
    if concern == "style":
        return "style"
    if concern == "config":
        return "build"
    if "fix" in keywords:
        return "fix"
    if "perf" in keywords:
        return "perf"
    if "refactor" in keywords and "feat" not in keywords:
        return "refactor"
    if "feat" in keywords:
        return "feat"
    return "chore"


def cluster(changes: list[Change]) -> list[CommitGroup]:
    # Primary key: (kind, module). Tests are pulled next to the src module they
    # cover so a feature and its tests land together.
    buckets: dict[tuple[str, str], list[Change]] = defaultdict(list)
    for ch in changes:
        kind = infer_kind(ch.concern, ch.keywords)
        # Group a test file under its source module (feature + its tests together).
        key_kind = kind
        if ch.concern == "test":
            # keep tests with their module but mark kind so message reads right
            key_kind = "feat" if any(
                c.module == ch.module and c.concern == "src" and infer_kind(c.concern, c.keywords) in ("feat", "fix")
                for c in changes
            ) else "test"
        buckets[(key_kind, ch.module)].append(ch)

    groups: list[CommitGroup] = []
    for (kind, module), items in buckets.items():
        files = [c.path for c in items]
        mixed = [c.path for c in items
                 if len(c.keywords) >= 2 and {"feat", "fix"} <= c.keywords]
        scope = "" if module == "root" else module
        msg = compose_message(kind, scope, items)
        rationale = summarize_rationale(kind, items)
        groups.append(CommitGroup(kind, scope, files, msg, rationale, mixed))

    # Deterministic, review-friendly order: build/config → refactor → feat → fix
    # → perf → test → docs → ci → style → chore.
    order = {k: i for i, k in enumerate(
        ["build", "refactor", "feat", "fix", "perf", "test", "docs", "ci", "style", "chore"])}
    groups.sort(key=lambda g: (order.get(g.kind, 99), g.scope))
    return groups


def compose_message(kind: str, scope: str, items: list[Change]) -> str:
    scope_str = f"({scope})" if scope else ""
    n = len(items)
    concerns = {c.concern for c in items}
    if kind == "docs":
        subject = "update documentation" if n > 1 else f"update {Path(items[0].path).name}"
    elif kind == "test":
        subject = f"add tests for {scope or 'core'}"
    elif kind == "build":
        subject = "update build/config"
    elif kind == "ci":
        subject = "update CI configuration"
    elif kind == "style":
        subject = "apply formatting/lint config"
    elif kind == "feat":
        subject = f"add {scope or 'functionality'}" if "test" not in concerns else f"add {scope} with tests"
    elif kind == "fix":
        subject = f"fix issue in {scope or 'core'}"
    elif kind == "perf":
        subject = f"optimize {scope or 'hot path'}"
    elif kind == "refactor":
        subject = f"refactor {scope or 'internals'}"
    else:
        subject = f"update {scope or 'project'}"
    return f"{kind}{scope_str}: {subject}"


def summarize_rationale(kind: str, items: list[Change]) -> str:
    total_a = sum(c.added for c in items)
    total_r = sum(c.removed for c in items)
    return (f"{len(items)} file(s), +{total_a}/-{total_r}; grouped as `{kind}` "
            f"because of file type and change keywords.")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_md(groups: list[CommitGroup]) -> str:
    if not groups:
        return "# 🔪 Commit Surgeon\n\nWorking tree is clean — nothing to commit."
    out = ["# 🔪 Commit Surgeon — proposed atomic commits", ""]
    out.append(f"Splitting your working tree into **{len(groups)} commits**, "
               "ordered for review:\n")
    for i, g in enumerate(groups, 1):
        out.append(f"## {i}. `{g.message}`")
        out.append(f"_{g.rationale}_\n")
        for f in g.files:
            out.append(f"- `{f}`")
        if g.mixed_flags:
            out.append("")
            out.append("> ⚠️ **Mixed concern** — these files contain both a feature "
                       "and a fix. Consider splitting them with `git add -p`:")
            for f in g.mixed_flags:
                out.append(f">  - `{f}`")
        out.append("")
    out.append("---")
    out.append("Apply with the generated `commit.sh`, or stage each group by hand. "
               "Review every message before committing — the type/scope are inferred.")
    return "\n".join(out)


def render_sh(groups: list[CommitGroup]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "# Generated by commit-surgeon. Review before running.",
        "# Each block stages one concern and commits it. Edit messages as needed.",
        "set -euo pipefail",
        "",
        "git reset -q  # unstage everything first for a clean split",
        "",
    ]
    for i, g in enumerate(groups, 1):
        lines.append(f"# --- Commit {i}: {g.kind} ---")
        if g.mixed_flags:
            lines.append("# NOTE: mixed-concern files below — consider 'git add -p' instead:")
            for f in g.mixed_flags:
                lines.append(f"#   {f}")
        quoted = " ".join(f'"{f}"' for f in g.files)
        lines.append(f"git add {quoted}")
        msg = g.message.replace('"', '\\"')
        lines.append(f'git commit -m "{msg}"')
        lines.append("")
    lines.append('echo "Done. Review with: git log --oneline --stat"')
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Split the working tree into atomic commits.")
    ap.add_argument("--md", metavar="PATH", help="Write the plan (Markdown) to PATH.")
    ap.add_argument("--sh", metavar="PATH", help="Write the staging script to PATH.")
    ap.add_argument("--json", metavar="PATH", help="Write JSON plan to PATH.")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    groups = cluster(build_changes())
    md = render_md(groups)
    sh = render_sh(groups)
    js = json.dumps([asdict(g) for g in groups], indent=2)

    if args.md:
        Path(args.md).write_text(md)
    if args.sh:
        p = Path(args.sh)
        p.write_text(sh)
        os.chmod(p, 0o755)
    if args.json:
        Path(args.json).write_text(js)
    print(js if args.format == "json" else md)


if __name__ == "__main__":
    main()
