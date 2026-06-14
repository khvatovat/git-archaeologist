variable "project" { type = string }
variable "env"     { type = string }
variable "aws_region" { type = string }

variable "vpc_id"             { type = string }
variable "public_subnet_ids"  { type = list(string) }
variable "private_subnet_ids" { type = list(string) }

variable "alb_sg_id"    { type = string }
variable "api_sg_id"    { type = string }
variable "worker_sg_id" { type = string }

variable "repos_table_name" { type = string }
variable "repos_table_arn"  { type = string }
variable "jobs_table_name"  { type = string }
variable "jobs_table_arn"   { type = string }

variable "queue_url" { type = string }
variable "queue_arn" { type = string }

variable "anthropic_secret_arn"    { type = string }
variable "github_token_secret_arn" { type = string }

variable "api_image"    { type = string }
variable "worker_image" { type = string }

variable "api_cpu"    { type = number; default = 256 }
variable "api_memory" { type = number; default = 512 }

variable "worker_cpu"    { type = number; default = 512 }
variable "worker_memory" { type = number; default = 1024 }

variable "api_desired_count"    { type = number; default = 1 }
variable "worker_desired_count" { type = number; default = 1 }
