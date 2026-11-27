# =============================================================================
# MSP AI Platform - Main Terraform Configuration
# =============================================================================
# This file uses DRY (Don't Repeat Yourself) principles with for_each loops
# to manage the platform's extensive infrastructure cleanly and efficiently.
# =============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Uncomment and configure for production state management
  # backend "s3" {
  #   bucket         = "your-tf-state-bucket"
  #   key            = "msp-triage/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-state-lock"
  # }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# =============================================================================
# LOCALS (Configuration Maps for DRY Resource Creation)
# =============================================================================

locals {
  prefix = "${var.project}-${var.environment}"

  # ---------------------------------------------------------------------------
  # 1. DYNAMODB TABLES
  # ---------------------------------------------------------------------------
  tables = {
    tenant_registry = {
      hash_key  = "tenant_id"
      range_key = null
      gsis      = ["entra_tenant_id"]
      ttl       = null
    }
    status_cache = {
      hash_key  = "cache_key"
      range_key = null
      gsis      = []
      ttl       = "ttl"
    }
    status_history = {
      hash_key  = "tenant_id"
      range_key = "snapshot_date"
      gsis      = []
      ttl       = "ttl"
    }
    analytics_summary = {
      hash_key  = "summary_type"
      range_key = "summary_date"
      gsis      = "summary_date"
      ttl       = "ttl"
    }
    agent_audit_log = {
      hash_key  = "audit_id"
      range_key = "timestamp"
      gsis      = ["tenant_id"]
      ttl       = "ttl"
    }
    agent_feedback = {
      hash_key  = "feedback_id"
      range_key = null
      gsis      = ["tenant_id", "status"]
      ttl       = "ttl"
    }
    agent_conversations = {
      hash_key  = "session_id"
      range_key = null
      gsis      = []
      ttl       = "ttl"
    }
    password_reset_tokens = {
      hash_key  = "token"
      range_key = null
      gsis      = []
      ttl       = "ttl"
    }
    confirmation_nonces = {
      hash_key  = "confirmation_id"
      range_key = null
      gsis      = []
      ttl       = "ttl"
    }
    webhook_configs = {
      hash_key  = "tenant_id"
      range_key = "webhook_id"
      gsis      = []
      ttl       = null
    }
    webhook_cooldowns = {
      hash_key  = "cooldown_key"
      range_key = null
      gsis      = []
      ttl       = "ttl"
    }
    custom_health_rules = {
      hash_key  = "tenant_id"
      range_key = "rule_id"
      gsis      = []
      ttl       = null
    }
    webhook_delivery_log = {
      hash_key  = "delivery_id"
      range_key = "timestamp"
      gsis      = ["tenant_id"]
      ttl       = "ttl"
    }
    rule_effectiveness_log = {
      hash_key  = "tenant_id"
      range_key = "evaluation_date"
      gsis      = []
      ttl       = "ttl"
    }
    portal_users = {
      hash_key  = "user_id"
      range_key = null
      gsis      = ["tenant_id"]
      ttl       = null
    }
  }

  # ---------------------------------------------------------------------------
  # 2. S3 BUCKETS
  # ---------------------------------------------------------------------------
  buckets = {
    agent_schemas      = { lifecycle_days = 0 }
    kb_documents       = { lifecycle_days = var.enable_knowledge_base ? 0 : null }
    customer_branding  = { lifecycle_days = 0 }
    few_shot_examples  = { lifecycle_days = 0 }
    tenant_portal      = { lifecycle_days = 0 }
  }

  # ---------------------------------------------------------------------------
  # 3. SQS QUEUES
  # ---------------------------------------------------------------------------
  queues = {
    tenant_provisioning = { retention = 1209600 } # 14 days
    customer_digest     = { retention = 1209600 }
    customer_insights   = { retention = 1209600 }
  }

  # ---------------------------------------------------------------------------
  # 4. LAMBDA FUNCTIONS
  # ---------------------------------------------------------------------------
  lambdas = {
    orchestrator                  = { timeout = 60, memory = 512 }
    worker                        = { timeout = 60, memory = 512 }
    teams_bot                     = { timeout = 30, memory = 256 }
    identity_tools                = { timeout = 30, memory = 256 }
    ticket_tools                  = { timeout = 30, memory = 256 }
    device_tools                  = { timeout = 30, memory = 256 }
    calendar_tools                = { timeout = 30, memory = 256 }
    tenant_onboarding             = { timeout = 30, memory = 256 }
    tenant_provisioning_worker    = { timeout = 900, memory = 512 }
    status_history_snapshot       = { timeout = 300, memory = 512 }
    webhook_notifier              = { timeout = 30, memory = 256 }
    analytics_aggregation         = { timeout = 300, memory = 512 }
    tenant_portal_api             = { timeout = 30, memory = 256 }
    custom_health_rules           = { timeout = 30, memory = 256 }
    customer_digest_orchestrator  = { timeout = 30, memory = 256 }
    customer_digest_worker        = { timeout = 300, memory = 512 }
    customer_insights_orchestrator= { timeout = 30, memory = 256 }
    customer_insights_worker      = { timeout = 300, memory = 512 }
    agent_feedback                = { timeout = 30, memory = 256 }
    agent_feedback_sync           = { timeout = 60, memory = 256 }
    kb_document_processor         = { timeout = 300, memory = 512 }
    reset_password                = { timeout = 30, memory = 256 }
    unsubscribe                   = { timeout = 30, memory = 256 }
    customer_insights_unsubscribe = { timeout = 30, memory = 256 }
  }
}

# =============================================================================
# DATA SOURCES
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Archive Lambda source code (assumes zip files are built in .build/)
data "archive_file" "lambdas" {
  for_each = local.lambdas
  type        = "zip"
  source_dir  = "src_${replace(each.key, "_", "-")}" # Adjust to match your actual directory names
  output_path = ".build/${each.key}.zip"
}

# =============================================================================
# DYNAMODB TABLES
# =============================================================================

resource "aws_dynamodb_table" "main" {
  for_each = local.tables

  name           = "${local.prefix}-${each.key}"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = each.value.hash_key
  range_key      = each.value.range_key

  dynamic "attribute" {
    for_each = toset(compact([each.value.hash_key, each.value.range_key]))
    content {
      name = attribute.value
      type = "S" # Defaulting to String for simplicity; adjust if needed
    }
  }

  dynamic "global_secondary_index" {
    for_each = toset(each.value.gsis)
    content {
      name               = "${global_secondary_index.key}-index"
      hash_key           = global_secondary_index.key
      projection_type    = "ALL"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl != null ? [1] : []
    content {
      attribute_name = each.value.ttl
      enabled        = true
    }
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = { Name = "${local.prefix}-${each.key}" }
}

# =============================================================================
# S3 BUCKETS
# =============================================================================

resource "aws_s3_bucket" "main" {
  for_each = local.buckets
  bucket   = "${local.prefix}-${each.key}"

  tags = { Name = "${local.prefix}-${each.key}" }
}

resource "aws_s3_bucket_public_access_block" "main" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.main[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "main" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.main[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.main[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "main" {
  for_each = { for k, v in local.buckets : k => v if v.lifecycle_days != null }
  bucket   = aws_s3_bucket.main[each.key].id

  rule {
    id     = "cleanup"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
 if each.key == "tenant_portal" {
      expiration {
        days = 30
      }
    }
  }
}

# TLS-Only Bucket Policy for all buckets
resource "aws_s3_bucket_policy" "tls_only" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.main[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.main[each.key].arn,
        "${aws_s3_bucket.main[each.key].arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

# =============================================================================
# SQS QUEUES & DLQs
# =============================================================================

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues
  name     = "${local.prefix}-${each.key}-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "main" {
  for_each = local.queues
  name     = "${local.prefix}-${each.key}"
  
  message_retention_seconds = each.value.retention
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 3
  })
}

# =============================================================================
# SECRETS MANAGER
# =============================================================================

resource "aws_secretsmanager_secret" "platform" {
  for_each = toset(["teams_bot_secret", "confirmation_signing_key"])
  name     = "${local.prefix}/${each.key}"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "platform" {
  for_each = toset(["teams_bot_secret", "confirmation_signing_key"])
  secret_id = aws_secretsmanager_secret.platform[each.key].id
  
  secret_string = jsonencode({
    "PLACEHOLDER" = "Update via CI/CD or Console"
  })
}

# =============================================================================
# IAM ROLES & POLICIES
# =============================================================================

# Base Lambda Execution Role
resource "aws_iam_role" "lambda_base" {
  name = "${local.prefix}-lambda-base-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_base" {
  role       = aws_iam_role.lambda_base.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_base.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Specific Policy for DynamoDB, S3, SQS, Secrets (Attached to Base Role)
resource "aws_iam_role_policy" "lambda_data_access" {
  name = "${local.prefix}-lambda-data-access"
  role = aws_iam_role.lambda_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
          "dynamodb:Query", "dynamodb:Scan"
        ]
        Resource = [for t in aws_dynamodb_table.main : t.arn]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = flatten([
          for b in aws_s3_bucket.main : [b.arn, "${b.arn}/*"]
        ])
      },
      {
        Effect = "Allow"
        Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [for q in aws_sqs_queue.main : q.arn]
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${local.prefix}/*"
      }
    ]
  })
}

# Bedrock Specific Policy
resource "aws_iam_role_policy" "lambda_bedrock_access" {
  name = "${local.prefix}-lambda-bedrock-access"
  role = aws_iam_role.lambda_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
          "bedrock:GetAgent", "bedrock:InvokeAgent", "bedrock:ListAgentAliases",
          "bedrock:CreateAgent", "bedrock:UpdateAgent", "bedrock:DeleteAgent",
          "bedrock:PrepareAgent", "bedrock:CreateAgentAlias", "bedrock:DeleteAgentAlias",
          "bedrock:CreateAgentActionGroup", "bedrock:DeleteAgentActionGroup",
          "bedrock:ListAgentKnowledgeBases", "bedrock:DisassociateAgentKnowledgeBase",
          "bedrock:StartIngestionJob"
        ]
        Resource = "*"
      }
    ]
  })
}

# =============================================================================
# LAMBDA FUNCTIONS
# =============================================================================

resource "aws_lambda_function" "main" {
  for_each = local.lambdas

  function_name = "${local.prefix}-${each.key}"
  role          = aws_iam_role.lambda_base.arn
  handler       = "${replace(each.key, "-", "_")}.lambda_handler" # e.g., tenant_onboarding.lambda_handler
  runtime       = "python3.13"
  architectures = ["arm64"]
  
  filename         = data.archive_file.lambdas[each.key].output_path
  source_code_hash = data.archive_file.lambdas[each.key].output_base64sha256
  
  timeout = each.value.timeout
  memory_size = each.value.memory

  environment {
    variables = {
      ENVIRONMENT                = var.environment
      TENANT_REGISTRY_TABLE      = aws_dynamodb_table.main["tenant_registry"].name
      STATUS_CACHE_TABLE         = aws_dynamodb_table.main["status_cache"].name
      PROVISIONING_QUEUE_URL     = aws_sqs_queue.main["tenant_provisioning"].url
      AGENT_SCHEMAS_BUCKET       = aws_s3_bucket.main["agent_schemas"].bucket
      KB_DOCUMENTS_BUCKET        = var.enable_knowledge_base ? aws_s3_bucket.main["kb_documents"].bucket : ""
      ENABLE_KB                  = var.enable_knowledge_base ? "true" : "false"
      ANALYTICS_SUMMARY_TABLE    = aws_dynamodb_table.main["analytics_summary"].name
      AUDIT_LOG_TABLE            = aws_dynamodb_table.main["agent_audit_log"].name
      FEEDBACK_TABLE             = aws_dynamodb_table.main["agent_feedback"].name
      CONVERSATIONS_TABLE        = aws_dynamodb_table.main["agent_conversations"].name
      KNOWLEDGE_BASE_ID          = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.main[0].id : ""
      DATA_SOURCE_ID             = var.enable_knowledge_base ? aws_bedrockagent_data_source.main[0].data_source_id : ""
      DEFAULT_AGENT_MODEL        = var.agent_model_id
      AGENT_MODEL_ID             = var.agent_model_id
      GUARDRAIL_ID               = var.enable_guardrails ? var.guardrail_id : ""
      GUARDRAIL_VERSION          = var.enable_guardrails ? var.guardrail_version : ""
    }
  }

  tracing_config {
    mode = var.enable_xray_tracing ? "Active" : "PassThrough"
  }
}

# =============================================================================
# API GATEWAY (HTTP APIs)
# =============================================================================

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = ["*"] # Restrict in production
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["content-type", "x-api-key", "authorization"]
  }
}

resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
}

# Example: Tenant Onboarding API Integration & Route
resource "aws_apigatewayv2_integration" "onboarding" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.main["tenant_onboarding"].invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "onboarding" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /tenants"
  target    = "integrations/${aws_apigatewayv2_integration.onboarding.id}"
}

resource "aws_apigatewayv2_route" "onboarding_get" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /tenants"
  target    = "integrations/${aws_apigatewayv2_integration.onboarding.id}"
}

resource "aws_apigatewayv2_route" "onboarding_get_id" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /tenants/{tenant_id}"
  target    = "integrations/${aws_apigatewayv2_integration.onboarding.id}"
}

resource "aws_apigatewayv2_route" "onboarding_delete" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "DELETE /tenants/{tenant_id}"
  target    = "integrations/${aws_apigatewayv2_integration.onboarding.id}"
}

# Lambda Permission for API Gateway
resource "aws_lambda_permission" "apigw" {
  for_each = toset(["tenant_onboarding", "tenant_portal_api", "webhook_notifier"])
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main[each.value].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# =============================================================================
# BEDROCK AGENT & KNOWLEDGE BASE
# =============================================================================

# IAM Role for Bedrock Agent
resource "aws_iam_role" "bedrock_agent" {
  name = "${local.prefix}-bedrock-agent-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount": data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn": "arn:aws:bedrock:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:agent/*" }
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_agent" {
  name = "${local.prefix}-bedrock-agent-policy"
  role = aws_iam_role.bedrock_agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/${var.agent_foundation_model_id}"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.main["agent_schemas"].arn, "${aws_s3_bucket.main["agent_schemas"].arn}/*"]
      }
    ]
  })
}

resource "aws_bedrockagent_agent" "main" {
  agent_name              = "${local.prefix}-default-agent"
  agent_resource_role_arn = aws_iam_role.bedrock_agent.arn
  foundation_model        = var.agent_foundation_model_id
  instruction             = var.default_agent_instruction
  idle_session_ttl_in_seconds = var.agent_idle_session_ttl_seconds

  dynamic "guardrail_configuration" {
    for_each = var.enable_guardrails ? [1] : []
    content {
      guardrail_identifier = var.guardrail_id
      guardrail_version    = var.guardrail_version
    }
  }
}

resource "aws_bedrockagent_agent_alias" "main" {
  agent_id      = aws_bedrockagent_agent.main.id
  agent_alias_name = "latest"
}

# Knowledge Base (Conditional)
resource "aws_bedrockagent_knowledge_base" "main" {
  count = var.enable_knowledge_base ? 1 : 0
  name     = "${local.prefix}-kb"
  role_arn = aws_iam_role.bedrock_agent.arn # Reusing role for simplicity; create dedicated KB role in prod

  knowledge_base_configuration {
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/${var.kb_embedding_model_id}"
    }
    type = "VECTOR"
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = var.aoss_collection_arn # Pass via variable or create via aws_opensearchserverless_collection
      vector_index_name = "msp-kg-index"
      field_mapping = {
        vectorField   = "vector"
        textField     = "text"
        metadataField = "metadata"
      }
    }
  }
}

resource "aws_bedrockagent_data_source" "main" {
  count = var.enable_knowledge_base ? 1 : 0
  knowledge_base_id = aws_bedrockagent_knowledge_base.main[0].id
  name              = "${local.prefix}-kb-docs"
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.main["kb_documents"].arn
    }
  }
}

# =============================================================================
# EVENTBRIDGE RULES (Scheduled Tasks)
# =============================================================================

resource "aws_cloudwatch_event_rule" "scheduled_tasks" {
  for_each = {
    status_snapshot  = "cron(0 6 * * ? *)" # 6 AM UTC daily
    digest           = "cron(0 11 * * ? *)" # 11 AM UTC daily
    insights         = "cron(0 9 ? * SUN *)" # 9 AM UTC Sunday
    analytics        = "cron(0 7 * * ? *)" # 7 AM UTC daily
  }
  name                = "${local.prefix}-${each.key}-rule"
  schedule_expression = each.value
}

resource "aws_cloudwatch_event_target" "scheduled_tasks" {
  for_each = {
    status_snapshot  = "status_history_snapshot"
    digest           = "customer_digest_orchestrator"
    insights         = "customer_insights_orchestrator"
    analytics        = "analytics_aggregation"
  }
  rule      = aws_cloudwatch_event_rule.scheduled_tasks[each.key].name
  target_id = each.value
  arn       = aws_lambda_function.main[each.value].arn
}

resource "aws_lambda_permission" "eventbridge" {
  for_each = {
    status_snapshot  = "status_history_snapshot"
    digest           = "customer_digest_orchestrator"
    insights         = "customer_insights_orchestrator"
    analytics        = "analytics_aggregation"
  }
  statement_id  = "AllowExecutionFromEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.main[each.value].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scheduled_tasks[each.key].arn
}

# =============================================================================
# COGNITO USER POOL (Tenant Portal)
# =============================================================================

resource "aws_cognito_user_pool" "portal" {
  count = var.enable_tenant_portal ? 1 : 0
  name = "${local.prefix}-portal-users"
  
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

resource "aws_cognito_user_pool_client" "portal" {
  count = var.enable_tenant_portal ? 1 : 0
  name         = "${local.prefix}-portal-client"
  user_pool_id = aws_cognito_user_pool.portal[0].id
  
  generate_secret = false
  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  
  callback_urls = ["${var.portal_callback_url}"]
  logout_urls   = ["${var.portal_logout_url}"]
  allowed_oauth_flows = ["code"]
  allowed_oauth_scopes = ["email", "openid", "profile"]
  supported_identity_providers = ["COGNITO"] # Add Entra ID SAML provider ARN here in prod
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "api_url" {
  value = aws_apigatewayv2_stage.main.invoke_url
}

output "portal_user_pool_id" {
  value = var.enable_tenant_portal ? aws_cognito_user_pool.portal[0].id : null
}

output "bedrock_agent_id" {
  value = aws_bedrockagent_agent.main.id
}

output "s3_buckets" {
  value = { for k, v in aws_s3_bucket.main : k => v.bucket }
}

output "dynamodb_tables" {
  value = { for k, v in aws_dynamodb_table.main : k => v.name }
}

# =============================================================================
# API GATEWAY - API KEY & USAGE PLAN
# =============================================================================

resource "aws_apigatewayv2_api_key" "onboarding" {
  name        = "${local.prefix}-onboarding-key"
  description = "API key for tenant onboarding and admin operations"
  enabled     = true
  
  # Auto-rotate every 90 days (optional)
  # value = random_password.api_key.result
}

resource "random_password" "api_key" {
  length  = 40
  special = false
}

resource "aws_apigatewayv2_stage" "authenticated" {
  api_id = aws_apigatewayv2_api.main.id
  name   = "authenticated"
  
  # Note: API Gateway v2 HTTP APIs don't natively support API keys
  # For production, use a Lambda authorizer or Cognito authorizer instead
}

# For HTTP API, use a Lambda authorizer (simplified approach)
resource "aws_apigatewayv2_authorizer" "api_key" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "REQUEST"
  authorizer_uri   = aws_lambda_function.main["tenant_onboarding"].invoke_arn
  name             = "${local.prefix}-api-key-auth"
  identity_sources = ["$request.header.x-api-key"]
  authorizer_payload_format_version = "2.0"
  enable_simple_responses = true
}

# =============================================================================
# CLOUDWATCH DASHBOARDS
# =============================================================================

resource "aws_cloudwatch_dashboard" "executive" {
  dashboard_name = "${local.prefix}-executive"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.main["tenant_onboarding"].function_name],
            ["...", aws_lambda_function.main["teams_bot"].function_name],
            ["...", aws_lambda_function.main["tenant_provisioning_worker"].function_name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Lambda Invocations (Key Functions)"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.main["tenant_registry"].name],
            ["...", aws_dynamodb_table.main["agent_audit_log"].name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "DynamoDB Read Capacity"
          period  = 300
        }
      }
    ]
  })
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.prefix}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.main["teams_bot"].function_name],
            ["...", aws_lambda_function.main["tenant_onboarding"].function_name],
            ["...", aws_lambda_function.main["tenant_provisioning_worker"].function_name],
            ["...", aws_lambda_function.main["identity_tools"].function_name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Lambda Errors (All Critical Functions)"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.main["tenant_provisioning"].name],
            ["...", aws_sqs_queue.main["customer_digest"].name],
            ["...", aws_sqs_queue.main["customer_insights"].name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "SQS Queue Depths"
          period  = 300
        }
      }
    ]
  })
}

resource "aws_cloudwatch_dashboard" "security" {
  dashboard_name = "${local.prefix}-security"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH('{AWS/Lambda,FunctionName} FunctionName', 'Sum', 300)", id = "e1", label = "All Lambda Errors" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Security-Relevant Errors"
          period  = 300
        }
      }
    ]
  })
}

resource "aws_cloudwatch_dashboard" "cost" {
  dashboard_name = "${local.prefix}-cost"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 24
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.main["teams_bot"].function_name, { stat = "Average" }],
            ["...", aws_lambda_function.main["tenant_provisioning_worker"].function_name, { stat = "Average" }],
            ["...", aws_lambda_function.main["analytics_aggregation"].function_name, { stat = "Average" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Lambda Duration (Cost Indicator)"
          period  = 300
        }
      }
    ]
  })
}

# =============================================================================
# CLOUDWATCH ALARMS
# =============================================================================

locals {
  alarms = {
    critical_lambda_errors = {
      metric_name = "Errors"
      namespace   = "AWS/Lambda"
      threshold   = 5
      period      = 300
      dimensions  = { FunctionName = aws_lambda_function.main["teams_bot"].function_name }
    }
    critical_dlq_messages = {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      threshold   = 0
      period      = 300
      dimensions  = { QueueName = aws_sqs_queue.dlq["tenant_provisioning"].name }
    }
    warning_dynamodb_throttles = {
      metric_name = "ThrottledRequests"
      namespace   = "AWS/DynamoDB"
      threshold   = 0
      period      = 300
      dimensions  = { TableName = aws_dynamodb_table.main["tenant_registry"].name }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "main" {
  for_each = local.alarms

  alarm_name          = "${local.prefix}-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = each.value.metric_name
  namespace           = each.value.namespace
  period              = each.value.period
  statistic           = "Sum"
  threshold           = each.value.threshold
  alarm_description   = "Alert: ${each.key} exceeded threshold"
  treat_missing_data  = "notBreaching"

  dimensions = each.value.dimensions

  alarm_actions = [aws_sns_topic.main["alerts"].arn]
  ok_actions    = [aws_sns_topic.main["alerts"].arn]
}

# =============================================================================
# SNS TOPICS (ALERTING)
# =============================================================================

resource "aws_sns_topic" "main" {
  for_each = toset(["alerts", "security", "cost"])
  name     = "${local.prefix}-${each.key}"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.main["alerts"].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# =============================================================================
# SQS EVENT SOURCE MAPPINGS (TRIGGER LAMBDAS FROM QUEUES)
# =============================================================================

resource "aws_lambda_event_source_mapping" "sqs" {
  for_each = {
    tenant_provisioning = {
      queue_key     = "tenant_provisioning"
      function_key  = "tenant_provisioning_worker"
      batch_size    = 1
    }
    customer_digest = {
      queue_key     = "customer_digest"
      function_key  = "customer_digest_worker"
      batch_size    = 10
    }
    customer_insights = {
      queue_key     = "customer_insights"
      function_key  = "customer_insights_worker"
      batch_size    = 10
    }
  }

  event_source_arn = aws_sqs_queue.main[each.value.queue_key].arn
  function_name    = aws_lambda_function.main[each.value.function_key].arn
  batch_size       = each.value.batch_size
  enabled          = true
}