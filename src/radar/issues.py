"""GitHub Issues client.

Thin wrapper over the REST API. All decision-making lives in
`alerts.reconcile`; this module only carries out the plan it is handed.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from .alerts import Finding, Plan, close_comment
from .sources import GITHUB_API, USER_AGENT, MutatingTransport

log = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_PAGES = 10


class IssueTracker:
    def __init__(self, transport: MutatingTransport, repo: str, token: str):
        self.transport = transport
        self.repo = repo
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {self.token}",
        }

    def list_open(self) -> list[dict[str, Any]]:
        """Every open issue, pull requests excluded.

        The Issues API returns PRs alongside issues; anything carrying a
        `pull_request` key is filtered out here.
        """
        issues: list[dict[str, Any]] = []

        for page in range(1, MAX_PAGES + 1):
            query = urllib.parse.urlencode({"state": "open", "per_page": PAGE_SIZE, "page": page})
            batch = self.transport.get_json(
                f"{GITHUB_API}/repos/{self.repo}/issues?{query}", self._headers()
            )
            if not batch:
                break
            issues.extend(item for item in batch if "pull_request" not in item)
            if len(batch) < PAGE_SIZE:
                break

        return issues

    def create(self, finding: Finding) -> dict[str, Any]:
        return self.transport.send_json(
            "POST",
            f"{GITHUB_API}/repos/{self.repo}/issues",
            self._headers(),
            {"title": finding.title, "body": finding.issue_body()},
        )

    def comment(self, number: int, text: str) -> dict[str, Any]:
        return self.transport.send_json(
            "POST",
            f"{GITHUB_API}/repos/{self.repo}/issues/{number}/comments",
            self._headers(),
            {"body": text},
        )

    def close(self, number: int) -> dict[str, Any]:
        return self.transport.send_json(
            "PATCH",
            f"{GITHUB_API}/repos/{self.repo}/issues/{number}",
            self._headers(),
            {"state": "closed", "state_reason": "completed"},
        )


def apply_plan(tracker: IssueTracker, plan: Plan, dry_run: bool = False) -> dict[str, int]:
    """Execute a plan, tolerating individual failures.

    One issue that cannot be created must not prevent the rest of the
    plan — or the data commit that follows — from going through.
    """
    counts = {"created": 0, "closed": 0, "failed": 0}

    for finding in plan.create:
        if dry_run:
            log.info("would open: %s", finding.title)
            counts["created"] += 1
            continue
        try:
            issue = tracker.create(finding)
            log.info("opened #%s: %s", issue.get("number"), finding.title)
            counts["created"] += 1
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            log.error("could not open issue for %s: %s", finding.key, exc)
            counts["failed"] += 1

    for number, key in plan.close:
        if dry_run:
            log.info("would close #%s (%s)", number, key)
            counts["closed"] += 1
            continue
        try:
            tracker.comment(number, close_comment(key))
            tracker.close(number)
            log.info("closed #%s (%s)", number, key)
            counts["closed"] += 1
        except Exception as exc:  # noqa: BLE001
            log.error("could not close #%s: %s", number, exc)
            counts["failed"] += 1

    return counts
