"""Analysis layer: deltas, growth, momentum, aggregates."""

import numpy as np
import pandas as pd
import pytest

from radar import analyze, transform


class TestLatestSnapshot:
    def test_one_row_per_repo(self, history):
        snapshot = analyze.latest_snapshot(history)
        assert len(snapshot) == 2
        assert set(snapshot["repo"]) == {"fast/riser", "slow/giant"}

    def test_takes_the_newest_date(self, history):
        snapshot = analyze.latest_snapshot(history)
        riser = snapshot[snapshot["repo"] == "fast/riser"].iloc[0]
        assert riser["date"] == "2026-08-23"
        assert riser["stars"] == 1000 + 30 * 50

    def test_empty_in_empty_out(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        assert analyze.latest_snapshot(empty).empty


class TestDeltaOver:
    def test_thirty_day_delta(self, history):
        delta = analyze.delta_over(history, "stars", 30)
        assert delta["fast/riser"] == pytest.approx(1500.0)
        assert delta["slow/giant"] == pytest.approx(300.0)

    def test_one_day_delta(self, history):
        delta = analyze.delta_over(history, "stars", 1)
        assert delta["fast/riser"] == pytest.approx(50.0)

    def test_window_longer_than_history_uses_first_row(self, history):
        # 365d window, but only 31 days exist -> falls back to the oldest row.
        assert analyze.delta_over(history, "stars", 365)["fast/riser"] == pytest.approx(1500.0)

    def test_tolerates_skipped_days(self, history):
        """Fridays are skipped, so row count != day count. The delta must
        still be anchored on dates, not on row offsets."""
        thinned = history[pd.to_datetime(history["date"]).dt.dayofweek != 4]
        delta = analyze.delta_over(thinned, "stars", 7)
        # Whatever rows survive, a 7-day window on a +50/day slope
        # cannot exceed 350.
        assert 0 < delta["fast/riser"] <= 350

    def test_empty_frame(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        assert analyze.delta_over(empty, "stars", 7).empty


class TestZscore:
    def test_centres_and_scales(self):
        result = analyze.zscore(pd.Series([1.0, 2.0, 3.0], dtype="Float64"))
        assert result.iloc[1] == pytest.approx(0.0)
        assert result.iloc[0] < 0 < result.iloc[2]

    def test_zero_variance_returns_zeros(self):
        result = analyze.zscore(pd.Series([5.0, 5.0, 5.0], dtype="Float64"))
        assert list(result) == [0.0, 0.0, 0.0]

    def test_single_value_is_undefined(self):
        result = analyze.zscore(pd.Series([5.0], dtype="Float64"))
        assert pd.isna(result.iloc[0])

    def test_ignores_nan_when_computing_stats(self):
        result = analyze.zscore(pd.Series([1.0, np.nan, 3.0], dtype="Float64"))
        assert pd.isna(result.iloc[1])
        assert result.iloc[0] == pytest.approx(-1.0)


class TestEnrich:
    def test_adds_all_derived_columns(self, history):
        snapshot = analyze.enrich(history)
        for column in (
            "stars_delta_1d",
            "stars_delta_7d",
            "stars_delta_30d",
            "growth_30d_pct",
            "issue_pressure",
            "momentum_z",
            "is_stale",
            "heavy_issues",
        ):
            assert column in snapshot.columns

    def test_growth_is_relative_not_absolute(self, history):
        """The whole point of the metric: a small fast project must beat
        a huge slow one even with fewer absolute stars."""
        snapshot = analyze.enrich(history).set_index("repo")
        assert (
            snapshot.loc["fast/riser", "growth_30d_pct"]
            > snapshot.loc["slow/giant", "growth_30d_pct"]
        )

    def test_growth_percentage_is_correct(self, history):
        snapshot = analyze.enrich(history).set_index("repo")
        # 1000 -> 2500 over the window: +1500 on a base of 1000 = 150%.
        assert snapshot.loc["fast/riser", "growth_30d_pct"] == pytest.approx(150.0, rel=1e-3)

    def test_issue_pressure_per_thousand_stars(self, history):
        snapshot = analyze.enrich(history).set_index("repo")
        # slow/giant: 4000 issues / 100300 stars * 1000 ~= 39.9
        assert snapshot.loc["slow/giant", "issue_pressure"] == pytest.approx(39.9, abs=0.5)

    def test_stale_flag_uses_threshold(self, history):
        snapshot = analyze.enrich(history).set_index("repo")
        assert bool(snapshot.loc["slow/giant", "is_stale"]) is True
        assert bool(snapshot.loc["fast/riser", "is_stale"]) is False

    def test_heavy_issue_flag(self, history):
        snapshot = analyze.enrich(history).set_index("repo")
        assert bool(snapshot.loc["slow/giant", "heavy_issues"]) is True

    def test_momentum_z_orders_the_same_as_growth(self, history):
        snapshot = analyze.enrich(history).set_index("repo")
        assert snapshot.loc["fast/riser", "momentum_z"] > snapshot.loc["slow/giant", "momentum_z"]

    def test_empty_input(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        assert analyze.enrich(empty).empty


class TestLeaderboard:
    def test_descending_by_default(self, history):
        snapshot = analyze.enrich(history)
        board = analyze.leaderboard(snapshot, "growth_30d_pct", top=2)
        assert board.iloc[0]["repo"] == "fast/riser"

    def test_ascending_finds_the_laggard(self, history):
        snapshot = analyze.enrich(history)
        board = analyze.leaderboard(snapshot, "growth_30d_pct", top=1, ascending=True)
        assert board.iloc[0]["repo"] == "slow/giant"

    def test_respects_top_n(self, history):
        snapshot = analyze.enrich(history)
        assert len(analyze.leaderboard(snapshot, "stars", top=1)) == 1

    def test_unknown_column_is_safe(self, history):
        snapshot = analyze.enrich(history)
        assert analyze.leaderboard(snapshot, "does_not_exist").empty


class TestCategorySummary:
    def test_one_row_per_category(self, history):
        summary = analyze.category_summary(analyze.enrich(history))
        assert len(summary) == 2
        assert set(summary["category"]) == {"data-engineering", "database"}

    def test_has_human_readable_label(self, history):
        summary = analyze.category_summary(analyze.enrich(history))
        assert "Data engineering" in set(summary["label"])

    def test_counts_stale_projects(self, history):
        summary = analyze.category_summary(analyze.enrich(history)).set_index("category")
        assert int(summary.loc["database", "stale"]) == 1
        assert int(summary.loc["data-engineering", "stale"]) == 0


class TestCoverage:
    def test_reports_dataset_shape(self, history):
        stats = analyze.coverage(history)
        assert stats["repos"] == 2
        assert stats["days"] == 31
        assert stats["observations"] == 62
        assert stats["first_date"] == "2026-07-24"
        assert stats["last_date"] == "2026-08-23"

    def test_empty_dataset(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        assert analyze.coverage(empty)["observations"] == 0


class TestHistoryFor:
    def test_returns_ordered_series(self, history):
        values = analyze.history_for(history, "fast/riser", "stars")
        assert len(values) == 31
        assert values == sorted(values)

    def test_unknown_repo_is_empty(self, history):
        assert analyze.history_for(history, "nobody/nothing") == []
