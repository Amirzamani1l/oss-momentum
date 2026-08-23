"""End-to-end: fake API -> CSV -> charts -> README, with no network."""

import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from conftest import gh_payload, pypi_payload
from radar import analyze, charts, report, storage, transform
from radar.config import Project
from radar.sources import GitHubSource, PyPiSource, collect

ROOT = Path(__file__).resolve().parents[1]


class ScriptedTransport:
    def __init__(self, stars: int):
        self.stars = stars

    def get_json(self, url, headers):
        if "/releases/latest" in url:
            return {"tag_name": "v2", "published_at": "2026-08-01T00:00:00Z"}
        if "/pypi/" in url:
            return pypi_payload()
        return gh_payload(stargazers_count=self.stars)


PROJECTS = (Project("pola-rs/polars", "data-engineering", "polars"),)


def run_day(history, stars: int, when: datetime):
    transport = ScriptedTransport(stars)
    results = collect(PROJECTS, GitHubSource(transport), PyPiSource(transport))
    fresh = transform.build_frame(results, when)
    return transform.merge_history(history, fresh)


class TestFullPipeline:
    def test_two_days_accumulate_into_a_series(self):
        empty = transform.coerce(__import__("pandas").DataFrame(columns=list(transform.SCHEMA)))
        day1 = run_day(empty, 30000, datetime(2026, 8, 22, tzinfo=UTC))
        day2 = run_day(day1, 30500, datetime(2026, 8, 23, tzinfo=UTC))

        assert len(day2) == 2
        snapshot = analyze.enrich(day2)
        assert snapshot.iloc[0]["stars"] == 30500
        assert snapshot.iloc[0]["stars_delta_1d"] == 500.0

    def test_artifacts_are_written_and_valid(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        empty = transform.coerce(__import__("pandas").DataFrame(columns=list(transform.SCHEMA)))
        frame = run_day(empty, 30000, datetime(2026, 8, 23, tzinfo=UTC))

        storage.save_history(frame, tmp_path / "observations.csv")
        assert (tmp_path / "observations.csv").exists()

        svg = charts.sparkline(analyze.history_for(frame, "pola-rs/polars"))
        ET.fromstring(svg)

        readme = report.splice("# Radar\n", report.build_markdown(frame, datetime.now(UTC)))
        assert "pola-rs/polars" in readme
        assert report.START in readme


class TestEntrypoint:
    def test_report_only_on_empty_data_exits_nonzero(self, tmp_path):
        """Guard against committing a report built from nothing."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect.py"), "--report-only"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 1
        assert "no stored observations" in result.stderr

    def test_help_works(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "collect.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0
        assert "--dry-run" in result.stdout
