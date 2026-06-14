import hashlib
import hmac
import json
import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ["REPOS_TABLE"] = "test-repos"
os.environ["JOBS_TABLE"] = "test-jobs"
os.environ["SQS_QUEUE_URL"] = "placeholder"
os.environ["AWS_REGION"] = "us-east-1"


@pytest.fixture()
def aws_resources():
    with mock_aws():
        dynamo = boto3.resource("dynamodb", region_name="us-east-1")
        dynamo.create_table(
            TableName="test-repos",
            KeySchema=[{"AttributeName": "repo_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "repo_id", "AttributeType": "S"},
                {"AttributeName": "name", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[{
                "IndexName": "name-index",
                "KeySchema": [{"AttributeName": "name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
        )
        dynamo.create_table(
            TableName="test-jobs",
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"},
                {"AttributeName": "repo_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[{
                "IndexName": "repo_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "repo_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
        )
        sqs_client = boto3.client("sqs", region_name="us-east-1")
        queue = sqs_client.create_queue(QueueName="test-queue")
        os.environ["SQS_QUEUE_URL"] = queue["QueueUrl"]

        yield


def _make_client(aws_resources):
    from api.main import app
    return TestClient(app)


def test_health(aws_resources):
    client = _make_client(aws_resources)
    with client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_register_and_list_repos(aws_resources):
    from api.main import app
    with TestClient(app) as client:
        resp = client.post("/repos", json={"name": "acme/myrepo", "path": "src/main.py"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "acme/myrepo"
        assert data["path"] == "src/main.py"
        assert "webhook_secret" in data
        assert "repo_id" in data

        resp2 = client.get("/repos")
        assert resp2.status_code == 200
        assert len(resp2.json()["repos"]) == 1


def test_webhook_unknown_repo(aws_resources):
    from api.main import app
    with TestClient(app) as client:
        payload = json.dumps({"repository": {"full_name": "nobody/norepo"}, "after": "abc123"})
        resp = client.post("/webhook", content=payload, headers={"Content-Type": "application/json"})
    assert resp.status_code == 404


def test_webhook_bad_signature(aws_resources):
    from api.main import app
    with TestClient(app) as client:
        reg = client.post("/repos", json={"name": "owner/repo"})
        assert reg.status_code == 201

        payload = json.dumps({
            "repository": {"full_name": "owner/repo"},
            "after": "abc123def456",
            "ref": "refs/heads/main",
        }).encode()
        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=badsignature",
            },
        )
    assert resp.status_code == 401


def test_webhook_queues_job(aws_resources):
    from api.main import app
    with TestClient(app) as client:
        reg = client.post("/repos", json={"name": "owner/repo", "path": "README.md"})
        assert reg.status_code == 201
        secret = reg.json()["webhook_secret"]
        repo_id = reg.json()["repo_id"]

        payload = json.dumps({
            "repository": {"full_name": "owner/repo"},
            "after": "deadbeef1234567890abcdef",
            "ref": "refs/heads/main",
        }).encode()
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        resp = client.post(
            "/webhook",
            content=payload,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        job_resp = client.get(f"/jobs/{job_id}")
        assert job_resp.status_code == 200
        assert job_resp.json()["status"] == "pending"
        assert job_resp.json()["repo_id"] == repo_id

        hist_resp = client.get(f"/repos/{repo_id}/history")
        assert hist_resp.status_code == 200
        assert len(hist_resp.json()["jobs"]) == 1


def test_get_job_not_found(aws_resources):
    from api.main import app
    with TestClient(app) as client:
        resp = client.get("/jobs/nonexistent-id")
    assert resp.status_code == 404
