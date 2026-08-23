"""Data acquisition.

The network layer is behind a small `Transport` protocol so that every
other module — and every test — can run without touching the network.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import Project

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
PYPI_API = "https://pypi.org/pypi"

USER_AGENT = "ecosystem-radar/1.0 (+https://github.com)"


class Transport(Protocol):
    """Minimal HTTP GET abstraction."""

    def get_json(self, url: str, headers: dict[str, str]) -> Any: ...


class HttpTransport:
    """urllib-backed transport with retry and polite backoff.

    stdlib only: keeps the CI image small and the cold start fast.
    """

    def __init__(self, retries: int = 3, backoff: float = 2.0, timeout: int = 25):
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout

    def get_json(self, url: str, headers: dict[str, str]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                # 404 is a real answer (repo renamed, package missing) — do not retry.
                if exc.code == 404:
                    raise
                # 403/429 mean rate limiting; honour the reset header when present.
                if exc.code in (403, 429):
                    wait = self._retry_after(exc)
                    log.warning("rate limited on %s, sleeping %.1fs", url, wait)
                    time.sleep(wait)
                    last_error = exc
                    continue
                last_error = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc

            sleep_for = self.backoff * (2**attempt)
            log.warning("retry %d for %s in %.1fs", attempt + 1, url, sleep_for)
            time.sleep(sleep_for)

        assert last_error is not None
        raise last_error

    def _retry_after(self, exc: urllib.error.HTTPError) -> float:
        reset = exc.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return max(1.0, min(90.0, float(reset) - time.time() + 1))
            except ValueError:
                pass
        return 30.0


@dataclass
class FetchResult:
    """Everything collected for one project in one run."""

    repo: str
    github: dict[str, Any] | None = None
    release: dict[str, Any] | None = None
    pypi: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.github is not None


class GitHubSource:
    def __init__(self, transport: Transport, token: str | None = None):
        self.transport = transport
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def repository(self, repo: str) -> dict[str, Any]:
        return self.transport.get_json(f"{GITHUB_API}/repos/{repo}", self._headers())

    def latest_release(self, repo: str) -> dict[str, Any] | None:
        try:
            return self.transport.get_json(
                f"{GITHUB_API}/repos/{repo}/releases/latest", self._headers()
            )
        except urllib.error.HTTPError as exc:
            # Plenty of healthy projects tag but never publish a Release.
            if exc.code == 404:
                return None
            raise


class PyPiSource:
    def __init__(self, transport: Transport):
        self.transport = transport

    def package(self, name: str) -> dict[str, Any] | None:
        try:
            return self.transport.get_json(f"{PYPI_API}/{name}/json", {"User-Agent": USER_AGENT})
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


def collect(
    projects: tuple[Project, ...],
    github: GitHubSource,
    pypi: PyPiSource,
    pause: float = 0.0,
) -> list[FetchResult]:
    """Fetch every project, isolating failures so one bad repo cannot
    take down the whole run."""
    results: list[FetchResult] = []

    for project in projects:
        result = FetchResult(repo=project.repo)

        try:
            result.github = github.repository(project.repo)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, recorded below
            result.errors.append(f"github: {exc}")
            log.error("failed to fetch %s: %s", project.repo, exc)
            results.append(result)
            continue

        try:
            result.release = github.latest_release(project.repo)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"release: {exc}")

        if project.pypi:
            try:
                result.pypi = pypi.package(project.pypi)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"pypi: {exc}")

        results.append(result)
        if pause:
            time.sleep(pause)

    return results
