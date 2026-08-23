"""Transform layer: raw payloads -> tidy rows."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from conftest import gh_payload, pypi_payload
from radar import transform
from radar.sources import FetchResult


class TestParseTs:
    def test_handles_github_z_suffix(self):
        parsed = transform.parse_ts("2026-08-22T09:00:00Z")
        assert parsed == datetime(2026, 8, 22, 9, 0, tzinfo=UTC)

    def test_handles_pypi_offset(self):
        parsed = transform.parse_ts("2026-08-22T09:00:00+00:00")
        assert parsed == datetime(2026, 8, 22, 9, 0, tzinfo=UTC)

    def test_assumes_utc_when_naive(self):
        assert transform.parse_ts("2026-08-22T09:00:00").tzinfo == UTC

    @pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", "2026-13-45"])
    def test_returns_none_for_junk(self, value):
        assert transform.parse_ts(value) is None


class TestDaysBetween:
    def test_counts_whole_days(self, now):
        earlier = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        assert transform.days_between(now, earlier) == 3

    def test_never_negative(self, now):
        future = datetime(2026, 9, 1, tzinfo=UTC)
        assert transform.days_between(now, future) == 0

    def test_none_input(self, now):
        assert transform.days_between(now, None) is None


class TestReleaseCadence:
    def test_median_gap_of_even_releases(self):
        # Releases 10 days apart -> median gap 10.
        assert transform.release_cadence_days(pypi_payload()["releases"]) == 10.0

    def test_needs_at_least_three_releases(self):
        releases = {"1.0.0": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}]}
        assert transform.release_cadence_days(releases) is None

    def test_skips_yanked_versions_with_no_files(self):
        releases = {
            "1.0.0": [],
            "1.1.0": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}],
            "1.2.0": [{"upload_time_iso_8601": "2026-01-05T00:00:00Z"}],
            "1.3.0": [{"upload_time_iso_8601": "2026-01-09T00:00:00Z"}],
        }
        assert transform.release_cadence_days(releases) == 4.0

    def test_only_uses_most_recent_sample(self):
        releases = {}
        # Ten releases 1 day apart, then three 30 days apart.
        for i in range(10):
            releases[f"0.{i}.0"] = [{"upload_time_iso_8601": f"2026-01-{i + 1:02d}T00:00:00Z"}]
        for i, day in enumerate(("2026-03-01", "2026-03-31", "2026-04-30")):
            releases[f"1.{i}.0"] = [{"upload_time_iso_8601": f"{day}T00:00:00Z"}]

        recent = transform.release_cadence_days(releases, sample=4)
        assert recent == 30.0


class TestToRow:
    def test_flattens_a_full_payload(self, result_ok, now):
        row = transform.to_row(result_ok, now)
        assert row["repo"] == "pola-rs/polars"
        assert row["date"] == "2026-08-23"
        assert row["stars"] == 30000
        assert row["license"] == "MIT"
        assert row["release_tag"] == "py-1.3.0"
        assert row["pypi_releases"] == 4
        assert row["pypi_cadence_days"] == 10.0
        assert row["category"] == "data-engineering"

    def test_returns_none_for_failed_fetch(self, result_failed, now):
        assert transform.to_row(result_failed, now) is None

    def test_survives_missing_release(self, now):
        result = FetchResult(repo="pola-rs/polars", github=gh_payload(), release=None)
        row = transform.to_row(result, now)
        assert row["release_tag"] is None
        assert row["days_since_release"] is None

    def test_survives_missing_licence(self, now):
        result = FetchResult(repo="pola-rs/polars", github=gh_payload(license=None))
        assert transform.to_row(result, now)["license"] is None

    def test_unknown_repo_gets_unknown_category(self, now):
        result = FetchResult(repo="nobody/nothing", github=gh_payload())
        assert transform.to_row(result, now)["category"] == "unknown"


class TestBuildFrame:
    def test_drops_failures_and_applies_schema(self, result_ok, result_failed, now):
        frame = transform.build_frame([result_ok, result_failed], now)
        assert len(frame) == 1
        assert list(frame.columns) == list(transform.SCHEMA)
        assert frame["stars"].dtype == "Int64"

    def test_empty_input_still_has_schema(self, now):
        frame = transform.build_frame([], now)
        assert frame.empty
        assert list(frame.columns) == list(transform.SCHEMA)


class TestMergeHistory:
    def test_appends_a_new_day(self, history, result_ok):
        fresh = transform.build_frame([result_ok], datetime(2026, 9, 1, tzinfo=UTC))
        merged = transform.merge_history(history, fresh)
        assert len(merged) == len(history) + 1

    def test_same_day_overwrites_rather_than_duplicating(self, result_ok, now):
        first = transform.build_frame([result_ok], now)
        second = transform.build_frame([result_ok], now)
        merged = transform.merge_history(first, second)
        assert len(merged) == 1

    def test_last_write_wins(self, result_ok, now):
        first = transform.build_frame([result_ok], now)
        updated = FetchResult(repo="pola-rs/polars", github=gh_payload(stargazers_count=31000))
        second = transform.build_frame([updated], now)
        merged = transform.merge_history(first, second)
        assert merged.iloc[0]["stars"] == 31000

    def test_sorted_by_repo_then_date(self, history, result_ok, now):
        fresh = transform.build_frame([result_ok], now)
        merged = transform.merge_history(history, fresh)
        for repo, group in merged.groupby("repo"):
            assert list(group["date"]) == sorted(group["date"])

    def test_merging_into_empty_history_works(self, result_ok, now):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        merged = transform.merge_history(empty, transform.build_frame([result_ok], now))
        assert len(merged) == 1
