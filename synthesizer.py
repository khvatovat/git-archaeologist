import asyncio
from typing import Any

import anthropic

from exceptions import SynthesisError

MODEL = "claude-sonnet-4-6"
_INPUT_COST_PER_M = 3.00
_OUTPUT_COST_PER_M = 15.00

_SYSTEM = (
    "You are a technical historian synthesizing a file's git evolution into a clear, "
    "readable narrative. Write for a senior engineer who wants to understand WHY this "
    "file exists, how it changed, and what forces shaped it — not a changelog of what changed."
)

_USER_TMPL = """\
Repository: {repo}
File: {path}
Branch: {branch}
Total commits: {commit_count}
Total PRs: {pr_count}
Date range: {date_from} to {date_to}

Era summaries (chronological):
{era_summaries}

Produce a structured narrative history in clean markdown with exactly these four sections. \
Be ruthlessly concise. Omit anything that is not essential. Prefer one precise sentence over three vague ones.

## Overview
3 sentences maximum. What this file does and its role in the project, inferred from the history. \
Do not describe current code — describe purpose and place in the system.

## Timeline
Narrative prose, not bullet points. Group related eras into thematic paragraphs — do not write \
one paragraph per era. Maximum 5 paragraphs, 2-3 sentences each. Include approximate dates.

## Key Decisions
Bullet list. Maximum 6 items, one sentence each. Format: decision made + outcome or consequence. \
No elaboration.

## Recurring Themes
Bullet list. Maximum 4 items, one sentence each. Patterns that recurred across the history.

Write only the markdown. No preamble, no meta-commentary."""


_MAX_RETRIES = 3


def _format_era_summaries(summaries: list[dict[str, Any]]) -> str:
    lines = []
    for s in summaries:
        from_date = (s.get("from_date") or "")[:10]
        to_date = (s.get("to_date") or "")[:10]
        lines.append(f"Era {s['era_index']} ({from_date} → {to_date}):")
        lines.append(s["summary"])
        lines.append("")
    return "\n".join(lines).strip()


async def synthesize(summaries: list[dict[str, Any]], repo_meta: dict[str, Any]) -> dict[str, Any]:
    repo = repo_meta["repo"]
    commits = repo_meta.get("commit_count", 0)
    prs = repo_meta.get("pr_count", 0)
    path = repo_meta.get("path", "")
    branch = repo_meta.get("branch", "")

    dates = [s.get("from_date") or "" for s in summaries] + [s.get("to_date") or "" for s in summaries]
    dates = [d[:10] for d in dates if d]
    date_from = min(dates) if dates else "unknown"
    date_to = max(dates) if dates else "unknown"

    prompt = _USER_TMPL.format(
        repo=repo,
        path=path,
        branch=branch,
        commit_count=commits,
        pr_count=prs,
        date_from=date_from,
        date_to=date_to,
        era_summaries=_format_era_summaries(summaries),
    )

    client = anthropic.AsyncAnthropic()
    for attempt in range(_MAX_RETRIES):
        try:
            msg = await client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return {
                "markdown": msg.content[0].text.strip(),
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            }
        except anthropic.RateLimitError as e:
            if attempt == _MAX_RETRIES - 1:
                raise SynthesisError(f"Synthesis failed: rate limit after {_MAX_RETRIES} attempts") from e
            wait = 60.0
            try:
                header = e.response.headers.get("retry-after", "")
                if header:
                    wait = float(header) + 2.0
            except Exception:
                pass
            await asyncio.sleep(wait)
    raise SynthesisError(f"Synthesis failed after {_MAX_RETRIES} attempts")  # pragma: no cover


def cost_estimate(result: dict[str, Any]) -> tuple[int, int, float]:
    total_in = result["input_tokens"]
    total_out = result["output_tokens"]
    cost = (total_in / 1_000_000) * _INPUT_COST_PER_M + (total_out / 1_000_000) * _OUTPUT_COST_PER_M
    return total_in, total_out, cost
