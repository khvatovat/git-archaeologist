locals {
  name = "${var.project}-${var.env}"
}

resource "aws_dynamodb_table" "repos" {
  name         = "${local.name}-repos"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "repo_id"

  attribute {
    name = "repo_id"
    type = "S"
  }

  attribute {
    name = "name"
    type = "S"
  }

  global_secondary_index {
    name            = "name-index"
    hash_key        = "name"
    projection_type = "ALL"
  }

  server_side_encryption {
    enabled = true
  }

  tags = { Name = "${local.name}-repos" }
}

resource "aws_dynamodb_table" "jobs" {
  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "repo_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "repo_id-created_at-index"
    hash_key        = "repo_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  server_side_encryption {
    enabled = true
  }

  tags = { Name = "${local.name}-jobs" }
}
