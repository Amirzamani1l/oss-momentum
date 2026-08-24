"""Findings and reconciliation — the logic that decides what becomes an issue."""

import pandas as pd
import pytest

from radar import alerts, analyze


def snapshot_of(**overrides) -> pd.DataFrame:
    base = {
        "repo": "a/b",
        "category": "data-engineering",
        "stars": 10000,
        "open_issues": 100,
        "days_since_push": 2,
        "days_since_release": 10,
        "pypi_cadence_days": 14.0,
        "growth_30d_pct": 5.0,
        "momentum_z": 0.5,
        "issue_pressure": 10.0,
    }
    base.update(overrides)
    return pd.DataFrame([base])


def issue(number: int, key: str | None, body_extra: str = "") -> dict:
    body = body_extra + (alerts.marker(key) if key else "")
    return {"number": number, "body": body, "title": "whatever"}


class TestMarker:
    def test_round_trips(self):
        assert alerts.extract_key(alerts.marker("stalled:a/b")) == "stalled:a/b"

    def test_survives_surrounding_prose(self):
        body = f"Some text\n\n{alerts.marker('spike:x/y')}\n\nmore text"
        assert alerts.extract_key(body) == "spike:x/y"

    @pytest.mark.parametrize("body", [None, "", "no marker here", "<!-- unrelated -->"])
    def test_returns_none_without_a_marker(self, body):
        assert alerts.extract_key(body) is None

    def test_finding_body_embeds_its_own_key(self):
        finding = alerts.Finding("stalled", "a/b", "t", "body")
        assert alerts.extract_key(finding.issue_body()) == "stalled:a/b"


class TestDeriveStalled:
    def test_fires_above_the_threshold(self):
        findings = alerts.derive(snapshot_of(days_since_push=90))
        assert [f.kind for f in findings] == ["stalled"]

    def test_silent_below_the_threshold(self):
        assert alerts.derive(snapshot_of(days_since_push=10)) == []

    def test_boundary_is_exclusive(self):
        assert alerts.derive(snapshot_of(days_since_push=alerts.STALLED_PUSH_DAYS)) == []

    def test_null_push_date_does_not_fire(self):
        assert alerts.derive(snapshot_of(days_since_push=pd.NA)) == []

    def test_body_mentions_the_branch_caveat(self):
        body = alerts.derive(snapshot_of(days_since_push=90))[0].body
        assert "every branch" in body


class TestDeriveSpike:
    def test_fires_on_a_high_zscore(self):
        findings = alerts.derive(snapshot_of(momentum_z=3.0))
        assert any(f.kind == "spike" for f in findings)

    def test_silent_on_ordinary_growth(self):
        assert alerts.derive(snapshot_of(momentum_z=1.0)) == []

    def test_body_warns_that_stars_are_bursty(self):
        body = next(f for f in alerts.derive(snapshot_of(momentum_z=3.0)) if f.kind == "spike").body
        assert "bursty" in body


class TestDeriveSlump:
    def test_fires_on_negative_growth(self):
        findings = alerts.derive(snapshot_of(growth_30d_pct=-2.0))
        assert any(f.kind == "slump" for f in findings)

    def test_silent_on_flat_growth(self):
        assert alerts.derive(snapshot_of(growth_30d_pct=0.0)) == []


class TestDeriveDrought:
    def test_fires_when_a_regular_shipper_goes_quiet(self):
        findings = alerts.derive(snapshot_of(days_since_release=300, pypi_cadence_days=14.0))
        assert any(f.kind == "drought" for f in findings)

    def test_silent_for_projects_that_always_shipped_slowly(self):
        """A two-year cadence going quiet for six months is not news."""
        findings = alerts.derive(snapshot_of(days_since_release=300, pypi_cadence_days=400.0))
        assert not any(f.kind == "drought" for f in findings)

    def test_silent_without_pypi_data(self):
        findings = alerts.derive(snapshot_of(days_since_release=300, pypi_cadence_days=pd.NA))
        assert not any(f.kind == "drought" for f in findings)


class TestDeriveUnreachable:
    def test_fires_after_repeated_failures(self):
        findings = alerts.derive(snapshot_of(), {"gone/repo": 5})
        assert any(f.kind == "unreachable" for f in findings)

    def test_tolerates_a_single_blip(self):
        findings = alerts.derive(snapshot_of(), {"gone/repo": 1})
        assert not any(f.kind == "unreachable" for f in findings)

    def test_marked_high_severity(self):
        finding = next(
            f for f in alerts.derive(snapshot_of(), {"gone/repo": 5}) if f.kind == "unreachable"
        )
        assert finding.severity == "high"


class TestDeriveGeneral:
    def test_one_project_can_raise_several_findings(self):
        findings = alerts.derive(snapshot_of(days_since_push=90, growth_30d_pct=-3.0))
        assert {f.kind for f in findings} == {"stalled", "slump"}

    def test_output_is_stable_across_calls(self):
        """Unstable ordering would churn issues on every run."""
        frame = pd.concat(
            [
                snapshot_of(repo="z/z", days_since_push=90),
                snapshot_of(repo="a/a", days_since_push=90),
            ]
        )
        first = [f.key for f in alerts.derive(frame)]
        second = [f.key for f in alerts.derive(frame)]
        assert first == second == ["stalled:a/a", "stalled:z/z"]

    def test_empty_snapshot_yields_nothing(self):
        assert alerts.derive(pd.DataFrame()) == []

    def test_real_fixture_flags_the_stale_project(self, history):
        findings = alerts.derive(analyze.enrich(history))
        assert any(f.kind == "stalled" and f.repo == "slow/giant" for f in findings)


class TestReconcile:
    def test_new_finding_becomes_a_create(self):
        finding = alerts.Finding("stalled", "a/b", "t", "b")
        plan = alerts.reconcile([finding], [])
        assert plan.create == (finding,)
        assert plan.close == ()

    def test_cleared_finding_becomes_a_close(self):
        plan = alerts.reconcile([], [issue(7, "stalled:a/b")])
        assert plan.close == ((7, "stalled:a/b"),)
        assert plan.create == ()

    def test_ongoing_finding_is_left_alone(self):
        finding = alerts.Finding("stalled", "a/b", "t", "b")
        plan = alerts.reconcile([finding], [issue(7, "stalled:a/b")])
        assert plan.empty

    def test_human_authored_issues_are_never_touched(self):
        """The single most important guarantee in this module."""
        plan = alerts.reconcile([], [issue(1, None, "I found a bug in the parser")])
        assert plan.empty

    def test_mixed_human_and_radar_issues(self):
        plan = alerts.reconcile([], [issue(1, None, "human report"), issue(2, "stalled:a/b")])
        assert plan.close == ((2, "stalled:a/b"),)

    def test_duplicates_keep_the_oldest_and_close_the_rest(self):
        finding = alerts.Finding("stalled", "a/b", "t", "b")
        plan = alerts.reconcile([finding], [issue(9, "stalled:a/b"), issue(3, "stalled:a/b")])
        # Lowest number is treated as the canonical one, so nothing is
        # created; the duplicate is not re-created either.
        assert plan.create == ()

    def test_issue_without_a_number_is_skipped(self):
        plan = alerts.reconcile([], [{"body": alerts.marker("stalled:a/b")}])
        assert plan.empty

    def test_simultaneous_create_and_close(self):
        finding = alerts.Finding("spike", "c/d", "t", "b")
        plan = alerts.reconcile([finding], [issue(4, "stalled:a/b")])
        assert plan.create == (finding,)
        assert plan.close == ((4, "stalled:a/b"),)

    def test_close_order_is_deterministic(self):
        plan = alerts.reconcile([], [issue(9, "spike:z/z"), issue(2, "stalled:a/a")])
        assert [key for _, key in plan.close] == ["stalled:a/a", "spike:z/z"]


class TestCloseComment:
    @pytest.mark.parametrize(
        "key,fragment",
        [
            ("stalled:a/b", "pushed to again"),
            ("spike:a/b", "normal range"),
            ("slump:a/b", "positive again"),
            ("drought:a/b", "new release"),
            ("unreachable:a/b", "reachable again"),
        ],
    )
    def test_explains_why_it_closed(self, key, fragment):
        assert fragment in alerts.close_comment(key)

    def test_unknown_kind_gets_a_generic_reason(self):
        assert "no longer holds" in alerts.close_comment("mystery:a/b")

    def test_mentions_that_it_can_reopen(self):
        assert "recurs" in alerts.close_comment("stalled:a/b")
