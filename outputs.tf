output "webhook_url" {
  value = "${aws_apigatewayv2_stage.default.invoke_url}/webhooks/psa"
}

output "queue_url"            { value = aws_sqs_queue.tickets.url }
output "dlq_url"              { value = aws_sqs_queue.dlq.url }
output "orchestrator_function" { value = aws_lambda_function.orchestrator.function_name }
output "orchestrator_log_group" { value = aws_cloudwatch_log_group.orchestrator.name }
output "secret_names" {
  value = {
    psa     = aws_secretsmanager_secret.psa.name
    rmm     = aws_secretsmanager_secret.rmm.name
    webhook = aws_secretsmanager_secret.webhook.name
  }
}