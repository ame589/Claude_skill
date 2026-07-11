#!/usr/bin/env python3
"""
blast_radius.py — Map the full impact ("blast radius") of a code change.

Given a git diff (working tree, staged, or against a base ref), this tool:
  1. Identifies changed files and the public symbols touched in each.
  2. Finds reverse dependencies (callers/importers) of those symbols across the repo.
  3. Flags collateral surfaces that changes commonly forget: tests, docs,
     API/schema/migration files, config, i18n/locale strings.
  4. Computes a per-change and overall risk score.
  5. Emits a human-readable Markdown report and a machine-readable JSON blob.

It is intentionally dependency-free (stdlib only) and language-agnostic:
symbol extraction is heuristic and covers Python, JS/TS, Go, Java, Ruby, Rust,
PHP, C/C++, C#, Kotlin, Swift. Reference search uses ripgrep when available and
falls back to a pure-Python walker.

Usage:
    python3 blast_radius.py                       # working tree + staged changes
    python3 blast_radius.py --base origin/main    # everything since a base ref
    python3 blast_radius.py --staged              # only staged changes
    python3 blast_radius.py --json report.json --md report.md
    python3 blast_radius.py --format json         # print JSON to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# File classification
# --------------------------------------------------------------------------- #

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java",
    ".rb", ".rs", ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt",
    ".swift", ".scala", ".m", ".mm",
}
DOC_EXTS = {".md", ".mdx", ".rst", ".adoc", ".txt"}
CONFIG_EXTS = {".yml", ".yaml", ".toml", ".ini", ".env", ".cfg", ".properties"}
CONFIG_NAMES = {
    "dockerfile", "makefile", "package.json", "pyproject.toml", "go.mod",
    "cargo.toml", "pom.xml", "build.gradle", "requirements.txt", "gemfile",
    "composer.json", ".env", "docker-compose.yml", "docker-compose.yaml",
}

TEST_HINTS = ("test", "spec", "__tests__", "e2e")
DOC_DIR_HINTS = ("doc", "docs", "documentation", "wiki")
MIGRATION_HINTS = ("migration", "migrations", "schema", "alembic")
API_HINTS = ("openapi", "swagger", ".proto", "graphql", ".gql", "api")
I18N_HINTS = ("locale", "locales", "i18n", "translation", "lang", "messages")


def classify(path: str) -> str:
    p = path.lower()
    name = os.path.basename(p)
    ext = os.path.splitext(name)[1]
    if any(h in p for h in TEST_HINTS):
        return "test"
    if any(h in p for h in MIGRATION_HINTS):
        return "migration"
    if any(h in p for h in API_HINTS) or ext in (".proto", ".graphql", ".gql"):
        return "api"
    if any(h in p for h in I18N_HINTS):
        return "i18n"
    if ext in DOC_EXTS or any(f"/{h}/" in f"/{p}" for h in DOC_DIR_HINTS):
        return "docs"
    if ext in CONFIG_EXTS or name in CONFIG_NAMES:
        return "config"
    if ext in CODE_EXTS:
        return "code"
    return "other"


# --------------------------------------------------------------------------- #
# Symbol extraction (heuristic, per-language)
# --------------------------------------------------------------------------- #

# Each pattern captures the symbol name in group 1.
SYMBOL_PATTERNS = [
    # Python
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),
    # JS/TS
    re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)"),
    re.compile(r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$]\w*)"),
    re.compile(r"^\s*export\s+const\s+([A-Za-z_$]\w*)"),
    re.compile(r"^\s*(?:export\s+)?(?:type|interface|enum)\s+([A-Za-z_$]\w*)"),
    # Go / Java / C-family / Kotlin / Swift / Rust
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?"
               r"(?:[A-Za-z_][\w<>\[\].]*\s+)([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|type)\s+([A-Za-z_]\w*)"),
    # Ruby
    re.compile(r"^\s*def\s+([A-Za-z_]\w*[!?=]?)"),
    re.compile(r"^\s*(?:module|class)\s+([A-Za-z_]\w*)"),
]

# Names too generic to be worth tracing as reverse dependencies.
NOISE_SYMBOLS = {
    "main", "init", "setup", "run", "get", "set", "new", "test", "index",
    "toString", "constructor", "handler", "process", "start", "stop", "close",
    "open", "read", "write", "update", "create", "delete", "list", "next",
    "value", "data", "result", "error", "self", "this", "String", "Error",
}


def extract_added_symbols(diff_body: str) -> set[str]:
    """Pull symbol names from ADDED/CHANGED lines of a unified diff hunk."""
    symbols: set[str] = set()
    for line in diff_body.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        for pat in SYMBOL_PATTERNS:
            m = pat.match(content)
            if m:
                sym = m.group(1)
                if sym and sym not in NOISE_SYMBOLS and len(sym) > 2:
                    symbols.add(sym)
    return symbols


# --------------------------------------------------------------------------- #
# Git plumbing
# --------------------------------------------------------------------------- #

def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        )
        return out.stdout
    except FileNotFoundError:
        sys.exit("error: git is not installed or not on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: git {' '.join(args)} failed:\n{e.stderr}")


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").strip())


def collect_diff(base: str | None, staged: bool) -> list[tuple[str, str]]:
    """Return [(path, diff_body)] for each changed file."""
    if base:
        diff_args = ["diff", "--unified=0", f"{base}...HEAD"]
        # Also fold in uncommitted work so the picture is complete.
        extra = git("diff", "--unified=0", base)
    elif staged:
        diff_args = ["diff", "--unified=0", "--staged"]
        extra = ""
    else:
        diff_args = ["diff", "--unified=0", "HEAD"]
        extra = git("diff", "--unified=0")  # unstaged
    raw = git(*diff_args)
    if extra and extra != raw:
        raw = raw + "\n" + extra
    return split_per_file(raw)


def split_per_file(raw: str) -> list[tuple[str, str]]:
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("diff --git"):
            m = re.search(r" b/(.+)$", line)
            current = m.group(1) if m else None
            if current:
                files.setdefault(current, [])
        elif current is not None:
            files[current].append(line)
    return [(p, "\n".join(b)) for p, b in files.items()]


# --------------------------------------------------------------------------- #
# Reverse dependency search
# --------------------------------------------------------------------------- #

def search_references(symbol: str, root: Path, exclude: str) -> list[str]:
    """Return files (repo-relative) that reference `symbol`, excluding `exclude`."""
    hits: set[str] = set()
    pattern = rf"\b{re.escape(symbol)}\b"
    if shutil.which("rg"):
        proc = subprocess.run(
            ["rg", "-l", "--no-messages", pattern, str(root)],
            capture_output=True, text=True,
        )
        for line in proc.stdout.splitlines():
            rel = os.path.relpath(line, root)
            if rel != exclude and not rel.startswith(".git/"):
                hits.add(rel)
    else:
        rx = re.compile(pattern)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "dist", "build"}]
            for fn in filenames:
                fp = Path(dirpath) / fn
                if fp.suffix.lower() not in CODE_EXTS:
                    continue
                rel = os.path.relpath(fp, root)
                if rel == exclude:
                    continue
                try:
                    if rx.search(fp.read_text(errors="ignore")):
                        hits.add(rel)
                except (OSError, UnicodeDecodeError):
                    continue
    return sorted(hits)


# --------------------------------------------------------------------------- #
# Analysis model
# --------------------------------------------------------------------------- #

@dataclass
class FileImpact:
    path: str
    kind: str
    symbols: list[str] = field(default_factory=list)
    referenced_by: dict[str, list[str]] = field(default_factory=dict)
    risk: int = 0
    flags: list[str] = field(default_factory=list)


@dataclass
class Report:
    files: list[FileImpact]
    collateral: dict[str, list[str]]
    overall_risk: str
    risk_score: int
    checklist: list[str]


def analyze(base: str | None, staged: bool) -> Report:
    root = repo_root()
    changes = collect_diff(base, staged)
    if not changes:
        return Report([], {}, "none", 0, ["No changes detected."])

    changed_paths = {p for p, _ in changes}
    impacts: list[FileImpact] = []
    collateral: dict[str, list[str]] = {
        "tests": [], "docs": [], "api": [], "migration": [],
        "config": [], "i18n": [],
    }

    for path, body in changes:
        kind = classify(path)
        fi = FileImpact(path=path, kind=kind)

        # Track collateral surfaces already included in the diff.
        if kind == "test":
            collateral["tests"].append(path)
        elif kind == "docs":
            collateral["docs"].append(path)
        elif kind == "api":
            collateral["api"].append(path)
        elif kind == "migration":
            collateral["migration"].append(path)
        elif kind == "config":
            collateral["config"].append(path)
        elif kind == "i18n":
            collateral["i18n"].append(path)

        if kind == "code":
            syms = sorted(extract_added_symbols(body))
            fi.symbols = syms
            for sym in syms:
                refs = [r for r in search_references(sym, root, path)
                        if r not in changed_paths]
                if refs:
                    fi.referenced_by[sym] = refs
            fan_out = sum(len(v) for v in fi.referenced_by.values())
            fi.risk = min(100, 10 + fan_out * 8 + len(syms) * 3)
            if fan_out == 0 and syms:
                fi.flags.append("New/leaf symbols — no external callers found.")
            if fan_out >= 5:
                fi.flags.append(f"High fan-out: {fan_out} referencing sites.")
        elif kind in ("api", "migration"):
            fi.risk = 70
            fi.flags.append(f"{kind.upper()} surface — likely externally visible / irreversible.")
        else:
            fi.risk = 15

        impacts.append(fi)

    checklist = build_checklist(impacts, collateral, changed_paths, root)
    score = min(100, max((f.risk for f in impacts), default=0))
    # Missing collateral inflates risk.
    if any("MISSING" in c for c in checklist):
        score = min(100, score + 15)
    level = ("high" if score >= 65 else "medium" if score >= 35 else "low")
    return Report(impacts, collateral, level, score, checklist)


def build_checklist(impacts, collateral, changed_paths, root) -> list[str]:
    items: list[str] = []
    code_files = [f for f in impacts if f.kind == "code"]
    has_tests = bool(collateral["tests"])
    has_docs = bool(collateral["docs"])

    # Tests: for each changed code file, is there a plausibly-related test in the diff?
    for f in code_files:
        stem = Path(f.path).stem
        related = [t for t in collateral["tests"] if stem in Path(t).stem]
        if not related:
            items.append(f"[MISSING TEST] `{f.path}` changed but no matching test in this diff.")

    if any(f.referenced_by for f in code_files) and not has_tests:
        items.append("[MISSING TEST] Symbols with external callers changed but no tests touched.")

    if any(f.referenced_by for f in code_files) and not has_docs:
        items.append("[REVIEW DOCS] Public symbols changed — verify docs/README are still accurate.")

    if collateral["api"]:
        items.append("[BREAKING?] API/schema files changed — confirm versioning & consumer migration.")
    if collateral["migration"]:
        items.append("[IRREVERSIBLE] Migration/schema files changed — confirm rollback plan & data safety.")
    if collateral["config"]:
        items.append("[DEPLOY] Config/build files changed — confirm env parity & deploy steps.")
    if collateral["i18n"]:
        items.append("[i18n] Locale files changed — confirm all languages updated.")

    # Changelog nudge
    changelog = any(Path(root, n).exists() for n in ("CHANGELOG.md", "CHANGELOG.rst"))
    if changelog and not any("changelog" in p.lower() for p in changed_paths):
        items.append("[CHANGELOG] Repo has a CHANGELOG but this diff does not update it.")

    if not items:
        items.append("No obvious collateral gaps detected. Still review the reverse-dependency list below.")
    return items


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

RISK_BADGE = {"high": "🔴 HIGH", "medium": "🟡 MEDIUM", "low": "🟢 LOW", "none": "⚪ NONE"}


def render_markdown(r: Report) -> str:
    out = ["# 🧭 Blast Radius Report", ""]
    out.append(f"**Overall risk: {RISK_BADGE.get(r.overall_risk, r.overall_risk)}** "
               f"(score {r.risk_score}/100)")
    out.append("")
    out.append("## ✅ Ship-readiness checklist")
    for c in r.checklist:
        out.append(f"- {c}")
    out.append("")

    surfaces = {k: v for k, v in r.collateral.items() if v}
    if surfaces:
        out.append("## 🎯 Collateral surfaces touched")
        for k, v in surfaces.items():
            out.append(f"- **{k}**: {', '.join(f'`{x}`' for x in v)}")
        out.append("")

    code = [f for f in r.files if f.kind == "code"]
    if code:
        out.append("## 🔗 Reverse dependencies (who calls what you changed)")
        for f in sorted(code, key=lambda x: -x.risk):
            out.append(f"\n### `{f.path}` — risk {f.risk}/100")
            if f.symbols:
                out.append(f"Changed symbols: {', '.join(f'`{s}`' for s in f.symbols)}")
            for flag in f.flags:
                out.append(f"> ⚠️ {flag}")
            if f.referenced_by:
                for sym, refs in f.referenced_by.items():
                    shown = ", ".join(f"`{x}`" for x in refs[:12])
                    more = f" … (+{len(refs) - 12} more)" if len(refs) > 12 else ""
                    out.append(f"- `{sym}` ← {shown}{more}")
            elif f.symbols:
                out.append("- _no external callers found_")
        out.append("")
    out.append("---")
    out.append("_Generated by the `blast-radius` skill. Heuristic analysis — "
               "review before shipping._")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Map the blast radius of a code change.")
    ap.add_argument("--base", help="Base ref to diff against (e.g. origin/main).")
    ap.add_argument("--staged", action="store_true", help="Only staged changes.")
    ap.add_argument("--json", metavar="PATH", help="Write JSON report to PATH.")
    ap.add_argument("--md", metavar="PATH", help="Write Markdown report to PATH.")
    ap.add_argument("--format", choices=["md", "json"], default="md",
                    help="What to print to stdout (default: md).")
    args = ap.parse_args()

    report = analyze(args.base, args.staged)
    md = render_markdown(report)
    js = json.dumps(_serialize(report), indent=2)

    if args.json:
        Path(args.json).write_text(js)
    if args.md:
        Path(args.md).write_text(md)

    print(js if args.format == "json" else md)


def _serialize(r: Report) -> dict:
    return {
        "overall_risk": r.overall_risk,
        "risk_score": r.risk_score,
        "checklist": r.checklist,
        "collateral": r.collateral,
        "files": [asdict(f) for f in r.files],
    }


if __name__ == "__main__":
    main()
