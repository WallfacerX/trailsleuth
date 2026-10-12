resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name}-ingestion-errors"
  alarm_description   = "Lambda invocation errors. Partial batch failures are reported in logs and eventually the DLQ. No notification actions configured."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.ingestion.function_name }
  alarm_actions       = []
  ok_actions          = []
}

resource "aws_cloudwatch_metric_alarm" "dead_letter" {
  alarm_name          = "${local.name}-ingestion-dlq-visible"
  alarm_description   = "Messages require investigation in the ingestion DLQ. No notification actions configured."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  alarm_actions       = []
  ok_actions          = []
}
