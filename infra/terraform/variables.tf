variable "aws_region" {
  description = "AWS Region for future resources; check service availability before deployment."
  type        = string
}

variable "project_name" {
  description = "Project name used to identify future resources."
  type        = string
}

variable "environment" {
  description = "Environment label for future resources, such as dev."
  type        = string
}

variable "common_tags" {
  description = "Additional tags. Project and Environment are set by their dedicated variables."
  type        = map(string)
  default     = {}
}
