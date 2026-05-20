import asyncio
import re
import time
from types import TracebackType
from typing import Any

import httpx
from rich.console import Console

from exceptions import FetchError

GITHUB_API = "https://api.github.com"


def _auth_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        if 'rel="next"' in part:
            m = re.search(r"<([^>]+)>", part)
            if m:
                return m.group(1)
    return None


def _extract_issue_refs(text: str | None) -> set[int]:
    if not text:
        return set()
    return {int(n) for n in re.findall(r"#(\d+)", text)}


def _shape_comment(c: dict[str, Any]) -> dict[str, Any]:
    user = c.get("user")
    return {
        "id": c["id"],
        "user": user["login"] if user else None,
        "body": c["body"],
        "created_at": c["created_at"],
    }


_MAX_CONCURRENCY = 10
_MAX_WAIT_SECONDS = 90


def _raise_first_error(results: list) -> None:
    for r in results:
        if isinstance(r, BaseException):
            raise r


class GitHubFetcher:
    def __init__(self, token: str | None, console: Console) -> None:
        self._headers = _auth_headers(token)
        self._console = console
        self._client: httpx.AsyncClient
        self._sem: asyncio.Semaphore

    async def __aenter__(self) -> "GitHubFetcher":
        self._client = httpx.AsyncClient(headers=self._headers, timeout=30)
        self._sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def _get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        async with self._sem:
            for attempt in range(6):
                resp = await self._client.get(url, params=params)
                if resp.status_code in (200, 404):
                    return resp
                if resp.status_code in (403, 429):
                    reset = resp.headers.get("X-RateLimit-Reset")
                    wait = max(1, int(reset) - int(time.time()) + 1) if reset else 2**attempt
                    if wait > _MAX_WAIT_SECONDS:
                        reset_at = time.strftime("%H:%M:%S", time.localtime(int(reset))) if reset else "unknown"
                        hint = "" if self._headers.get("Authorization") else " Set GITHUB_TOKEN to raise the limit."
                        raise FetchError(
                            f"GitHub rate limit exceeded — resets at {reset_at} ({wait}s).{hint}"
                        )
                    self._console.log(f"[yellow]rate limited, waiting {wait}s[/yellow]")
                    await asyncio.sleep(wait)
                else:
                    wait = 2**attempt
                    self._console.log(
                        f"[yellow]HTTP {resp.status_code}, retrying in {wait}s[/yellow]"
                    )
                    await asyncio.sleep(wait)
        raise FetchError(
            f"GitHub API request failed after 6 attempts: {url} (last status: {resp.status_code})"
        )

    async def _paginate(
        self, url: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while url:
            resp = await self._get(url, params)
            if resp.status_code != 200:
                break
            items.extend(resp.json())
            params = None
            url = _parse_next_link(resp.headers.get("Link", ""))
        return items

    async def _default_branch(self, repo: str) -> str:
        resp = await self._get(f"{GITHUB_API}/repos/{repo}")
        if resp.status_code == 200:
            return resp.json().get("default_branch", "main")
        return "main"

    async def _fetch_pr(self, repo: str, number: int) -> dict[str, Any] | None:
        base = f"{GITHUB_API}/repos/{repo}"
        pr_resp, review_comments, issue_comments = await asyncio.gather(
            self._get(f"{base}/pulls/{number}"),
            self._paginate(f"{base}/pulls/{number}/comments"),
            self._paginate(f"{base}/issues/{number}/comments"),
        )
        if pr_resp.status_code != 200:
            return None
        pr = pr_resp.json()

        issue_refs = _extract_issue_refs(pr.get("body"))
        linked_issues: list[dict[str, Any]] = []
        if issue_refs:
            issue_resps = await asyncio.gather(
                *(self._get(f"{base}/issues/{n}") for n in sorted(issue_refs))
            )
            for r in issue_resps:
                if r.status_code == 200:
                    d = r.json()
                    if "pull_request" not in d:
                        linked_issues.append(
                            {
                                "number": d["number"],
                                "title": d["title"],
                                "body": d.get("body"),
                                "state": d["state"],
                            }
                        )

        return {
            "number": number,
            "title": pr["title"],
            "body": pr.get("body"),
            "state": pr["state"],
            "merged_at": pr.get("merged_at"),
            "review_comments": [_shape_comment(c) for c in review_comments],
            "issue_comments": [_shape_comment(c) for c in issue_comments],
            "linked_issues": linked_issues,
        }

    async def fetch_history(
        self, repo: str, path: str, branch: str | None
    ) -> dict[str, Any]:
        if not branch:
            branch = await self._default_branch(repo)

        self._console.log(f"fetching commits: {repo} / {path} ({branch})")
        raw_commits = await self._paginate(
            f"{GITHUB_API}/repos/{repo}/commits",
            {"path": path, "sha": branch, "per_page": 100},
        )
        self._console.log(f"{len(raw_commits)} commits")

        self._console.log("resolving commit -> PR associations")
        assoc_resps = await asyncio.gather(
            *(
                self._get(f"{GITHUB_API}/repos/{repo}/commits/{c['sha']}/pulls")
                for c in raw_commits
            ),
            return_exceptions=True,
        )
        _raise_first_error(assoc_resps)

        pr_numbers: set[int] = set()
        commits: list[dict[str, Any]] = []
        for commit, assoc in zip(raw_commits, assoc_resps):
            msg = commit["commit"]["message"]
            author = commit["commit"]["author"]
            nums: set[int] = set()
            if isinstance(assoc, BaseException):
                self._console.log(f"[yellow]commits/{commit['sha'][:7]}/pulls — association lookup failed[/yellow]")
            elif assoc.status_code == 200:
                for pr in assoc.json():
                    nums.add(pr["number"])
            else:
                self._console.log(f"[red]commits/{commit['sha'][:7]}/pulls → {assoc.status_code}[/red]")
            # squash-merged PRs aren't linked via the API; parse the commit message
            nums |= {int(m) for m in re.findall(r"\(#(\d+)\)", msg)}
            pr_numbers |= nums
            commits.append(
                {
                    "sha": commit["sha"],
                    "message": msg,
                    "author": author.get("name"),
                    "date": author.get("date"),
                    "pr_numbers": sorted(nums),
                }
            )

        self._console.log(f"{len(pr_numbers)} unique PRs")

        prs_by_number: dict[int, dict[str, Any]] = {}
        if pr_numbers:
            self._console.log(
                f"fetching {len(pr_numbers)} PRs with comments and linked issues"
            )
            pr_results = await asyncio.gather(
                *(self._fetch_pr(repo, n) for n in sorted(pr_numbers)),
                return_exceptions=True,
            )
            _raise_first_error(pr_results)
            for pr in pr_results:
                if pr and not isinstance(pr, BaseException):
                    prs_by_number[pr["number"]] = pr

        for c in commits:
            c["prs"] = [prs_by_number[n] for n in c["pr_numbers"] if n in prs_by_number]

        return {
            "repo": repo,
            "path": path,
            "branch": branch,
            "commit_count": len(commits),
            "pr_count": len(prs_by_number),
            "commits": commits,
        }
