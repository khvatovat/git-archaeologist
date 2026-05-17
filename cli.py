import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from chunker import chunk, estimate_tokens
from cleaner import clean
from fetcher import GitHubFetcher


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch commit and PR history for a path in a GitHub repo."
    )
    parser.add_argument("--repo", required=True, metavar="OWNER/REPO")
    parser.add_argument("--path", required=True, metavar="PATH")
    parser.add_argument("--branch", default=None, metavar="BRANCH")
    parser.add_argument("--raw", action="store_true", help="print raw JSON, skip clean+chunk")
    parser.add_argument("--summarize", action="store_true", help="summarize each era with Haiku")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    stderr = Console(stderr=True)
    stdout = Console()

    if not token:
        stderr.print(
            "[yellow]GITHUB_TOKEN not set — unauthenticated requests are rate-limited to 60/hr[/yellow]"
        )

    async def run() -> dict:
        async with GitHubFetcher(token, stderr) as fetcher:
            return await fetcher.fetch_history(args.repo, args.path, args.branch)

    try:
        result = asyncio.run(run())
    except KeyboardInterrupt:
        stderr.print("interrupted")
        sys.exit(1)
    except RuntimeError as e:
        stderr.print(f"[red]error:[/red] {e}")
        sys.exit(1)

    if args.raw:
        stdout.print_json(json.dumps(result))
        return

    cleaned = clean(result)
    chunks = chunk(cleaned)

    table = Table(title=f"[bold]{args.repo}[/bold] / {args.path}", show_lines=True)
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

    stdout.print(table)
    stderr.print(f"[green]{len(chunks)} chunks, {result['commit_count']} commits, {result['pr_count']} PRs[/green]")

    if not args.summarize:
        return

    from summarizer import cost_estimate, summarize_all

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=stderr,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Summarizing eras...", total=len(chunks))
        try:
            summaries = asyncio.run(summarize_all(chunks, progress, task_id))
        except KeyboardInterrupt:
            stderr.print("interrupted")
            sys.exit(1)

    for s in summaries:
        from_date = (s.get("from_date") or "")[:10]
        to_date = (s.get("to_date") or "")[:10]
        stdout.rule(f"[cyan]Era {s['era_index']}[/cyan]  [green]{from_date} → {to_date}[/green]")
        stdout.print(s["summary"])
        stdout.print()

    total_in, total_out, cost = cost_estimate(summaries)
    stderr.print(
        f"[dim]{total_in:,} input tokens / {total_out:,} output tokens — "
        f"est. cost: [bold]${cost:.4f}[/bold][/dim]"
    )


if __name__ == "__main__":
    main()
