# This foundation declares configuration only: no resources or AWS lookups.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(var.common_tags, {
      Project     = var.project_name
      Environment = var.environment
    })
  }
}
