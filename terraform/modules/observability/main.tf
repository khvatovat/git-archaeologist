locals {
  name = "${var.project}-${var.env}"
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0; y = 0; width = 12; height = 6
        properties = {
          title  = "ALB Request Count"
          period = 60
          stat   = "Sum"
          metrics = [[
            "AWS/ApplicationELB",
            "RequestCount",
            "LoadBalancer", var.alb_arn_suffix
          ]]
        }
      },
      {
        type   = "metric"
        x      = 12; y = 0; width = 12; height = 6
        properties = {
          title  = "ALB Target Response Time (p95)"
          period = 60
          stat   = "p95"
          metrics = [[
            "AWS/ApplicationELB",
            "TargetResponseTime",
            "LoadBalancer", var.alb_arn_suffix,
            "TargetGroup", var.target_group_arn_suffix
          ]]
        }
      },
      {
        type   = "metric"
        x      = 0; y = 6; width = 12; height = 6
        properties = {
          title  = "SQS Queue Depth"
          period = 60
          stat   = "Maximum"
          metrics = [[
            "AWS/SQS",
            "ApproximateNumberOfMessagesVisible",
            "QueueName", var.queue_name
          ]]
        }
      },
      {
        type   = "metric"
        x      = 12; y = 6; width = 12; height = 6
        properties = {
          title  = "Worker ECS Task Count"
          period = 60
          stat   = "Average"
          metrics = [[
            "ECS/ContainerInsights",
            "RunningTaskCount",
            "ClusterName", var.cluster_name,
            "ServiceName", var.worker_service_name
          ]]
        }
      },
      {
        type   = "metric"
        x      = 0; y = 12; width = 12; height = 6
        properties = {
          title  = "ALB 5xx Error Rate"
          period = 60
          stat   = "Sum"
          metrics = [[
            "AWS/ApplicationELB",
            "HTTPCode_Target_5XX_Count",
            "LoadBalancer", var.alb_arn_suffix
          ]]
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${local.name}-queue-depth-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.queue_depth_alarm_threshold
  alarm_description   = "SQS job queue depth exceeds ${var.queue_depth_alarm_threshold} — worker may be stuck or under-provisioned"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.queue_name
  }

  alarm_actions = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "API 5xx error count exceeds 10 in a minute"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_actions = var.alarm_actions
}
