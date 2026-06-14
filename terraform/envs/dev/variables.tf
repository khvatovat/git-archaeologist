variable "project" {
  type    = string
  default = "git-archaeologist"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "github_token" {
  type      = string
  sensitive = true
}

variable "api_image" {
  type        = string
  description = "Full ECR image URI for the API (e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/git-archaeologist-dev-api:sha)"
  default     = "python:3.11-slim"
}

variable "worker_image" {
  type        = string
  description = "Full ECR image URI for the worker"
  default     = "python:3.11-slim"
}
