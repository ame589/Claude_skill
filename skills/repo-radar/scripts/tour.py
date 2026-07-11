#!/usr/bin/env python3
"""
tour.py — Generate an instant guided tour of an unfamiliar codebase.

Dropping into a new repo, the first hour is spent answering "where do I even
start?". This tool answers it mechanically. It combines three signals:

  * churn        — how often a file changes (git history) → where the action is
  * centrality   — how many other files reference it → the load-bearing modules
  * entry-ness   — is it a recognizable entry point (main/index/app/cli/server)

…into a ranked reading order, plus a map of languages, where tests live, and the
key config. The output is a "Start here → then read these → here's the layout"
tour that gets a newcomer productive fast.

Dependency-free (stdlib + git; uses ripgrep if present).

Usage:
    python3 tour.py                 # tour the current repo
    python3 tour.py --top 15 --md TOUR.md
    python3 tour.py --format json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".go", ".java", ".rb", ".rs",
    ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt", ".swift", ".scala",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "vendor",
             "target", "__pycache__", ".next", ".cache", "coverage", "out"}
ENTRY_NAMES = {"main", "index", "app", "server", "cli", "__main__", "manage",
               "run", "start", "wsgi", "asgi", "bootstrap", "program"}
ENTRY_DIRS = ("cmd/", "bin/", "src/bin/")
TEST_HINTS = ("test", "spec", "__tests__", "e2e")
CONFIG_NAMES = {"package.json", "pyproject.toml", "go.mod", "cargo.toml",
                "pom.xml", "build.gradle", "requirements.txt", "gemfile",
                "composer.json", "dockerfile", "docker-compose.yml", "makefile",
                "setup.py", "tsconfig.json", "readme.md"}


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout
    except Exception:
        return None


def repo_root() -> Path:
    out = git("rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else Path.cwd()


@dataclass
class FileNode:
    path: str
    ext: str
    churn: int = 0
    centrality: int = 0
    is_entry: bool = False
    is_test: bool = False
    score: float = 0.0
    loc: int = 0


def walk_repo(root: Path) -> list[FileNode]:
    nodes: list[FileNode] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            fp = Path(dirpath) / fn
            ext = fp.suffix.lower()
            if ext not in CODE_EXTS:
                continue
            rel = os.path.relpath(fp, root)
            low = rel.lower()
            is_test = any(h in low for h in TEST_HINTS)
            is_entry = (fp.stem.lower() in ENTRY_NAMES) or any(low.startswith(d) for d in ENTRY_DIRS)
            try:
                loc = sum(1 for _ in fp.open(errors="ignore"))
            except OSError:
                loc = 0
            nodes.append(FileNode(rel, ext, is_entry=is_entry, is_test=is_test, loc=loc))
    return nodes


def compute_churn(root: Path, nodes: list[FileNode]) -> None:
    log = git("log", "--pretty=format:", "--name-only", "--no-merges")
    if not log:
        return
    counts = Counter(l.strip() for l in log.splitlines() if l.strip())
    for n in nodes:
        n.churn = counts.get(n.path, 0)


def compute_centrality(root: Path, nodes: list[FileNode]) -> None:
    """In-degree: how many files mention this module's basename (import proxy)."""
    have_rg = shutil.which("rg") is not None
    # Precompute module tokens to search for (basename without extension).
    for n in nodes:
        token = Path(n.path).stem
        if len(token) < 3 or token in ("index", "main", "test", "utils"):
            n.centrality = 0
            continue
        pattern = rf"\b{re.escape(token)}\b"
        count = 0
        if have_rg:
            proc = subprocess.run(
                ["rg", "-l", "--no-messages", pattern, str(root)],
                capture_output=True, text=True)
            files = [f for f in proc.stdout.splitlines()
                     if os.path.relpath(f, root) != n.path]
            count = len(files)
        else:
            rx = re.compile(pattern)
            for other in nodes:
                if other.path == n.path:
                    continue
                try:
                    if rx.search((root / other.path).read_text(errors="ignore")):
                        count += 1
                except OSError:
                    pass
        n.centrality = count


def score(nodes: list[FileNode]) -> None:
    max_churn = max((n.churn for n in nodes), default=1) or 1
    max_cent = max((n.centrality for n in nodes), default=1) or 1
    for n in nodes:
        if n.is_test:
            n.score = 0.0
            continue
        churn_n = n.churn / max_churn
        cent_n = n.centrality / max_cent
        n.score = round(0.45 * cent_n + 0.35 * churn_n + (0.20 if n.is_entry else 0.0), 4)


def detect_languages(nodes: list[FileNode]) -> list[tuple[str, int]]:
    c = Counter(n.ext for n in nodes)
    return c.most_common()


def find_configs(root: Path) -> list[str]:
    found = []
    for name in CONFIG_NAMES:
        for p in root.glob(name):
            found.append(os.path.relpath(p, root))
        # case-insensitive top-level
    for p in root.iterdir() if root.is_dir() else []:
        if p.is_file() and p.name.lower() in CONFIG_NAMES:
            rel = os.path.relpath(p, root)
            if rel not in found:
                found.append(rel)
    return sorted(set(found))


def test_layout(nodes: list[FileNode]) -> list[str]:
    dirs = Counter()
    for n in nodes:
        if n.is_test:
            dirs[str(Path(n.path).parent)] += 1
    return [f"{d} ({c} files)" for d, c in dirs.most_common(5)]


def build_tour(top: int) -> dict:
    root = repo_root()
    nodes = walk_repo(root)
    if not nodes:
        return {"error": "No source files found."}
    compute_churn(root, nodes)
    compute_centrality(root, nodes)
    score(nodes)

    ranked = sorted(nodes, key=lambda n: -n.score)
    entries = [n for n in nodes if n.is_entry and not n.is_test]
    entries.sort(key=lambda n: -n.score)
    core = [n for n in ranked if not n.is_entry and not n.is_test][:top]
    hottest = sorted((n for n in nodes if not n.is_test), key=lambda n: -n.churn)[:top]

    return {
        "root": str(root),
        "file_count": len(nodes),
        "languages": [{"ext": e, "files": c} for e, c in detect_languages(nodes)],
        "entry_points": [asdict(n) for n in entries[:top]],
        "core_modules": [asdict(n) for n in core],
        "hottest_files": [asdict(n) for n in hottest],
        "test_layout": test_layout(nodes),
        "configs": find_configs(root),
    }


def bar(v: float, width: int = 12) -> str:
    filled = int(round(v * width))
    return "█" * filled + "·" * (width - filled)


def render_md(t: dict, top: int) -> str:
    if t.get("error"):
        return f"# 🛰️ Repo Radar\n\n{t['error']}"
    out = ["# 🛰️ Repo Radar — a guided tour", ""]
    langs = ", ".join(f"`{l['ext']}`×{l['files']}" for l in t["languages"][:6])
    out.append(f"**{t['file_count']} source files** · {langs}")
    out.append("")

    if t["configs"]:
        out.append("## 🧰 Read these first (project shape)")
        for c in t["configs"][:10]:
            out.append(f"- `{c}`")
        out.append("")

    if t["entry_points"]:
        out.append("## 🚪 Start here — entry points")
        for n in t["entry_points"]:
            out.append(f"- `{n['path']}`  _(churn {n['churn']}, refs {n['centrality']})_")
        out.append("")

    out.append("## 🧭 Core modules — read in this order")
    out.append("_Ranked by reference-centrality × churn — the load-bearing code._\n")
    maxs = max((n["score"] for n in t["core_modules"]), default=1) or 1
    for i, n in enumerate(t["core_modules"], 1):
        rel = n["score"] / maxs
        out.append(f"{i:>2}. `{n['path']}`  {bar(rel)}  "
                   f"_(refs {n['centrality']}, churn {n['churn']}, {n['loc']} loc)_")
    out.append("")

    out.append("## 🔥 Hottest files (most-changed — likely where bugs & features live)")
    for n in t["hottest_files"][:min(top, 10)]:
        if n["churn"]:
            out.append(f"- `{n['path']}`  _({n['churn']} commits)_")
    out.append("")

    if t["test_layout"]:
        out.append("## 🧪 Where the tests live")
        for d in t["test_layout"]:
            out.append(f"- `{d}`")
        out.append("")

    out.append("---")
    out.append("_Generated by the `repo-radar` skill. A statistical map, not a "
               "substitute for the README — but a fast way to know what matters._")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a guided tour of a codebase.")
    ap.add_argument("--top", type=int, default=12, help="How many files per section.")
    ap.add_argument("--md", metavar="PATH", help="Write the tour (Markdown) to PATH.")
    ap.add_argument("--json", metavar="PATH", help="Write JSON to PATH.")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    tour = build_tour(args.top)
    md = render_md(tour, args.top)
    js = json.dumps(tour, indent=2)
    if args.md:
        Path(args.md).write_text(md)
    if args.json:
        Path(args.json).write_text(js)
    print(js if args.format == "json" else md)


if __name__ == "__main__":
    main()
