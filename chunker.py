import json
from typing import Any

TOKEN_BUDGET = 3000
_CHARS_PER_TOKEN = 4


def estimate_tokens(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False)) // _CHARS_PER_TOKEN


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
    return {
        "era_index": era,
        "from_date": min(dates) if dates else None,
        "to_date": max(dates) if dates else None,
        "commits": commits,
    }
