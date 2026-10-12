resource "aws_cloudwatch_log_group" "ingestion" {
  name              = "/aws/lambda/${local.name}-ingestion"
  retention_in_days = 14
}

resource "aws_iam_role" "ingestion" {
  name = "${local.name}-ingestion"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ingestion" {
  name = "ingestion-access"
  role = aws_iam_role.ingestion.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadNotifiedVersions"
        Effect   = "Allow"
        Action   = ["s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.storage["input"].arn}/${local.input_prefix}*"
      },
      {
        Sid      = "WriteResults"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.storage["results"].arn}/${local.results_prefix}*"
      },
      {
        Sid      = "ConsumeQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.ingestion.arn
      },
      {
        Sid      = "WriteLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.ingestion.arn}:log-stream:*"
      },
    ]
  })
}

resource "aws_lambda_function" "ingestion" {
  function_name                  = "${local.name}-ingestion"
  description                    = "Version-aware rule-based ingestion of synthetic CloudTrail uploads"
  role                           = aws_iam_role.ingestion.arn
  handler                        = "trailsleuth.ingestion.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  filename                       = local.artifact_path
  source_code_hash               = filebase64sha256(local.artifact_path)
  timeout                        = local.lambda_timeout
  memory_size                    = 512
  reserved_concurrent_executions = local.ingestion_concurrency

  environment {
    variables = {
      INPUT_BUCKET   = aws_s3_bucket.storage["input"].id
      RESULTS_BUCKET = aws_s3_bucket.storage["results"].id
    }
  }

  depends_on = [aws_iam_role_policy.ingestion, aws_cloudwatch_log_group.ingestion]
}

resource "aws_lambda_event_source_mapping" "ingestion" {
  event_source_arn                   = aws_sqs_queue.ingestion.arn
  function_name                      = aws_lambda_function.ingestion.arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = local.batch_window
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = local.ingestion_concurrency
  }
  depends_on = [aws_sqs_queue_redrive_allow_policy.dead_letter]
}
