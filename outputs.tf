# =============================================================================
# MSP AI Platform - Terraform Outputs
# =============================================================================
# This file exposes key infrastructure details for consumption by:
#   - Shell scripts (Makefile, deployment scripts, test scripts)
#   - Other Terraform modules
#   - Developers and operations teams
#   - CI/CD pipelines
#
# All outputs are organized by category for easy navigation.
# =============================================================================

# =============================================================================
# CORE INFRASTRUCTURE
# =============================================================================

output "project" {
  description = "Project name prefix"
  value       = var.project
}

output "environment" {
  description = "Deployment environment (dev/staging/prod)"
  value       = var.environment
}

output "aws_region" {
  description = "AWS region where resources are deployed"
  value       = data.aws_region.current.name
}

output "aws_account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "resource_prefix" {
  description = "Common prefix for all resources (e.g., msp-triage-dev)"
  value       = local.prefix
}

# =============================================================================
# API GATEWAY
# =============================================================================

output "api_url" {
  description = "Base URL for the main HTTP API Gateway"
  value       = aws_apigatewayv2_stage.main.invoke_url
}

output "api_id" {
  description = "API Gateway ID"
  value       = aws_apigatewayv2_api.main.id
}

output "api_execution_arn" {
  description = "API Gateway execution ARN (for IAM policies)"
  value       = aws_apigatewayv2_api.main.execution_arn
}

output "tenant_onboarding_api_url" {
  description = "Full URL for tenant onboarding API (used by scripts)"
  value       = "${aws_apigatewayv2_stage.main.invoke_url}"
}

output "onboarding_api_key_id" {
  description = "API Gateway API Key ID for onboarding API authentication"
  value       = aws_apigatewayv2_api_key.onboarding.id
}

output "onboarding_api_key_value" {
  description = "API Gateway API Key value (SENSITIVE - use with caution)"
  value       = aws_apigatewayv2_api_key.onboarding.value
  sensitive   = true
}

# =============================================================================
# LAMBDA FUNCTIONS
# =============================================================================

output "lambda_function_names" {
  description = "Map of all Lambda function names"
  value       = { for k, v in aws_lambda_function.main : k => v.function_name }
}

output "lambda_function_arns" {
  description = "Map of all Lambda function ARNs"
  value       = { for k, v in aws_lambda_function.main : k => v.arn }
}

output "lambda_invoke_arns" {
  description = "Map of all Lambda invoke ARNs (for API Gateway/SQS integration)"
  value       = { for k, v in aws_lambda_function.main : k => v.invoke_arn }
}

output "lambda_role_arn" {
  description = "IAM role ARN used by all Lambda functions"
  value       = aws_iam_role.lambda_base.arn
}

output "lambda_role_name" {
  description = "IAM role name used by all Lambda functions"
  value       = aws_iam_role.lambda_base.name
}

# Specific Lambda outputs commonly referenced by scripts
output "teams_bot_function_name" {
  description = "Name of the Teams Bot Lambda function"
  value       = aws_lambda_function.main["teams_bot"].function_name
}

output "tenant_onboarding_function_name" {
  description = "Name of the Tenant Onboarding Lambda function"
  value       = aws_lambda_function.main["tenant_onboarding"].function_name
}

output "tenant_provisioning_worker_function_name" {
  description = "Name of the Tenant Provisioning Worker Lambda function"
  value       = aws_lambda_function.main["tenant_provisioning_worker"].function_name
}

output "analytics_aggregation_function_name" {
  description = "Name of the Analytics Aggregation Lambda function"
  value       = aws_lambda_function.main["analytics_aggregation"].function_name
}

output "reset_password_function_name" {
  description = "Name of the Reset Password Lambda function"
  value       = aws_lambda_function.main["reset_password"].function_name
}

# =============================================================================
# DYNAMODB TABLES
# =============================================================================

output "dynamodb_table_names" {
  description = "Map of all DynamoDB table names"
  value       = { for k, v in aws_dynamodb_table.main : k => v.name }
}

output "dynamodb_table_arns" {
  description = "Map of all DynamoDB table ARNs"
  value       = { for k, v in aws_dynamodb_table.main : k => v.arn }
}

output "dynamodb_table_streams" {
  description = "Map of DynamoDB table stream ARNs (for change data capture)"
  value       = { for k, v in aws_dynamodb_table.main : k => v.stream_arn }
}

# Specific table outputs commonly referenced by scripts
output "tenant_registry_table" {
  description = "Name of the Tenant Registry DynamoDB table"
  value       = aws_dynamodb_table.main["tenant_registry"].name
}

output "status_cache_table" {
  description = "Name of the Status Cache DynamoDB table"
  value       = aws_dynamodb_table.main["status_cache"].name
}

output "analytics_summary_table" {
  description = "Name of the Analytics Summary DynamoDB table"
  value       = aws_dynamodb_table.main["analytics_summary"].name
}

output "audit_log_table" {
  description = "Name of the Audit Log DynamoDB table"
  value       = aws_dynamodb_table.main["agent_audit_log"].name
}

output "feedback_table" {
  description = "Name of the Feedback DynamoDB table"
  value       = aws_dynamodb_table.main["agent_feedback"].name
}

output "conversations_table" {
  description = "Name of the Conversations DynamoDB table"
  value       = aws_dynamodb_table.main["agent_conversations"].name
}

output "password_reset_tokens_table" {
  description = "Name of the Password Reset Tokens DynamoDB table"
  value       = aws_dynamodb_table.main["password_reset_tokens"].name
}

output "confirmation_nonces_table" {
  description = "Name of the Confirmation Nonces DynamoDB table"
  value       = aws_dynamodb_table.main["confirmation_nonces"].name
}

output "webhook_configs_table" {
  description = "Name of the Webhook Configs DynamoDB table"
  value       = aws_dynamodb_table.main["webhook_configs"].name
}

output "custom_health_rules_table" {
  description = "Name of the Custom Health Rules DynamoDB table"
  value       = aws_dynamodb_table.main["custom_health_rules"].name
}

# =============================================================================
# S3 BUCKETS
# =============================================================================

output "s3_bucket_names" {
  description = "Map of all S3 bucket names"
  value       = { for k, v in aws_s3_bucket.main : k => v.bucket }
}

output "s3_bucket_arns" {
  description = "Map of all S3 bucket ARNs"
  value       = { for k, v in aws_s3_bucket.main : k => v.arn }
}

output "s3_bucket_domains" {
  description = "Map of all S3 bucket domain names"
  value       = { for k, v in aws_s3_bucket.main : k => v.bucket_domain_name }
}

# Specific bucket outputs commonly referenced by scripts
output "agent_schemas_bucket" {
  description = "Name of the Agent Schemas S3 bucket"
  value       = aws_s3_bucket.main["agent_schemas"].bucket
}

output "kb_documents_bucket" {
  description = "Name of the Knowledge Base Documents S3 bucket"
  value       = var.enable_knowledge_base ? aws_s3_bucket.main["kb_documents"].bucket : null
}

output "customer_branding_bucket" {
  description = "Name of the Customer Branding S3 bucket"
  value       = aws_s3_bucket.main["customer_branding"].bucket
}

output "few_shot_examples_bucket" {
  description = "Name of the Few-Shot Examples S3 bucket"
  value       = aws_s3_bucket.main["few_shot_examples"].bucket
}

output "tenant_portal_bucket" {
  description = "Name of the Tenant Portal S3 bucket"
  value       = var.enable_tenant_portal ? aws_s3_bucket.main["tenant_portal"].bucket : null
}

output "portal_bucket_name" {
  description = "Name of the Portal bucket (alias for scripts)"
  value       = var.enable_tenant_portal ? aws_s3_bucket.main["tenant_portal"].bucket : null
}

# =============================================================================
# SQS QUEUES
# =============================================================================

output "sqs_queue_urls" {
  description = "Map of all SQS queue URLs"
  value       = { for k, v in aws_sqs_queue.main : k => v.url }
}

output "sqs_queue_arns" {
  description = "Map of all SQS queue ARNs"
  value       = { for k, v in aws_sqs_queue.main : k => v.arn }
}

output "sqs_dlq_urls" {
  description = "Map of all Dead Letter Queue URLs"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.url }
}

output "sqs_dlq_arns" {
  description = "Map of all Dead Letter Queue ARNs"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.arn }
}

# Specific queue outputs commonly referenced by scripts
output "provisioning_queue_url" {
  description = "URL of the Tenant Provisioning SQS queue"
  value       = aws_sqs_queue.main["tenant_provisioning"].url
}

output "provisioning_queue_arn" {
  description = "ARN of the Tenant Provisioning SQS queue"
  value       = aws_sqs_queue.main["tenant_provisioning"].arn
}

output "provisioning_dlq_url" {
  description = "URL of the Tenant Provisioning Dead Letter Queue"
  value       = aws_sqs_queue.dlq["tenant_provisioning"].url
}

output "digest_queue_url" {
  description = "URL of the Customer Digest SQS queue"
  value       = aws_sqs_queue.main["customer_digest"].url
}

output "insights_queue_url" {
  description = "URL of the Customer Insights SQS queue"
  value       = aws_sqs_queue.main["customer_insights"].url
}

# =============================================================================
# BEDROCK (AI/ML)
# =============================================================================

output "bedrock_agent_id" {
  description = "ID of the default Bedrock Agent"
  value       = aws_bedrockagent_agent.main.id
}

output "bedrock_agent_arn" {
  description = "ARN of the default Bedrock Agent"
  value       = aws_bedrockagent_agent.main.agent_arn
}

output "bedrock_agent_name" {
  description = "Name of the default Bedrock Agent"
  value       = aws_bedrockagent_agent.main.agent_name
}

output "bedrock_agent_alias_id" {
  description = "ID of the 'latest' Bedrock Agent alias"
  value       = aws_bedrockagent_agent_alias.main.agent_alias_id
}

output "bedrock_agent_alias_arn" {
  description = "ARN of the 'latest' Bedrock Agent alias"
  value       = aws_bedrockagent_agent_alias.main.agent_alias_arn
}

output "bedrock_agent_role_arn" {
  description = "IAM role ARN used by the Bedrock Agent"
  value       = aws_iam_role.bedrock_agent.arn
}

output "default_agent_id" {
  description = "Default agent ID (alias for scripts)"
  value       = aws_bedrockagent_agent.main.id
}

# Knowledge Base outputs (conditional)
output "knowledge_base_id" {
  description = "ID of the Bedrock Knowledge Base (null if KB disabled)"
  value       = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.main[0].id : null
}

output "knowledge_base_arn" {
  description = "ARN of the Bedrock Knowledge Base (null if KB disabled)"
  value       = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.main[0].arn : null
}

output "knowledge_base_data_source_id" {
  description = "ID of the KB data source (null if KB disabled)"
  value       = var.enable_knowledge_base ? aws_bedrockagent_data_source.main[0].id : null
}

# =============================================================================
# SECRETS MANAGER
# =============================================================================

output "secrets_arns" {
  description = "Map of all Secrets Manager secret ARNs"
  value       = { for k, v in aws_secretsmanager_secret.platform : k => v.arn }
}

output "secrets_names" {
  description = "Map of all Secrets Manager secret names"
  value       = { for k, v in aws_secretsmanager_secret.platform : k => v.name }
}

output "teams_bot_secret_arn" {
  description = "ARN of the Teams Bot secret"
  value       = aws_secretsmanager_secret.platform["teams_bot_secret"].arn
}

output "confirmation_signing_key_arn" {
  description = "ARN of the Confirmation Signing Key secret"
  value       = aws_secretsmanager_secret.platform["confirmation_signing_key"].arn
}

# =============================================================================
# COGNITO (TENANT PORTAL)
# =============================================================================

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID for the tenant portal (null if portal disabled)"
  value       = var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].id : null
}

output "cognito_user_pool_arn" {
  description = "Cognito User Pool ARN (null if portal disabled)"
  value       = var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].arn : null
}

output "cognito_user_pool_endpoint" {
  description = "Cognito User Pool endpoint URL (null if portal disabled)"
  value       = var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].endpoint : null
}

output "cognito_client_id" {
  description = "Cognito User Pool Client ID (null if portal disabled)"
  value       = var.enable_tenant_portal ? aws_cognito_user_pool_client.portal[0].id : null
}

output "portal_user_pool_id" {
  description = "Portal User Pool ID (alias for scripts)"
  value       = var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].id : null
}

# =============================================================================
# EVENTBRIDGE (SCHEDULED TASKS)
# =============================================================================

output "eventbridge_rule_names" {
  description = "Map of all EventBridge rule names"
  value       = { for k, v in aws_cloudwatch_event_rule.scheduled_tasks : k => v.name }
}

output "eventbridge_rule_arns" {
  description = "Map of all EventBridge rule ARNs"
  value       = { for k, v in aws_cloudwatch_event_rule.scheduled_tasks : k => v.arn }
}

output "status_snapshot_rule_name" {
  description = "Name of the Status Snapshot scheduled rule"
  value       = aws_cloudwatch_event_rule.scheduled_tasks["status_snapshot"].name
}

output "digest_rule_name" {
  description = "Name of the Customer Digest scheduled rule"
  value       = aws_cloudwatch_event_rule.scheduled_tasks["digest"].name
}

output "insights_rule_name" {
  description = "Name of the Customer Insights scheduled rule"
  value       = aws_cloudwatch_event_rule.scheduled_tasks["insights"].name
}

output "analytics_rule_name" {
  description = "Name of the Analytics Aggregation scheduled rule"
  value       = aws_cloudwatch_event_rule.scheduled_tasks["analytics"].name
}

# =============================================================================
# IAM ROLES
# =============================================================================

output "iam_role_arns" {
  description = "Map of all IAM role ARNs"
  value = {
    lambda_base    = aws_iam_role.lambda_base.arn
    bedrock_agent  = aws_iam_role.bedrock_agent.arn
  }
}

output "iam_role_names" {
  description = "Map of all IAM role names"
  value = {
    lambda_base    = aws_iam_role.lambda_base.name
    bedrock_agent  = aws_iam_role.bedrock_agent.name
  }
}

# =============================================================================
# CLOUDWATCH DASHBOARDS
# =============================================================================

output "cloudwatch_dashboard_names" {
  description = "Names of all CloudWatch dashboards"
  value = [
    aws_cloudwatch_dashboard.executive.dashboard_name,
    aws_cloudwatch_dashboard.operations.dashboard_name,
    aws_cloudwatch_dashboard.security.dashboard_name,
    aws_cloudwatch_dashboard.cost.dashboard_name,
  ]
}

output "executive_dashboard_name" {
  description = "Name of the Executive Overview dashboard"
  value       = aws_cloudwatch_dashboard.executive.dashboard_name
}

output "operations_dashboard_name" {
  description = "Name of the Operations dashboard"
  value       = aws_cloudwatch_dashboard.operations.dashboard_name
}

output "security_dashboard_name" {
  description = "Name of the Security & Compliance dashboard"
  value       = aws_cloudwatch_dashboard.security.dashboard_name
}

output "cost_dashboard_name" {
  description = "Name of the Cost & Usage dashboard"
  value       = aws_cloudwatch_dashboard.cost.dashboard_name
}

# =============================================================================
# CLOUDWATCH ALARMS
# =============================================================================

output "cloudwatch_alarm_names" {
  description = "Names of all CloudWatch alarms"
  value       = [for a in aws_cloudwatch_metric_alarm.main : a.alarm_name]
}

output "critical_alarm_arns" {
  description = "ARNs of critical alarms (for PagerDuty integration)"
  value       = [for k, a in aws_cloudwatch_metric_alarm.main : a.arn if startswith(k, "critical_")]
}

# =============================================================================
# SNS TOPICS (ALERTING)
# =============================================================================

output "sns_topic_arns" {
  description = "Map of SNS topic ARNs for alerting"
  value       = { for k, v in aws_sns_topic.main : k => v.arn }
}

output "alerts_topic_arn" {
  description = "ARN of the main alerts SNS topic"
  value       = aws_sns_topic.main["alerts"].arn
}

output "security_topic_arn" {
  description = "ARN of the security alerts SNS topic"
  value       = aws_sns_topic.main["security"].arn
}

# =============================================================================
# COMPOSITE OUTPUTS (FOR SCRIPTS)
# =============================================================================

output "platform_summary" {
  description = "Consolidated summary of the platform deployment"
  value = {
    prefix            = local.prefix
    environment       = var.environment
    region            = data.aws_region.current.name
    account_id        = data.aws_caller_identity.current.account_id
    api_url           = aws_apigatewayv2_stage.main.invoke_url
    bedrock_agent_id  = aws_bedrockagent_agent.main.id
    lambda_count      = length(aws_lambda_function.main)
    table_count       = length(aws_dynamodb_table.main)
    bucket_count      = length(aws_s3_bucket.main)
    queue_count       = length(aws_sqs_queue.main)
    kb_enabled        = var.enable_knowledge_base
    portal_enabled    = var.enable_tenant_portal
  }
}

output "script_environment" {
  description = "Environment variables for shell scripts (use with: export $(terraform output -raw script_environment))"
  value = join(" ", [
    "API_URL=${aws_apigatewayv2_stage.main.invoke_url}",
    "API_KEY=${aws_apigatewayv2_api_key.onboarding.value}",
    "ENVIRONMENT=${var.environment}",
    "AWS_REGION=${data.aws_region.current.name}",
    "TENANT_REGISTRY_TABLE=${aws_dynamodb_table.main["tenant_registry"].name}",
    "PROVISIONING_QUEUE_URL=${aws_sqs_queue.main["tenant_provisioning"].url}",
    "AGENT_SCHEMAS_BUCKET=${aws_s3_bucket.main["agent_schemas"].bucket}",
    "KB_DOCUMENTS_BUCKET=${var.enable_knowledge_base ? aws_s3_bucket.main["kb_documents"].bucket : ""}",
    "DEFAULT_AGENT_ID=${aws_bedrockagent_agent.main.id}",
  ])
  sensitive = true
}

# =============================================================================
# QUICK REFERENCE (HUMAN-READABLE)
# =============================================================================

output "quick_reference" {
  description = "Quick reference for common resources (run: terraform output quick_reference)"
  value = <<-EOT

    ╔════════════════════════════════════════════════════════════╗
    ║          MSP AI Platform - Deployment Summary              ║
    ╚════════════════════════════════════════════════════════════╝

    Environment:     ${var.environment}
    Region:          ${data.aws_region.current.name}
    Account:         ${data.aws_caller_identity.current.account_id}
    Prefix:          ${local.prefix}

    ─────────────────────────────────────────────────────────────
    API ENDPOINTS
    ─────────────────────────────────────────────────────────────
    API URL:         ${aws_apigatewayv2_stage.main.invoke_url}
    API Key ID:      ${aws_apigatewayv2_api_key.onboarding.id}

    ─────────────────────────────────────────────────────────────
    AI/ML (BEDROCK)
    ─────────────────────────────────────────────────────────────
    Agent ID:        ${aws_bedrockagent_agent.main.id}
    Agent Alias:     ${aws_bedrockagent_agent_alias.main.agent_alias_id}
    KB ID:           ${var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.main[0].id : "DISABLED"}

    ─────────────────────────────────────────────────────────────
    RESOURCES
    ─────────────────────────────────────────────────────────────
    Lambda Functions: ${length(aws_lambda_function.main)}
    DynamoDB Tables:  ${length(aws_dynamodb_table.main)}
    S3 Buckets:       ${length(aws_s3_bucket.main)}
    SQS Queues:       ${length(aws_sqs_queue.main)}

    ─────────────────────────────────────────────────────────────
    KEY TABLES
    ─────────────────────────────────────────────────────────────
    Tenant Registry:  ${aws_dynamodb_table.main["tenant_registry"].name}
    Audit Log:        ${aws_dynamodb_table.main["agent_audit_log"].name}
    Status Cache:     ${aws_dynamodb_table.main["status_cache"].name}

    ─────────────────────────────────────────────────────────────
    KEY BUCKETS
    ─────────────────────────────────────────────────────────────
    Agent Schemas:    ${aws_s3_bucket.main["agent_schemas"].bucket}
    KB Documents:     ${var.enable_knowledge_base ? aws_s3_bucket.main["kb_documents"].bucket : "DISABLED"}
    Few-Shot:         ${aws_s3_bucket.main["few_shot_examples"].bucket}

    ─────────────────────────────────────────────────────────────
    KEY QUEUES
    ─────────────────────────────────────────────────────────────
    Provisioning:     ${aws_sqs_queue.main["tenant_provisioning"].url}
    Digest:           ${aws_sqs_queue.main["customer_digest"].url}
    Insights:         ${aws_sqs_queue.main["customer_insights"].url}

    ─────────────────────────────────────────────────────────────
    PORTAL (COGNITO)
    ─────────────────────────────────────────────────────────────
    User Pool:        ${var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].id : "DISABLED"}
    Client ID:        ${var.enable_tenant_portal ? aws_cognito_user_pool_client.portal[0].id : "DISABLED"}

    ╔════════════════════════════════════════════════════════════╗
    ║  Use 'terraform output <name>' to retrieve specific values ║
    ╚════════════════════════════════════════════════════════════╝

  EOT
}