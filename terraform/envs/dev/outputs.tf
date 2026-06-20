output "alb_dns_name" {
  description = "ALB DNS — set this as the API base URL"
  value       = module.ecs.alb_dns_name
}

output "api_ecr_url" {
  description = "ECR repo URL for the API image"
  value       = module.ecs.api_ecr_url
}

output "worker_ecr_url" {
  description = "ECR repo URL for the worker image"
  value       = module.ecs.worker_ecr_url
}

output "frontend_url"     { value = module.frontend.website_url }
output "repos_table_name" { value = module.data.repos_table_name }
output "jobs_table_name"  { value = module.data.jobs_table_name }
output "queue_url"        { value = module.messaging.queue_url }
output "dashboard_name"   { value = module.observability.dashboard_name }
