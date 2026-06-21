output "repos_table_name" { value = aws_dynamodb_table.repos.name }
output "repos_table_arn" { value = aws_dynamodb_table.repos.arn }
output "jobs_table_name" { value = aws_dynamodb_table.jobs.name }
output "jobs_table_arn" { value = aws_dynamodb_table.jobs.arn }
