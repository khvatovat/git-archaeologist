import re
from typing import Any

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def _is_bot(username: str | None) -> bool:
    return username is not None and username.endswith("[bot]")


def _clean_text(text: str | None) -> str | None:
    if text is None:
        return None
    text = _IMAGE_RE.sub("", text)
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    text = text.strip()
    return text or None


def _clean_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for c in comments:
        if _is_bot(c.get("user")):
            continue
        cleaned.append({**c, "body": _clean_text(c.get("body"))})
    return cleaned


def _clean_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        **pr,
        "body": _clean_text(pr.get("body")),
        "review_comments": _clean_comments(pr.get("review_comments", [])),
        "issue_comments": _clean_comments(pr.get("issue_comments", [])),
    }


def clean(data: dict[str, Any]) -> dict[str, Any]:
    cleaned_commits = []
    for commit in data.get("commits", []):
        cleaned_prs = [_clean_pr(pr) for pr in commit.get("prs", [])]
        cleaned_commits.append({**commit, "prs": cleaned_prs})
    return {**data, "commits": cleaned_commits}
