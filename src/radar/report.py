"""Rendering.

Builds the Markdown block that gets spliced into README.md between two
sentinel comments, plus a machine-readable JSON report.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import pandas as pd

from . import analyze
from .config import CATEGORIES

START = "<!-- RADAR:START -->"
END = "<!-- RADAR:END -->"


def _num(value: Any, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    if digits:
        return f"{float(value):,.{digits}f}"
    return f"{int(float(value)):,}"


def _signed(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    return f"{'+' if number >= 0 else ''}{number:,.0f}"


def _repo_link(repo: str) -> str:
    return f"[{repo}](https://github.com/{repo})"


def movers_table(rows: pd.DataFrame, title: str) -> str:
    if rows.empty:
        return f"### {title}\n\n_Not enough history yet._\n"

    lines = [
        f"### {title}",
        "",
        "| Project | Category | Stars | 30d | Growth | Momentum |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for _, row in rows.iterrows():
        lines.append(
            "| {repo} | {cat} | {stars} | {delta} | {growth}% | {z} |".format(
                repo=_repo_link(row["repo"]),
                cat=CATEGORIES.get(row["category"], row["category"]),
                stars=_num(row["stars"]),
                delta=_signed(row.get("stars_delta_30d")),
                growth=_num(row.get("growth_30d_pct"), 2),
                z=_num(row.get("momentum_z"), 2),
            )
        )
    return "\n".join(lines) + "\n"


def category_table(summary: pd.DataFrame) -> str:
    if summary.empty:
        return ""
    lines = [
        "### Categories",
        "",
        "| Category | Projects | Stars | 30d | Median growth | Stale |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in summary.iterrows():
        lines.append(
            "| {label} | {n} | {stars} | {delta} | {growth}% | {stale} |".format(
                label=row["label"],
                n=_num(row["projects"]),
                stars=_num(row["total_stars"]),
                delta=_signed(row["stars_30d"]),
                growth=_num(row["median_growth"], 2),
                stale=_num(row["stale"]),
            )
        )
    return "\n".join(lines) + "\n"


def watchlist_table(snapshot: pd.DataFrame, limit: int = 8) -> str:
    """Projects worth a second look: stalled pushes or heavy issue load."""
    if snapshot.empty:
        return ""

    flagged = snapshot[snapshot["is_stale"].fillna(False) | snapshot["heavy_issues"].fillna(False)]
    if flagged.empty:
        return "### Watchlist\n\n_Nothing flagged._\n"

    flagged = flagged.sort_values("days_since_push", ascending=False).head(limit)
    lines = [
        "### Watchlist",
        "",
        "| Project | Days since push | Open issues / 1k stars | Flag |",
        "| --- | ---: | ---: | --- |",
    ]
    for _, row in flagged.iterrows():
        flags = []
        if bool(row.get("is_stale")):
            flags.append("stalled")
        if bool(row.get("heavy_issues")):
            flags.append("issue load")
        lines.append(
            "| {repo} | {days} | {pressure} | {flag} |".format(
                repo=_repo_link(row["repo"]),
                days=_num(row.get("days_since_push")),
                pressure=_num(row.get("issue_pressure"), 2),
                flag=", ".join(flags),
            )
        )
    return "\n".join(lines) + "\n"


def build_markdown(frame: pd.DataFrame, generated_at: datetime) -> str:
    snapshot = analyze.enrich(frame)
    stats = analyze.coverage(frame)

    risers = analyze.leaderboard(snapshot, "growth_30d_pct", top=8, ascending=False)
    fallers = analyze.leaderboard(snapshot, "growth_30d_pct", top=5, ascending=True)
    summary = analyze.category_summary(snapshot)

    header = (
        f"_Last run: **{generated_at.strftime('%Y-%m-%d %H:%M UTC')}** · "
        f"{stats['repos']} projects · {stats['observations']:,} observations · "
        f"{stats['days']} days of history "
        f"({stats['first_date']} → {stats['last_date']})_\n"
    )

    blocks = [
        START,
        "",
        "## Ecosystem Radar",
        "",
        header,
        "![Category momentum](charts/categories.svg)",
        "",
        movers_table(risers, "Fastest growing (30d, star growth as % of base)"),
        "",
        movers_table(fallers, "Losing momentum (30d)"),
        "",
        category_table(summary),
        "",
        watchlist_table(snapshot),
        "",
        "_Generated automatically. Methodology in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)._",
        "",
        END,
    ]
    return "\n".join(blocks)


def splice(readme: str, block: str) -> str:
    """Replace the region between the sentinels, or append it if absent."""
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if pattern.search(readme):
        return pattern.sub(lambda _: block, readme)
    separator = "" if readme.endswith("\n\n") else "\n\n"
    return readme + separator + block + "\n"


def build_json(frame: pd.DataFrame, generated_at: datetime) -> str:
    snapshot = analyze.enrich(frame)
    payload = {
        "generated_at": generated_at.isoformat(),
        "coverage": analyze.coverage(frame),
        "projects": json.loads(snapshot.to_json(orient="records")) if not snapshot.empty else [],
        "categories": json.loads(analyze.category_summary(snapshot).to_json(orient="records"))
        if not snapshot.empty
        else [],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def commit_message(frame: pd.DataFrame, generated_at: datetime) -> str:
    """A message that says what actually changed, so the history is
    readable months later."""
    snapshot = analyze.enrich(frame)
    if snapshot.empty:
        return f"data: snapshot {generated_at:%Y-%m-%d}"

    total = snapshot["stars_delta_1d"].sum() if "stars_delta_1d" in snapshot else 0
    top = analyze.leaderboard(snapshot, "stars_delta_1d", top=1, ascending=False)
    lead = top.iloc[0]["repo"].split("/")[-1] if not top.empty else "ecosystem"
    return (
        f"data: {generated_at:%Y-%m-%d} snapshot "
        f"({len(snapshot)} projects, {_signed(total)} stars, {lead} leading)"
    )
