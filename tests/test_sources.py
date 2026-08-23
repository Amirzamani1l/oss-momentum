"""Acquisition layer — exercised with a fake transport, never the network."""

import urllib.error

import pytest

from conftest import gh_payload, pypi_payload
from radar.config import Project
from radar.sources import GitHubSource, PyPiSource, collect


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


class FakeTransport:
    """Records calls and replays scripted responses."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, url: str, headers: dict[str, str]):
        self.calls.append(url)
        for fragment, response in self.responses.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response
        raise http_error(404)


class TestGitHubSource:
    def test_sends_auth_header_when_token_present(self):
        transport = FakeTransport({"/repos/": gh_payload()})
        source = GitHubSource(transport, token="secret")
        assert source._headers()["Authorization"] == "Bearer secret"

    def test_omits_auth_header_without_token(self):
        source = GitHubSource(FakeTransport({}), token=None)
        assert "Authorization" not in source._headers()

    def test_pins_the_api_version(self):
        source = GitHubSource(FakeTransport({}))
        assert source._headers()["X-GitHub-Api-Version"] == "2022-11-28"

    def test_missing_release_is_not_an_error(self):
        """Many healthy projects tag but never publish a Release."""
        transport = FakeTransport({"/releases/latest": http_error(404)})
        assert GitHubSource(transport).latest_release("a/b") is None

    def test_other_release_errors_propagate(self):
        transport = FakeTransport({"/releases/latest": http_error(500)})
        with pytest.raises(urllib.error.HTTPError):
            GitHubSource(transport).latest_release("a/b")


class TestPyPiSource:
    def test_returns_payload(self):
        transport = FakeTransport({"/pypi/": pypi_payload()})
        assert PyPiSource(transport).package("polars")["info"]["name"] == "polars"

    def test_unknown_package_returns_none(self):
        transport = FakeTransport({"/pypi/": http_error(404)})
        assert PyPiSource(transport).package("nope") is None


class TestCollect:
    def setup_method(self):
        self.projects = (
            Project("pola-rs/polars", "data-engineering", "polars"),
            Project("postgres/postgres", "database", None),
        )

    def test_happy_path(self):
        transport = FakeTransport(
            {
                "/releases/latest": {"tag_name": "v1", "published_at": "2026-07-01T00:00:00Z"},
                "/repos/": gh_payload(),
                "/pypi/": pypi_payload(),
            }
        )
        results = collect(self.projects, GitHubSource(transport), PyPiSource(transport))
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_skips_pypi_for_projects_without_a_package(self):
        transport = FakeTransport({"/releases/latest": http_error(404), "/repos/": gh_payload()})
        collect(self.projects, GitHubSource(transport), PyPiSource(transport))
        pypi_calls = [c for c in transport.calls if "/pypi/" in c]
        assert len(pypi_calls) == 1  # only polars, not postgres

    def test_one_broken_repo_does_not_abort_the_run(self):
        class Selective(FakeTransport):
            def get_json(self, url, headers):
                if "pola-rs" in url:
                    raise http_error(500)
                return super().get_json(url, headers)

        transport = Selective({"/releases/latest": http_error(404), "/repos/": gh_payload()})
        results = collect(self.projects, GitHubSource(transport), PyPiSource(transport))
        assert results[0].ok is False
        assert results[0].errors
        assert results[1].ok is True

    def test_release_failure_is_recorded_but_not_fatal(self):
        transport = FakeTransport({"/releases/latest": http_error(503), "/repos/": gh_payload()})
        results = collect(self.projects[:1], GitHubSource(transport), PyPiSource(transport))
        assert results[0].ok is True
        assert any("release" in e for e in results[0].errors)
