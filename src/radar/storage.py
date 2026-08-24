"""Filesystem IO — the only module that touches disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .transform import SCHEMA, coerce

DATA_DIR = Path("data")
OBSERVATIONS = DATA_DIR / "observations.csv"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
REPORT_JSON = DATA_DIR / "latest_report.json"
HEALTH = DATA_DIR / "health.json"
CHART_DIR = Path("charts")
README = Path("README.md")


def load_history(path: Path = OBSERVATIONS) -> pd.DataFrame:
    if not path.exists():
        return coerce(pd.DataFrame(columns=list(SCHEMA)))
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    return coerce(frame)


def save_history(frame: pd.DataFrame, path: Path = OBSERVATIONS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def save_snapshot(payload: object, when: datetime, directory: Path = SNAPSHOT_DIR) -> Path:
    """Keep the raw API response for the day, so the derived table can
    always be rebuilt from source."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{when:%Y-%m-%d}.json"
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_text(path: Path, default: str = "") -> str:
    return path.read_text(encoding="utf-8") if path.exists() else default


def load_health(path: Path = HEALTH) -> dict[str, int]:
    """Consecutive fetch-failure counts per repo.

    Kept out of the observation table because it describes the collector,
    not the ecosystem.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): int(v) for k, v in raw.items() if isinstance(v, int | float)}


def save_health(counts: dict[str, int], path: Path = HEALTH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Repos that recovered are dropped rather than stored as zero, so the
    # file stays small and its contents are always actionable.
    live = {k: v for k, v in sorted(counts.items()) if v > 0}
    path.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_health(
    previous: dict[str, int], failed: list[str], attempted: list[str]
) -> dict[str, int]:
    """Increment failures, reset anything that succeeded this run."""
    updated = dict(previous)
    failures = set(failed)
    for repo in attempted:
        if repo in failures:
            updated[repo] = updated.get(repo, 0) + 1
        else:
            updated.pop(repo, None)
    return updated
