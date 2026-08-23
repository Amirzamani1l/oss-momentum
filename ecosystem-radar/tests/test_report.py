"""Rendering: Markdown block, README splicing, JSON report."""

import json
from datetime import UTC, datetime

import pandas as pd

from radar import report, transform

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class TestFormatters:
    def test_missing_values_render_as_dash(self):
        assert report._num(None) == "—"
        assert report._num(pd.NA) == "—"
        assert report._signed(None) == "—"

    def test_thousands_separator(self):
        assert report._num(1234567) == "1,234,567"

    def test_signed_adds_plus(self):
        assert report._signed(500) == "+500"
        assert report._signed(-500) == "-500"

    def test_repo_link_points_at_github(self):
        assert report._repo_link("a/b") == "[a/b](https://github.com/a/b)"


class TestBuildMarkdown:
    def test_wrapped_in_sentinels(self, history):
        block = report.build_markdown(history, NOW)
        assert block.startswith(report.START)
        assert block.rstrip().endswith(report.END)

    def test_includes_both_repos(self, history):
        block = report.build_markdown(history, NOW)
        assert "fast/riser" in block
        assert "slow/giant" in block

    def test_states_dataset_coverage(self, history):
        block = report.build_markdown(history, NOW)
        assert "31 days of history" in block
        assert "2026-07-24" in block

    def test_flags_the_stale_project_in_the_watchlist(self, history):
        block = report.build_markdown(history, NOW)
        watchlist = block.split("### Watchlist", 1)[1]
        assert "slow/giant" in watchlist
        assert "stalled" in watchlist

    def test_handles_an_empty_dataset(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        block = report.build_markdown(empty, NOW)
        assert report.START in block and report.END in block


class TestSplice:
    def test_replaces_an_existing_block(self):
        readme = f"# Title\n\nintro\n\n{report.START}\nOLD\n{report.END}\n\nfooter\n"
        result = report.splice(readme, f"{report.START}\nNEW\n{report.END}")
        assert "OLD" not in result
        assert "NEW" in result
        assert "footer" in result
        assert "# Title" in result

    def test_appends_when_no_block_exists(self):
        result = report.splice("# Title\n", f"{report.START}\nNEW\n{report.END}")
        assert "# Title" in result
        assert "NEW" in result

    def test_is_idempotent(self):
        block = f"{report.START}\nNEW\n{report.END}"
        once = report.splice("# T\n", block)
        twice = report.splice(once, block)
        assert once.count(report.START) == twice.count(report.START) == 1

    def test_does_not_treat_content_as_a_regex_template(self):
        """A block containing backslash-g or similar must survive verbatim."""
        block = f"{report.START}\nC:\\path\\g<1> & 100%\n{report.END}"
        result = report.splice(f"x\n{report.START}\nold\n{report.END}\n", block)
        assert "C:\\path\\g<1> & 100%" in result


class TestBuildJson:
    def test_is_valid_json(self, history):
        payload = json.loads(report.build_json(history, NOW))
        assert payload["coverage"]["repos"] == 2
        assert len(payload["projects"]) == 2
        assert len(payload["categories"]) == 2

    def test_empty_dataset_still_parses(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        payload = json.loads(report.build_json(empty, NOW))
        assert payload["projects"] == []


class TestCommitMessage:
    def test_describes_the_change(self, history):
        message = report.commit_message(history, NOW)
        assert message.startswith("data: 2026-08-23 snapshot")
        assert "2 projects" in message

    def test_names_the_days_leader(self, history):
        # fast/riser gains 50/day, slow/giant only 10.
        assert "riser" in report.commit_message(history, NOW)

    def test_empty_dataset_gets_a_generic_message(self):
        empty = transform.coerce(pd.DataFrame(columns=list(transform.SCHEMA)))
        assert report.commit_message(empty, NOW) == "data: snapshot 2026-08-23"

    def test_message_is_a_single_line(self, history):
        assert "\n" not in report.commit_message(history, NOW)


class TestLeaderboardOrdering:
    """Regression: the fallers table must rank by relative growth, not by
    absolute star delta, or a big healthy project lands in it by accident."""

    def test_fallers_are_the_slowest_growers(self, history):
        block = report.build_markdown(history, NOW)
        fallers = block.split("### Losing momentum", 1)[1].split("###", 1)[0]
        first_row = [line for line in fallers.splitlines() if line.startswith("| [")][0]
        assert "slow/giant" in first_row

    def test_risers_and_fallers_are_ordered_oppositely(self, history):
        block = report.build_markdown(history, NOW)
        risers = block.split("### Fastest growing", 1)[1].split("###", 1)[0]
        fallers = block.split("### Losing momentum", 1)[1].split("###", 1)[0]
        top_riser = [ln for ln in risers.splitlines() if ln.startswith("| [")][0]
        top_faller = [ln for ln in fallers.splitlines() if ln.startswith("| [")][0]
        assert "fast/riser" in top_riser
        assert "slow/giant" in top_faller
