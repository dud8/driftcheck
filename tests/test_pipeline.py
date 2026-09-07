"""Orchestration and verdict reconciliation, with the model stubbed out.

These are the adversarial cases: an issue with no clear criteria, a PR that closes an issue it
does not address, and a diff that wanders into files the issue never mentioned.
"""

import asyncio
from types import SimpleNamespace

import pytest

from driftcheck import pipeline, tools
from driftcheck.schema import Criterion, DriftReport, FileReview, Finding, Plan, SilentChange


def plan_of(*texts, paths=()):
    return Plan(
        issue_summary="summary",
        criteria=[
            Criterion(id=f"AC{i}", text=t, source="explicit") for i, t in enumerate(texts, 1)
        ],
        in_scope_paths=list(paths),
    )


# --------------------------------------------------------------- reconcile


def test_missing_criteria_become_unaddressed_not_silently_dropped():
    plan = plan_of("timeout is configurable", "default stays 30s", "docs mention the flag")
    report = DriftReport(
        bottom_line="looks fine",
        verdicts=[Finding(criterion_id="AC1", verdict="met", evidence="hunk", note="")],
    )
    out = pipeline.reconcile(plan, report)

    assert [v.criterion_id for v in out.verdicts] == ["AC1", "AC2", "AC3"]
    assert [v.verdict for v in out.verdicts] == ["met", "unaddressed", "unaddressed"]


def test_hallucinated_criterion_ids_are_dropped():
    plan = plan_of("only one thing")
    report = DriftReport(
        bottom_line="",
        verdicts=[
            Finding(criterion_id="AC1", verdict="met", evidence="e", note=""),
            Finding(criterion_id="AC7", verdict="met", evidence="invented", note=""),
        ],
    )
    out = pipeline.reconcile(plan, report)
    assert [v.criterion_id for v in out.verdicts] == ["AC1"]


def test_verdict_order_follows_the_plan_not_the_model():
    plan = plan_of("first", "second")
    report = DriftReport(
        bottom_line="",
        verdicts=[
            Finding(criterion_id="AC2", verdict="met", evidence="e", note=""),
            Finding(criterion_id="AC1", verdict="partial", evidence="e", note=""),
        ],
    )
    out = pipeline.reconcile(plan, report)
    assert [v.criterion_id for v in out.verdicts] == ["AC1", "AC2"]


def test_silent_changes_are_ordered_by_risk():
    plan = plan_of("one")
    report = DriftReport(
        bottom_line="",
        verdicts=[],
        silent_changes=[
            SilentChange(path="a", description="d", risk="low", evidence="e"),
            SilentChange(path="b", description="d", risk="high", evidence="e"),
            SilentChange(path="c", description="d", risk="medium", evidence="e"),
        ],
    )
    out = pipeline.reconcile(plan, report)
    assert [s.path for s in out.silent_changes] == ["b", "c", "a"]


def test_reconcile_passes_none_through():
    assert pipeline.reconcile(plan_of("x"), None) is None


# --------------------------------------------------------------- file selection


def test_largest_diffs_win_the_reviewer_budget():
    diffs = {"small.py": "x" * 10, "huge.py": "x" * 900, "mid.py": "x" * 100}
    reviewed, skipped = pipeline._pick_files(diffs, max_files=2)
    assert reviewed == ["huge.py", "mid.py"]
    assert skipped == ["small.py"]


def test_no_cap_means_no_skips():
    diffs = {"a": "x", "b": "yy"}
    reviewed, skipped = pipeline._pick_files(diffs, max_files=10)
    assert sorted(reviewed) == ["a", "b"] and skipped == []


# --------------------------------------------------------------- orchestration


class FakeAgent:
    """Stands in for a Strands Agent: returns a canned structured output."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def invoke_async(self, prompt, structured_output_model=None, **_):
        self.prompts.append(prompt)
        value = self.payload(prompt) if callable(self.payload) else self.payload
        return SimpleNamespace(structured_output=value)

    def as_tool(self, **_):
        return self


@pytest.fixture
def wired(monkeypatch):
    """Wire the pipeline to fakes and capture what each stage saw."""

    seen = {}

    def install(plan, review_fn, report):
        monkeypatch.setattr(pipeline, "make_planner", lambda: FakeAgent(plan))
        seen["reviewers"] = []

        def reviewer(with_tools=True):
            a = FakeAgent(review_fn)
            seen["reviewers"].append(a)
            return a

        monkeypatch.setattr(pipeline, "make_reviewer", reviewer)
        synth = FakeAgent(report)
        seen["synth"] = synth
        monkeypatch.setattr(pipeline, "make_synthesizer", lambda _r: synth)

    seen["install"] = install
    return seen


def _stub_github(monkeypatch, body, diff, title="a pr"):
    monkeypatch.setattr(
        tools, "fetch_pr", lambda n: {"number": n, "title": title, "body": body, "files": []}
    )
    monkeypatch.setattr(tools, "fetch_diff", lambda n: diff)
    monkeypatch.setattr(tools, "fetch_issue", lambda n: f"# Issue #{n}: an issue\n\nbody")


def test_pr_that_names_no_issue_is_refused_rather_than_guessed(monkeypatch, wired):
    _stub_github(monkeypatch, body="A tidy-up. See #4 for background.", diff="")
    wired["install"](plan_of("x"), FileReview(path="p"), DriftReport(bottom_line="", verdicts=[]))

    with pytest.raises(SystemExit, match="--issue"):
        asyncio.run(pipeline.analyze(1))


def test_issue_is_taken_from_the_closing_keyword(monkeypatch, wired):
    _stub_github(monkeypatch, body="Fixes #42", diff="diff --git a/a.py b/a.py\n+x\n")
    wired["install"](plan_of("x"), FileReview(path="a.py"), DriftReport(bottom_line="", verdicts=[]))

    result = asyncio.run(pipeline.analyze(1))
    assert result.issue_number == 42


def test_explicit_issue_overrides_the_pr_body(monkeypatch, wired):
    _stub_github(monkeypatch, body="Fixes #42", diff="")
    wired["install"](plan_of("x"), FileReview(path="p"), DriftReport(bottom_line="", verdicts=[]))

    assert asyncio.run(pipeline.analyze(1, issue_number=99)).issue_number == 99


def test_one_reviewer_per_changed_file_each_seeing_only_its_own_diff(monkeypatch, wired):
    diff = (
        "diff --git a/one.py b/one.py\n@@ -1 +1 @@\n+ONE_MARKER\n"
        "diff --git a/two.py b/two.py\n@@ -1 +1 @@\n+TWO_MARKER\n"
    )
    _stub_github(monkeypatch, body="Closes #7", diff=diff)
    wired["install"](
        plan_of("a"),
        lambda p: FileReview(path="ignored"),
        DriftReport(bottom_line="", verdicts=[]),
    )

    result = asyncio.run(pipeline.analyze(5))

    # One extra reviewer instance exists only to be handed to the synthesizer as a tool.
    used = [a for a in wired["reviewers"] if a.prompts]
    assert len(used) == 2
    prompts = [a.prompts[0] for a in used]
    assert sum("ONE_MARKER" in p for p in prompts) == 1
    assert sum("TWO_MARKER" in p for p in prompts) == 1
    for p in prompts:
        assert not ("ONE_MARKER" in p and "TWO_MARKER" in p)
    # The path is ours, never the model's abbreviation of it.
    assert sorted(r.path for r in result.file_reviews) == ["one.py", "two.py"]


def test_a_reviewer_that_returns_nothing_does_not_sink_the_run(monkeypatch, wired):
    _stub_github(monkeypatch, body="Closes #7", diff="diff --git a/a.py b/a.py\n+x\n")
    wired["install"](plan_of("a"), None, DriftReport(bottom_line="", verdicts=[]))

    result = asyncio.run(pipeline.analyze(5))
    assert result.file_reviews[0].path == "a.py"
    assert result.file_reviews[0].findings == []


def test_a_pr_that_addresses_nothing_reports_every_criterion_unaddressed(monkeypatch, wired):
    """The whole point: the PR says 'Closes #7', the diff touches an unrelated file."""
    _stub_github(
        monkeypatch,
        body="Closes #7",
        diff="diff --git a/unrelated/README.md b/unrelated/README.md\n@@ -1 +1 @@\n+typo\n",
    )
    wired["install"](
        plan_of("timeout is configurable", "default stays 30s"),
        FileReview(
            path="unrelated/README.md",
            out_of_scope_changes=[
                SilentChange(path="unrelated/README.md", description="doc edit", risk="low", evidence="+typo")
            ],
        ),
        DriftReport(bottom_line="This PR does not touch the reported behaviour.", verdicts=[]),
    )

    result = asyncio.run(pipeline.analyze(5))
    assert [v.verdict for v in result.report.verdicts] == ["unaddressed", "unaddressed"]


def test_an_issue_with_no_extractable_criteria_yields_an_empty_but_valid_report(monkeypatch, wired):
    _stub_github(monkeypatch, body="Closes #7", diff="diff --git a/a.py b/a.py\n+x\n")
    empty_plan = Plan(issue_summary="'it is broken', with no detail", criteria=[])
    wired["install"](empty_plan, FileReview(path="a.py"), DriftReport(bottom_line="No criteria could be extracted.", verdicts=[]))

    result = asyncio.run(pipeline.analyze(5))
    assert result.report.verdicts == []
    assert result.plan.criteria == []


def test_files_beyond_the_cap_are_reported_not_hidden(monkeypatch, wired):
    diff = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'x' * (10 - i)}\n" for i in range(4)
    )
    _stub_github(monkeypatch, body="Closes #7", diff=diff)
    wired["install"](plan_of("a"), FileReview(path="p"), DriftReport(bottom_line="", verdicts=[]))

    result = asyncio.run(pipeline.analyze(5, max_files=2))
    assert len(result.file_reviews) == 2
    assert len(result.skipped_files) == 2
    assert "Not reviewed (diff cap)" in wired["synth"].prompts[0]


def test_the_synthesizer_sees_every_file_review(monkeypatch, wired):
    diff = "diff --git a/a.py b/a.py\n+x\ndiff --git a/b.py b/b.py\n+y\n"
    _stub_github(monkeypatch, body="Closes #7", diff=diff)
    wired["install"](
        plan_of("a"),
        lambda p: FileReview(path="x", findings=[Finding(criterion_id="AC1", verdict="met", evidence="EV", note="")]),
        DriftReport(bottom_line="", verdicts=[]),
    )

    asyncio.run(pipeline.analyze(5))
    prompt = wired["synth"].prompts[0]
    assert "review of a.py" in prompt and "review of b.py" in prompt


# --------------------------------------------------------------- scope framing


def _scope_line(monkeypatch, wired, in_scope, diff_path):
    diff = f"diff --git a/{diff_path} b/{diff_path}\n@@ -1 +1 @@\n+x\n"
    _stub_github(monkeypatch, body="Closes #7", diff=diff)
    plan = plan_of("a criterion", paths=in_scope)
    wired["install"](plan, FileReview(path=diff_path), DriftReport(bottom_line="", verdicts=[]))
    asyncio.run(pipeline.analyze(5))
    return next(a.prompts[0] for a in wired["reviewers"] if a.prompts)


def test_a_file_the_issue_never_named_is_flagged_as_out_of_scope(monkeypatch, wired):
    prompt = _scope_line(monkeypatch, wired, ["src/parser.py"], "src/cache.py")
    assert "does NOT name this file" in prompt
    assert "out of scope" in prompt


def test_a_file_the_issue_named_is_not_prejudged(monkeypatch, wired):
    prompt = _scope_line(monkeypatch, wired, ["src/parser.py"], "src/parser.py")
    assert "names this file's area" in prompt
    assert "does NOT name" not in prompt


def test_an_issue_that_names_no_paths_falls_back_to_the_criteria(monkeypatch, wired):
    prompt = _scope_line(monkeypatch, wired, [], "src/anything.py")
    assert "named no paths at all" in prompt


def test_a_reviewer_that_raises_is_reported_not_fatal(monkeypatch, wired):
    diff = "diff --git a/boom.py b/boom.py\n+x\ndiff --git a/ok.py b/ok.py\n+yy\n"
    _stub_github(monkeypatch, body="Closes #7", diff=diff)

    def review(prompt):
        if "boom.py" in prompt:
            raise RuntimeError("model refused")
        return FileReview(path="ok.py")

    wired["install"](plan_of("a"), review, DriftReport(bottom_line="", verdicts=[]))

    result = asyncio.run(pipeline.analyze(5))
    assert result.failed_files == ["boom.py: RuntimeError"]
    assert result.report is not None  # the run still produced a report


def test_a_failing_synthesizer_leaves_a_renderable_analysis(monkeypatch, wired):
    _stub_github(monkeypatch, body="Closes #7", diff="diff --git a/a.py b/a.py\n+x\n")

    def boom(_prompt):
        raise RuntimeError("no")

    wired["install"](plan_of("a"), FileReview(path="a.py"), boom)

    result = asyncio.run(pipeline.analyze(5))
    assert result.report is None
    assert result.plan.criteria  # the plan survived


def test_a_failed_reviewer_is_retried_once_before_being_given_up_on(monkeypatch, wired):
    _stub_github(monkeypatch, body="Closes #7", diff="diff --git a/a.py b/a.py\n+x\n")
    attempts = []

    def review(prompt):
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise RuntimeError("no structured output")
        return FileReview(path="a.py", findings=[Finding(criterion_id="AC1", verdict="met", evidence="e", note="")])

    wired["install"](plan_of("a"), review, DriftReport(bottom_line="", verdicts=[]))

    result = asyncio.run(pipeline.analyze(5))
    assert len(attempts) == 2
    assert result.failed_files == []
    assert result.file_reviews[0].findings[0].verdict == "met"


def test_an_empty_diff_cannot_be_reported_as_met(monkeypatch, wired):
    """No diff means no evidence. The synthesizer is not asked, so it cannot invent any."""
    _stub_github(monkeypatch, body="Closes #7", diff="")
    liar = DriftReport(
        bottom_line="Looks good to me.",
        verdicts=[
            Finding(criterion_id="AC1", verdict="met", evidence="line 12", note="done"),
            Finding(criterion_id="AC2", verdict="met", evidence="line 40", note="done"),
        ],
    )
    wired["install"](plan_of("timeout is configurable", "default stays 30s"), FileReview(path="p"), liar)

    result = asyncio.run(pipeline.analyze(5))

    assert [v.verdict for v in result.report.verdicts] == ["unaddressed", "unaddressed"]
    assert wired["synth"].prompts == []
    assert result.file_reviews == []
