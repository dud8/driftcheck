"""The three-stage pipeline: plan, review, synthesize.

Stage boundaries are the point. The planner never sees the diff, so the acceptance criteria
cannot be bent into whatever the PR happened to do. Each reviewer sees exactly one file, so a
large diff cannot bury a small behavioural change. The synthesizer sees the criteria and every
file review, and is the only stage allowed to call a verdict.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from strands import Agent

from . import tools
from .model import build_model
from .schema import DriftReport, Finding, FileReview, Plan

logger = logging.getLogger(__name__)

MAX_FILE_DIFF_CHARS = 18_000

PLANNER_PROMPT = """You are a requirements analyst on a code review team.

You are given one GitHub issue. Read it and write down the acceptance criteria a pull request
must satisfy to close it. You have NOT seen the pull request and you must not speculate about it.

Rules:
- Prefer the issue's own words. A criterion is one testable statement, not a paragraph.
- Mark a criterion 'explicit' only when the issue states it outright. If the issue reports a bug
  without stating a fix, the criterion that the bug no longer reproduces is 'implied'.
- Include criteria the issue takes for granted, such as not regressing the behaviour it describes
  as currently working. Do not invent generic engineering wishes: no criterion about test
  coverage, documentation or style unless the issue asks for it.
- 3 to 8 criteria. Fewer is better than padded.
- in_scope_paths: only paths or directories the issue actually names or unmistakably implies.
  An empty list is the correct answer when the issue names none.

Use the read_issue tool once to get the issue, then answer."""

REVIEWER_PROMPT = """You are reviewing ONE file from a merged pull request.

You are given the acceptance criteria for the issue the PR claims to close, and the diff for your
file only. Other files are being reviewed by your colleagues; do not guess at them.

Two jobs:

1. For each criterion this file speaks to, decide met / partial / unaddressed, and quote the hunk,
   function name or line that settles it. Skip criteria this file has nothing to do with — an
   empty findings list is a valid answer for a file that only touches unrelated code.
   'met' requires code in THIS diff that does the thing. A comment, a docstring or a test name
   that mentions it is not the thing.

2. Report out-of-scope changes: behaviour this diff changes that no criterion asked for.
   That means altered defaults, changed return values or types, new or removed error handling,
   renamed or deleted public symbols, changed thresholds and constants, and tightened or
   loosened validation.

   Scope is decided by the issue, not by intent. You are told which paths the issue named. If
   your file is NOT among them, every behaviour change in it is out of scope — including a
   change that plainly serves the issue's goal, matches the fix applied elsewhere in the PR, or
   looks like an improvement. "It is the same fix, applied somewhere the issue did not ask for"
   is the single most valuable thing you can report, not a reason to stay silent. Say what it
   does and let the risk rating carry your opinion of it.

   NOT out of scope, and never worth reporting: formatting, import ordering, comments, new
   includes, test additions that exercise the criteria, and a change in a file the issue DID
   name that a criterion already covers. A NEW helper, declaration or symbol is not a
   behaviour change on its own — report the call site where it replaced the old behaviour,
   not the helper it calls. Something must behave differently than it did before, or there is
   nothing to report.
   Risk is about the blast radius on callers, not the size of the hunk.
   Keep evidence to one short line: a file and line range, a symbol, or a single changed
   statement. Never paste a hunk.

Tools: read_source shows code the diff did not include, find_callers shows who uses a symbol you
are about to call changed. Use them when a hunk's effect on the rest of the repo is unclear;
one or two calls, not a survey.

Be concrete or say nothing. An empty out_of_scope_changes list is a good answer for a tight diff."""

SYNTH_PROMPT = """You are the reviewer who signs off.

You are given the acceptance criteria for an issue and one review per changed file. Produce the
final report.

Rules:
- verdicts must contain exactly one entry per criterion, in the criteria's own order, using the
  criterion ids you were given. If no file review addressed a criterion, its verdict is
  'unaddressed' and the evidence says which file you would have expected it in.
- When two file reviews disagree about a criterion, the one holding concrete diff evidence wins.
  Downgrade to 'partial' when a criterion is met in one place and left broken in another.
- silent_changes: merge duplicates, and drop every entry that is not a change in behaviour —
  anything a criterion already covers, pure formatting, new includes, and any entry whose only
  content is that a helper, declaration or symbol was added. A new function is machinery for a
  change reported elsewhere; report the call site, not the helper. What remains must be a place
  where something behaves differently than it did before. Order by risk, highest first, and keep
  the file review's evidence line as it stands.
- bottom_line: one sentence a reviewer can act on. Name the single worst problem if there is one,
  or say the PR does what the issue asked if it does.

You may call review_file to take a second look at one file when the reviews conflict on it and
the disagreement changes a verdict. Otherwise answer directly."""


@dataclass
class Analysis:
    """Everything one run produced, for rendering and for tests."""

    pr_number: int
    issue_number: int
    pr_title: str
    issue_title: str
    plan: Plan
    file_reviews: list[FileReview] = field(default_factory=list)
    report: DriftReport | None = None
    skipped_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)


def _pick_files(diff_by_path: dict[str, str], max_files: int) -> tuple[list[str], list[str]]:
    """Largest diffs first, capped. Returns (reviewed, skipped)."""
    ordered = sorted(diff_by_path, key=lambda p: len(diff_by_path[p]), reverse=True)
    return ordered[:max_files], ordered[max_files:]


def reconcile(plan: Plan, report: DriftReport | None) -> DriftReport | None:
    """Force the report to carry exactly one verdict per criterion, in the plan's order.

    Small models drop criteria and invent ids. Neither is acceptable in a report whose whole
    claim is per-criterion coverage, so the gaps are filled here as 'unaddressed' and the
    inventions are dropped rather than shown to a reviewer as if they were real.
    """
    if report is None:
        return None
    by_id = {v.criterion_id: v for v in report.verdicts}
    report.verdicts = [
        by_id.get(
            c.id,
            Finding(
                criterion_id=c.id,
                verdict="unaddressed",
                evidence="No file review spoke to this criterion.",
                note="Nothing in the reviewed diff addresses it.",
            ),
        )
        for c in plan.criteria
    ]
    report.silent_changes.sort(key=lambda s: {"high": 0, "medium": 1, "low": 2}.get(s.risk, 3))
    return report


def _issue_title(number: int) -> str:
    return tools.fetch_issue(number).splitlines()[0].split(": ", 1)[-1]


def _criteria_block(plan: Plan) -> str:
    return "\n".join(f"- {c.id} ({c.source}): {c.text}" for c in plan.criteria)


def make_planner() -> Agent:
    return Agent(
        name="planner",
        description="Extracts acceptance criteria from a GitHub issue",
        model=build_model(temperature=0.0),
        system_prompt=PLANNER_PROMPT,
        tools=[tools.read_issue],
        callback_handler=None,
    )


def make_reviewer(with_tools: bool = True) -> Agent:
    """One reviewer. ``with_tools=False`` is the retry: no tool calls to get lost in."""
    return Agent(
        name="review_file",
        description=(
            "Reviews one changed file against the acceptance criteria and reports out-of-scope "
            "behaviour changes. Input: the criteria, the file path, and that file's diff."
        ),
        model=build_model(temperature=0.0),
        system_prompt=REVIEWER_PROMPT,
        tools=[tools.read_source, tools.find_callers] if with_tools else [],
        callback_handler=None,
    )


def make_synthesizer(reviewer: Agent) -> Agent:
    return Agent(
        name="synthesizer",
        description="Turns per-file reviews into a per-criterion verdict and a silent-changes list",
        model=build_model(temperature=0.0, max_tokens=6144),
        system_prompt=SYNTH_PROMPT,
        # Agents-as-tools: the synthesizer can send a file back to a reviewer sub-agent.
        tools=[reviewer.as_tool()],
        callback_handler=None,
    )


async def _review_one(
    path: str, diff: str, plan: Plan, sem: asyncio.Semaphore
) -> tuple[FileReview, str | None]:
    named = plan.in_scope_paths
    if not named:
        scope = (
            "The issue named no paths at all. Judge scope by the criteria alone: a behaviour "
            "change no criterion asked for is out of scope."
        )
    elif any(n in path or path.endswith(n) for n in named):
        scope = f"The issue names this file's area. Paths the issue named: {', '.join(named)}"
    else:
        scope = (
            f"The issue does NOT name this file. Paths and components the issue named: "
            f"{', '.join(named)}. A change here that a criterion above explicitly asks for is "
            f"that criterion's work — this file may simply be where it lives. Anything else "
            f"{path} changes is out of scope, however sensible it looks."
        )
    prompt = (
        f"Acceptance criteria for the issue:\n{_criteria_block(plan)}\n\n"
        f"Scope: {scope}\n\n"
        f"File under review: {path}\n\nDiff for this file only:\n```diff\n"
        f"{diff[:MAX_FILE_DIFF_CHARS]}\n```"
    )
    # A local model occasionally fails to emit the structured-output call. That is a bad roll,
    # not a bad file, so retry once with the tools removed before giving up on the file.
    for attempt in (0, 1):
        async with sem:
            agent = make_reviewer(with_tools=attempt == 0)
            try:
                result = await agent.invoke_async(prompt, structured_output_model=FileReview)
            except Exception as exc:  # noqa: BLE001 — one bad file must not sink the run
                logger.warning("reviewer attempt %d failed on %s: %s", attempt, path, exc)
                if attempt:
                    return FileReview(path=path), f"{path}: {type(exc).__name__}"
                continue
        review = result.structured_output
        if review is not None:
            review.path = path  # the model likes to abbreviate paths; keep ours
            return review, None
    return FileReview(path=path), f"{path}: no structured output"


async def analyze(
    pr_number: int,
    issue_number: int | None = None,
    max_files: int = 10,
    concurrency: int = 3,
    on_event=lambda _msg: None,
) -> Analysis:
    """Run the full pipeline against one merged PR.

    Args:
        pr_number: The PR to check.
        issue_number: Override the issue. By default the PR body's closing keyword is used.
        max_files: Cap on reviewer sub-agents; the largest diffs win.
        concurrency: How many reviewers run at once.
        on_event: Called with progress strings, for the CLI.
    """
    pr = tools.fetch_pr(pr_number)
    if issue_number is None:
        refs = tools.issue_refs(pr.get("body") or "")
        if not refs:
            raise SystemExit(
                f"PR #{pr_number} does not say it closes an issue. Pass --issue N explicitly."
            )
        issue_number = refs[0]

    on_event(f"issue #{issue_number} → planner")
    planner = make_planner()
    plan_result = await planner.invoke_async(
        f"Extract the acceptance criteria for issue #{issue_number}.",
        structured_output_model=Plan,
    )
    plan: Plan = plan_result.structured_output
    if plan is None:
        raise RuntimeError("Planner returned no structured output; the model may not support it.")

    diff_by_path = tools.split_diff(tools.fetch_diff(pr_number))
    reviewed, skipped = _pick_files(diff_by_path, max_files)
    on_event(f"{len(plan.criteria)} criteria → {len(reviewed)} reviewers")

    if not reviewed:
        # No diff means no evidence, and a synthesizer handed criteria but no reviews will
        # happily invent some. Answer deterministically instead of asking the model.
        on_event("no diff to review")
        return Analysis(
            pr_number=pr_number,
            issue_number=issue_number,
            pr_title=pr["title"],
            issue_title=_issue_title(issue_number),
            plan=plan,
            report=reconcile(
                plan,
                DriftReport(
                    bottom_line="The PR has no reviewable diff, so nothing addresses the issue.",
                    verdicts=[],
                ),
            ),
        )

    sem = asyncio.Semaphore(concurrency)
    outcomes = await asyncio.gather(
        *(_review_one(p, diff_by_path[p], plan, sem) for p in reviewed)
    )
    reviews = [r for r, _ in outcomes]
    failures = [f for _, f in outcomes if f]
    if failures:
        on_event(f"{len(failures)} reviewer(s) failed: {'; '.join(failures)}")

    on_event("synthesizing")
    reviewer = make_reviewer()
    synth = make_synthesizer(reviewer)
    payload = [
        f"Acceptance criteria:\n{_criteria_block(plan)}",
        f"\nIssue #{issue_number} summary: {plan.issue_summary}",
        f"\nPR #{pr_number}: {pr['title']}",
    ]
    for r in reviews:
        payload.append(f"\n--- review of {r.path} ---\n{r.model_dump_json(indent=1)}")
    if skipped:
        payload.append(f"\nNot reviewed (diff cap): {', '.join(skipped)}")

    try:
        synth_result = await synth.invoke_async(
            "\n".join(payload), structured_output_model=DriftReport
        )
        report = reconcile(plan, synth_result.structured_output)
    except Exception as exc:  # noqa: BLE001
        logger.error("synthesizer failed: %s", exc)
        report = None

    return Analysis(
        pr_number=pr_number,
        issue_number=issue_number,
        pr_title=pr["title"],
        issue_title=_issue_title(issue_number),
        plan=plan,
        file_reviews=list(reviews),
        report=report,
        skipped_files=skipped,
        failed_files=failures,
    )
