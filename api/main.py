import hashlib
import hmac
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    region = os.environ.get("AWS_REGION", "us-east-1")
    dynamo = boto3.resource("dynamodb", region_name=region)
    app.state.repos_table = dynamo.Table(os.environ["REPOS_TABLE"])
    app.state.jobs_table = dynamo.Table(os.environ["JOBS_TABLE"])
    app.state.sqs = boto3.client("sqs", region_name=region)
    app.state.queue_url = os.environ["SQS_QUEUE_URL"]
    yield


app = FastAPI(title="git-archaeologist", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegisterRepoRequest(BaseModel):
    name: str
    path: str = "README.md"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/repos", status_code=201)
def register_repo(body: RegisterRepoRequest, request: Request) -> dict[str, Any]:
    repos_table = request.app.state.repos_table
    repo_id = str(uuid.uuid4())
    webhook_secret = uuid.uuid4().hex + uuid.uuid4().hex
    item: dict[str, Any] = {
        "repo_id": repo_id,
        "name": body.name,
        "path": body.path,
        "webhook_secret": webhook_secret,
        "created_at": _now(),
    }
    repos_table.put_item(Item=item)
    return item


@app.get("/repos")
def list_repos(request: Request) -> dict[str, Any]:
    repos_table = request.app.state.repos_table
    result = repos_table.scan()
    items = sorted(result.get("Items", []), key=lambda r: r.get("created_at", ""))
    return {"repos": items}


@app.post("/webhook", status_code=202)
async def receive_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")

    repo_name: str = payload.get("repository", {}).get("full_name", "")
    if not repo_name:
        raise HTTPException(400, "missing repository.full_name in payload")

    repos_table = request.app.state.repos_table
    result = repos_table.scan(FilterExpression=Attr("name").eq(repo_name))
    items = result.get("Items", [])
    if not items:
        raise HTTPException(404, f"repo '{repo_name}' not registered")
    repo = items[0]

    sig_header = request.headers.get("X-Hub-Signature-256", "")
    expected_sig = "sha256=" + hmac.new(
        repo["webhook_secret"].encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_header, expected_sig):
        raise HTTPException(401, "invalid webhook signature")

    commit_sha: str = payload.get("after", "")
    if not commit_sha or commit_sha == "0000000000000000000000000000000000000000":
        return {"status": "skipped", "reason": "no commits in push"}

    ref: str = payload.get("ref", "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None

    jobs_table = request.app.state.jobs_table
    sqs = request.app.state.sqs
    queue_url = request.app.state.queue_url

    job_id = str(uuid.uuid4())
    now = _now()
    file_path: str = repo.get("path", "README.md")

    jobs_table.put_item(Item={
        "job_id": job_id,
        "repo_id": repo["repo_id"],
        "repo_name": repo_name,
        "file_path": file_path,
        "commit_sha": commit_sha,
        "branch": branch,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    })

    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            "job_id": job_id,
            "repo_id": repo["repo_id"],
            "repo_name": repo_name,
            "file_path": file_path,
            "commit_sha": commit_sha,
            "branch": branch,
        }),
    )

    return {"job_id": job_id, "status": "queued"}


@app.get("/repos/{repo_id}/history")
def get_repo_history(repo_id: str, request: Request) -> dict[str, Any]:
    jobs_table = request.app.state.jobs_table
    result = jobs_table.query(
        IndexName="repo_id-created_at-index",
        KeyConditionExpression=Key("repo_id").eq(repo_id),
        ScanIndexForward=False,
        Limit=20,
    )
    return {"jobs": result.get("Items", [])}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    jobs_table = request.app.state.jobs_table
    result = jobs_table.get_item(Key={"job_id": job_id})
    if "Item" not in result:
        raise HTTPException(404, "job not found")
    return result["Item"]
