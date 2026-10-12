variable "aws_region" {
  description = "AWS Region for the ingestion stack."
  type        = string
}

variable "project_name" {
  description = "Lowercase project name used to identify resources."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,15}$", var.project_name))
    error_message = "Use 1-16 lowercase letters, digits, or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Short environment label, such as dev."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,7}$", var.environment))
    error_message = "Use 1-8 lowercase letters, digits, or hyphens, starting with a letter."
  }
}

variable "expected_account_id" {
  description = "Intended 12-digit AWS account ID. The provider refuses a different account."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Set the intended 12-digit AWS account ID in your ignored variable file."
  }
}

variable "common_tags" {
  description = "Additional tags. Project and Environment are set by their dedicated variables."
  type        = map(string)
  default     = {}
}
