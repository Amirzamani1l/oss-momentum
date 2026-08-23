"""Analysis layer.

Turns the observation table into the numbers a human actually wants:
who is gaining, who is stalling, and how each category is doing.

Every function takes and returns a DataFrame. No IO.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CATEGORIES

# A project is "stale" once it has gone this long without a push.
STALE_PUSH_DAYS = 45
# Open issues per 1000 stars above which maintenance load looks heavy.
ISSUE_PRESSURE_WARN = 25.0


def _series_for(frame: pd.DataFrame, repo: str) -> pd.DataFrame:
    return frame[frame["repo"] == repo].sort_values("date")


def delta_over(frame: pd.DataFrame, column: str, days: int) -> pd.Series:
    """Change in `column` over the last `days` days, per repo.

    Uses the earliest observation at or before the cutoff rather than a
    fixed row offset, because runs can be skipped (Fridays, outages) and
    row counts do not map cleanly onto calendar days.
    """
    if frame.empty:
        return pd.Series(dtype="Float64")

    dates = pd.to_datetime(frame["date"])
    latest = dates.max()
    cutoff = latest - pd.Timedelta(days=days)

    out: dict[str, float] = {}
    for repo, group in frame.assign(_d=dates).groupby("repo", sort=False):
        group = group.sort_values("_d")
        current = group.iloc[-1][column]
        past_rows = group[group["_d"] <= cutoff]
        baseline_row = past_rows.iloc[-1] if not past_rows.empty else group.iloc[0]
        baseline = baseline_row[column]
        if pd.isna(current) or pd.isna(baseline):
            continue
        out[repo] = float(current) - float(baseline)

    return pd.Series(out, dtype="Float64")


def latest_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per repo: the most recent observation."""
    if frame.empty:
        return frame.copy()
    ordered = frame.assign(_d=pd.to_datetime(frame["date"])).sort_values("_d")
    return (
        ordered.groupby("repo", as_index=False, sort=False)
        .tail(1)
        .drop(columns="_d")
        .reset_index(drop=True)
    )


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach derived metrics to the latest snapshot."""
    snapshot = latest_snapshot(frame)
    if snapshot.empty:
        return snapshot

    for window in (1, 7, 30):
        snapshot[f"stars_delta_{window}d"] = (
            snapshot["repo"].map(delta_over(frame, "stars", window)).astype("Float64")
        )

    stars = snapshot["stars"].astype("Float64")

    # Growth as a percentage of the existing base, so a 500-star gain on a
    # 2k-star project outranks the same gain on a 200k-star project.
    baseline_30d = stars - snapshot["stars_delta_30d"]
    snapshot["growth_30d_pct"] = np.where(
        baseline_30d > 0,
        (snapshot["stars_delta_30d"] / baseline_30d) * 100.0,
        np.nan,
    )
    snapshot["growth_30d_pct"] = snapshot["growth_30d_pct"].astype("Float64").round(2)

    # Maintenance load proxy.
    snapshot["issue_pressure"] = np.where(
        stars > 0, (snapshot["open_issues"].astype("Float64") / stars) * 1000.0, np.nan
    )
    snapshot["issue_pressure"] = snapshot["issue_pressure"].astype("Float64").round(2)

    snapshot["momentum_z"] = zscore(snapshot["growth_30d_pct"]).round(2)
    snapshot["is_stale"] = snapshot["days_since_push"].astype("Float64") > STALE_PUSH_DAYS
    snapshot["heavy_issues"] = snapshot["issue_pressure"] > ISSUE_PRESSURE_WARN

    return snapshot


def zscore(series: pd.Series) -> pd.Series:
    """Standard score, guarding against a zero-variance column."""
    values = series.astype("Float64")
    valid = values.dropna()
    if len(valid) < 2:
        return pd.Series([pd.NA] * len(values), index=values.index, dtype="Float64")
    spread = float(valid.std(ddof=0))
    if spread == 0:
        return pd.Series([0.0] * len(values), index=values.index, dtype="Float64")
    return ((values - float(valid.mean())) / spread).astype("Float64")


def leaderboard(
    snapshot: pd.DataFrame, column: str, top: int = 8, ascending: bool = False
) -> pd.DataFrame:
    if snapshot.empty or column not in snapshot:
        return pd.DataFrame()
    ranked = snapshot.dropna(subset=[column]).sort_values(column, ascending=ascending)
    return ranked.head(top).reset_index(drop=True)


def category_summary(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per category so the README has a bird's-eye table."""
    if snapshot.empty:
        return pd.DataFrame()

    grouped = snapshot.groupby("category", as_index=False).agg(
        projects=("repo", "count"),
        total_stars=("stars", "sum"),
        stars_30d=("stars_delta_30d", "sum"),
        median_growth=("growth_30d_pct", "median"),
        stale=("is_stale", "sum"),
    )
    grouped["label"] = grouped["category"].map(CATEGORIES).fillna(grouped["category"])
    grouped["median_growth"] = grouped["median_growth"].astype("Float64").round(2)
    return grouped.sort_values("stars_30d", ascending=False).reset_index(drop=True)


def coverage(frame: pd.DataFrame) -> dict[str, object]:
    """Dataset-level facts, printed in the README so the reader can judge
    how much history the numbers are standing on."""
    if frame.empty:
        return {"observations": 0, "repos": 0, "days": 0, "first_date": None, "last_date": None}

    dates = pd.to_datetime(frame["date"])
    return {
        "observations": int(len(frame)),
        "repos": int(frame["repo"].nunique()),
        "days": int(dates.nunique()),
        "first_date": dates.min().date().isoformat(),
        "last_date": dates.max().date().isoformat(),
    }


def history_for(frame: pd.DataFrame, repo: str, column: str = "stars") -> list[float]:
    """Ordered value series for one repo — feeds the sparklines."""
    series = _series_for(frame, repo)[column].dropna()
    return [float(v) for v in series]
