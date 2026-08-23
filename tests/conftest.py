import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from radar.sources import FetchResult  # noqa: E402

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def gh_payload(**overrides):
    base = {
        "full_name": "pola-rs/polars",
        "stargazers_count": 30000,
        "forks_count": 1900,
        "subscribers_count": 210,
        "open_issues_count": 1800,
        "size": 45000,
        "pushed_at": "2026-08-22T09:00:00Z",
        "language": "Rust",
        "license": {"spdx_id": "MIT"},
    }
    base.update(overrides)
    return base


def pypi_payload(versions=("1.0.0", "1.1.0", "1.2.0", "1.3.0")):
    stamps = [
        "2026-06-01T00:00:00.000000Z",
        "2026-06-11T00:00:00.000000Z",
        "2026-06-21T00:00:00.000000Z",
        "2026-07-01T00:00:00.000000Z",
    ]
    releases = {
        version: [{"upload_time_iso_8601": stamp}] for version, stamp in zip(versions, stamps)
    }
    return {
        "info": {
            "name": "polars",
            "version": versions[-1],
            "requires_python": ">=3.10",
        },
        "releases": releases,
    }


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def result_ok():
    return FetchResult(
        repo="pola-rs/polars",
        github=gh_payload(),
        release={"tag_name": "py-1.3.0", "published_at": "2026-07-01T00:00:00Z"},
        pypi=pypi_payload(),
    )


@pytest.fixture
def result_failed():
    return FetchResult(repo="ghost/repo", errors=["github: HTTP 404"])


@pytest.fixture
def history():
    """Two repos, 31 days of daily observations with known slopes."""
    rows = []
    for day in range(31):
        date = (datetime(2026, 7, 24, tzinfo=UTC) + pd.Timedelta(days=day)).date()
        rows.append(
            {
                "date": date.isoformat(),
                "repo": "fast/riser",
                "category": "data-engineering",
                "stars": 1000 + day * 50,
                "forks": 100,
                "watchers": 20,
                "open_issues": 10,
                "size_kb": 500,
                "days_since_push": 1,
                "language": "Python",
                "license": "MIT",
                "release_tag": "v1",
                "days_since_release": 3,
                "pypi_version": "1.0.0",
                "pypi_releases": 12,
                "pypi_cadence_days": 10.0,
                "requires_python": ">=3.9",
            }
        )
        rows.append(
            {
                "date": date.isoformat(),
                "repo": "slow/giant",
                "category": "database",
                "stars": 100000 + day * 10,
                "forks": 9000,
                "watchers": 900,
                "open_issues": 4000,
                "size_kb": 900000,
                "days_since_push": 90,
                "language": "C",
                "license": "Apache-2.0",
                "release_tag": None,
                "days_since_release": None,
                "pypi_version": None,
                "pypi_releases": None,
                "pypi_cadence_days": None,
                "requires_python": None,
            }
        )

    from radar.transform import coerce

    return coerce(pd.DataFrame(rows))
