"""Terminal rendering. ANSI only, no dependency."""

from __future__ import annotations

import os
import shutil
import textwrap

from .pipeline import Analysis
from .schema import DriftReport

_NO_COLOR = bool(os.environ.get("NO_COLOR"))


def _c(code: str, s: str) -> str:
    return s if _NO_COLOR else f"\033[{code}m{s}\033[0m"


DIM = lambda s: _c("2", s)  # noqa: E731
BOLD = lambda s: _c("1", s)  # noqa: E731

MARK = {
    "met": ("✓", "32"),
    "partial": ("◐", "33"),
    "unaddressed": ("✗", "31"),
}
RISK = {"high": "31", "medium": "33", "low": "2"}


def _width() -> int:
    return min(shutil.get_terminal_size((100, 24)).columns, 100)


def _wrap(text: str, indent: str, limit: int = 400) -> str:
    """Collapse whitespace and wrap. Long evidence gets clipped rather than flooding the report."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        flat = flat[:limit].rsplit(" ", 1)[0] + " …"
    return textwrap.fill(flat, width=_width(), initial_indent=indent, subsequent_indent=indent)


def _rule(label: str = "") -> str:
    w = _width()
    if not label:
        return DIM("─" * w)
    return DIM("── ") + BOLD(label) + DIM(" " + "─" * max(0, w - len(label) - 4))


def render(a: Analysis, show_low: bool = False) -> str:
    out: list[str] = ["", _rule("DriftCheck")]
    out.append(f"  PR #{a.pr_number}  {BOLD(a.pr_title)}")
    out.append(f"  closes #{a.issue_number}  {DIM(a.issue_title)}")
    out.append("")

    r: DriftReport | None = a.report
    if r is None:
        out.append("  (no report produced)")
        return "\n".join(out)

    by_id = {c.id: c for c in a.plan.criteria}
    tally = {"met": 0, "partial": 0, "unaddressed": 0}

    out.append(_rule("acceptance criteria"))
    for v in r.verdicts:
        glyph, colour = MARK.get(v.verdict, ("?", "0"))
        tally[v.verdict] = tally.get(v.verdict, 0) + 1
        crit = by_id.get(v.criterion_id)
        head = crit.text if crit else v.criterion_id
        src = DIM(f"[{crit.source}]") if crit else ""
        label = f"{v.verdict.upper():<12}"
        out.append(f"  {_c(colour, glyph)} {_c(colour, label)} {head} {src}")
        out.append(DIM(_wrap(v.evidence, "      → ")))
        if v.note:
            out.append(DIM(_wrap(v.note, "        ")))
        out.append("")

    out.append(_rule("silent changes"))
    shown = r.silent_changes if show_low else [s for s in r.silent_changes if s.risk != "low"]
    hidden = len(r.silent_changes) - len(shown)
    if not r.silent_changes:
        out.append(DIM("  none found — the diff stayed inside what the issue asked for"))
    elif not shown:
        out.append(DIM(f"  nothing above low risk ({hidden} low-risk, --all to show)"))
    for s in shown:
        colour = RISK.get(s.risk, "0")
        risk = f"{s.risk.upper():<7}"
        out.append(f"  {_c(colour, chr(9679))} {_c(colour, risk)} {BOLD(s.path)}")
        out.append(_wrap(s.description, "      "))
        out.append(DIM(_wrap(s.evidence, "      → ")))
    if shown and hidden:
        out.append(DIM(f"  {hidden} low-risk change(s) hidden — --all to show"))
    out.append("")

    out.append(_rule())
    counts = "  ".join(
        _c(MARK[k][1], f"{tally.get(k, 0)} {k}") for k in ("met", "partial", "unaddressed")
    )
    out.append(f"  {counts}   {DIM(f'{len(shown)} silent change(s)')}")
    out.append(_wrap(r.bottom_line, "  "))
    if a.failed_files:
        out.append(_c("31", _wrap("reviewer failed on: " + ", ".join(a.failed_files), "  ")))
    if a.skipped_files:
        out.append(DIM(_wrap("not reviewed (file cap): " + ", ".join(a.skipped_files), "  ")))
    out.append("")
    return "\n".join(out)
