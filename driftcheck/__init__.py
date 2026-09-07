"""DriftCheck: read a merged PR against the issue it claims to close."""

from .pipeline import Analysis, analyze
from .schema import Criterion, DriftReport, FileReview, Finding, Plan, SilentChange

__all__ = [
    "Analysis",
    "analyze",
    "Criterion",
    "DriftReport",
    "FileReview",
    "Finding",
    "Plan",
    "SilentChange",
]
__version__ = "0.1.0"
