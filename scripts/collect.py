#!/usr/bin/env python3
"""Pipeline entrypoint: collect -> transform -> analyse -> render.

Run locally with:
    GITHUB_TOKEN=ghp_xxx python scripts/collect.py
    python scripts/collect.py --dry-run     # no writes
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from radar import analyze, charts, report, storage, transform  # noqa: E402
from radar.config import PROJECTS  # noqa: E402
from radar.sources import GitHubSource, HttpTransport, PyPiSource, collect  # noqa: E402

log = logging.getLogger("collect")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect ecosystem metrics.")
    parser.add_argument("--dry-run", action="store_true", help="fetch but write nothing")
    parser.add_argument("--limit", type=int, default=0, help="only fetch N projects")
    parser.add_argument("--pause", type=float, default=0.12, help="seconds between requests")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip fetching; rebuild charts and README from stored data",
    )
    return parser.parse_args()


def render(frame, now: datetime, dry_run: bool) -> None:
    """Charts, README block and JSON report — all derived from `frame`."""
    snapshot = analyze.enrich(frame)

    summary = analyze.category_summary(snapshot)
    if not summary.empty:
        items = [(row["label"], float(row["stars_30d"] or 0)) for _, row in summary.iterrows()]
        chart = charts.bar_chart(items)
    else:
        chart = charts.bar_chart([])

    markdown = report.build_markdown(frame, now)
    payload = report.build_json(frame, now)

    if dry_run:
        log.info("dry run — skipping writes")
        print(markdown)
        return

    storage.write_text(storage.CHART_DIR / "categories.svg", chart)

    for _, row in snapshot.iterrows():
        history = analyze.history_for(frame, row["repo"], "stars")
        slug = row["repo"].replace("/", "__")
        storage.write_text(
            storage.CHART_DIR / "sparklines" / f"{slug}.svg", charts.sparkline(history)
        )

    storage.write_text(storage.REPORT_JSON, payload)
    storage.write_text(storage.README, report.splice(storage.read_text(storage.README), markdown))
    print(report.commit_message(frame, now))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    args = parse_args()
    now = datetime.now(UTC).replace(microsecond=0)

    history = storage.load_history()

    if args.report_only:
        if history.empty:
            log.error("no stored observations to report on")
            return 1
        render(history, now, args.dry_run)
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        log.warning("no GITHUB_TOKEN set — unauthenticated limit is 60 requests/hour")

    projects = PROJECTS[: args.limit] if args.limit else PROJECTS
    transport = HttpTransport()

    log.info("fetching %d projects", len(projects))
    results = collect(
        projects,
        GitHubSource(transport, token),
        PyPiSource(transport),
        pause=args.pause,
    )

    failures = [r for r in results if not r.ok]
    log.info("fetched %d ok, %d failed", len(results) - len(failures), len(failures))
    for failed in failures:
        log.error("  %s: %s", failed.repo, "; ".join(failed.errors))

    # Bail out rather than commit a half-empty day into the time series.
    if len(failures) > len(projects) * 0.4:
        log.error("more than 40%% of fetches failed — aborting without writing")
        return 1

    fresh = transform.build_frame(results, now)
    merged = transform.merge_history(history, fresh)

    if not args.dry_run:
        storage.save_history(merged)
        storage.save_snapshot([asdict(r) for r in results], now)

    log.info("history now holds %d observations", len(merged))
    render(merged, now, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
