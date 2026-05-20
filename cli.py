import argparse
import asyncio
import os
import re
import sys
import time

from dotenv import load_dotenv
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import cache
from chunker import chunk, estimate_tokens
from cleaner import clean
from exceptions import ArchaeologistError
from fetcher import GitHubFetcher
from renderer import parse_sections, render
from summarizer import cost_estimate as era_cost, summarize_all
from synthesizer import cost_estimate as synth_cost, synthesize

console = Console()


# ── Phase tracker ───────────────────────────────────────────────────────────

class PhaseTracker:
    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self._phases: list[dict] = []
        self._frame = 0

    def add(self, label: str) -> int:
        idx = len(self._phases)
        self._phases.append({"label": label, "state": "pending", "detail": "", "start": 0.0, "elapsed": 0.0})
        return idx

    def start(self, idx: int, detail: str = "") -> None:
        p = self._phases[idx]
        p["state"] = "running"
        p["detail"] = detail
        p["start"] = time.monotonic()

    def update(self, idx: int, detail: str) -> None:
        self._phases[idx]["detail"] = detail

    def done(self, idx: int, detail: str) -> None:
        p = self._phases[idx]
        p["state"] = "done"
        p["detail"] = detail
        p["elapsed"] = time.monotonic() - p["start"] if p["start"] else 0.0

    def __rich__(self) -> Table:
        self._frame += 1
        spin = self._SPINNER[self._frame % len(self._SPINNER)]

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold", min_width=20)
        table.add_column(min_width=54)
        table.add_column(style="dim", justify="right", min_width=5)

        for p in self._phases:
            if p["state"] == "pending":
                detail = Text("waiting...", style="dim")
                elapsed = Text("")
            elif p["state"] == "running":
                detail = Text(f"{spin}  {p['detail']}", style="yellow")
                elapsed = Text("")
            else:
                detail = Text(f"✓  {p['detail']}", style="green")
                elapsed = Text(f"{p['elapsed']:.1f}s")
            table.add_row(p["label"], detail, elapsed)

        return table


# ── Helpers ─────────────────────────────────────────────────────────────────

def _validate_repo(repo: str) -> None:
    if not re.match(r"^[^/\s]+/[^/\s]+$", repo):
        console.print(f"[red]error:[/red] --repo must be OWNER/REPO (e.g. fastify/fastify), got: {repo!r}")
        sys.exit(1)


def _print_chunk_table(chunks: list[dict], repo: str, path: str) -> None:
    table = Table(title=f"[bold]{repo}[/bold] / {path}", show_lines=True)
    table.add_column("Era", style="cyan", justify="right")
    table.add_column("From", style="green")
    table.add_column("To", style="green")
    table.add_column("Commits", justify="right")
    table.add_column("~Tokens", justify="right", style="yellow")
    for c in chunks:
        raw = c.get("raw_tokens", estimate_tokens(c["commits"]))
        trunc = c.get("truncated_tokens", raw)
        token_str = str(trunc) if trunc == raw else f"{trunc} [dim](was {raw})[/dim]"
        table.add_row(
            str(c["era_index"]),
            (c["from_date"] or "")[:10],
            (c["to_date"] or "")[:10],
            str(len(c["commits"])),
            token_str,
        )
    console.print(table)


# ── Pipeline ─────────────────────────────────────────────────────────────────

async def _run_pipeline(
    args: argparse.Namespace,
    token: str | None,
    tracker: PhaseTracker,
    ph_fetch: int,
    ph_analyze: int,
    ph_synth: int,
) -> tuple[list[dict], list[dict], dict]:
    fetch_cache_file = cache.fetch_cache_path(args.repo, args.path)
    summaries_cache_file = cache.summaries_cache_path(args.repo, args.path)

    cached_fetch = None if args.no_cache else cache.load(fetch_cache_file)
    cached_summaries: dict = {} if args.no_cache else (cache.load(summaries_cache_file) or {})

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    if cached_fetch is not None:
        tracker.start(ph_fetch, "loading from cache...")
        result = cached_fetch
        cleaned = clean(result)
        chunks = chunk(cleaned)
        tracker.done(
            ph_fetch,
            f"{result['commit_count']} commits · {result['pr_count']} PRs · {len(chunks)} eras  [dim](cached)[/dim]",
        )
    else:
        tracker.start(ph_fetch, f"fetching {args.repo} / {args.path}...")
        fetcher_console = Console(stderr=True, quiet=not args.verbose)
        async with GitHubFetcher(token, fetcher_console) as fetcher:
            result = await fetcher.fetch_history(args.repo, args.path, args.branch)
        cache.save(fetch_cache_file, result)
        cleaned = clean(result)
        chunks = chunk(cleaned)
        tracker.done(
            ph_fetch,
            f"{result['commit_count']} commits · {result['pr_count']} PRs · {len(chunks)} eras",
        )

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    total_eras = len(chunks)
    cached_count = sum(1 for c in chunks if cache.chunk_hash(c) in cached_summaries)
    tracker.start(ph_analyze, f"0/{total_eras} eras")

    def on_progress(done: int, total: int) -> None:
        tracker.update(ph_analyze, f"{done}/{total} eras ({done * 100 // total}%)")

    summaries = await summarize_all(chunks, on_progress=on_progress, cached=cached_summaries)

    # Persist summaries cache (merge with existing; strip internal _cached flag)
    chunks_by_era = {c["era_index"]: c for c in chunks}
    updated_summaries_cache = dict(cached_summaries)
    for s in summaries:
        h = cache.chunk_hash(chunks_by_era[s["era_index"]])
        updated_summaries_cache[h] = {k: v for k, v in s.items() if k != "_cached"}
    cache.save(summaries_cache_file, updated_summaries_cache)

    _, _, haiku_cost = era_cost(summaries)
    cache_note = f" · {cached_count} cached" if cached_count else ""
    tracker.done(ph_analyze, f"{len(summaries)} eras analyzed{cache_note} · est. ${haiku_cost:.4f}")

    # ── Phase 3 ──────────────────────────────────────────────────────────────
    repo_meta = {
        "repo": args.repo,
        "path": args.path,
        "branch": result["branch"],
        "commit_count": result["commit_count"],
        "pr_count": result["pr_count"],
    }

    tracker.start(ph_synth, "synthesizing narrative...")
    synth_result = await synthesize(summaries, repo_meta)
    tracker.done(ph_synth, "Report ready")

    return chunks, summaries, synth_result


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Produce a narrative history of a file's evolution from its GitHub commit and PR history."
    )
    parser.add_argument("--repo", required=True, metavar="OWNER/REPO")
    parser.add_argument("--path", required=True, metavar="PATH")
    parser.add_argument("--branch", default=None, metavar="BRANCH")
    parser.add_argument("--no-cache", action="store_true", help="bypass all cached data")
    parser.add_argument("--output", default=None, metavar="PATH", help="custom output path for the report")
    parser.add_argument("--verbose", action="store_true", help="show chunk table and era summaries")
    args = parser.parse_args()

    _validate_repo(args.repo)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        console.print(
            "[yellow]warning:[/yellow] GITHUB_TOKEN not set — unauthenticated requests are "
            "rate-limited to 60/hr. Add it to .env or run: export GITHUB_TOKEN=ghp_..."
        )

    tracker = PhaseTracker()
    ph_fetch = tracker.add("[1/3] Fetching    ")
    ph_analyze = tracker.add("[2/3] Analyzing   ")
    ph_synth = tracker.add("[3/3] Synthesizing")

    with Live(tracker, refresh_per_second=8, console=console):
        try:
            chunks, summaries, synth_result = asyncio.run(
                _run_pipeline(args, token, tracker, ph_fetch, ph_analyze, ph_synth)
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")
            sys.exit(1)
        except ArchaeologistError as e:
            console.print(f"[red]error:[/red] {e}")
            sys.exit(1)

    # Live exits — 3 summary lines committed to terminal
    console.print()

    if args.verbose:
        _print_chunk_table(chunks, args.repo, args.path)
        for s in summaries:
            from_date = (s.get("from_date") or "")[:10]
            to_date = (s.get("to_date") or "")[:10]
            console.rule(f"[cyan]Era {s['era_index']}[/cyan]  [green]{from_date} → {to_date}[/green]")
            console.print(s["summary"])
            console.print()

    # ── Report panels ─────────────────────────────────────────────────────────
    for title, content in parse_sections(synth_result["markdown"]):
        console.print(Panel(Markdown(content), title=f"[bold cyan]{title}[/bold cyan]", expand=True))

    output_path = render(synth_result["markdown"], args.repo, args.path, args.output)

    _, _, haiku_cost = era_cost(summaries)
    _, _, sonnet_cost = synth_cost(synth_result)
    console.print(
        f"[dim]report saved → {output_path} · total cost [bold]${haiku_cost + sonnet_cost:.4f}[/bold][/dim]"
    )


if __name__ == "__main__":
    main()
