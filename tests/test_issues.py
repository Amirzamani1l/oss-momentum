"""Issue tracker client — fake transport, never the network."""

import urllib.error

import pytest

from radar.alerts import Finding, Plan, marker
from radar.issues import IssueTracker, apply_plan


class FakeTransport:
    """Records every call and replays canned pages."""

    def __init__(self, pages: list[list[dict]] | None = None, fail_on: str | None = None):
        self.pages = pages or [[]]
        self.fail_on = fail_on
        self.gets: list[str] = []
        self.sends: list[tuple[str, str, dict]] = []

    def get_json(self, url, headers):
        self.gets.append(url)
        index = len(self.gets) - 1
        return self.pages[index] if index < len(self.pages) else []

    def send_json(self, method, url, headers, payload):
        if self.fail_on and self.fail_on in url:
            raise urllib.error.HTTPError(url, 422, "boom", {}, None)
        self.sends.append((method, url, payload))
        return {"number": 123}


def make_issue(number: int, key: str | None = None, is_pr: bool = False) -> dict:
    item = {"number": number, "body": marker(key) if key else "plain", "title": "t"}
    if is_pr:
        item["pull_request"] = {"url": "..."}
    return item


@pytest.fixture
def finding():
    return Finding("stalled", "a/b", "a/b looks stalled", "It has not moved.")


class TestHeaders:
    def test_always_authenticated(self):
        tracker = IssueTracker(FakeTransport(), "o/r", "tok")
        assert tracker._headers()["Authorization"] == "Bearer tok"

    def test_pins_the_api_version(self):
        tracker = IssueTracker(FakeTransport(), "o/r", "tok")
        assert tracker._headers()["X-GitHub-Api-Version"] == "2022-11-28"


class TestListOpen:
    def test_returns_issues(self):
        transport = FakeTransport([[make_issue(1), make_issue(2)]])
        assert len(IssueTracker(transport, "o/r", "t").list_open()) == 2

    def test_filters_out_pull_requests(self):
        """The Issues API returns PRs too; counting them would corrupt
        every reconciliation."""
        transport = FakeTransport([[make_issue(1), make_issue(2, is_pr=True)]])
        issues = IssueTracker(transport, "o/r", "t").list_open()
        assert [i["number"] for i in issues] == [1]

    def test_stops_on_a_short_page(self):
        transport = FakeTransport([[make_issue(1)]])
        IssueTracker(transport, "o/r", "t").list_open()
        assert len(transport.gets) == 1

    def test_follows_pagination(self):
        full = [make_issue(n) for n in range(100)]
        transport = FakeTransport([full, [make_issue(999)]])
        issues = IssueTracker(transport, "o/r", "t").list_open()
        assert len(issues) == 101
        assert len(transport.gets) == 2

    def test_requests_only_open_issues(self):
        transport = FakeTransport()
        IssueTracker(transport, "o/r", "t").list_open()
        assert "state=open" in transport.gets[0]

    def test_empty_repository(self):
        assert IssueTracker(FakeTransport([[]]), "o/r", "t").list_open() == []


class TestMutations:
    def test_create_posts_title_and_body(self, finding):
        transport = FakeTransport()
        IssueTracker(transport, "o/r", "t").create(finding)
        method, url, payload = transport.sends[0]
        assert method == "POST"
        assert url.endswith("/repos/o/r/issues")
        assert payload["title"] == finding.title
        assert "radar:stalled:a/b" in payload["body"]

    def test_close_patches_state(self):
        transport = FakeTransport()
        IssueTracker(transport, "o/r", "t").close(5)
        method, url, payload = transport.sends[0]
        assert method == "PATCH"
        assert url.endswith("/issues/5")
        assert payload == {"state": "closed", "state_reason": "completed"}

    def test_comment_posts_to_the_comments_endpoint(self):
        transport = FakeTransport()
        IssueTracker(transport, "o/r", "t").comment(5, "hello")
        _, url, payload = transport.sends[0]
        assert url.endswith("/issues/5/comments")
        assert payload["body"] == "hello"


class TestApplyPlan:
    def test_creates_and_closes(self, finding):
        transport = FakeTransport()
        tracker = IssueTracker(transport, "o/r", "t")
        counts = apply_plan(tracker, Plan(create=(finding,), close=((4, "spike:c/d"),)))
        assert counts == {"created": 1, "closed": 1, "failed": 0}

    def test_comments_before_closing(self):
        """A bare state flip with no explanation is hostile to readers."""
        transport = FakeTransport()
        tracker = IssueTracker(transport, "o/r", "t")
        apply_plan(tracker, Plan(close=((4, "stalled:a/b"),)))
        methods = [(m, u.split("/repos/o/r/")[1]) for m, u, _ in transport.sends]
        assert methods == [("POST", "issues/4/comments"), ("PATCH", "issues/4")]

    def test_dry_run_changes_nothing(self, finding):
        transport = FakeTransport()
        tracker = IssueTracker(transport, "o/r", "t")
        counts = apply_plan(tracker, Plan(create=(finding,)), dry_run=True)
        assert transport.sends == []
        assert counts["created"] == 1

    def test_one_failure_does_not_abort_the_rest(self):
        """A rejected create must not block the data commit that follows."""
        transport = FakeTransport(fail_on="/issues")
        tracker = IssueTracker(transport, "o/r", "t")
        counts = apply_plan(
            tracker,
            Plan(create=(Finding("stalled", "a/b", "t", "b"), Finding("spike", "c/d", "t", "b"))),
        )
        assert counts["failed"] == 2
        assert counts["created"] == 0

    def test_empty_plan_is_a_no_op(self):
        transport = FakeTransport()
        counts = apply_plan(IssueTracker(transport, "o/r", "t"), Plan())
        assert counts == {"created": 0, "closed": 0, "failed": 0}
        assert transport.sends == []
