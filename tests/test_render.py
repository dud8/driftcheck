"""The report must render without colour codes and without crashing on empty sections."""

import os

from driftcheck.pipeline import Analysis
from driftcheck.render import render
from driftcheck.schema import Criterion, DriftReport, Finding, Plan, SilentChange


def _analysis(report):
    return Analysis(
        pr_number=1,
        issue_number=2,
        pr_title="a pr",
        issue_title="an issue",
        plan=Plan(
            issue_summary="s",
            criteria=[Criterion(id="AC1", text="the timeout is configurable", source="explicit")],
        ),
        report=report,
    )


def test_render_shows_verdict_criterion_and_evidence(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    import importlib

    import driftcheck.render as r

    importlib.reload(r)
    out = r.render(
        _analysis(
            DriftReport(
                bottom_line="ships what was asked",
                verdicts=[
                    Finding(criterion_id="AC1", verdict="met", evidence="vc_sync.py:112", note="n")
                ],
                silent_changes=[
                    SilentChange(path="a.py", description="default flipped", risk="high", evidence="h")
                ],
            )
        )
    )
    assert "MET" in out
    assert "the timeout is configurable" in out
    assert "vc_sync.py:112" in out
    assert "HIGH" in out and "default flipped" in out
    assert "ships what was asked" in out
    assert "\033[" not in out
    importlib.reload(r)


def test_render_survives_an_empty_report():
    out = render(_analysis(DriftReport(bottom_line="", verdicts=[])))
    assert "none found" in out


def test_render_survives_no_report():
    assert "no report" in render(_analysis(None))


def test_long_evidence_is_clipped_not_dumped():
    from driftcheck.render import _wrap

    out = _wrap("word " * 400, "  ")
    assert len(out) < 600
    assert out.rstrip().endswith("…")


def _report_with_risks(*risks):
    return DriftReport(
        bottom_line="b",
        verdicts=[],
        silent_changes=[
            SilentChange(path=f"f{i}.py", description="d", risk=r, evidence="e")
            for i, r in enumerate(risks)
        ],
    )


def test_low_risk_changes_are_hidden_by_default_and_counted():
    out = render(_analysis(_report_with_risks("high", "low", "low")))
    assert "f0.py" in out and "f1.py" not in out
    assert "2 low-risk change(s) hidden" in out


def test_all_shows_them():
    out = render(_analysis(_report_with_risks("high", "low")), show_low=True)
    assert "f0.py" in out and "f1.py" in out


def test_only_low_risk_reads_as_clean_not_empty():
    out = render(_analysis(_report_with_risks("low")))
    assert "nothing above low risk" in out
    assert "none found" not in out
