"""Filesystem layer — every test runs inside tmp_path."""

import json

import pandas as pd

from radar import storage, transform


class TestHistoryRoundTrip:
    def test_missing_file_yields_empty_frame_with_schema(self, tmp_path):
        frame = storage.load_history(tmp_path / "nope.csv")
        assert frame.empty
        assert list(frame.columns) == list(transform.SCHEMA)

    def test_save_then_load_preserves_values(self, tmp_path, history):
        path = tmp_path / "obs.csv"
        storage.save_history(history, path)
        reloaded = storage.load_history(path)
        assert len(reloaded) == len(history)
        assert reloaded.iloc[0]["repo"] == history.iloc[0]["repo"]

    def test_save_then_load_preserves_dtypes(self, tmp_path, history):
        path = tmp_path / "obs.csv"
        storage.save_history(history, path)
        reloaded = storage.load_history(path)
        assert reloaded["stars"].dtype == "Int64"
        assert reloaded["pypi_cadence_days"].dtype == "Float64"

    def test_nulls_survive_the_round_trip(self, tmp_path, history):
        """slow/giant has no PyPI package; those columns must stay null,
        not become the string 'nan'."""
        path = tmp_path / "obs.csv"
        storage.save_history(history, path)
        reloaded = storage.load_history(path)
        giant = reloaded[reloaded["repo"] == "slow/giant"].iloc[0]
        assert pd.isna(giant["pypi_version"])

    def test_creates_parent_directories(self, tmp_path, history):
        path = tmp_path / "deep" / "nested" / "obs.csv"
        storage.save_history(history, path)
        assert path.exists()


class TestSnapshot:
    def test_writes_a_dated_json_file(self, tmp_path, now):
        path = storage.save_snapshot([{"repo": "a/b"}], now, tmp_path)
        assert path.name == "2026-08-23.json"
        assert json.loads(path.read_text())[0]["repo"] == "a/b"

    def test_rerunning_the_same_day_overwrites(self, tmp_path, now):
        storage.save_snapshot([{"repo": "a/b"}], now, tmp_path)
        storage.save_snapshot([{"repo": "c/d"}], now, tmp_path)
        assert len(list(tmp_path.glob("*.json"))) == 1


class TestTextHelpers:
    def test_read_missing_file_returns_default(self, tmp_path):
        assert storage.read_text(tmp_path / "gone.md", "fallback") == "fallback"

    def test_write_then_read(self, tmp_path):
        path = tmp_path / "a" / "b.md"
        storage.write_text(path, "hello")
        assert storage.read_text(path) == "hello"
