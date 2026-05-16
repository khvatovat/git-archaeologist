import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
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
        table.add_row(
            str(c["era_index"]),
            (c["from_date"] or "")[:10],
            (c["to_date"] or "")[:10],
            str(len(c["commits"])),
            str(estimate_tokens(c["commits"])),
        )

    stdout.print(table)
    stderr.print(f"[green]{len(chunks)} chunks, {result['commit_count']} commits, {result['pr_count']} PRs[/green]")


if __name__ == "__main__":
    main()
