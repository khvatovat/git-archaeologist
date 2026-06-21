output "alb_sg_id" { value = aws_security_group.alb.id }
output "api_sg_id" { value = aws_security_group.api.id }
output "worker_sg_id" { value = aws_security_group.worker.id }

output "anthropic_secret_arn" {
  value = aws_secretsmanager_secret.anthropic_key.arn
}

output "github_token_secret_arn" {
  value = aws_secretsmanager_secret.github_token.arn
}
