locals {
  name                  = "${var.project_name}-${var.environment}"
  bucket_base           = "${local.name}-${var.expected_account_id}-${var.aws_region}"
  input_prefix          = "incoming/"
  results_prefix        = "results/v1/"
  lambda_timeout        = 60
  batch_window          = 0
  ingestion_concurrency = 2
  artifact_path         = "${path.module}/../../build/lambda/ingestion.zip"
}

resource "aws_s3_bucket" "storage" {
  for_each      = toset(["input", "results"])
  bucket        = "${local.bucket_base}-${each.key}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "storage" {
  for_each                = aws_s3_bucket.storage
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "storage" {
  for_each = aws_s3_bucket.storage
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  for_each = aws_s3_bucket.storage
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "input" {
  bucket = aws_s3_bucket.storage["input"].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "https_only" {
  for_each = aws_s3_bucket.storage
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = {
        Bool = {
          "aws:SecureTransport"       = "false"
          "aws:PrincipalIsAWSService" = "false"
        }
      }
    }]
  })
}

resource "aws_s3_bucket_notification" "incoming" {
  bucket = aws_s3_bucket.storage["input"].id
  queue {
    queue_arn     = aws_sqs_queue.ingestion.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = local.input_prefix
  }
  depends_on = [
    aws_s3_bucket_versioning.input,
    aws_sqs_queue_policy.notifications,
  ]
}
