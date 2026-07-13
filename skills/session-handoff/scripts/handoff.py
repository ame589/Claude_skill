#!/usr/bin/env python3
"""
handoff.py — Export a working session as a resumable handoff bundle, and
restore it on the other side.

A session's knowledge lives in two places:
  * MECHANICAL state — the repo, uncommitted work, untracked files, and the
    exact documents/knowledge sources that were loaded. This script captures
    all of it, content-hashed so the receiver can verify nothing drifted.
  * SEMANTIC state — decisions made, findings, dead ends, next steps. That
    lives in the conversation and must be written into HANDOFF.md by whoever
    (or whatever) ran the session. This script scaffolds the template; the
    session author fills it.

`create` produces a `.handoff/` bundle:
    HANDOFF.md          narrative template (auto sections filled, TODOs for author)
    state.json          branch, HEAD, remote, dirty/untracked file lists
    uncommitted.patch   all tracked changes vs HEAD (staged + unstaged)
    untracked/…         copies of untracked files (size-capped)
    manifest.json       sha256 of every knowledge-source and changed file

`restore` takes a bundle (dir or .tar.gz), verifies the repo/commit/hashes,
and (with --apply) re-applies the uncommitted work and untracked files, then
prints the resume brief.

Stdlib + git only.

Usage:
    python3 handoff.py create [--kb PATH ...] [--out DIR] [--pack]
    python3 handoff.py restore --bundle PATH [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_UNTRACKED_BYTES = 5 * 1024 * 1024  # per-file cap for bundle copies
SKIP_DIRS = {".git", ".handoff", "node_modules", ".venv", "venv",
             "__pycache__", "dist", "build", "target"}


def git(*args: str, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, check=check)
        return r.stdout
    except FileNotFoundError:
        sys.exit("error: git not found on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: git {' '.join(args)} failed:\n{e.stderr}")


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").strip())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #

def collect_state(root: Path) -> dict:
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    head = git("rev-parse", "HEAD").strip()
    remote = git("remote", "get-url", "origin", check=False).strip() or None
    dirty, untracked = [], []
    for line in git("status", "--porcelain=1", "--untracked-files=all").splitlines():
        if not line.strip():
            continue
        status, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith(".handoff/") or path.startswith("handoff-"):
            continue
        (untracked if status.strip() == "??" else dirty).append(path)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": branch,
        "head": head,
        "remote": remote,
        "dirty_files": dirty,
        "untracked_files": untracked,
    }


def build_manifest(root: Path, state: dict, kb_paths: list[str]) -> dict:
    entries: dict[str, dict] = {}

    def add(rel: str, role: str) -> None:
        fp = root / rel
        if not fp.is_file():
            return
        entries[rel] = {"sha256": sha256(fp), "bytes": fp.stat().st_size, "role": role}

    for kb in kb_paths:
        p = root / kb
        if p.is_file():
            add(kb, "knowledge-source")
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part in SKIP_DIRS for part in f.parts):
                    add(str(f.relative_to(root)), "knowledge-source")
    for rel in state["dirty_files"] + state["untracked_files"]:
        if rel not in entries:
            add(rel, "work-in-progress")
    return entries


def cmd_create(args: argparse.Namespace) -> None:
    root = repo_root()
    out = root / args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "untracked").mkdir(parents=True)

    state = collect_state(root)
    manifest = build_manifest(root, state, args.kb or [])

    patch = git("diff", "HEAD", "--binary")
    (out / "uncommitted.patch").write_text(patch)

    skipped: list[str] = []
    for rel in state["untracked_files"]:
        src = root / rel
        if not src.is_file():
            continue
        if src.stat().st_size > MAX_UNTRACKED_BYTES:
            skipped.append(rel)
            continue
        dst = out / "untracked" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    state["untracked_skipped_too_large"] = skipped

    (out / "state.json").write_text(json.dumps(state, indent=2))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out / "HANDOFF.md").write_text(render_handoff_template(state, manifest, args.out))

    print(f"✅ Bundle written to {out.relative_to(root)}/")
    print(f"   {len(state['dirty_files'])} dirty file(s) captured in uncommitted.patch")
    print(f"   {len(state['untracked_files']) - len(skipped)} untracked file(s) copied"
          + (f" ({len(skipped)} skipped — too large: {', '.join(skipped)})" if skipped else ""))
    print(f"   {sum(1 for e in manifest.values() if e['role'] == 'knowledge-source')} "
          f"knowledge-source file(s) hashed")
    print()
    print("⚠️  NOW FILL THE SEMANTIC SECTIONS of HANDOFF.md (marked ✍️ TODO).")
    print("    The bundle is not a handoff until a stranger could resume from it.")

    if args.pack:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        tar_path = root / f"handoff-{stamp}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(out, arcname=".handoff")
        print(f"\n📦 Packed: {tar_path.name} — send this file to the next developer.")


def render_handoff_template(state: dict, manifest: dict, out_dir: str) -> str:
    kb = [(p, e) for p, e in manifest.items() if e["role"] == "knowledge-source"]
    wip = [(p, e) for p, e in manifest.items() if e["role"] == "work-in-progress"]
    lines = [
        "# 🤝 Session Handoff",
        "",
        f"_Created {state['created_at']} on branch `{state['branch']}` "
        f"at `{state['head'][:12]}`._",
        "",
        "## 🎯 Mission",
        "✍️ TODO(author): one paragraph — what is this work trying to achieve, "
        "and for whom?",
        "",
        "## 📍 Current step — where processing stopped",
        "✍️ TODO(author): the exact point reached. What was just finished, what "
        "was mid-flight? Be precise enough that the reader knows what NOT to redo.",
        "",
        "## 🧠 Decisions made & why",
        "✍️ TODO(author): every decision the next person must not re-litigate, "
        "with its rationale. Include rejected alternatives and WHY they were "
        "rejected — dead ends are the most expensive knowledge to lose.",
        "",
        "## 🔍 Key findings / facts established",
        "✍️ TODO(author): facts extracted from the documents/code that the next "
        "steps depend on. Cite the source file for each (see manifest below).",
        "",
        "## ⏭️ Next steps (in order)",
        "✍️ TODO(author): numbered, concrete, starting with the very next action.",
        "",
        "## ❓ Open questions & risks",
        "✍️ TODO(author): anything unresolved, plus who/what can resolve it.",
        "",
        "---",
        "",
        "## 📚 Knowledge sources (auto — verified by hash on restore)",
        "",
    ]
    if kb:
        lines.append("| File | SHA256 (12) | Size |")
        lines.append("| ---- | ----------- | ---- |")
        for p, e in kb:
            lines.append(f"| `{p}` | `{e['sha256'][:12]}` | {e['bytes']} B |")
    else:
        lines.append("_None registered — pass `--kb <path>` to hash your document set._")
    lines += ["", "## 🧰 Work in progress (auto)", ""]
    if state["dirty_files"]:
        lines.append("**Modified (in `uncommitted.patch`):** "
                     + ", ".join(f"`{f}`" for f in state["dirty_files"]))
    if state["untracked_files"]:
        lines.append("**Untracked (in `untracked/`):** "
                     + ", ".join(f"`{f}`" for f in state["untracked_files"]))
    if not wip and not state["dirty_files"] and not state["untracked_files"]:
        lines.append("_Working tree was clean._")
    lines += [
        "",
        "---",
        "",
        "## 🔄 How to resume (auto)",
        "",
        "```bash",
        f"git fetch origin {state['branch']}",
        f"git checkout {state['branch']} && git reset --hard {state['head'][:12]}",
        f"python3 skills/session-handoff/scripts/handoff.py restore --bundle {out_dir}",
        f"python3 skills/session-handoff/scripts/handoff.py restore --bundle {out_dir} --apply",
        "```",
        "",
        "### Resume prompt (paste into the new Claude session)",
        "",
        "```",
        "You are resuming another developer's session from a handoff bundle.",
        f"Read {out_dir}/HANDOFF.md in full before doing anything else. Verify the",
        f"bundle with: python3 skills/session-handoff/scripts/handoff.py restore --bundle {out_dir}",
        "Treat 'Decisions made' as settled unless evidence contradicts them, do",
        "not redo anything listed as finished in 'Current step', and start with",
        "step 1 of 'Next steps'. Ask about 'Open questions' before assuming.",
        "```",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# restore
# --------------------------------------------------------------------------- #

def load_bundle(path: Path, root: Path) -> Path:
    if path.is_dir():
        return path
    if path.is_file() and (path.name.endswith(".tar.gz") or path.name.endswith(".tgz")):
        # Materialize into the repo so HANDOFF.md survives the restore run;
        # fall back to a temp dir if .handoff/ is already occupied.
        target = root / ".handoff"
        if target.exists():
            target = Path(tempfile.mkdtemp(prefix="handoff-"))
        with tarfile.open(path) as tf:
            tf.extractall(target.parent if target.name == ".handoff" else target,
                          filter="data")
        inner = target if target.name == ".handoff" else target / ".handoff"
        return inner if inner.is_dir() else target
    sys.exit(f"error: bundle not found or unsupported: {path}")


def cmd_restore(args: argparse.Namespace) -> None:
    root = repo_root()
    bundle = load_bundle(Path(args.bundle), root)
    state = json.loads((bundle / "state.json").read_text())
    manifest = json.loads((bundle / "manifest.json").read_text())
    problems: list[str] = []

    head = git("rev-parse", "HEAD").strip()
    if head != state["head"]:
        known = git("cat-file", "-t", state["head"], check=False).strip() == "commit"
        problems.append(
            f"HEAD mismatch: bundle was made at {state['head'][:12]}, you are at "
            f"{head[:12]}." + ("" if known else f" Commit {state['head'][:12]} is not "
            f"in this clone — fetch branch `{state['branch']}` first."))

    drift = []
    for rel, e in manifest.items():
        fp = root / rel
        if e["role"] == "knowledge-source":
            if not fp.is_file():
                drift.append(f"missing: {rel}")
            elif sha256(fp) != e["sha256"]:
                drift.append(f"content drift: {rel}")
    if drift:
        problems.append("Knowledge sources differ from the original session:\n    "
                        + "\n    ".join(drift))

    print(f"🤝 Handoff bundle from {state['created_at']} "
          f"(branch `{state['branch']}`, HEAD {state['head'][:12]})")
    if problems:
        print("\n⚠️  Verification problems:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("✅ Repo state and knowledge-source hashes verified.")

    patch = (bundle / "uncommitted.patch")
    has_patch = patch.is_file() and patch.read_text().strip()
    untracked_dir = bundle / "untracked"
    untracked = [p for p in untracked_dir.rglob("*") if p.is_file()] if untracked_dir.is_dir() else []

    if not args.apply:
        print(f"\nDry run. Bundle contains: patch={'yes' if has_patch else 'no'}, "
              f"{len(untracked)} untracked file(s).")
        print(f"Re-run with --apply to restore them. Then read "
              f"{bundle / 'HANDOFF.md'} in full.")
        return

    if problems and not args.force:
        sys.exit("\nRefusing to --apply with verification problems (use --force to override).")

    if has_patch:
        check = subprocess.run(["git", "apply", "--check", str(patch)],
                               capture_output=True, text=True)
        if check.returncode != 0:
            sys.exit(f"error: patch does not apply cleanly:\n{check.stderr}"
                     "Reset to the bundle HEAD first (see HANDOFF.md).")
        git("apply", str(patch))
        print("✅ uncommitted.patch applied.")
    for f in untracked:
        rel = f.relative_to(untracked_dir)
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    if untracked:
        print(f"✅ {len(untracked)} untracked file(s) restored.")
    print(f"\n📖 Now read {bundle / 'HANDOFF.md'} — the semantic state is there.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export/restore a session handoff bundle.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Capture the current session state.")
    c.add_argument("--kb", action="append", metavar="PATH",
                   help="Knowledge-source file/dir to hash (repeatable).")
    c.add_argument("--out", default=".handoff", help="Bundle directory (default .handoff).")
    c.add_argument("--pack", action="store_true", help="Also pack into handoff-<ts>.tar.gz.")
    c.set_defaults(func=cmd_create)

    r = sub.add_parser("restore", help="Verify (and optionally apply) a bundle.")
    r.add_argument("--bundle", required=True, help="Bundle dir or .tar.gz.")
    r.add_argument("--apply", action="store_true", help="Apply patch + untracked files.")
    r.add_argument("--force", action="store_true", help="Apply despite verification problems.")
    r.set_defaults(func=cmd_restore)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
