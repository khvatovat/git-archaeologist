variable "project" { type = string }
variable "env" { type = string }
variable "vpc_id" { type = string }

variable "anthropic_api_key" {
  description = "Anthropic API key — stored in Secrets Manager, never in state"
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub personal access token — stored in Secrets Manager"
  type        = string
  sensitive   = true
}
