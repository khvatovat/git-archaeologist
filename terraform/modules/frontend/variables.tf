variable "project" {
  type = string
}

variable "env" {
  type = string
}

variable "alb_dns_name" {
  type        = string
  description = "DNS name of the ALB — injected into config.js so the frontend can reach the API"
}
