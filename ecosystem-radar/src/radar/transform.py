"""Raw payloads -> one tidy row per (date, repo).

This module is pure: no network, no filesystem. That is what makes the
whole pipeline testable with fixtures.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .config import PROJECT_BY_REPO
from .sources import FetchResult

SCHEMA: dict[str, str] = {
    "date": "string",
    "repo": "string",
    "category": "string",
    "stars": "Int64",
    "forks": "Int64",
    "watchers": "Int64",
    "open_issues": "Int64",
    "size_kb": "Int64",
    "days_since_push": "Int64",
    "language": "string",
    "license": "string",
    "release_tag": "string",
    "days_since_release": "Int64",
    "pypi_version": "string",
    "pypi_releases": "Int64",
    "pypi_cadence_days": "Float64",
    "requires_python": "string",
}


def parse_ts(value: str | None) -> datetime | None:
    """GitHub returns Z-suffixed ISO-8601; PyPI sometimes returns +00:00."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def days_between(later: datetime, earlier: datetime | None) -> int | None:
    if earlier is None:
        return None
    return max(0, int((later - earlier).total_seconds() // 86400))


def release_cadence_days(
    releases: dict[str, list[dict[str, Any]]], sample: int = 10
) -> float | None:
    """Median gap between the most recent `sample` PyPI releases.

    A stable cadence is a decent proxy for project health; a long or
    erratic one is worth flagging.
    """
    stamps: list[datetime] = []
    for files in releases.values():
        if not files:
            continue
        parsed = parse_ts(files[0].get("upload_time_iso_8601"))
        if parsed:
            stamps.append(parsed)

    if len(stamps) < 3:
        return None

    stamps.sort()
    recent = stamps[-sample:]
    gaps = [
        (b - a).total_seconds() / 86400.0
        for a, b in zip(recent, recent[1:], strict=False)  # pairwise gaps
        if (b - a).total_seconds() > 0
    ]
    if not gaps:
        return None
    return round(statistics.median(gaps), 2)


def to_row(result: FetchResult, observed_at: datetime) -> dict[str, Any] | None:
    """Flatten one FetchResult into a single observation row."""
    if not result.ok:
        return None

    gh = result.github or {}
    project = PROJECT_BY_REPO.get(result.repo)

    licence = gh.get("license") or {}
    pushed = parse_ts(gh.get("pushed_at"))

    release_tag = None
    release_at = None
    if result.release:
        release_tag = result.release.get("tag_name")
        release_at = parse_ts(result.release.get("published_at"))

    pypi_version = None
    pypi_releases = None
    cadence = None
    requires_python = None
    if result.pypi:
        info = result.pypi.get("info") or {}
        pypi_version = info.get("version")
        requires_python = info.get("requires_python")
        releases = result.pypi.get("releases") or {}
        pypi_releases = len(releases)
        cadence = release_cadence_days(releases)

    return {
        "date": observed_at.date().isoformat(),
        "repo": result.repo,
        "category": project.category if project else "unknown",
        "stars": gh.get("stargazers_count"),
        "forks": gh.get("forks_count"),
        "watchers": gh.get("subscribers_count"),
        "open_issues": gh.get("open_issues_count"),
        "size_kb": gh.get("size"),
        "days_since_push": days_between(observed_at, pushed),
        "language": gh.get("language"),
        "license": licence.get("spdx_id"),
        "release_tag": release_tag,
        "days_since_release": days_between(observed_at, release_at),
        "pypi_version": pypi_version,
        "pypi_releases": pypi_releases,
        "pypi_cadence_days": cadence,
        "requires_python": requires_python,
    }


def build_frame(results: list[FetchResult], observed_at: datetime) -> pd.DataFrame:
    rows = [row for row in (to_row(r, observed_at) for r in results) if row]
    frame = pd.DataFrame(rows, columns=list(SCHEMA))
    return coerce(frame)


def coerce(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the declared schema so the CSV round-trips losslessly."""
    for column, dtype in SCHEMA.items():
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = frame[column].astype(dtype)
    return frame[list(SCHEMA)]


def merge_history(history: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """Append today's observations, keeping one row per (date, repo).

    The pipeline runs three times a day, so the same date is written
    repeatedly. Last write wins, which keeps the series daily and the
    diff small.
    """
    if history.empty:
        combined = fresh.copy()
    else:
        combined = pd.concat([coerce(history), fresh], ignore_index=True)

    combined = combined.drop_duplicates(subset=["date", "repo"], keep="last")
    combined = combined.sort_values(["repo", "date"], kind="stable").reset_index(drop=True)
    return coerce(combined)
