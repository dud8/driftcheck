"""Repository access: gh CLI, file reads, ripgrep — as plain functions and as Strands tools.

The plain functions are pure enough to test; the ``@tool`` wrappers are what the agents see.
Repo coordinates live in one module-level ``Context`` so the tools keep a flat signature the
model can fill in without being told the repo every call.
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from strands import tool

MAX_TOOL_CHARS = 24_000


@dataclass
class Context:
    """Where DriftCheck is looking."""

    repo: str = ""
    """owner/name, passed to gh."""
    worktree: Path | None = None
    """Local clone, used for file reads and ripgrep. Optional."""


CTX = Context()


def configure(repo: str, worktree: str | Path | None = None) -> None:
    """Point the tools at a repository. Clears the gh response cache."""
    CTX.repo = repo
    CTX.worktree = Path(worktree).resolve() if worktree else None
    _gh.cache_clear()


def _clip(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more characters]"


@functools.lru_cache(maxsize=64)
def _gh(*args: str) -> str:
    """Run gh and return stdout. Cached: the same PR is fetched by several agents."""
    if not shutil.which("gh"):
        raise RuntimeError("gh CLI not found on PATH — install it and run `gh auth login`")
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=120  # noqa: S603,S607
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def fetch_issue(number: int) -> str:
    """Title and body of an issue, as markdown."""
    out = _gh(
        "issue", "view", str(number), "--repo", CTX.repo, "--json", "number,title,body,labels"
    )
    import json

    d = json.loads(out)
    labels = ", ".join(lbl["name"] for lbl in d.get("labels", []))
    return f"# Issue #{d['number']}: {d['title']}\nlabels: {labels or 'none'}\n\n{d['body'] or '(empty body)'}"


def fetch_pr(number: int) -> dict:
    """PR metadata including the list of changed files."""
    import json

    out = _gh(
        "pr", "view", str(number), "--repo", CTX.repo,
        "--json", "number,title,body,files,additions,deletions,mergedAt",
    )
    return json.loads(out)


def fetch_diff(number: int) -> str:
    """The full unified diff of a PR."""
    return _gh("pr", "diff", str(number), "--repo", CTX.repo)


_DIFF_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)


def split_diff(diff: str) -> dict[str, str]:
    """Split a unified diff into ``path -> hunk text``.

    The b-side path wins, so renames and additions key on where the file ended up.
    A diff with no ``diff --git`` headers yields an empty mapping rather than raising.
    """
    marks = list(_DIFF_HEADER.finditer(diff))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(diff)
        path = m.group(2)
        # /dev/null on the b-side means a deletion; key it on the a-side instead.
        if path == "dev/null":
            path = m.group(1)
        out[path] = diff[m.start() : end]
    return out


def issue_refs(text: str) -> list[int]:
    """Issue numbers a PR body claims to close, in order of appearance.

    Matches GitHub's own closing keywords. ``#12`` on its own is a mention, not a claim,
    so it is deliberately ignored.
    """
    pat = re.compile(
        r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[:\s]+#(\d+)", re.IGNORECASE
    )
    seen: list[int] = []
    for n in (int(m.group(1)) for m in pat.finditer(text or "")):
        if n not in seen:
            seen.append(n)
    return seen


# --------------------------------------------------------------------------- tools


@tool
def read_issue(number: int) -> str:
    """Read a GitHub issue's title, labels and body.

    Args:
        number: The issue number, without the leading '#'.
    """
    return _clip(fetch_issue(number))


@tool
def read_pull_request(number: int) -> str:
    """Read a pull request's title, body and the list of files it changed.

    Args:
        number: The pull request number, without the leading '#'.
    """
    pr = fetch_pr(number)
    files = "\n".join(
        f"  {f['path']} (+{f['additions']}/-{f['deletions']})" for f in pr.get("files", [])
    )
    return _clip(
        f"# PR #{pr['number']}: {pr['title']}\n"
        f"merged: {pr.get('mergedAt')}  +{pr['additions']}/-{pr['deletions']}\n\n"
        f"{pr['body'] or '(empty body)'}\n\nChanged files:\n{files}"
    )


@tool
def read_diff(number: int, path: str = "") -> str:
    """Read the diff of a pull request, optionally narrowed to one file.

    Args:
        number: The pull request number.
        path: Repository-relative path. Leave empty for the whole diff.
    """
    diff = fetch_diff(number)
    if not path:
        return _clip(diff)
    per_file = split_diff(diff)
    if path in per_file:
        return _clip(per_file[path])
    hit = next((k for k in per_file if k.endswith(path)), None)
    if hit:
        return _clip(per_file[hit])
    return f"No diff for {path!r}. Files in this PR: {', '.join(sorted(per_file))}"


@tool
def read_source(path: str, start: int = 1, end: int = 400) -> str:
    """Read lines from a file in the local checkout, to see code the diff did not show.

    Args:
        path: Repository-relative path.
        start: First line, 1-indexed.
        end: Last line, inclusive.
    """
    if CTX.worktree is None:
        return "No local checkout configured; work from the diff alone."
    target = (CTX.worktree / path).resolve()
    if CTX.worktree not in target.parents and target != CTX.worktree:
        return "Refused: path escapes the checkout."
    if not target.is_file():
        return f"No such file: {path}"
    lines = target.read_text(errors="replace").splitlines()
    lo, hi = max(1, start), min(len(lines), max(start, end))
    body = "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(lo, hi + 1))
    return _clip(f"{path} lines {lo}-{hi} of {len(lines)}\n{body}")


@tool
def find_callers(symbol: str, glob: str = "") -> str:
    """Search the local checkout for uses of a symbol, to see who a changed function affects.

    Args:
        symbol: Function, class or constant name.
        glob: Optional ripgrep glob such as '*.py' to narrow the search.
    """
    if CTX.worktree is None:
        return "No local checkout configured; work from the diff alone."
    if not shutil.which("rg"):
        return "ripgrep not installed."
    cmd = ["rg", "--line-number", "--no-heading", "--max-count", "4", "-w", symbol]
    if glob:
        cmd += ["--glob", glob]
    proc = subprocess.run(  # noqa: S603
        cmd, cwd=CTX.worktree, capture_output=True, text=True, timeout=60
    )
    if not proc.stdout.strip():
        return f"No uses of {symbol!r} found."
    return _clip("\n".join(proc.stdout.splitlines()[:60]), 6000)
