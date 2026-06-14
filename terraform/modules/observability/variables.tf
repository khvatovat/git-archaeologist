variable "project" { type = string }
variable "env"     { type = string }

variable "cluster_name"        { type = string }
variable "api_service_name"    { type = string }
variable "worker_service_name" { type = string }
variable "queue_name"          { type = string }
variable "alb_arn_suffix"      { type = string }
variable "target_group_arn_suffix" { type = string }

variable "queue_depth_alarm_threshold" {
  type    = number
  default = 20
}

variable "alarm_actions" {
  type    = list(string)
  default = []
}
