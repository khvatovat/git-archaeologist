import asyncio
import json
from collections.abc import Callable
from typing import Any

import anthropic

from cache import chunk_hash
from exceptions import SummarizationError

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
        except anthropic.RateLimitError as e:
            if attempt == _MAX_RETRIES - 1:
                raise SummarizationError(f"Era {chunk['era_index']} failed: rate limit after {_MAX_RETRIES} attempts") from e
            # Respect retry-after header; fall back to 60s (full TPM window)
            wait = 60.0
            try:
                header = e.response.headers.get("retry-after", "")
                if header:
                    wait = float(header) + 2.0
            except Exception:
                pass
            await asyncio.sleep(wait)
    raise SummarizationError(f"Era {chunk['era_index']} failed after {_MAX_RETRIES} attempts")  # pragma: no cover


_INTER_REQUEST_DELAY = 3.0  # seconds between requests; keeps throughput under 50k tokens/min


async def summarize_all(
    chunks: list[dict[str, Any]],
    on_progress: Callable[[int, int], None] | None = None,
    cached: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    client = anthropic.AsyncAnthropic()
    results: list[dict[str, Any]] = []
    total = len(chunks)
    need_delay = False
    for i, c in enumerate(chunks):
        h = chunk_hash(c)
        if cached and h in cached:
            results.append({**cached[h], "_cached": True})
        else:
            if need_delay:
                await asyncio.sleep(_INTER_REQUEST_DELAY)
            result = await summarize_chunk(client, c)
            results.append({**result, "_cached": False})
            need_delay = True
        if on_progress is not None:
            on_progress(i + 1, total)
    return sorted(results, key=lambda r: r["era_index"])


def cost_estimate(summaries: list[dict[str, Any]]) -> tuple[int, int, float]:
    fresh = [s for s in summaries if not s.get("_cached", False)]
    total_in = sum(s["input_tokens"] for s in fresh)
    total_out = sum(s["output_tokens"] for s in fresh)
    cost = (total_in / 1_000_000) * _INPUT_COST_PER_M + (total_out / 1_000_000) * _OUTPUT_COST_PER_M
    return total_in, total_out, cost
