"""Findings — the analysis output that deserves a human's attention.

Two responsibilities, both pure:

* `derive`     — turn a snapshot into a set of findings
* `reconcile`  — diff findings against currently open issues

Nothing here talks to GitHub. That keeps the interesting logic — when to
open an issue and when to close one — fully testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# A project that has not been pushed to in this long is worth a look.
STALLED_PUSH_DAYS = 45
# z-score above which growth counts as a genuine outlier, not noise.
SPIKE_Z = 2.5
# Losing stars outright over 30 days.
SLUMP_GROWTH_PCT = 0.0
# No release in this long, for a project that previously shipped regularly.
DROUGHT_DAYS = 180
DROUGHT_PRIOR_CADENCE_DAYS = 45
# Consecutive failed fetches before we assume the repo really is gone.
UNREACHABLE_RUNS = 3

MARKER_RE = re.compile(r"<!--\s*radar:([a-z_]+:[^\s>]+?)\s*-->")


def marker(key: str) -> str:
    """Machine-readable tag embedded in every issue body.

    Titles get edited and translated; this does not. It is how a later
    run recognises an issue it opened itself.
    """
    return f"<!-- radar:{key} -->"


def extract_key(body: str | None) -> str | None:
    if not body:
        return None
    found = MARKER_RE.search(body)
    return found.group(1) if found else None


@dataclass(frozen=True)
class Finding:
    kind: str
    repo: str
    title: str
    body: str
    severity: str = "info"

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.repo}"

    def issue_body(self) -> str:
        return f"{self.body}\n\n{marker(self.key)}\n"


@dataclass(frozen=True)
class Plan:
    """What to do about the current findings."""

    create: tuple[Finding, ...] = ()
    close: tuple[tuple[int, str], ...] = ()  # (issue_number, reason)

    @property
    def empty(self) -> bool:
        return not self.create and not self.close


def _num(value: object, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    return f"{float(value):,.{digits}f}"


def _link(repo: str) -> str:
    return f"[{repo}](https://github.com/{repo})"


def derive(snapshot: pd.DataFrame, unreachable: dict[str, int] | None = None) -> list[Finding]:
    """Findings implied by the latest snapshot.

    Deterministic and order-stable, so a run that changes nothing
    produces exactly the same set and therefore no issue churn.
    """
    findings: list[Finding] = []
    unreachable = unreachable or {}

    if not snapshot.empty:
        for _, row in snapshot.sort_values("repo").iterrows():
            findings.extend(_for_row(row))

    for repo in sorted(unreachable):
        if unreachable[repo] >= UNREACHABLE_RUNS:
            findings.append(
                Finding(
                    kind="unreachable",
                    repo=repo,
                    title=f"Cannot reach {repo}",
                    body=(
                        f"{_link(repo)} has failed to fetch on "
                        f"{unreachable[repo]} consecutive runs.\n\n"
                        "The repository was most likely renamed, made private or "
                        "deleted. Update `src/radar/config.py` to point at the new "
                        "location, or drop the entry."
                    ),
                    severity="high",
                )
            )

    return findings


def _for_row(row: pd.Series) -> list[Finding]:
    repo = str(row["repo"])
    out: list[Finding] = []

    days_since_push = row.get("days_since_push")
    if pd.notna(days_since_push) and float(days_since_push) > STALLED_PUSH_DAYS:
        out.append(
            Finding(
                kind="stalled",
                repo=repo,
                title=f"{repo} looks stalled",
                body=(
                    f"{_link(repo)} has not been pushed to in "
                    f"**{_num(days_since_push)} days** "
                    f"(threshold {STALLED_PUSH_DAYS}).\n\n"
                    "Note that `pushed_at` covers every branch, so a project with "
                    "active feature branches but a frozen default branch will not "
                    "appear here. Worth confirming before drawing conclusions."
                ),
                severity="medium",
            )
        )

    momentum = row.get("momentum_z")
    growth = row.get("growth_30d_pct")
    if pd.notna(momentum) and float(momentum) >= SPIKE_Z:
        out.append(
            Finding(
                kind="spike",
                repo=repo,
                title=f"Unusual momentum: {repo}",
                body=(
                    f"{_link(repo)} is growing at **{_num(growth, 2)}%** over 30 days, "
                    f"a z-score of **{_num(momentum, 2)}** against the tracked set.\n\n"
                    "Star growth is bursty — a conference talk or a front-page post "
                    "produces a spike unrelated to adoption. Worth checking whether "
                    "this is a durable trend or a single event."
                ),
                severity="info",
            )
        )

    if pd.notna(growth) and float(growth) < SLUMP_GROWTH_PCT:
        out.append(
            Finding(
                kind="slump",
                repo=repo,
                title=f"{repo} is losing stars",
                body=(
                    f"{_link(repo)} has **{_num(growth, 2)}%** growth over 30 days — "
                    "a net loss.\n\n"
                    "Usually this means GitHub pruned spam accounts rather than that "
                    "real users left. Check the raw counts in "
                    "`data/observations.csv` before reading anything into it."
                ),
                severity="medium",
            )
        )

    since_release = row.get("days_since_release")
    cadence = row.get("pypi_cadence_days")
    if (
        pd.notna(since_release)
        and float(since_release) > DROUGHT_DAYS
        and pd.notna(cadence)
        and float(cadence) < DROUGHT_PRIOR_CADENCE_DAYS
    ):
        out.append(
            Finding(
                kind="drought",
                repo=repo,
                title=f"Release drought: {repo}",
                body=(
                    f"{_link(repo)} last released **{_num(since_release)} days ago**, "
                    f"but its historical median cadence is **{_num(cadence, 1)} days**.\n\n"
                    "A project shipping every few weeks that then goes quiet for six "
                    "months is a stronger signal than one that always released slowly."
                ),
                severity="medium",
            )
        )

    return out


def reconcile(findings: list[Finding], open_issues: list[dict]) -> Plan:
    """Diff findings against open issues.

    * finding with no open issue  -> create
    * open issue with no finding  -> close, the condition cleared
    * both                        -> leave it alone

    Issues without a radar marker are ignored entirely, so anything a
    human opened by hand is never touched.
    """
    current = {f.key: f for f in findings}

    tracked: dict[str, int] = {}
    for issue in open_issues:
        key = extract_key(issue.get("body"))
        if key is None:
            continue
        number = issue.get("number")
        if number is None:
            continue
        # If duplicates somehow exist, keep the lowest number and close
        # the rest as resolved.
        if key not in tracked or number < tracked[key]:
            tracked[key] = int(number)

    create = tuple(f for key, f in current.items() if key not in tracked)
    # Oldest issue first, so the close order matches the order they were opened.
    close = tuple(
        (number, key)
        for key, number in sorted(tracked.items(), key=lambda item: item[1])
        if key not in current
    )

    return Plan(create=create, close=close)


def close_comment(key: str) -> str:
    kind = key.split(":", 1)[0]
    reasons = {
        "stalled": "The project has been pushed to again.",
        "spike": "Growth has returned to the normal range.",
        "slump": "Star growth is positive again.",
        "drought": "A new release has shipped.",
        "unreachable": "The repository is reachable again.",
    }
    return (
        f"{reasons.get(kind, 'The condition no longer holds.')} "
        "Closing automatically — this issue will reopen if it recurs."
    )
