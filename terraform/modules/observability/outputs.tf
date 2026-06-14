output "dashboard_name"       { value = aws_cloudwatch_dashboard.main.dashboard_name }
output "queue_depth_alarm_arn" { value = aws_cloudwatch_metric_alarm.queue_depth.arn }
output "api_5xx_alarm_arn"    { value = aws_cloudwatch_metric_alarm.api_5xx.arn }
