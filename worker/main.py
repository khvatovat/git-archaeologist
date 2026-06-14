import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import boto3

# In the container, archaeologist modules are copied alongside this file.
# In local dev, add the repo root to the path.
_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, os.path.abspath(_root))

from chunker import chunk
from cleaner import clean
from exceptions import ArchaeologistError
from fetcher import GitHubFetcher
from summarizer import summarize_all
from synthesizer import synthesize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
JOBS_TABLE = os.environ["JOBS_TABLE"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]

sqs = boto3.client("sqs", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
jobs_table = dynamodb.Table(JOBS_TABLE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_job(job_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    set_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    expr_names = {f"#{k}": k for k in fields}
    expr_values = {f":{k}": v for k, v in fields.items()}
    jobs_table.update_item(
        Key={"job_id": job_id},
        UpdateExpression=set_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


async def _run_analysis(repo_name: str, file_path: str, branch: str | None, github_token: str | None) -> str:
    from rich.console import Console
    console = Console(stderr=True, quiet=True)

    async with GitHubFetcher(github_token, console) as fetcher:
        fetch_result = await fetcher.fetch_history(repo_name, file_path, branch)

    cleaned = clean(fetch_result)
    chunks = chunk(cleaned)
    summaries = await summarize_all(chunks, cached={})

    repo_meta: dict[str, Any] = {
        "repo": repo_name,
        "path": file_path,
        "branch": fetch_result["branch"],
        "commit_count": fetch_result["commit_count"],
        "pr_count": fetch_result["pr_count"],
    }
    synth_result = await synthesize(summaries, repo_meta)
    return synth_result["markdown"]


def _process_message(msg: dict[str, Any], github_token: str | None) -> None:
    job: dict[str, Any] = json.loads(msg["Body"])
    job_id: str = job["job_id"]
    receipt: str = msg["ReceiptHandle"]

    log.info("processing job %s — %s / %s", job_id, job["repo_name"], job.get("file_path"))
    _update_job(job_id, status="running")

    try:
        markdown = asyncio.run(_run_analysis(
            repo_name=job["repo_name"],
            file_path=job.get("file_path", "README.md"),
            branch=job.get("branch"),
            github_token=github_token,
        ))
        _update_job(job_id, status="done", result=markdown)
        log.info("job %s done", job_id)
    except ArchaeologistError as e:
        log.error("job %s failed (archaeologist error): %s", job_id, e)
        _update_job(job_id, status="failed", error=str(e))
    except Exception as e:
        log.exception("job %s unexpected error", job_id)
        _update_job(job_id, status="failed", error=str(e))
    finally:
        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt)


def main() -> None:
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        log.warning("GITHUB_TOKEN not set — GitHub API rate limits will apply")

    log.info("worker started, polling %s", SQS_QUEUE_URL)

    while True:
        response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=900,
        )
        for msg in response.get("Messages", []):
            _process_message(msg, github_token)


if __name__ == "__main__":
    main()
