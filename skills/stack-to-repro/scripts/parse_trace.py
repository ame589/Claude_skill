#!/usr/bin/env python3
"""
parse_trace.py — Turn a stack trace into a pinpointed, in-repo reproduction target.

Paste a production/CI stack trace (Python, JS/TS/Node, Java/Kotlin, Ruby, Go,
PHP) and this tool:
  1. Detects the language and parses every frame.
  2. Keeps only frames that resolve to files inside THIS repo.
  3. Picks the culprit frame — the deepest application frame before the error.
  4. Extracts the enclosing function/method source around that line.
  5. Emits a repro brief: exception, culprit `file:line`, the function body, a
     suggested test-file path, and a language-appropriate failing-test skeleton.

The point is to collapse "here's a crash" into "here's a red test that
reproduces it" so the fix can be written and verified immediately.

Dependency-free (stdlib + git). Reads the trace from a file, stdin, or --text.

Usage:
    python3 parse_trace.py trace.txt
    pbpaste | python3 parse_trace.py -
    python3 parse_trace.py --text "Traceback ..." --json brief.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# Frame parsers — each yields (raw_path, line, func, lang)
# --------------------------------------------------------------------------- #

FRAME_PATTERNS = [
    # Python: File "path/to/x.py", line 42, in func_name
    ("python", re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')),
    # Node/JS/TS: at func (path:line:col)  OR  at path:line:col
    ("js", re.compile(r'at (?:(?P<func>[^\s(]+) \()?(?P<path>[^\s():]+):(?P<line>\d+):\d+\)?')),
    # Java/Kotlin: at pkg.Class.method(File.java:123)
    ("java", re.compile(r'at (?P<func>[\w.$<>]+)\((?P<path>[\w./$-]+\.(?:java|kt)):(?P<line>\d+)\)')),
    # Ruby: path:line:in `method'
    ("ruby", re.compile(r"(?P<path>[^\s:]+):(?P<line>\d+):in [`'](?P<func>[^']+)'")),
    # Go: \tpath:line +0x..   (function is on the preceding line, handled below)
    ("go", re.compile(r'^\s+(?P<path>[^\s:]+\.go):(?P<line>\d+)(?: \+0x[0-9a-f]+)?')),
    # PHP: #N path(line): Class->method()
    ("php", re.compile(r'#\d+ (?P<path>[^\s(]+)\((?P<line>\d+)\): (?P<func>[\w\\>:-]+)')),
    # Generic fallback: path:line  (only used if nothing else matched a file in-repo)
    ("generic", re.compile(r'(?P<path>[\w./\\-]+\.(?:py|js|jsx|ts|tsx|rb|go|php|java|kt|rs|c|cpp|cs)):(?P<line>\d+)')),
]

EXCEPTION_PATTERNS = [
    re.compile(r'^(?P<type>[A-Z][\w.]*(?:Error|Exception|Warning))\b:?\s*(?P<msg>.*)$'),
    re.compile(r'^(?P<type>[\w.]+(?:Error|Exception))\b:?\s*(?P<msg>.*)$'),
    re.compile(r'panic:\s*(?P<msg>.*)$'),         # Go
    re.compile(r'Uncaught (?P<type>\w+):\s*(?P<msg>.*)$'),  # JS
]


@dataclass
class Frame:
    path: str          # repo-relative if resolved, else raw
    line: int
    func: str
    lang: str
    in_repo: bool


def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except Exception:
        return Path.cwd()


def resolve_in_repo(raw: str, root: Path) -> str | None:
    """Return repo-relative path if `raw` maps to a tracked/existing file."""
    raw = raw.strip()
    # Absolute path inside repo?
    try:
        p = Path(raw)
        if p.is_absolute() and p.exists():
            rel = os.path.relpath(p, root)
            if not rel.startswith(".."):
                return rel
    except OSError:
        pass
    # Relative to root?
    cand = root / raw
    if cand.exists():
        return raw.lstrip("./")
    # Basename search (traces often carry partial paths). Match unique basename.
    base = os.path.basename(raw)
    if base and "." in base:
        matches = [p for p in root.rglob(base)
                   if ".git" not in p.parts and "node_modules" not in p.parts]
        if len(matches) == 1:
            return os.path.relpath(matches[0], root)
    return None


def parse_exception(text: str) -> tuple[str, str]:
    # The exception is usually the last non-empty, non-frame line.
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines):
        for pat in EXCEPTION_PATTERNS:
            m = pat.search(line.strip())
            if m:
                gd = m.groupdict()
                return gd.get("type", "Error") or "Error", (gd.get("msg") or "").strip()
    return "UnknownError", lines[-1] if lines else ""


def parse_frames(text: str, root: Path) -> list[Frame]:
    frames: list[Frame] = []
    seen: set[tuple[str, int]] = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for lang, pat in FRAME_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            gd = m.groupdict()
            raw = gd["path"]
            ln = int(gd["line"])
            func = gd.get("func") or ""
            # Go: function name sits on the previous line.
            if lang == "go" and not func and i > 0:
                prev = lines[i - 1].strip()
                func = re.sub(r"\(.*", "", prev).split("/")[-1]
            rel = resolve_in_repo(raw, root)
            key = (rel or raw, ln)
            if key in seen:
                continue
            seen.add(key)
            frames.append(Frame(rel or raw, ln, func, lang, rel is not None))
            break  # one pattern per line
    return frames


def pick_culprit(frames: list[Frame]) -> Frame | None:
    """Deepest application frame: for most languages the top of the trace is the
    innermost call. Python lists outermost-first, so the LAST in-repo frame is
    innermost; JS/Java/Ruby/Go list innermost-first, so the FIRST in-repo frame."""
    in_repo = [f for f in frames if f.in_repo]
    if not in_repo:
        return frames[0] if frames else None
    langs = {f.lang for f in in_repo}
    if "python" in langs:
        return in_repo[-1]
    return in_repo[0]


def extract_function(root: Path, rel: str, line: int) -> tuple[str, str]:
    """Return (function_name, source_snippet) enclosing `line` (1-indexed)."""
    fp = root / rel
    try:
        src = fp.read_text(errors="ignore").splitlines()
    except OSError:
        return "", ""
    idx = min(max(line - 1, 0), len(src) - 1)
    ext = fp.suffix.lower()
    defkw = {
        ".py": ("def ", "class "),
        ".rb": ("def ", "class ", "module "),
        ".go": ("func ",),
        ".rs": ("fn ", "pub fn "),
    }.get(ext, ("function", "def ", "func ", "fn ", "public ", "private ", "static "))
    # Walk upward to the enclosing declaration.
    start = idx
    name = ""
    for j in range(idx, max(idx - 200, -1), -1):
        stripped = src[j].lstrip()
        if any(stripped.startswith(k) for k in defkw) or re.match(r'.*\b\w+\s*\([^)]*\)\s*\{?\s*$', src[j]) and j < idx:
            start = j
            m = re.search(r'(?:def|func|fn|function|class)\s+([A-Za-z_]\w*)', src[j])
            name = m.group(1) if m else ""
            break
    # Walk downward: brace balance for C-like, indentation for Python/Ruby.
    end = idx
    if ext in (".py", ".rb"):
        base_indent = len(src[start]) - len(src[start].lstrip())
        for j in range(start + 1, len(src)):
            if src[j].strip() and (len(src[j]) - len(src[j].lstrip())) <= base_indent:
                end = j
                break
            end = j
    else:
        depth = 0
        started = False
        for j in range(start, min(start + 200, len(src))):
            depth += src[j].count("{") - src[j].count("}")
            if "{" in src[j]:
                started = True
            if started and depth <= 0:
                end = j
                break
            end = j
    snippet = "\n".join(f"{k+1:>5}| {src[k]}" for k in range(start, min(end + 1, len(src))))
    return name, snippet


# --------------------------------------------------------------------------- #
# Test skeletons
# --------------------------------------------------------------------------- #

def suggest_test_path(rel: str) -> str:
    p = Path(rel)
    ext = p.suffix
    stem = p.stem
    if ext == ".py":
        return str(p.parent / f"test_{stem}.py")
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        return str(p.with_suffix("")) + f".test{ext}"
    if ext == ".go":
        return str(p.with_name(f"{stem}_test.go"))
    if ext == ".rb":
        return str(Path("spec") / f"{stem}_spec.rb")
    if ext in (".java", ".kt"):
        return str(p.with_name(f"{stem}Test{ext}"))
    return f"test_{stem}{ext}"


def test_skeleton(rel: str, func: str, exc_type: str, exc_msg: str) -> str:
    ext = Path(rel).suffix
    fn = func or "the_failing_function"
    if ext == ".py":
        return (
            f"# Reproduces {exc_type}: {exc_msg}\n"
            f"import pytest\n\n"
            f"def test_repro_{fn}():\n"
            f"    # Arrange: the exact inputs from the failing call site.\n"
            f"    # Act + Assert: this MUST fail with {exc_type} before the fix.\n"
            f"    with pytest.raises({exc_type}):\n"
            f"        {fn}(...)  # TODO fill args that trigger the crash\n"
        )
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        return (
            f"// Reproduces {exc_type}: {exc_msg}\n"
            f"test('repro {fn} throws {exc_type}', () => {{\n"
            f"  // This MUST throw before the fix.\n"
            f"  expect(() => {fn}(/* args that trigger the crash */)).toThrow();\n"
            f"}});\n"
        )
    if ext == ".go":
        return (
            f"// Reproduces panic/{exc_type}: {exc_msg}\n"
            f"func TestRepro_{fn}(t *testing.T) {{\n"
            f"    // This MUST fail before the fix.\n"
            f"    // {fn}(/* inputs that trigger the crash */)\n"
            f"}}\n"
        )
    if ext == ".rb":
        return (
            f"# Reproduces {exc_type}: {exc_msg}\n"
            f"RSpec.describe '{fn}' do\n"
            f"  it 'raises {exc_type}' do\n"
            f"    expect {{ {fn}(nil) }}.to raise_error({exc_type})\n"
            f"  end\nend\n"
        )
    return f"// Write a test calling {fn} with the crashing inputs; assert it raises {exc_type}."


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def build_brief(text: str) -> dict:
    root = repo_root()
    exc_type, exc_msg = parse_exception(text)
    frames = parse_frames(text, root)
    culprit = pick_culprit(frames)
    brief = {
        "exception": {"type": exc_type, "message": exc_msg},
        "frames": [asdict(f) for f in frames],
        "in_repo_frames": sum(1 for f in frames if f.in_repo),
        "culprit": None,
        "function": None,
        "function_source": None,
        "suggested_test_path": None,
        "test_skeleton": None,
    }
    if culprit and culprit.in_repo:
        name, snippet = extract_function(root, culprit.path, culprit.line)
        func = name or culprit.func
        brief["culprit"] = asdict(culprit)
        brief["function"] = func
        brief["function_source"] = snippet
        brief["suggested_test_path"] = suggest_test_path(culprit.path)
        brief["test_skeleton"] = test_skeleton(culprit.path, func, exc_type, exc_msg)
    elif culprit:
        brief["culprit"] = asdict(culprit)
    return brief


def render_md(b: dict) -> str:
    e = b["exception"]
    out = ["# 🎯 Stack-to-Repro Brief", ""]
    out.append(f"**Exception:** `{e['type']}` — {e['message']}")
    out.append(f"**In-repo frames:** {b['in_repo_frames']} of {len(b['frames'])}")
    out.append("")
    if not b["culprit"]:
        out.append("> No frames could be parsed from the trace. Paste the raw trace, "
                   "including the `File ...`/`at ...` lines.")
        return "\n".join(out)
    c = b["culprit"]
    if not c.get("in_repo"):
        out.append(f"> ⚠️ Deepest frame `{c['path']}:{c['line']}` is outside this repo "
                   f"(likely a library). The bug may be in how you call it — check the "
                   f"nearest in-repo frame in the list below.")
        out.append("")
        out.append("## Frames")
        for f in b["frames"]:
            mark = "🏠" if f["in_repo"] else "  "
            out.append(f"- {mark} `{f['path']}:{f['line']}` in `{f['func']}`")
        return "\n".join(out)
    out.append(f"## 🔴 Culprit: `{c['path']}:{c['line']}`  (in `{b['function']}`)")
    out.append("")
    if b["function_source"]:
        out.append("```")
        out.append(b["function_source"])
        out.append("```")
    out.append("")
    out.append(f"## 🧪 Reproduce it — suggested test: `{b['suggested_test_path']}`")
    out.append("```")
    out.append(b["test_skeleton"] or "")
    out.append("```")
    out.append("")
    out.append("## Full frame list")
    for f in b["frames"]:
        mark = "🏠" if f["in_repo"] else "  "
        out.append(f"- {mark} `{f['path']}:{f['line']}` in `{f['func']}`")
    out.append("")
    out.append("---")
    out.append("_Generated by the `stack-to-repro` skill. Fill the test inputs from the "
               "real failing call, confirm it goes red, then fix and confirm green._")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn a stack trace into a repro target.")
    ap.add_argument("source", nargs="?", default="-",
                    help="Trace file, or '-' for stdin (default).")
    ap.add_argument("--text", help="Pass the trace inline instead of a file.")
    ap.add_argument("--json", metavar="PATH", help="Write JSON brief to PATH.")
    ap.add_argument("--md", metavar="PATH", help="Write Markdown brief to PATH.")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    if args.text is not None:
        text = args.text
    elif args.source == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.source).read_text(errors="ignore")

    if not text.strip():
        sys.exit("error: no trace provided (pass a file, --text, or pipe via stdin).")

    brief = build_brief(text)
    md = render_md(brief)
    js = json.dumps(brief, indent=2)
    if args.json:
        Path(args.json).write_text(js)
    if args.md:
        Path(args.md).write_text(md)
    print(js if args.format == "json" else md)


if __name__ == "__main__":
    main()
