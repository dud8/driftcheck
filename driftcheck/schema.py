"""Structured output contracts shared by the three agents."""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["met", "partial", "unaddressed"]
Risk = Literal["low", "medium", "high"]


class Criterion(BaseModel):
    """One acceptance criterion the issue asks the PR to satisfy."""

    id: str = Field(description="Short stable id, e.g. AC1")
    text: str = Field(description="The criterion in one sentence, as the issue implies it")
    source: Literal["explicit", "implied"] = Field(
        description="explicit if the issue states it outright, implied if it follows from the report"
    )


class Plan(BaseModel):
    """The planner's reading of the issue, before any diff is judged."""

    issue_summary: str = Field(description="What the issue asks for, in two sentences")
    criteria: list[Criterion] = Field(description="3 to 8 criteria, ordered by importance")
    in_scope_paths: list[str] = Field(
        default_factory=list,
        description="Files or directories the issue names or clearly implies. Empty if the issue names none.",
    )


class Finding(BaseModel):
    """A per-criterion judgement backed by a specific place in the diff."""

    criterion_id: str
    verdict: Verdict
    evidence: str = Field(
        description=(
            "One short line: the symbol, line range or single statement that settles it, or the "
            "absence that does not. Never a pasted hunk."
        )
    )
    note: str = Field(description="One sentence of reasoning")


class SilentChange(BaseModel):
    """Behaviour the diff changed that the issue never asked about."""

    path: str
    description: str = Field(description="What behaviour changed, concretely")
    risk: Risk
    evidence: str = Field(
        description="One short line: the symbol, line range or single changed statement."
    )


class FileReview(BaseModel):
    """One reviewer sub-agent's verdict on one changed file."""

    path: str
    findings: list[Finding] = Field(
        default_factory=list, description="Only criteria this file speaks to. Omit the rest."
    )
    out_of_scope_changes: list[SilentChange] = Field(default_factory=list)


class DriftReport(BaseModel):
    """The synthesizer's answer: did the diff do what the issue asked?"""

    bottom_line: str = Field(description="One sentence a reviewer can act on")
    verdicts: list[Finding] = Field(description="Exactly one entry per criterion in the plan")
    silent_changes: list[SilentChange] = Field(
        default_factory=list, description="Deduplicated, highest risk first"
    )
