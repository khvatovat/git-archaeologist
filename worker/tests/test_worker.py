import importlib
import json
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ["JOBS_TABLE"] = "test-jobs"
os.environ["SQS_QUEUE_URL"] = "placeholder"
os.environ["AWS_REGION"] = "us-east-1"


@pytest.fixture()
def aws_resources():
    with mock_aws():
        dynamo = boto3.resource("dynamodb", region_name="us-east-1")
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

        import worker.main as wm
        importlib.reload(wm)
        yield wm


def _seed_job(wm, job_id: str) -> None:
    wm.jobs_table.put_item(Item={
        "job_id": job_id,
        "repo_id": "repo-1",
        "repo_name": "owner/repo",
        "file_path": "README.md",
        "commit_sha": "abc123",
        "branch": "main",
        "status": "pending",
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
    })


def _enqueue_and_receive(wm, job_id: str) -> dict:
    job_payload = {
        "job_id": job_id,
        "repo_id": "repo-1",
        "repo_name": "owner/repo",
        "file_path": "README.md",
        "commit_sha": "abc123",
        "branch": "main",
    }
    wm.sqs.send_message(QueueUrl=os.environ["SQS_QUEUE_URL"], MessageBody=json.dumps(job_payload))
    resp = wm.sqs.receive_message(
        QueueUrl=os.environ["SQS_QUEUE_URL"],
        MaxNumberOfMessages=1,
        WaitTimeSeconds=0,
    )
    return resp["Messages"][0]


@patch("worker.main.asyncio.run", return_value="# Report\n\nsome content")
def test_process_message_success(mock_run, aws_resources):
    wm = aws_resources
    job_id = "job-success-1"
    _seed_job(wm, job_id)
    msg = _enqueue_and_receive(wm, job_id)

    wm._process_message(msg, github_token=None)

    item = wm.jobs_table.get_item(Key={"job_id": job_id})["Item"]
    assert item["status"] == "done"
    assert "# Report" in item["result"]


@patch("worker.main.asyncio.run", side_effect=Exception("network error"))
def test_process_message_failure(mock_run, aws_resources):
    wm = aws_resources
    job_id = "job-fail-1"
    _seed_job(wm, job_id)
    msg = _enqueue_and_receive(wm, job_id)

    wm._process_message(msg, github_token=None)

    item = wm.jobs_table.get_item(Key={"job_id": job_id})["Item"]
    assert item["status"] == "failed"
    assert "network error" in item["error"]
