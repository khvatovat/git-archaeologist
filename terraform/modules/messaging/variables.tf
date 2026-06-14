variable "project" { type = string }
variable "env"     { type = string }

variable "visibility_timeout_seconds" {
  type    = number
  default = 960
}

variable "message_retention_seconds" {
  type    = number
  default = 86400
}
