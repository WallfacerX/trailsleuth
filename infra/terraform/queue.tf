resource "aws_sqs_queue" "dead_letter" {
  name                      = "${local.name}-ingestion-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "ingestion" {
  name                       = "${local.name}-ingestion"
  sqs_managed_sse_enabled    = true
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = 6 * local.lambda_timeout + local.batch_window
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dead_letter" {
  queue_url = aws_sqs_queue.dead_letter.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.ingestion.arn]
  })
}

resource "aws_sqs_queue_policy" "notifications" {
  queue_url = aws_sqs_queue.ingestion.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowOnlyIntendedS3Notifications"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.ingestion.arn
      Condition = {
        ArnEquals    = { "aws:SourceArn" = aws_s3_bucket.storage["input"].arn }
        StringEquals = { "aws:SourceAccount" = var.expected_account_id }
      }
    }]
  })
}
