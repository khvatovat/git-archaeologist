import asyncio
import json
import random
from typing import Any

import anthropic

MODEL = "claude-haiku-4-5-20251001"
_INPUT_COST_PER_M = 0.80
_OUTPUT_COST_PER_M = 4.00

_SYSTEM = (
    "You are a senior developer analyzing git history to understand the evolution of a codebase. "
    "Focus on DECISIONS and INTENT — why changes were made, what tradeoffs were accepted, "
    "what alternatives were rejected. Do not describe code mechanics."
)

_USER_TMPL = """\
Analyze this era of commits ({from_date} to {to_date}).

Identify:
- What problem or goal drove these commits
- What approach was chosen (and why, if visible from PR/review comments)
- Any notable debates, rejected alternatives, or concerns raised in comments

Commits:
{commits_json}

Write 2-4 plain prose sentences. No markdown headers or bullet points. Be specific about decisions, not descriptive about code changes. If there is not enough data to draw conclusions, say so in one sentence."""


_MAX_RETRIES = 6
_RETRY_BASE = 2.0


async def summarize_chunk(
    client: anthropic.AsyncAnthropic,
    chunk: dict[str, Any],
) -> dict[str, Any]:
    prompt = _USER_TMPL.format(
        from_date=chunk.get("from_date", ""),
        to_date=chunk.get("to_date", ""),
        commits_json=json.dumps(chunk["commits"], ensure_ascii=False),
    )
    for attempt in range(_MAX_RETRIES):
        try:
            msg = await client.messages.create(
                model=MODEL,
                max_tokens=256,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return {
                "era_index": chunk["era_index"],
                "from_date": chunk.get("from_date"),
                "to_date": chunk.get("to_date"),
                "summary": msg.content[0].text.strip(),
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            }
        except anthropic.RateLimitError:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _RETRY_BASE ** attempt + random.uniform(0, 1)
            await asyncio.sleep(wait)


_CONCURRENCY = 2


async def summarize_all(
    chunks: list[dict[str, Any]],
    progress=None,
    task_id=None,
) -> list[dict[str, Any]]:
    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _run(chunk: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            result = await summarize_chunk(client, chunk)
        if progress is not None and task_id is not None:
            progress.advance(task_id)
        return result

    results = await asyncio.gather(*[_run(c) for c in chunks])
    return sorted(results, key=lambda r: r["era_index"])


def cost_estimate(summaries: list[dict[str, Any]]) -> tuple[int, int, float]:
    total_in = sum(s["input_tokens"] for s in summaries)
    total_out = sum(s["output_tokens"] for s in summaries)
    cost = (total_in / 1_000_000) * _INPUT_COST_PER_M + (total_out / 1_000_000) * _OUTPUT_COST_PER_M
    return total_in, total_out, cost
