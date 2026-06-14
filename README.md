# git-archaeologist — cloud service

A webhook-triggered GitHub history analysis service built on AWS, deployed via Terraform, with CI/CD on both GitHub Actions and GitLab CI.

---

## 1. Context & scope

`git-archaeologist` was originally a CLI tool that fetches a file's commit and PR history from a GitHub repo and generates a narrative analysis using Claude Haiku (era summaries) and Claude Sonnet (synthesis). This project wraps that logic into a cloud-hosted service:

- Users register GitHub repos to watch via a static web UI
- A GitHub webhook fires on each push; the API validates it, creates a job record, and enqueues the job
- A worker picks up the job, runs the existing analysis pipeline (unchanged), and stores the result in DynamoDB
- A history page shows per-repo analysis runs with expandable markdown output

The focus of this project is **infrastructure, automation, security, and observability** — not the AI logic, which is reused verbatim.

---

## 2. Architecture

```
                          ┌─────────────────────────────────────────────────────┐
                          │  AWS (us-east-1)                                    │
                          │                                                     │
 User browser ────────────┼──▶  ALB (public, port 80)                          │
                          │       │                                             │
 GitHub webhook ──────────┼───────┤                                             │
                          │       ▼                                             │
                          │  ECS Fargate — api  (private subnet)               │
                          │    POST /repos         → DynamoDB repos             │
                          │    GET  /repos         ← DynamoDB repos             │
                          │    POST /webhook       → DynamoDB jobs              │
                          │                        → SQS jobs queue             │
                          │    GET  /repos/{id}/history ← DynamoDB jobs (GSI)  │
                          │    GET  /jobs/{id}     ← DynamoDB jobs              │
                          │                                                     │
                          │  SQS ──▶ ECS Fargate — worker (private subnet)     │
                          │               │  runs analysis pipeline             │
                          │               ▼                                     │
                          │          DynamoDB jobs  (status, result)            │
                          │               │                                     │
                          │  Secrets Manager  ──▶  ANTHROPIC_API_KEY           │
                          │                  ──▶  GITHUB_TOKEN                 │
                          │                                                     │
                          │  CloudWatch: dashboard + 2 alarms                  │
                          └─────────────────────────────────────────────────────┘
```

**Two AZs**: public subnets hold the ALB and NAT Gateway; private subnets hold ECS tasks. One NAT GW shared across both AZs (cost optimisation — acceptable for dev).

**Least-privilege IAM**:

| Role | Allowed actions |
|---|---|
| API task role | DynamoDB `PutItem/GetItem/Scan/Query` (repos + jobs), SQS `SendMessage` |
| Worker task role | DynamoDB `GetItem/UpdateItem` (jobs only), SQS `ReceiveMessage/DeleteMessage`, Secrets Manager `GetSecretValue` |
| ECS execution role | ECR pull, CloudWatch Logs write, Secrets Manager `GetSecretValue` (for container env injection) |

No service has broader access than it needs. DynamoDB is accessed only from private subnets via AWS-managed endpoints (traffic stays within AWS).

---

## 3. Why DynamoDB + SQS

**DynamoDB** is the right fit because:
- All access patterns are key-based: look up a job by `job_id`, list jobs for a `repo_id` (GSI), register a repo by `repo_id`. No joins, no aggregations.
- Schema is flat: a job is a bag of attributes (id, status, result, timestamps). Relational structure is not needed.
- Pay-per-request billing means near-zero cost at low traffic.
- RDS would add ~$15–30/month for a dev instance, require a VPN or private endpoint for ECS access, and add operational complexity (backups, patches, connection pooling) that brings no benefit here.

**SQS** is the right fit because:
- Analysis jobs are long-running (minutes), inherently async, and fully decoupled from the HTTP request.
- The job queue pattern (one producer, one consumer) is exactly what SQS is built for.
- Visibility timeout + dead-letter queue provide automatic retry and failure isolation.
- Step Functions would add orchestration overhead with no benefit — there is only one step (run analysis).

---

## 4. Terraform module breakdown

Modules live under `terraform/modules/`, wired in `terraform/envs/dev/main.tf`.

| Module | Resources |
|---|---|
| `network` | VPC, 2 public subnets (ALB/NAT), 2 private subnets (ECS), IGW, NAT GW, route tables |
| `security` | ALB security group (inbound :80), API SG (inbound :8080 from ALB only), worker SG (no inbound), Secrets Manager secrets for API key and GitHub token |
| `messaging` | SQS jobs queue + dead-letter queue with 3-attempt redrive |
| `data` | DynamoDB `repos` table (PK: `repo_id`, GSI on `name`), `jobs` table (PK: `job_id`, GSI on `repo_id+created_at`) |
| `ecs` | ECS Fargate cluster, ECR repos (api, worker), CloudWatch log groups, IAM roles (execution + per-service task roles), ALB + target group + listener, task definitions (with Secrets Manager env injection for worker), ECS services |
| `observability` | CloudWatch dashboard (5 widgets: request count, latency p95, queue depth, worker task count, 5xx errors), 2 alarms (queue depth > 20, API 5xx > 10/min) |

**State backend**: S3 bucket + DynamoDB lock table (see `terraform/envs/dev/backend.tf`). See setup instructions below.

### Screenshots

> _Add `terraform plan` output screenshot here after first plan._
> _Add `terraform apply` completion screenshot here after first apply._
> _Add AWS console screenshots (ECS services, DynamoDB tables, SQS queue) here._

---

## 5. CI/CD pipelines

### Pipeline A — GitHub Actions (app code)

File: `.github/workflows/app.yml`
Triggers on push/PR to `main` for changes under `api/`, `worker/`, or root `*.py`.

Stages:
1. **test** — installs deps, runs `pytest api/tests/ worker/tests/` with `coverage`
2. **sonar** — SonarCloud scan (push to main only); uploads coverage XML
3. **sca-scan** — Trivy filesystem scan (CRITICAL+HIGH), uploads SARIF to GitHub Security tab
4. **build-and-push** (main push only):
   - Docker build for `api` → Trivy image scan → push to ECR
   - Docker build for `worker` → Trivy image scan → push to ECR
   - `aws ecs update-service --force-new-deployment` for both services

Authentication: GitHub OIDC → IAM role (no long-lived access keys).

### Pipeline B — GitHub Actions (Terraform)

File: `.github/workflows/terraform.yml`
Triggers on push/PR to `main` for changes under `terraform/`.

Stages:
1. **validate** — `terraform fmt -check`, `terraform validate`
2. **security-scan** — Checkov IaC scan, uploads SARIF
3. **plan** (PRs only) — `terraform plan`, posts output as PR comment; manual review required before merge
4. **apply** (main push only) — `terraform apply -auto-approve` via GitHub environment `production` (requires reviewer approval in GitHub settings)

### Pipeline C — GitLab CI (mirrored repo)

File: `.gitlab-ci.yml`
GitLab mirrors the GitHub repo. Uses a **different toolchain** from Pipeline A:

| Concern | GitHub Actions (A) | GitLab CI (C) |
|---|---|---|
| SAST | SonarCloud | GitLab Semgrep template |
| Dependency scan | Trivy (filesystem) | GitLab Gemnasium template |
| Secret detection | (not in A) | GitLab Secret Detection template |
| Image build | Push to ECR | Build-only verification |

Stages: `test` → `scan` → `build`.

### Screenshots

> _Add green GitHub Actions run screenshot here._
> _Add Trivy scan report screenshot here._
> _Add SonarCloud dashboard screenshot here._
> _Add GitLab pipeline screenshot here._
> _Add Checkov report screenshot here._

---

## 6. Security decisions

### IAM (least privilege)

The worker task role is deliberately narrow:

```json
{
  "Statement": [
    {
      "Sid": "DynamoJobs",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/git-archaeologist-dev-jobs",
        "arn:aws:dynamodb:us-east-1:*:table/git-archaeologist-dev-jobs/index/*"
      ]
    },
    {
      "Sid": "SQSConsume",
      "Effect": "Allow",
      "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      "Resource": "arn:aws:sqs:us-east-1:*:git-archaeologist-dev-jobs"
    },
    {
      "Sid": "SecretsRead",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:git-archaeologist-dev/anthropic-api-key-*",
        "arn:aws:secretsmanager:us-east-1:*:secret:git-archaeologist-dev/github-token-*"
      ]
    }
  ]
}
```

The worker cannot read or write repos, cannot send SQS messages, cannot access any other secret. The API task role cannot read secrets or touch the worker's DynamoDB update path.

### Security groups

```
ALB SG:    inbound 0.0.0.0/0 :80  → outbound all
API SG:    inbound ALB_SG :8080   → outbound all (AWS APIs via NAT)
Worker SG: no inbound             → outbound all
```

The API is never reachable from the internet directly — only via the ALB. The worker has no listening port.

### Anthropic API key

The key is stored in AWS Secrets Manager under `git-archaeologist-dev/anthropic-api-key`. It is injected into the worker container via the ECS task definition `secrets` field (not an environment variable set in Terraform). It never appears in:
- Terraform state (only the ARN is stored; the Secrets Manager resource points to a `sensitive` variable)
- Container logs
- Application source code

### Webhook signature

Every incoming GitHub webhook is verified using HMAC-SHA256 with the per-repo `webhook_secret` stored in DynamoDB. The comparison uses `hmac.compare_digest` to prevent timing attacks. Requests that fail verification return HTTP 401 before any DynamoDB write occurs.

---

## 7. Observability

CloudWatch dashboard `git-archaeologist-dev-dashboard` (5 widgets):

- **ALB request count** — requests/minute, SUM
- **ALB target response time p95** — latency percentile
- **SQS queue depth** — messages visible (shows job backlog)
- **Worker ECS running task count** — from Container Insights
- **ALB 5xx error count** — SUM

Two alarms:
- `git-archaeologist-dev-queue-depth-high` — fires when queue > 20 messages for 2 consecutive minutes (worker stuck or underprovisioned)
- `git-archaeologist-dev-api-5xx-high` — fires when 5xx count > 10/minute for 2 minutes

Worker and API logs stream to CloudWatch Logs under `/ecs/git-archaeologist-dev/{api,worker}` with 14-day retention.

### Screenshots

> _Add CloudWatch dashboard screenshot here._
> _Add alarm firing screenshot here (trigger manually by stopping worker and queuing jobs)._

---

## 8. Limitations & what production would add

| Limitation | Production mitigation |
|---|---|
| Single NAT Gateway (AZ failure loses egress) | One NAT GW per AZ |
| No HTTPS / TLS on ALB | ACM certificate + HTTPS listener, HTTP→HTTPS redirect |
| Worker does not auto-scale | ECS Application Auto Scaling on SQS queue depth metric |
| DynamoDB scan for repo list | Acceptable at small scale; GSI on a sort key or ElastiCache for large scale |
| No auth on the API | API Gateway with Cognito or API key; GitHub webhook secret is the only authentication in scope |
| Secrets Manager call on worker restart | ECS parameter caching or SSM Parameter Store for lower-cost secrets |
| `terraform apply` runs on main push with `-auto-approve` | Separate `staging` environment + canary deployment; manual approval gate in GitHub Environments (already configured as `environment: production`) |
| No CI image tag pinning in task definition | Pipeline should call `terraform apply -var=api_image=...` with the exact SHA after push |

---

## 9. Cost & resilience tradeoffs

**Cost (dev, low traffic, approximate monthly):**

| Resource | Estimate |
|---|---|
| ECS Fargate — api (0.25 vCPU / 0.5 GB, 1 task) | ~$6 |
| ECS Fargate — worker (0.5 vCPU / 1 GB, 1 task) | ~$11 |
| NAT Gateway (1, minimal traffic) | ~$35 |
| DynamoDB (PAY_PER_REQUEST, dev traffic) | < $1 |
| SQS (dev traffic) | < $1 |
| ALB | ~$16 |
| Secrets Manager (2 secrets) | ~$0.80 |
| CloudWatch (logs + dashboard) | ~$3 |
| **Total** | **~$73/month** |

The NAT Gateway dominates. At low traffic the operational savings of Fargate + SQS over a self-managed EC2 + RabbitMQ stack outweigh the cost.

**Resilience tradeoffs:**
- Fargate eliminates EC2 management; AWS handles underlying instance failures and task placement
- SQS dead-letter queue (maxReceiveCount=3) captures jobs the worker cannot process, preventing silent data loss
- DynamoDB is multi-AZ by default; ECS tasks can be spread across AZs but need the `placement_strategies` config added for true HA
- One NAT GW is a single point of failure for private-subnet egress; tolerated for dev

---

## Setup

### Prerequisites
- AWS CLI configured with admin access
- Terraform >= 1.6
- Docker
- Python 3.11

### First-time infra setup

```bash
# 1. Create Terraform state backend
aws s3 mb s3://git-archaeologist-tfstate --region us-east-1
aws s3api put-bucket-versioning \
  --bucket git-archaeologist-tfstate \
  --versioning-configuration Status=Enabled

aws dynamodb create-table \
  --table-name terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1

# 2. Configure secrets
cp terraform/envs/dev/terraform.tfvars.example terraform/envs/dev/terraform.tfvars
# Edit terraform.tfvars with your real API keys

# 3. Deploy infrastructure
cd terraform/envs/dev
terraform init
terraform apply

# 4. Build and push images (first time, after ECR repos exist)
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
API_REPO="${AWS_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/git-archaeologist-dev-api"
WORKER_REPO="${AWS_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/git-archaeologist-dev-worker"
aws ecr get-login-password | docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"
docker build -f api/Dockerfile -t "${API_REPO}:latest" .
docker push "${API_REPO}:latest"
docker build -f worker/Dockerfile -t "${WORKER_REPO}:latest" .
docker push "${WORKER_REPO}:latest"
# Then re-apply Terraform to pin the image tags in the task definitions
```

### Running tests locally

```bash
pip install fastapi uvicorn boto3 pydantic anthropic httpx rich python-dotenv \
            pytest pytest-asyncio "moto[dynamodb,sqs,secretsmanager]" coverage
pytest api/tests/ worker/tests/ -v
```

### GitHub Actions secrets required

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN with ECS + ECR deploy permissions (OIDC) |
| `ANTHROPIC_API_KEY` | Your Anthropic key (Terraform stores it in Secrets Manager) |
| `GH_WATCH_TOKEN` | GitHub PAT for the worker to call the GitHub API |
| `SONAR_TOKEN` | SonarCloud project token |

### GitLab mirror setup

1. GitLab → New project → Import project → Repository by URL → paste GitHub HTTPS URL
2. Enable "Mirror repository" with Pull direction
3. The `.gitlab-ci.yml` is picked up automatically; no extra CI variables needed for the built-in templates
