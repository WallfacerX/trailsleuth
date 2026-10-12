provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = merge(var.common_tags, {
      Project     = var.project_name
      Environment = var.environment
    })
  }
}
