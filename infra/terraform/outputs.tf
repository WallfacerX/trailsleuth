output "input_bucket_name" {
  description = "Versioned input bucket for synthetic uploads."
  value       = aws_s3_bucket.storage["input"].id
}

output "input_prefix" {
  value = local.input_prefix
}

output "results_bucket_name" {
  value = aws_s3_bucket.storage["results"].id
}

output "results_prefix" {
  value = local.results_prefix
}

output "queue_url" {
  value = aws_sqs_queue.ingestion.id
}

output "queue_arn" {
  value = aws_sqs_queue.ingestion.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dead_letter.id
}

output "dlq_arn" {
  value = aws_sqs_queue.dead_letter.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.ingestion.function_name
}

output "event_source_mapping_uuid" {
  value = aws_lambda_event_source_mapping.ingestion.uuid
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.ingestion.name
}

output "alarm_names" {
  value = [aws_cloudwatch_metric_alarm.lambda_errors.alarm_name, aws_cloudwatch_metric_alarm.dead_letter.alarm_name]
}

output "account_id" {
  value = var.expected_account_id
}

output "aws_region" {
  value = var.aws_region
}
