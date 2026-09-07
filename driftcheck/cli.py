"""driftcheck — did this merged PR do what its issue asked?"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict

from . import tools
from .pipeline import analyze
from .render import render


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="driftcheck", description=__doc__)
    p.add_argument("pr", type=int, help="merged pull request number")
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--worktree", help="local checkout, enables source reads and caller search")
    p.add_argument("--issue", type=int, help="override the issue the PR claims to close")
    p.add_argument("--max-files", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--all", action="store_true", help="include low-risk silent changes")
    p.add_argument("--json", dest="as_json", action="store_true", help="emit the raw report")
    args = p.parse_args(argv)

    tools.configure(args.repo, args.worktree)
    started = time.monotonic()

    def progress(msg: str) -> None:
        if not args.as_json:
            print(f"\033[2m  · {msg}\033[0m", file=sys.stderr, flush=True)

    analysis = asyncio.run(
        analyze(
            args.pr,
            issue_number=args.issue,
            max_files=args.max_files,
            concurrency=args.concurrency,
            on_event=progress,
        )
    )

    if args.as_json:
        payload = asdict(analysis)
        payload["plan"] = analysis.plan.model_dump()
        payload["file_reviews"] = [r.model_dump() for r in analysis.file_reviews]
        payload["report"] = analysis.report.model_dump() if analysis.report else None
        print(json.dumps(payload, indent=2))
    else:
        print(render(analysis, show_low=args.all))
        print(f"\033[2m  {time.monotonic() - started:.0f}s\033[0m\n", file=sys.stderr)

    r = analysis.report
    if r is None:
        return 2
    return 1 if any(v.verdict != "met" for v in r.verdicts) or r.silent_changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
