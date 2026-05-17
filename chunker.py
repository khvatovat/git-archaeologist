import json
from typing import Any

TOKEN_BUDGET = 3000
TOKEN_HARD_LIMIT = 6000
_CHARS_PER_TOKEN = 4
_TRUNCATE_LEN = 500
_TRUNCATE_SUFFIX = "[truncated]"


def estimate_tokens(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False)) // _CHARS_PER_TOKEN


def _trunc(text: str | None) -> str | None:
    if text is None or len(text) <= _TRUNCATE_LEN:
        return text
    return text[:_TRUNCATE_LEN] + _TRUNCATE_SUFFIX


def _trunc_comments(commits: list[dict], field: str) -> list[dict]:
    result = []
    for commit in commits:
        new_prs = []
        for pr in commit.get("prs", []):
            comments = [{**c, "body": _trunc(c.get("body"))} for c in pr.get(field, [])]
            new_prs.append({**pr, field: comments})
        result.append({**commit, "prs": new_prs})
    return result


def _trunc_pr_bodies(commits: list[dict]) -> list[dict]:
    result = []
    for commit in commits:
        new_prs = [{**pr, "body": _trunc(pr.get("body"))} for pr in commit.get("prs", [])]
        result.append({**commit, "prs": new_prs})
    return result


def _truncate_to_fit(commits: list[dict]) -> list[dict]:
    passes = [
        lambda c: _trunc_comments(c, "issue_comments"),
        lambda c: _trunc_comments(c, "review_comments"),
        _trunc_pr_bodies,
    ]
    for trunc_fn in passes:
        if estimate_tokens(commits) <= TOKEN_HARD_LIMIT:
            break
        commits = trunc_fn(commits)
    return commits


def chunk(data: dict[str, Any], token_budget: int = TOKEN_BUDGET) -> list[dict[str, Any]]:
    commits = sorted(data.get("commits", []), key=lambda c: c.get("date") or "")

    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    era = 0

    for commit in commits:
        cost = estimate_tokens(commit)
        if current and current_tokens + cost > token_budget:
            chunks.append(_make_chunk(era, current))
            era += 1
            current = []
            current_tokens = 0
        current.append(commit)
        current_tokens += cost

    if current:
        chunks.append(_make_chunk(era, current))

    return chunks


def _make_chunk(era: int, commits: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [c["date"] for c in commits if c.get("date")]
    raw_tokens = estimate_tokens(commits)

    if raw_tokens > TOKEN_HARD_LIMIT:
        commits = _truncate_to_fit(commits)

    truncated_tokens = estimate_tokens(commits)

    return {
        "era_index": era,
        "from_date": min(dates) if dates else None,
        "to_date": max(dates) if dates else None,
        "commits": commits,
        "raw_tokens": raw_tokens,
        "truncated_tokens": truncated_tokens,
    }
