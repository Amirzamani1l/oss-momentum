#!/usr/bin/env python3
"""Open and close issues for whatever the latest data says.

Runs after collection. Reads only stored data, so it can be re-run at any
time without touching the APIs it collects from.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/name python scripts/sync_issues.py
    python scripts/sync_issues.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from radar import alerts, analyze, storage  # noqa: E402
from radar.issues import IssueTracker, apply_plan  # noqa: E402
from radar.sources import HttpTransport  # noqa: E402

log = logging.getLogger("sync-issues")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync findings to GitHub Issues.")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    args = parse_args()

    history = storage.load_history()
    if history.empty:
        log.error("no observations stored — run scripts/collect.py first")
        return 1

    snapshot = analyze.enrich(history)
    findings = alerts.derive(snapshot, storage.load_health())

    log.info("%d finding(s) from %d projects", len(findings), len(snapshot))
    for finding in findings:
        log.info("  [%s] %s", finding.severity, finding.title)

    if args.dry_run and not args.repo:
        # Useful locally: show what would be raised without needing a token.
        plan = alerts.reconcile(findings, [])
        log.info("would open %d issue(s)", len(plan.create))
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not args.repo or not token:
        log.error("GITHUB_REPOSITORY and GITHUB_TOKEN are both required")
        return 1

    tracker = IssueTracker(HttpTransport(), args.repo, token)

    try:
        open_issues = tracker.list_open()
    except Exception as exc:  # noqa: BLE001
        log.error("could not list issues: %s", exc)
        return 1

    plan = alerts.reconcile(findings, open_issues)

    if plan.empty:
        log.info("nothing to do — %d issue(s) already tracked", len(open_issues))
        return 0

    counts = apply_plan(tracker, plan, dry_run=args.dry_run)
    log.info(
        "opened %d, closed %d, failed %d",
        counts["created"],
        counts["closed"],
        counts["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
