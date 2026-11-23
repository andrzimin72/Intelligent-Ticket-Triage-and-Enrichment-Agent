# =============================================================================
# DATA SOURCES
# =============================================================================
data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"

  # Public URL for the secure password reset form (custom domain)
  password_reset_public_url = "https://${var.password_reset_domain_name}/set-password"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    DataClass   = "customer-confidential"
  }
}

# =============================================================================
# BEDROCK GUARDRAIL - TICKET TRIAGE
# =============================================================================
resource "aws_bedrock_guardrail" "triage" {
  name                      = "${local.name_prefix}-triage-guardrail"
  description               = "Redacts PII and blocks off-topic content for MSP ticket triage"
  blocked_input_messaging   = "The input contains sensitive or inappropriate content and cannot be processed."
  blocked_outputs_messaging = "The output contains sensitive or inappropriate content and has been redacted."

  content_policy_config {
    filters_config { type = "HATE";          input_strength = "HIGH";   output_strength = "HIGH" }
    filters_config { type = "VIOLENCE";      input_strength = "HIGH";   output_strength = "HIGH" }
    filters_config { type = "SEXUAL";        input_strength = "HIGH";   output_strength = "HIGH" }
    filters_config { type = "INSULTS";       input_strength = "MEDIUM"; output_strength = "MEDIUM" }
    filters_config { type = "MISCONDUCT";    input_strength = "MEDIUM"; output_strength = "MEDIUM" }
    filters_config { type = "PROMPT_ATTACK"; input_strength = "HIGH";   output_strength = "NONE" }
  }

  sensitive_information_policy_config {
    pii_entities_config { type = "NAME";                     action = "BLOCK" }
    pii_entities_config { type = "EMAIL";                    action = "BLOCK" }
    pii_entities_config { type = "PHONE";                    action = "BLOCK" }
    pii_entities_config { type = "SSN";                      action = "BLOCK" }
    pii_entities_config { type = "CREDIT_DEBIT_CARD_NUMBER"; action = "BLOCK" }
    pii_entities_config { type = "IP_ADDRESS";               action = "BLOCK" }
    pii_entities_config { type = "PASSWORD";                 action = "BLOCK" }
  }

  topic_policy_config {
    topics_config {
      name       = "Non-IT-Support"
      definition = "Topics unrelated to IT support, such as medical advice, legal advice, financial advice, political opinions, or personal counseling."
      type       = "DENY"
      examples   = ["What are the symptoms of the flu?", "Should I invest in stocks?", "Who should I vote for?", "How do I file for divorce?"]
    }
  }

  word_policy_config {
    managed_word_lists_config { type = "PROFANITY" }
    words_config { text = "ignore previous instructions" }
    words_config { text = "forget all prior instructions" }
    words_config { text = "you are now a different AI" }
  }
}

resource "aws_bedrock_guardrail_version" "triage_v1" {
  guardrail_id = aws_bedrock_guardrail.triage.id
  description  = "Initial version"
}

# =============================================================================
# BEDROCK GUARDRAIL - CUSTOMER DIGEST
# =============================================================================
resource "aws_bedrock_guardrail" "customer_digest" {
  name                      = "${local.name_prefix}-customer-digest-guardrail"
  description               = "Ensures customer-facing security insights are professional, reassuring, and PII-free"
  blocked_input_messaging   = "The content cannot be processed."
  blocked_outputs_messaging = "The content has been filtered for professionalism and safety."

  content_policy_config {
    filters_config { type = "HATE";       input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "VIOLENCE";   input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "SEXUAL";     input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "INSULTS";    input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "MISCONDUCT"; input_strength = "HIGH"; output_strength = "HIGH" }
  }

  sensitive_information_policy_config {
    pii_entities_config { type = "NAME";                     action = "BLOCK" }
    pii_entities_config { type = "EMAIL";                    action = "BLOCK" }
    pii_entities_config { type = "PHONE";                    action = "BLOCK" }
    pii_entities_config { type = "SSN";                      action = "BLOCK" }
    pii_entities_config { type = "CREDIT_DEBIT_CARD_NUMBER"; action = "BLOCK" }
    pii_entities_config { type = "IP_ADDRESS";               action = "BLOCK" }
    pii_entities_config { type = "PASSWORD";                 action = "BLOCK" }
  }

  topic_policy_config {
    topics_config {
      name       = "Non-Security-IT"
      definition = "Topics outside of IT security, such as medical advice, legal advice, financial advice, political opinions, or personal matters."
      type       = "DENY"
      examples   = ["What are the symptoms of the flu?", "Should I invest in stocks?", "Who should I vote for?"]
    }
    topics_config {
      name       = "Alarming-Content"
      definition = "Language that could cause unnecessary panic or alarm."
      type       = "DENY"
      examples   = ["Your system is completely compromised and you must shut everything down immediately", "Catastrophic failure imminent, all data will be lost"]
    }
  }

  word_policy_config {
    managed_word_lists_config { type = "PROFANITY" }
  }
}

resource "aws_bedrock_guardrail_version" "customer_digest_v1" {
  guardrail_id = aws_bedrock_guardrail.customer_digest.id
  description  = "Initial version"
}

# =============================================================================
# BEDROCK GUARDRAIL - AGENT (customer-facing, strict)
# =============================================================================
resource "aws_bedrock_guardrail" "agent" {
  name                      = "${local.name_prefix}-agent-guardrail"
  description               = "Strict guardrail for customer-facing AI IT Concierge"
  blocked_input_messaging   = "I can't process that request. Please try rephrasing or contact your IT admin."
  blocked_outputs_messaging = "I can't provide that response. Please contact your IT admin for assistance."

  content_policy_config {
    filters_config { type = "HATE";       input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "VIOLENCE";   input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "SEXUAL";     input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "INSULTS";    input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "MISCONDUCT"; input_strength = "HIGH"; output_strength = "HIGH" }
  }

  sensitive_information_policy_config {
    pii_entities_config { type = "NAME";                     action = "BLOCK" }
    pii_entities_config { type = "EMAIL";                    action = "BLOCK" }
    pii_entities_config { type = "PHONE";                    action = "BLOCK" }
    pii_entities_config { type = "SSN";                      action = "BLOCK" }
    pii_entities_config { type = "CREDIT_DEBIT_CARD_NUMBER"; action = "BLOCK" }
    pii_entities_config { type = "IP_ADDRESS";               action = "BLOCK" }
    pii_entities_config { type = "PASSWORD";                 action = "BLOCK" }
  }

  topic_policy_config {
    topics_config {
      name       = "Non-IT-Support"
      definition = "Topics outside of IT support, such as medical, legal, financial advice, political opinions, personal matters, pricing discussions, contract negotiations, or company strategy."
      type       = "DENY"
      examples = [
        "What are the symptoms of the flu?",
        "Should I invest in stocks?",
        "How much does your service cost?",
        "Can we renegotiate our contract?",
        "Who should I vote for?"
      ]
    }
    topics_config {
      name       = "Sensitive-Operations"
      definition = "Requests to perform sensitive operations that require human approval, such as deleting user accounts, modifying security policies, accessing other users' data, or making changes outside the user's own account."
      type       = "DENY"
      examples = [
        "Delete my user account",
        "Show me other users' passwords",
        "Change the company security policy",
        "Access the CEO's email"
      ]
    }
  }

  word_policy_config {
    managed_word_lists_config { type = "PROFANITY" }
    words_config { text = "ignore previous instructions" }
    words_config { text = "you are now a different AI" }
  }
}

resource "aws_bedrock_guardrail_version" "agent_v1" {
  guardrail_id = aws_bedrock_guardrail.agent.id
  description  = "Initial version"
}

# =============================================================================
# BEDROCK GUARDRAIL - CUSTOMER INSIGHTS (strategic tone)
# =============================================================================
resource "aws_bedrock_guardrail" "customer_insights" {
  name                      = "${local.name_prefix}-customer-insights-guardrail"
  description               = "Ensures strategic customer insights are professional, constructive, and PII-free"
  blocked_input_messaging   = "The content cannot be processed."
  blocked_outputs_messaging = "The content has been filtered for professionalism and safety."

  content_policy_config {
    filters_config { type = "HATE";       input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "VIOLENCE";   input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "SEXUAL";     input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "INSULTS";    input_strength = "HIGH"; output_strength = "HIGH" }
    filters_config { type = "MISCONDUCT"; input_strength = "HIGH"; output_strength = "HIGH" }
  }

  sensitive_information_policy_config {
    pii_entities_config { type = "NAME";                     action = "BLOCK" }
    pii_entities_config { type = "EMAIL";                    action = "BLOCK" }
    pii_entities_config { type = "PHONE";                    action = "BLOCK" }
    pii_entities_config { type = "SSN";                      action = "BLOCK" }
    pii_entities_config { type = "CREDIT_DEBIT_CARD_NUMBER"; action = "BLOCK" }
    pii_entities_config { type = "IP_ADDRESS";               action = "BLOCK" }
    pii_entities_config { type = "PASSWORD";                 action = "BLOCK" }
  }

  topic_policy_config {
    topics_config {
      name       = "Non-Strategic-IT"
      definition = "Topics outside of strategic IT insights, such as medical, legal, financial advice, political opinions, personal matters, pricing discussions, contract negotiations, or operational minutiae."
      type       = "DENY"
      examples = [
        "What are the symptoms of the flu?",
        "Should I invest in stocks?",
        "How much does your service cost?",
        "Who should I vote for?"
      ]
    }
    topics_config {
      name       = "Alarming-Content"
      definition = "Language that could cause unnecessary panic or alarm, such as catastrophic predictions, emergency declarations without context, or blame-shifting language."
      type       = "DENY"
      examples = [
        "Your systems are completely compromised and you must shut everything down immediately",
        "Catastrophic failure imminent, all data will be lost",
        "This is entirely your fault for not upgrading"
      ]
    }
  }

  word_policy_config {
    managed_word_lists_config { type = "PROFANITY" }
  }
}

resource "aws_bedrock_guardrail_version" "customer_insights_v1" {
  guardrail_id = aws_bedrock_guardrail.customer_insights.id
  description  = "Initial version"
}

# =============================================================================
# SECRETS
# =============================================================================
resource "aws_secretsmanager_secret" "psa" {
  name                    = "${var.environment}/msp/psa/api_keys"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret" "rmm" {
  name                    = "${var.environment}/msp/rmm/api_keys"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret" "webhook" {
  name                    = "${var.environment}/msp/webhook/token"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret" "unsubscribe_signing" {
  name                    = "${var.environment}/msp/unsubscribe/signing_key"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret" "teams_bot_secret" {
  name                    = "${var.environment}/${var.teams_bot_shared_secret_name}"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret" "entra_graph" {
  name                    = "${var.environment}/${var.entra_graph_secret_name}"
  recovery_window_in_days = var.secret_recovery_window_days
}

# Agent confirmation signing key (for HMAC-bound approval nonces)
resource "aws_secretsmanager_secret" "agent_confirmation_signing" {
  name                    = "${var.environment}/msp/agent/confirmation_signing_key"
  recovery_window_in_days = var.secret_recovery_window_days
}

# SES identity for agent security notifications
resource "aws_ses_email_identity" "agent_notification_sender" {
  email = var.agent_notification_sender_email
}

# SES identity for password reset emails
resource "aws_ses_email_identity" "password_reset_sender" {
  email = var.password_reset_sender_email
}

# SES identity for weekly metrics reports
resource "aws_ses_email_identity" "metrics_report_sender" {
  email = var.metrics_report_sender_email
}

# SES identity for customer digest emails
resource "aws_ses_email_identity" "customer_digest_sender" {
  email = var.customer_digest_sender_email
}

# =============================================================================
# DYNAMODB - IDEMPOTENCY TABLE
# =============================================================================
resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.name_prefix}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticket_id"

  attribute { name = "ticket_id"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "Idempotency" }
}

# =============================================================================
# DYNAMODB - METRICS TABLE
# =============================================================================
resource "aws_dynamodb_table" "metrics" {
  name         = "${local.name_prefix}-metrics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticket_id"

  attribute { name = "ticket_id"; type = "S" }
  attribute { name = "timestamp"; type = "S" }

  global_secondary_index {
    name            = "timestamp-index"
    hash_key        = "timestamp"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "BusinessMetrics" }
}

# =============================================================================
# DYNAMODB - FEEDBACK TABLE
# =============================================================================
resource "aws_dynamodb_table" "feedback" {
  name         = "${local.name_prefix}-feedback"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticket_id"

  attribute { name = "ticket_id"; type = "S" }
  attribute { name = "status";    type = "S" }

  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "FeedbackLoop" }
}

# =============================================================================
# DYNAMODB - CUSTOMER PREFERENCES TABLE
# =============================================================================
resource "aws_dynamodb_table" "customer_preferences" {
  name         = "${local.name_prefix}-customer-preferences"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "customer_id"

  attribute { name = "customer_id"; type = "S" }
  attribute { name = "enabled";     type = "N" }

  global_secondary_index {
    name            = "enabled-index"
    hash_key        = "enabled"
    range_key       = "customer_id"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "CustomerPreferences" }
}

# =============================================================================
# DYNAMODB - CUSTOMER ALERT HISTORY TABLE
# =============================================================================
resource "aws_dynamodb_table" "customer_alert_history" {
  name         = "${local.name_prefix}-customer-alert-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "customer_id"
  range_key    = "date_key"

  attribute { name = "customer_id"; type = "S" }
  attribute { name = "date_key";    type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "CustomerAlertHistory" }
}

# =============================================================================
# DYNAMODB - CUSTOMER INSIGHTS PREFERENCES (NEW)
# Stores opt-in, contact info, timezone, cadence, and branding for strategic reports.
# =============================================================================
resource "aws_dynamodb_table" "customer_insights_preferences" {
  name         = "${local.name_prefix}-customer-insights-preferences"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "customer_id"

  attribute { name = "customer_id"; type = "S" }
  attribute { name = "enabled";     type = "N" }

  global_secondary_index {
    name            = "enabled-index"
    hash_key        = "enabled"
    range_key       = "customer_id"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "CustomerInsightsPreferences" }
}

# =============================================================================
# DYNAMODB - AGENT CONVERSATION STATE
# =============================================================================
resource "aws_dynamodb_table" "agent_conversations" {
  name         = "${local.name_prefix}-agent-conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute { name = "session_id"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "AgentConversations" }
}

# =============================================================================
# DYNAMODB - AGENT AUDIT LOG
# =============================================================================
resource "aws_dynamodb_table" "agent_audit_log" {
  name         = "${local.name_prefix}-agent-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "audit_id"
  range_key    = "timestamp"

  attribute { name = "audit_id";  type = "S" }
  attribute { name = "timestamp"; type = "S" }
  attribute { name = "user_id";   type = "S" }

  global_secondary_index {
    name            = "user-index"
    hash_key        = "user_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "AgentAuditLog" }
}

# =============================================================================
# DYNAMODB - AGENT RATE LIMITS (NEW for increment 2)
# =============================================================================
resource "aws_dynamodb_table" "agent_rate_limits" {
  name         = "${local.name_prefix}-agent-rate-limits"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute { name = "pk"; type = "S" }
  attribute { name = "sk"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "AgentRateLimits" }
}

# =============================================================================
# DYNAMODB - TENANT REGISTRY (Multi-Tenant Foundation)
# Maps external identifiers (Entra tenant ID, etc.) to internal tenant records.
# Each tenant has its own secrets, customers, and isolated data.
# =============================================================================
resource "aws_dynamodb_table" "tenant_registry" {
  name         = "${local.name_prefix}-tenant-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"

  attribute { name = "tenant_id";       type = "S" }
  attribute { name = "entra_tenant_id"; type = "S" }
  attribute { name = "enabled";         type = "N" }

  # Lookup by Entra tenant ID (from Teams activity)
  global_secondary_index {
    name            = "entra-tenant-index"
    hash_key        = "entra_tenant_id"
    projection_type = "ALL"
  }

  # Lookup enabled tenants
  global_secondary_index {
    name            = "enabled-index"
    hash_key        = "enabled"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = var.environment == "prod" }

  tags = { Purpose = "TenantRegistry" }
}

# =============================================================================
# DYNAMODB - STATUS CACHE (Phase C)
# Caches computed tenant status to avoid expensive on-demand computation.
# =============================================================================
resource "aws_dynamodb_table" "status_cache" {
  count        = var.enable_onboarding_api ? 1 : 0
  name         = "${local.name_prefix}-status-cache"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cache_key"

  attribute { name = "cache_key"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  tags = { Purpose = "StatusCache" }
}

# =============================================================================
# DYNAMODB - STATUS HISTORY (Sub-Phase 1)
# Stores daily snapshots of tenant status for trend analysis.
# =============================================================================
resource "aws_dynamodb_table" "status_history" {
  count        = var.enable_status_history ? 1 : 0
  name         = "${local.name_prefix}-status-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "snapshot_date"

  attribute { name = "tenant_id";      type = "S" }
  attribute { name = "snapshot_date";  type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "StatusHistory" }
}

# =============================================================================
# DYNAMODB - AGENT FEEDBACK TABLE (Phase 2: tenant-scoped)
# Stores user/IT staff feedback on agent responses.
# Now includes tenant_id for cross-tenant isolation.
# =============================================================================
resource "aws_dynamodb_table" "agent_feedback" {
  name         = "${local.name_prefix}-agent-feedback"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feedback_id"

  attribute { name = "feedback_id"; type = "S" }
  attribute { name = "status";      type = "S" }
  attribute { name = "created_at";  type = "S" }
  attribute { name = "tenant_id";   type = "S" }   # NEW

  # GSI for finding pending reviews (unchanged)
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # NEW: GSI for per-tenant queries (used by sync Lambda)
  global_secondary_index {
    name            = "tenant-status-index"
    hash_key        = "tenant_id"
    range_key       = "status"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "AgentFeedback" }
}

# =============================================================================
# DYNAMODB - DEVICE OWNERSHIP MAPPING (optional fallback for Increment 3)
# Maps user AAD IDs to NinjaOne device IDs when NinjaOne ownership fields
# are not populated. Maintained by IT via a separate sync process.
# =============================================================================
resource "aws_dynamodb_table" "device_ownership_mapping" {
  count        = var.ninjaone_device_mapping_table != "" ? 1 : 0
  name         = var.ninjaone_device_mapping_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_aad_id"
  range_key    = "device_id"

  attribute { name = "user_aad_id"; type = "S" }
  attribute { name = "device_id";   type = "S" }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "DeviceOwnershipMapping" }
}

# =============================================================================
# DYNAMODB - PENDING OPERATIONS (two-phase confirmation)
# =============================================================================
resource "aws_dynamodb_table" "agent_pending_operations" {
  name         = "${local.name_prefix}-agent-pending-operations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "confirmation_id"

  attribute { name = "confirmation_id"; type = "S" }
  attribute { name = "session_id";      type = "S" }
  attribute { name = "created_at";      type = "S" }

  global_secondary_index {
    name            = "session-index"
    hash_key        = "session_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "AgentPendingOperations" }
}

# =============================================================================
# DYNAMODB - CONFIRMATION NONCES
# Deliberately a SEPARATE table so IAM can withhold read access from the
# action-group Lambda. The nonce must never enter the agent's context.
#   identity_tools : PutItem only  (write, cannot read back)
#   teams_bot      : GetItem, DeleteItem (one-time read when composing the card)
# =============================================================================
resource "aws_dynamodb_table" "agent_confirmation_nonces" {
  name         = "${local.name_prefix}-agent-confirmation-nonces"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "confirmation_id"

  attribute { name = "confirmation_id"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "AgentConfirmationNonces" }
}

# =============================================================================
# DYNAMODB - PASSWORD RESET TOKENS
# Stores one-time tokens for secure password reset flow.
# Tokens are single-use, time-limited, and bound to a specific user.
# =============================================================================
resource "aws_dynamodb_table" "password_reset_tokens" {
  name         = "${local.name_prefix}-password-reset-tokens"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token"

  attribute { name = "token";      type = "S" }
  attribute { name = "user_aad_id"; type = "S" }

  # GSI for querying tokens by user (useful for audit / revocation)
  global_secondary_index {
    name            = "user-index"
    hash_key        = "user_aad_id"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "PasswordResetTokens" }
}

# =============================================================================
# S3 - FEW-SHOT EXAMPLES STORE
# =============================================================================
resource "aws_s3_bucket_policy" "few_shot_examples_tls" {
  bucket = aws_s3_bucket.few_shot_examples.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.few_shot_examples.arn,
        "${aws_s3_bucket.few_shot_examples.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_s3_bucket_versioning" "few_shot_examples" {
  bucket = aws_s3_bucket.few_shot_examples.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "few_shot_examples" {
  bucket = aws_s3_bucket.few_shot_examples.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "few_shot_examples" {
  bucket                  = aws_s3_bucket.few_shot_examples.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "few_shot_examples_init" {
  bucket       = aws_s3_bucket.few_shot_examples.id
  key          = "examples.json"
  content      = "[]"
  content_type = "application/json"
}

# =============================================================================
# S3 - CUSTOMER BRANDING ASSETS
# =============================================================================
resource "aws_s3_bucket_customer" "customer_branding_tls" {
  bucket = aws_s3_bucket.customer_branding.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.customer_branding.arn,
        "${aws_s3_bucket.customer_branding}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "customer_branding" {
  bucket = aws_s3_bucket.customer_branding.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "customer_branding" {
  bucket                  = aws_s3_bucket.customer_branding.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =============================================================================
# S3 - AGENT SCHEMAS (UPDATED for increment 2)
# =============================================================================
resource "aws_s3_bucket" "agent_schemas" {
  bucket = "${local.name_prefix}-agent-schemas-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agent_schemas" {
  bucket = aws_s3_bucket.agent_schemas.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "agent_schemas" {
  bucket                  = aws_s3_bucket.agent_schemas.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =============================================================================
# S3 BUCKET POLICY - AGENT SCHEMAS (TLS-ONLY)
# Denies all non-HTTPS access to the agent schemas bucket.
# =============================================================================
resource "aws_s3_bucket_policy" "agent_schemas_tls" {
  bucket = aws_s3_bucket.agent_schemas.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.agent_schemas.arn,
        "${aws_s3_bucket.agent_schemas.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_s3_object" "identity_tools_schema" {
  bucket       = aws_s3_bucket.agent_schemas.id
  key          = "identity-tools-schema.json"
  content_type = "application/json"
  content = jsonencode({
    openapi = "3.0.0"
    info = {
      title   = "Identity Tools"
      version = "3.0.0"
    }
    paths = {
      "/get-user-info" = {
        post = {
          operationId = "getUserInfo"
          summary     = "Get information about a user by email or name"
          description = "Look up a user's basic information including display name, job title, department, and manager."
          parameters = [{
            name        = "user_identifier"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "Email address or display name of the user to look up"
          }]
          responses = {
            "200" = {
              description = "User information retrieved successfully"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success      = { type = "boolean" }
                      user_id      = { type = "string" }
                      display_name = { type = "string" }
                      email        = { type = "string" }
                      job_title    = { type = "string" }
                      department   = { type = "string" }
                      manager      = { type = "string" }
                      error        = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/verify-identity" = {
        post = {
          operationId = "verifyIdentity"
          summary     = "Verify a user's identity and check account status"
          description = "Check a user's MFA status, last sign-in time, and account enabled status."
          parameters = [{
            name        = "user_id"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "The user's unique ID (from get-user-info)"
          }]
          responses = {
            "200" = {
              description = "Verification result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success         = { type = "boolean" }
                      is_verified     = { type = "boolean" }
                      mfa_enabled     = { type = "boolean" }
                      last_sign_in    = { type = "string" }
                      account_enabled = { type = "boolean" }
                      error           = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/check-account-lockout" = {
        post = {
          operationId = "checkAccountLockout"
          summary     = "Check if a user's account is locked out"
          description = "Check whether a user's account is currently locked out. This is a read-only operation."
          parameters = [{
            name        = "user_identifier"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "Email address or display name of the user"
          }]
          responses = {
            "200" = {
              description = "Lockout status"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success              = { type = "boolean" }
                      is_locked_out        = { type = "boolean" }
                      failed_sign_in_count = { type = "integer" }
                      lockout_timestamp    = { type = "string" }
                      error                = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/request-password-reset" = {
        post = {
          operationId = "requestPasswordReset"
          summary     = "Request a password reset (phase 1 of two-phase flow)"
          description = "Creates a pending operation. An approval card will be sent to the user. The user must click Approve on the card before the operation can be executed. Do NOT ask the user to type CONFIRM."
          parameters = [
            {
              name        = "target_user_identifier"
              in          = "query"
              required    = true
              schema      = { type = "string" }
              description = "Email address or display name of the user whose password should be reset"
            },
            {
              name        = "justification"
              in          = "query"
              required    = false
              schema      = { type = "string" }
              description = "Business reason for resetting another user's password (required for admin overrides, at least 20 characters)"
            }
          ]
          responses = {
            "200" = {
              description = "Request result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success               = { type = "boolean" }
                      confirmation_id       = { type = "string" }
                      operation_type        = { type = "string" }
                      target_display_name   = { type = "string" }
                      is_admin_override     = { type = "boolean" }
                      expires_in_seconds    = { type = "integer" }
                      user_message          = { type = "string" }
                      error                 = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/execute-password-reset" = {
        post = {
          operationId = "executePasswordReset"
          summary     = "Execute a password reset (phase 2 of two-phase flow)"
          description = "Executes the password reset for a previously approved operation. The confirmation_id must be from a request_password_reset call that was approved via the Teams card."
          parameters = [{
            name        = "confirmation_id"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "The confirmation_id returned by request_password_reset"
          }]
          responses = {
            "200" = {
              description = "Execution result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success                   = { type = "boolean" }
                      temp_password             = { type = "string" }
                      must_change_at_next_login = { type = "boolean" }
                      message                   = { type = "string" }
                      error                     = { type = "string" }
                      retryable                 = { type = "boolean" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/request-account-unlock" = {
        post = {
          operationId = "requestAccountUnlock"
          summary     = "Request an account unlock (phase 1 of two-phase flow)"
          description = "Creates a pending operation. An approval card will be sent to the user. The user must click Approve on the card before the operation can be executed."
          parameters = [
            {
              name        = "target_user_identifier"
              in          = "query"
              required    = true
              schema      = { type = "string" }
              description = "Email address or display name of the user whose account should be unlocked"
            },
            {
              name        = "justification"
              in          = "query"
              required    = false
              schema      = { type = "string" }
              description = "Business reason for unlocking another user's account (required for admin overrides, at least 20 characters)"
            }
          ]
          responses = {
            "200" = {
              description = "Request result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success               = { type = "boolean" }
                      confirmation_id       = { type = "string" }
                      operation_type        = { type = "string" }
                      target_display_name   = { type = "string" }
                      is_admin_override     = { type = "boolean" }
                      expires_in_seconds    = { type = "integer" }
                      user_message          = { type = "string" }
                      error                 = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/execute-account-unlock" = {
        post = {
          operationId = "executeAccountUnlock"
          summary     = "Execute an account unlock (phase 2 of two-phase flow)"
          description = "Executes the account unlock for a previously approved operation. The confirmation_id must be from a request_account_unlock call that was approved via the Teams card."
          parameters = [{
            name        = "confirmation_id"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "The confirmation_id returned by request_account_unlock"
          }]
          responses = {
            "200" = {
              description = "Execution result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success      = { type = "boolean" }
                      was_disabled = { type = "boolean" }
                      message      = { type = "string" }
                      error        = { type = "string" }
                      retryable    = { type = "boolean" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      "/get-operation-status" = {
        post = {
          operationId = "getOperationStatus"
          summary     = "Check the status of a pending operation"
          description = "Returns the current status of a pending operation (pending_approval, approved, consumed, denied, expired, or failed)."
          parameters = [{
            name        = "confirmation_id"
            in          = "query"
            required    = true
            schema      = { type = "string" }
            description = "The confirmation_id to check"
          }]
          responses = {
            "200" = {
              description = "Status result"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      found               = { type = "boolean" }
                      status              = { type = "string" }
                      operation_type      = { type = "string" }
                      target_display_name = { type = "string" }
                      approved            = { type = "boolean" }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  })
}

# =============================================================================
# S3 - AGENT FEW-SHOT EXAMPLES (for continuous improvement)
# Initialized with an empty array; populated by agent_feedback_sync Lambda.
# =============================================================================
resource "aws_s3_object" "agent_examples_init" {
  bucket       = aws_s3_bucket.agent_schemas.id
  key          = "agent-examples.json"
  content      = "[]"
  content_type = "application/json"
}

resource "aws_s3_object" "ticket_tools_schema" {
  bucket       = aws_s3_bucket.agent_schemas.id
  key          = "ticket-tools-schema.json"
  content_type = "application/json"
  content = jsonencode({
    openapi = "3.0.0"
    info    = { title = "Ticket Tools", version = "1.0.0" }
    paths = {
      "/create-ticket" = {
        post = {
          operationId = "createTicket"
          summary     = "Create a new support ticket"
          description = "Creates a new support ticket in ConnectWise. Uses conversational confirmation — ask the user to confirm before calling."
          parameters = [
            { name = "summary", in = "query", required = true, schema = { type = "string" }, description = "Brief summary of the issue" },
            { name = "description", in = "query", required = true, schema = { type = "string" }, description = "Detailed description of the issue" },
          ]
          responses = { "200" = { description = "Ticket created", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, ticket_id = { type = "integer" }, message = { type = "string" }, error = { type = "string" } } } } } } }
        }
      }
      "/get-ticket-status" = {
        post = {
          operationId = "getTicketStatus"
          summary     = "Get the status of a support ticket"
          parameters = [{ name = "ticket_id", in = "query", required = true, schema = { type = "integer" }, description = "The ticket ID to look up" }]
          responses = { "200" = { description = "Ticket status", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, ticket_id = { type = "integer" }, status = { type = "string" }, summary = { type = "string" }, board = { type = "string" }, error = { type = "string" } } } } } } }
        }
      }
      "/list-my-tickets" = {
        post = {
          operationId = "listMyTickets"
          summary     = "List recent tickets for the current user"
          parameters = [{ name = "limit", in = "query", required = false, schema = { type = "integer", default = 5 }, description = "Maximum number of tickets to return (default 5, max 20)" }]
          responses = { "200" = { description = "List of tickets", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, tickets = { type = "array", items = { type = "object" } }, count = { type = "integer" }, error = { type = "string" } } } } } } }
        }
      }
    }
  })
}

resource "aws_s3_object" "device_tools_schema" {
  bucket       = aws_s3_bucket.agent_schemas.id
  key          = "device-tools-schema.json"
  content_type = "application/json"
  content = jsonencode({
    openapi = "3.0.0"
    info    = { title = "Device Tools", version = "1.0.0" }
    paths = {
      "/list-my-devices" = {
        post = {
          operationId = "listMyDevices"
          summary     = "List devices owned by the current user"
          description = "Returns devices where the user is listed as the owner. If no ownership mapping exists, returns an empty list."
          responses = { "200" = { description = "List of devices", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, devices = { type = "array", items = { type = "object" } }, count = { type = "integer" }, error = { type = "string" } } } } } } }
        }
      }
      "/get-device-status" = {
        post = {
          operationId = "getDeviceStatus"
          summary     = "Get the status of a specific device"
          parameters = [{ name = "device_id", in = "query", required = true, schema = { type = "string" }, description = "The NinjaOne device ID" }]
          responses = { "200" = { description = "Device status", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, device_id = { type = "string" }, device_name = { type = "string" }, status = { type = "string" }, last_seen = { type = "string" }, error = { type = "string" } } } } } } }
        }
      }
      "/get-device-alerts" = {
        post = {
          operationId = "getDeviceAlerts"
          summary     = "Get recent alerts for a specific device"
          parameters = [
            { name = "device_id", in = "query", required = true, schema = { type = "string" }, description = "The NinjaOne device ID" },
            { name = "limit", in = "query", required = false, schema = { type = "integer", default = 10 }, description = "Maximum number of alerts to return" },
          ]
          responses = { "200" = { description = "List of alerts", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, alerts = { type = "array", items = { type = "object" } }, count = { type = "integer" }, error = { type = "string" } } } } } } }
        }
      }
    }
  })
}

resource "aws_s3_object" "calendar_tools_schema" {
  bucket       = aws_s3_bucket.agent_schemas.id
  key          = "calendar-tools-schema.json"
  content_type = "application/json"
  content = jsonencode({
    openapi = "3.0.0"
    info    = { title = "Calendar Tools", version = "1.0.0" }
    paths = {
      # 1. List calendar events
      "/list-my-calendar" = {
        post = {
          operationId = "listMyCalendar"
          summary     = "List upcoming calendar events for the current user"
          parameters = [
            { name = "hours_ahead", in = "query", required = false, schema = { type = "integer", default = 24 }, description = "How many hours ahead to look (default 24, max 168)" },
            { name = "limit", in = "query", required = false, schema = { type = "integer", default = 10 }, description = "Maximum number of events to return" },
          ]
          responses = { "200" = { description = "List of events", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, events = { type = "array", items = { type = "object" } }, count = { type = "integer" }, error = { type = "string" } } } } } } }
        }
      }
      
      # 2. Find free time (proper implementation)
      "/find-free-time" = {
        post = {
          operationId = "findFreeTime"
          summary     = "Find free time slots in the user's calendar"
          description = "Returns available time slots for a meeting of the specified duration. Optionally filter by working hours and exclude weekends."
          parameters = [
            { name = "duration_minutes", in = "query", required = true, schema = { type = "integer" }, description = "Duration of the meeting in minutes (15-480)" },
            { name = "hours_ahead", in = "query", required = false, schema = { type = "integer", default = 48 }, description = "How many hours ahead to search (default 48, max 168 = 1 week)" },
            { name = "limit", in = "query", required = false, schema = { type = "integer", default = 5 }, description = "Maximum number of slots to return (default 5, max 10)" },
            { name = "work_start_hour", in = "query", required = false, schema = { type = "integer" }, description = "Only return slots starting at or after this hour (0-23, UTC)" },
            { name = "work_end_hour", in = "query", required = false, schema = { type = "integer" }, description = "Only return slots starting before this hour (0-23, UTC)" },
            { name = "skip_weekends", in = "query", required = false, schema = { type = "boolean", default = false }, description = "If true, exclude Saturday and Sunday" },
          ]
          responses = {
            "200" = {
              description = "List of free time slots"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      success = { type = "boolean" }
                      slots = {
                        type = "array"
                        items = {
                          type = "object"
                          properties = {
                            start = { type = "string", description = "ISO 8601 start time" }
                            end = { type = "string", description = "ISO 8601 end time" }
                            duration_minutes = { type = "integer" }
                            day_of_week = { type = "string", description = "e.g., Monday" }
                            date = { type = "string", description = "YYYY-MM-DD" }
                            time = { type = "string", description = "HH:MM" }
                          }
                        }
                      }
                      count = { type = "integer" }
                      message = { type = "string" }
                      error = { type = "string" }
                    }
                  }
                }
              }
            }
          }
        }
      }
      
      # 3. List bookable rooms
      "/list-bookable-rooms" = {
        post = {
          operationId = "listBookableRooms"
          summary     = "List bookable meeting rooms"
          parameters = [{ name = "limit", in = "query", required = false, schema = { type = "integer", default = 20 }, description = "Maximum number of rooms to return" }]
          responses = { "200" = { description = "List of rooms", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, rooms = { type = "array", items = { type = "object" } }, count = { type = "integer" }, error = { type = "string" } } } } } } }
        }
      }
      
      # 4. Request room booking (phase 1)
      "/request-room-booking" = {
        post = {
          operationId = "requestRoomBooking"
          summary     = "Request a room booking (phase 1 of two-phase flow)"
          description = "Creates a pending room booking. An approval card will be sent to the user."
          parameters = [
            { name = "room_email", in = "query", required = true, schema = { type = "string" }, description = "Email address of the room to book" },
            { name = "subject", in = "query", required = true, schema = { type = "string" }, description = "Meeting subject" },
            { name = "start_time", in = "query", required = true, schema = { type = "string" }, description = "Start time in ISO 8601 format" },
            { name = "duration_minutes", in = "query", required = true, schema = { type = "integer" }, description = "Duration in minutes" },
          ]
          responses = { "200" = { description = "Booking request result", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, confirmation_id = { type = "string" }, user_message = { type = "string" }, error = { type = "string" } } } } } } }
        }
      }
      
      # 5. Execute room booking (phase 2)
      "/execute-room-booking" = {
        post = {
          operationId = "executeRoomBooking"
          summary     = "Execute a room booking (phase 2 of two-phase flow)"
          parameters = [
            { name = "confirmation_id", in = "query", required = true, schema = { type = "string" }, description = "The confirmation_id from request_room_booking" },
            { name = "subject", in = "query", required = true, schema = { type = "string" }, description = "Meeting subject" },
            { name = "start_time", in = "query", required = true, schema = { type = "string" }, description = "Start time in ISO 8601 format" },
            { name = "duration_minutes", in = "query", required = true, schema = { type = "integer" }, description = "Duration in minutes" },
          ]
          responses = { "200" = { description = "Booking result", content = { "application/json" = { schema = { type = "object", properties = { success = { type = "boolean" }, event_id = { type = "string" }, message = { type = "string" }, error = { type = "string" } } } } } } }
        }
      }
    }
  })
}

# =============================================================================
# S3 - KNOWLEDGE BASE DOCUMENTS
# Stores tenant-scoped documents for RAG ingestion.
# Only created if enable_knowledge_base = true.
# =============================================================================
resource "aws_s3_bucket_policy" "kb_documents_tls" {
  bucket = aws_s3_bucket.few_shot_examples.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.kb_documents.arn,
        "${aws_s3_bucket.kb_documents.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_s3_bucket_versioning" "kb_documents" {
  count  = var.enable_knowledge_base ? 1 : 0
  bucket = aws_s3_bucket.kb_documents[0].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "kb_documents" {
  count  = var.enable_knowledge_base ? 1 : 0
  bucket = aws_s3_bucket.kb_documents[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# =============================================================================
# S3 LIFECYCLE - KB DOCUMENTS (VERSIONED BUCKET CLEANUP)
# Automatically expires old object versions after 90 days to control costs.
# NOTE: This is a cost backstop only. Tenant data deletion is handled
# explicitly by the deprovisioning worker (version-aware purge).
# =============================================================================
resource "aws_s3_bucket_lifecycle_configuration" "kb_documents" {
  count  = var.enable_knowledge_base ? 1 : 0
  bucket = aws_s3_bucket.kb_documents[0].id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "kb_documents" {
  count                   = var.enable_knowledge_base ? 1 : 0
  bucket                  = aws_s3_bucket.kb_documents[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Initialize tenant folder structure with placeholder objects
resource "aws_s3_object" "kb_tenant_folders" {
  for_each = var.enable_knowledge_base ? var.tenants : {}

  bucket  = aws_s3_bucket.kb_documents[0].id
  key     = "tenants/${each.key}/.keep"
  content = "placeholder"
}

# =============================================================================
# OPENSEARCH SERVERLESS - VECTOR STORE FOR KB
# Only created if enable_knowledge_base = true AND kb_vector_store_type = "opensearch_serverless"
# WARNING: Minimum cost is ~$700/month (4 indexing OCUs)
# =============================================================================
resource "aws_opensearchserverless_security_policy" "kb_encryption" {
  count = var.enable_knowledge_base && var.kb_vector_store_type == "opensearch_serverless" ? 1 : 0

  name = "${replace(local.name_prefix, "-", "")}kbenc"
  type = "encryption"
  policy = jsonencode({
    Rules = [{
      Resource     = ["collection/${replace(local.name_prefix, "-", "")}kb"]
      ResourceType = "collection"
    }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "kb_network" {
  count = var.enable_knowledge_base && var.kb_vector_store_type == "opensearch_serverless" ? 1 : 0

  name = "${replace(local.name_prefix, "-", "")}kbnet"
  type = "network"
  policy = jsonencode([
    {
      Rules = [{
        Resource     = ["collection/${replace(local.name_prefix, "-", "")}kb"]
        ResourceType = "collection"
      }]
      AllowFromPublic = true  # Restrict to VPC in production!
    }
  ])
}

resource "aws_opensearchserverless_collection" "kb_vectors" {
  count = var.enable_knowledge_base && var.kb_vector_store_type == "opensearch_serverless" ? 1 : 0

  name = "${replace(local.name_prefix, "-", "")}kb"
  type = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.kb_encryption,
    aws_opensearchserverless_security_policy.kb_network,
  ]
}

# =============================================================================
# IAM - BEDROCK KB SERVICE ROLE
# This role is assumed by the Bedrock service to access S3, embeddings, and AOSS.
# =============================================================================
resource "aws_iam_role" "kb_service" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${local.name_prefix}-kb-service"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "kb_service" {
  count = var.enable_knowledge_base ? 1 : 0
  role  = aws_iam_role.kb_service[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "ReadS3Documents"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.kb_documents[0].arn,
          "${aws_s3_bucket.kb_documents[0].arn}/*"
        ]
      },
      {
        Sid = "InvokeEmbeddingModel"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.kb_embedding_model_id}"
      },
      {
        Sid = "OpenSearchAccess"
        Effect = "Allow"
        Action = ["aoss:APIAccessAll"]
        Resource = aws_opensearchserverless_collection.kb_vectors[0].arn
      }
    ]
  })
}

# =============================================================================
# IAM - KB INGESTION LAMBDA ROLE
# =============================================================================
resource "aws_iam_role" "kb_ingestion" {
  count = var.enable_knowledge_base ? 1 : 0
  name  = "${local.name_prefix}-kb-ingestion"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "kb_ingestion" {
  count = var.enable_knowledge_base ? 1 : 0
  role  = aws_iam_role.kb_ingestion[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "ReadS3Documents"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.kb_documents[0].arn,
          "${aws_s3_bucket.kb_documents[0].arn}/*"
        ]
      },
      {
        Sid = "StartKBSync"
        Effect = "Allow"
        Action = ["bedrock:StartIngestionJob"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:knowledge-base/*"
        ]
      },
      {
        Sid = "WriteLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-kb-document-processor:*"]
      }
    ]
  })
}

# AOSS data access policy: allows Bedrock and ingestion Lambda to read/write
resource "aws_opensearchserverless_access_policy" "kb_data" {
  count = var.enable_knowledge_base && var.kb_vector_store_type == "opensearch_serverless" ? 1 : 0

  name = "${replace(local.name_prefix, "-", "")}kbdata"
  type = "data"
  policy = jsonencode([
    {
      Rules = [
        {
          Resource     = ["collection/${replace(local.name_prefix, "-", "")}kb"]
          ResourceType = "collection"
          Permission   = ["aoss:DescribeCollectionItems", "aoss:CreateCollectionItems", "aoss:UpdateCollectionItems"]
        },
        {
          Resource     = ["index/${replace(local.name_prefix, "-", "")}kb/*"]
          ResourceType = "index"
          Permission = [
            "aoss:DescribeIndex",
            "aoss:CreateIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndexItems",
            "aoss:CreateIndexItems",
            "aoss:UpdateIndexItems",
            "aoss:DeleteIndexItems"
          ]
        }
      ]
      Principal = [
        aws_iam_role.bedrock_agent.arn,
        aws_iam_role.kb_service[0].arn,
        aws_iam_role.kb_ingestion[0].arn
      ]
    }
  ])
}

# =============================================================================
# BEDROCK KNOWLEDGE BASE
# =============================================================================
resource "aws_bedrockagent_knowledge_base" "it_concierge" {
  count = var.enable_knowledge_base ? 1 : 0

  name        = "${local.name_prefix}-it-concierge-kb"
  description = "Tenant-scoped knowledge base for IT Concierge agent (RAG)"
  role_arn    = aws_iam_role.kb_service[0].arn

  knowledge_base_configuration {
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.kb_embedding_model_id}"
    }
    type = "VECTOR"
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb_vectors[0].arn
      vector_index_name = "bedrock-kb-index"
      field_mapping {
        metadata_field = "METADATA"
        primary_key    = "ID"
        text_field     = "bedrock-kb-text"
        vector_field   = "bedrock-kb-vector"
      }
    }
  }

  depends_on = [
    aws_opensearchserverless_access_policy.kb_data,
    aws_iam_role_policy.kb_service,
  ]
}

# Data source pointing to S3 bucket
resource "aws_bedrockagent_data_source" "kb_documents" {
  count = var.enable_knowledge_base ? 1 : 0

  knowledge_base_id = aws_bedrockagent_knowledge_base.it_concierge[0].id
  name              = "tenant-documents"
  description       = "Tenant-scoped documents from S3"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.kb_documents[0].arn
      inclusion_prefixes = ["tenants/"]
    }
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = var.kb_chunk_size
        overlap_percentage = var.kb_chunk_overlap > 0 ? ceil(var.kb_chunk_overlap * 100 / var.kb_chunk_size) : 0
      }
    }
  }

  depends_on = [aws_iam_role_policy.kb_ingestion]
}

# =============================================================================
# PACKAGING
# =============================================================================
data "archive_file" "orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/.build/orchestrator.zip"
}

data "archive_file" "authorizer" {
  type        = "zip"
  source_dir  = "${path.module}/src_authorizer"
  output_path = "${path.module}/.build/authorizer.zip"
}

data "archive_file" "metrics_reporter" {
  type        = "zip"
  source_dir  = "${path.module}/src_metrics_reporter"
  output_path = "${path.module}/.build/metrics_reporter.zip"
}

data "archive_file" "feedback_collector" {
  type        = "zip"
  source_dir  = "${path.module}/src_feedback_collector"
  output_path = "${path.module}/.build/feedback_collector.zip"
}

data "archive_file" "feedback_sync" {
  type        = "zip"
  source_dir  = "${path.module}/src_feedback_sync"
  output_path = "${path.module}/.build/feedback_sync.zip"
}

data "archive_file" "customer_digest_orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/src_customer_digest_orchestrator"
  output_path = "${path.module}/.build/customer_digest_orchestrator.zip"
}

data "archive_file" "customer_digest_worker" {
  type        = "zip"
  source_dir  = "${path.module}/src_customer_digest_worker"
  output_path = "${path.module}/.build/customer_digest_worker.zip"
}

data "archive_file" "unsubscribe_handler" {
  type        = "zip"
  source_dir  = "${path.module}/src_unsubscribe"
  output_path = "${path.module}/.build/unsubscribe.zip"
}

data "archive_file" "customer_insights_orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/src_customer_insights_orchestrator"
  output_path = "${path.module}/.build/customer_insights_orchestrator.zip"
}

data "archive_file" "customer_insights_worker" {
  type        = "zip"
  source_dir  = "${path.module}/src_customer_insights_worker"
  output_path = "${path.module}/.build/customer_insights_worker.zip"
}

data "archive_file" "customer_insights_unsubscribe" {
  type        = "zip"
  source_dir  = "${path.module}/src_customer_insights_unsubscribe"
  output_path = "${path.module}/.build/customer_insights_unsubscribe.zip"
}

data "archive_file" "identity_tools" {
  type        = "zip"
  source_dir  = "${path.module}/src_identity_tools"
  output_path = "${path.module}/.build/identity_tools.zip"
}

data "archive_file" "reset_password" {
  type        = "zip"
  source_dir  = "${path.module}/src_reset_password"
  output_path = "${path.module}/.build/reset_password.zip"
}

data "archive_file" "teams_bot" {
  type        = "zip"
  source_dir  = "${path.module}/src_teams_bot"
  output_path = "${path.module}/.build/teams_bot.zip"
# Verify the JWT validation layer zip exists before packaging
# Run: cd layers/bot_framework_jwt && ./build.sh
}

data "archive_file" "ticket_tools" {
  type        = "zip"
  source_dir  = "${path.module}/src_ticket_tools"
  output_path = "${path.module}/.build/ticket_tools.zip"
}

data "archive_file" "device_tools" {
  type        = "zip"
  source_dir  = "${path.module}/src_device_tools"
  output_path = "${path.module}/.build/device_tools.zip"
}

data "archive_file" "calendar_tools" {
  type        = "zip"
  source_dir  = "${path.module}/src_calendar_tools"
  output_path = "${path.module}/.build/calendar_tools.zip"
}

data "archive_file" "kb_document_processor" {
  count       = var.enable_knowledge_base ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_kb_document_processor"
  output_path = "${path.module}/.build/kb_document_processor.zip"
}

data "archive_file" "agent_feedback_handler" {
  type        = "zip"
  source_dir  = "${path.module}/src_agent_feedback"
  output_path = "${path.module}/.build/agent_feedback.zip"
}

data "archive_file" "agent_feedback_sync" {
  type        = "zip"
  source_dir  = "${path.module}/src_agent_feedback_sync"
  output_path = "${path.module}/.build/agent_feedback_sync.zip"
}

# =============================================================================
# LOG GROUPS
# =============================================================================
resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/aws/lambda/${local.name_prefix}-orchestrator"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "authorizer" {
  name              = "/aws/lambda/${local.name_prefix}-authorizer"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "apigw" {
  name              = "/aws/apigateway/${local.name_prefix}-webhook"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "metrics_reporter" {
  name              = "/aws/lambda/${local.name_prefix}-metrics-reporter"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "feedback_collector" {
  name              = "/aws/lambda/${local.name_prefix}-feedback-collector"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "feedback_sync" {
  name              = "/aws/lambda/${local.name_prefix}-feedback-sync"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_digest_orchestrator" {
  name              = "/aws/lambda/${local.name_prefix}-customer-digest-orchestrator"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_digest_worker" {
  name              = "/aws/lambda/${local.name_prefix}-customer-digest-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "unsubscribe_handler" {
  name              = "/aws/lambda/${local.name_prefix}-unsubscribe"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "unsubscribe_apigw" {
  name              = "/aws/apigateway/${local.name_prefix}-unsubscribe"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_insights_orchestrator" {
  name              = "/aws/lambda/${local.name_prefix}-customer-insights-orchestrator"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_insights_worker" {
  name              = "/aws/lambda/${local.name_prefix}-customer-insights-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_insights_unsubscribe" {
  name              = "/aws/lambda/${local.name_prefix}-customer-insights-unsubscribe"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "customer_insights_apigw" {
  name              = "/aws/apigateway/${local.name_prefix}-customer-insights"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "identity_tools" {
  name              = "/aws/lambda/${local.name_prefix}-identity-tools"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "teams_bot" {
  name              = "/aws/lambda/${local.name_prefix}-teams-bot"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "teams_bot_apigw" {
  name              = "/aws/apigateway/${local.name_prefix}-teams-bot"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "kb_ingestion" {
  count             = var.enable_knowledge_base ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-kb-document-processor"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ticket_tools" {
  name              = "/aws/lambda/${local.name_prefix}-ticket-tools"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "device_tools" {
  name              = "/aws/lambda/${local.name_prefix}-device-tools"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "calendar_tools" {
  name              = "/aws/lambda/${local.name_prefix}-calendar-tools"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "reset_password" {
  name              = "/aws/lambda/${local.name_prefix}-reset-password"
  retention_in_days = var.log_retention_days
}

# =============================================================================
# QUEUES
# =============================================================================
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name_prefix}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "tickets" {
  name                       = "${local.name_prefix}-tickets"
  visibility_timeout_seconds = var.lambda_timeout_seconds * 6
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "customer_digest_dlq" {
  name                      = "${local.name_prefix}-customer-digest-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "customer_digest" {
  name                       = "${local.name_prefix}-customer-digest"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.customer_digest_dlq.arn
    maxReceiveCount     = 2
  })
}

# =============================================================================
# SQS - CUSTOMER INSIGHTS QUEUE + DLQ (NEW)
# =============================================================================
resource "aws_sqs_queue" "customer_insights_dlq" {
  name                      = "${local.name_prefix}-customer-insights-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "customer_insights" {
  name                       = "${local.name_prefix}-customer-insights"
  visibility_timeout_seconds = 300  # 5 minutes per customer (reports take longer)
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.customer_insights_dlq.arn
    maxReceiveCount     = 2
  })
}

# =============================================================================
# IAM - SHARED ASSUME-ROLE
# =============================================================================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# =============================================================================
# LAMBDA LAYER - BOT FRAMEWORK JWT VALIDATION
# Provides PyJWT and cryptography libraries for JWT signature verification.
# =============================================================================
resource "aws_lambda_layer_version" "bot_framework_jwt" {
  filename            = "${path.module}/layers/bot_framework_jwt/bot_framework_jwt.zip"
  layer_name          = "${local.name_prefix}-bot-framework-jwt"
  description         = "PyJWT and cryptography for Bot Framework JWT validation"
  compatible_runtimes = ["python3.13"]
  
  # Force recreation if the zip changes
  source_code_hash = filebase64sha256("${path.module}/layers/bot_framework_jwt/bot_framework_jwt.zip")
}

# =============================================================================
# IAM - ORCHESTRATOR (ticket triage)
# =============================================================================
resource "aws_iam_role" "orchestrator" {
  name               = "${local.name_prefix}-orchestrator"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "orchestrator" {
  statement {
    sid     = "BedrockInvoke"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.foundation_model_id}",
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.fallback_model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.fallback_foundation_model_id}",
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.haiku_model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.haiku_foundation_model_id}",
    ]
  }

  statement {
    sid     = "BedrockGuardrail"
    actions = ["bedrock:ApplyGuardrail"]
    resources = [
      aws_bedrock_guardrail.triage.arn,
      aws_bedrock_guardrail_version.triage_v1.arn,
    ]
  }

  statement {
    sid       = "ReadApiSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.psa.arn, aws_secretsmanager_secret.rmm.arn]
  }

  statement {
    sid     = "ConsumeQueue"
    actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.tickets.arn]
  }

  statement {
    sid       = "IdempotencyTable"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.idempotency.arn]
  }

  statement {
    sid       = "WriteMetrics"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.metrics.arn]
  }

  statement {
    sid       = "ReadFewShotExamples"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.few_shot_examples.arn}/examples.json"]
  }

  statement {
    sid       = "EmitCustomMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.orchestrator.arn}:*"]
  }
}

resource "aws_iam_role_policy" "orchestrator" {
  name   = "${local.name_prefix}-orchestrator"
  role   = aws_iam_role.orchestrator.id
  policy = data.aws_iam_policy_document.orchestrator.json
}

resource "aws_lambda_function" "orchestrator" {
  function_name    = "${local.name_prefix}-orchestrator"
  role             = aws_iam_role.orchestrator.arn
  runtime          = "python3.13"
  handler          = "lambda_function.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.orchestrator.output_path
  source_code_hash = data.archive_file.orchestrator.output_base64sha256
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb

  tracing_config { mode = "Active" }

  environment {
    variables = {
      MODEL_ID                            = var.model_id
      FALLBACK_MODEL_ID                   = var.fallback_model_id
      HAIKU_MODEL_ID                      = var.haiku_model_id
      ENABLE_COST_OPTIMIZATION            = tostring(var.enable_cost_optimization)
      SIMPLE_TICKET_CONFIDENCE_THRESHOLD  = tostring(var.simple_ticket_confidence_threshold)
      SIMPLE_TICKET_MAX_TOKENS            = tostring(var.simple_ticket_max_tokens)
      MAX_RETRIES                         = tostring(var.max_retries)
      RETRY_BASE_DELAY_MS                 = tostring(var.retry_base_delay_ms)
      PSA_SECRET_NAME                     = aws_secretsmanager_secret.psa.name
      RMM_SECRET_NAME                     = aws_secretsmanager_secret.rmm.name
      GUARDRAIL_ID                        = aws_bedrock_guardrail.triage.id
      GUARDRAIL_VERSION                   = aws_bedrock_guardrail_version.triage_v1.guardrail_version
      IDEMPOTENCY_TABLE                   = aws_dynamodb_table.idempotency.name
      IDEMPOTENCY_TTL_DAYS                = "30"
      METRICS_TABLE                       = aws_dynamodb_table.metrics.name
      METRICS_TTL_DAYS                    = tostring(var.metrics_retention_days)
      FEW_SHOT_EXAMPLES_BUCKET            = aws_s3_bucket.few_shot_examples.id
      FEW_SHOT_EXAMPLES_KEY               = "examples.json"
      MAX_FEW_SHOT_EXAMPLES               = tostring(var.max_few_shot_examples)
      FEW_SHOT_CACHE_TTL                  = tostring(var.few_shot_examples_cache_ttl_seconds)
      LOG_LEVEL                           = var.environment == "prod" ? "INFO" : "DEBUG"
    }
  }

  depends_on = [aws_cloudwatch_log_group.orchestrator]
}

resource "aws_lambda_event_source_mapping" "tickets" {
  event_source_arn        = aws_sqs_queue.tickets.arn
  function_name          = aws_lambda_function.orchestrator.arn
  batch_size             = 1
  maximum_concurrency    = var.max_concurrency
  function_response_types = ["ReportBatchItemFailures"]
}

# =============================================================================
# IAM + LAMBDA - AUTHORIZER
# =============================================================================
resource "aws_iam_role" "authorizer" {
  name               = "${local.name_prefix}-authorizer"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "authorizer" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.webhook.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.authorizer.arn}:*"]
  }
}

resource "aws_iam_role_policy" "authorizer" {
  role   = aws_iam_role.authorizer.id
  policy = data.aws_iam_policy_document.authorizer.json
}

resource "aws_lambda_function" "authorizer" {
  function_name    = "${local.name_prefix}-authorizer"
  role             = aws_iam_role.authorizer.arn
  runtime          = "python3.13"
  handler          = "authorizer.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.authorizer.output_path
  source_code_hash = data.archive_file.authorizer.output_base64sha256
  timeout          = 5
  memory_size      = 256

  environment {
    variables = {
      WEBHOOK_SECRET_NAME = aws_secretsmanager_secret.webhook.name
      HEADER_NAME         = var.webhook_header_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.authorizer]
}

# =============================================================================
# IAM + LAMBDA - METRICS REPORTER
# =============================================================================
resource "aws_iam_role" "metrics_reporter" {
  name               = "${local.name_prefix}-metrics-reporter"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "metrics_reporter" {
  statement {
    sid       = "ReadMetricsTable"
    actions   = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.metrics.arn, "${aws_dynamodb_table.metrics.arn}/index/*"]
  }

  statement {
    sid       = "ReadFeedbackTable"
    actions   = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.feedback.arn, "${aws_dynamodb_table.feedback.arn}/index/*"]
  }

  statement {
    sid       = "ReadAgentFeedbackTable"
    actions   = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [
      aws_dynamodb_table.agent_feedback.arn,
      "${aws_dynamodb_table.agent_feedback.arn}/index/*"
    ]
  }

  statement {
    sid       = "ReadApiSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.psa.arn]
  }

  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.metrics_reporter.arn}:*"]
  }
}

resource "aws_iam_role_policy" "metrics_reporter" {
  role   = aws_iam_role.metrics_reporter.id
  policy = data.aws_iam_policy_document.metrics_reporter.json
}

resource "aws_lambda_function" "metrics_reporter" {
  function_name    = "${local.name_prefix}-metrics-reporter"
  role             = aws_iam_role.metrics_reporter.arn
  runtime          = "python3.13"
  handler          = "metrics_reporter.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.metrics_reporter.output_path
  source_code_hash = data.archive_file.metrics_reporter.output_base64sha256
  timeout          = 60
  memory_size      = 512

  tracing_config { mode = "Active" }

  environment {
    variables = {
      METRICS_TABLE        = aws_dynamodb_table.metrics.name
      FEEDBACK_TABLE       = aws_dynamodb_table.feedback.name
      PSA_SECRET_NAME      = aws_secretsmanager_secret.psa.name
      SENDER_EMAIL         = var.metrics_report_sender_email
      RECIPIENT_EMAIL      = var.metrics_report_recipient_email
      AWS_REGION_NAME      = var.aws_region
      AI_ACCURACY_FIELD_ID = tostring(var.ai_accuracy_field_id)
      AGENT_FEEDBACK_TABLE = aws_dynamodb_table.agent_feedback.name
      TENANT_REGISTRY_TABLE = aws_dynamodb_table.tenant_registry.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.metrics_reporter]
}

# =============================================================================
# IAM + LAMBDA - FEEDBACK COLLECTOR
# =============================================================================
resource "aws_iam_role" "feedback_collector" {
  name               = "${local.name_prefix}-feedback-collector"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "feedback_collector" {
  statement {
    sid       = "ReadApiSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.psa.arn]
  }

  statement {
    sid       = "ReadWriteFeedbackTable"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.feedback.arn, "${aws_dynamodb_table.feedback.arn}/index/*"]
  }

  statement {
    sid       = "ReadMetricsTable"
    actions   = ["dynamodb:GetItem", "dynamodb:Scan", "dynamodb:Query"]
    resources = [aws_dynamodb_table.metrics.arn, "${aws_dynamodb_table.metrics.arn}/index/*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.feedback_collector.arn}:*"]
  }
}

resource "aws_iam_role_policy" "feedback_collector" {
  role   = aws_iam_role.feedback_collector.id
  policy = data.aws_iam_policy_document.feedback_collector.json
}

resource "aws_lambda_function" "feedback_collector" {
  function_name    = "${local.name_prefix}-feedback-collector"
  role             = aws_iam_role.feedback_collector.arn
  runtime          = "python3.13"
  handler          = "feedback_collector.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.feedback_collector.output_path
  source_code_hash = data.archive_file.feedback_collector.output_base64sha256
  timeout          = 120
  memory_size      = 512

  tracing_config { mode = "Active" }

  environment {
    variables = {
      FEEDBACK_TABLE               = aws_dynamodb_table.feedback.name
      METRICS_TABLE                = aws_dynamodb_table.metrics.name
      PSA_SECRET_NAME              = aws_secretsmanager_secret.psa.name
      AI_ACCURACY_FIELD_ID         = tostring(var.ai_accuracy_field_id)
      AI_CORRECTION_NOTES_FIELD_ID = tostring(var.ai_correction_notes_field_id)
      AWS_REGION_NAME              = var.aws_region
      FEEDBACK_TTL_DAYS            = tostring(var.feedback_retention_days)
    }
  }

  depends_on = [aws_cloudwatch_log_group.feedback_collector]
}

# =============================================================================
# IAM + LAMBDA - FEEDBACK SYNC
# =============================================================================
resource "aws_iam_role" "feedback_sync" {
  name               = "${local.name_prefix}-feedback-sync"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "feedback_sync" {
  statement {
    sid       = "ReadWriteFeedbackTable"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.feedback.arn, "${aws_dynamodb_table.feedback.arn}/index/*"]
  }

  statement {
    sid       = "ReadWriteFewShotExamples"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.few_shot_examples.arn}/examples.json"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.feedback_sync.arn}:*"]
  }
}

resource "aws_iam_role_policy" "feedback_sync" {
  role   = aws_iam_role.feedback_sync.id
  policy = data.aws_iam_policy_document.feedback_sync.json
}

resource "aws_lambda_function" "feedback_sync" {
  function_name    = "${local.name_prefix}-feedback-sync"
  role             = aws_iam_role.feedback_sync.arn
  runtime          = "python3.13"
  handler          = "feedback_sync.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.feedback_sync.output_path
  source_code_hash = data.archive_file.feedback_sync.output_base64sha256
  timeout          = 60
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      FEEDBACK_TABLE           = aws_dynamodb_table.feedback.name
      FEW_SHOT_EXAMPLES_BUCKET = aws_s3_bucket.few_shot_examples.id
      FEW_SHOT_EXAMPLES_KEY    = "examples.json"
      MAX_FEW_SHOT_EXAMPLES    = tostring(var.max_few_shot_examples)
      AWS_REGION_NAME          = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.feedback_sync]
}

# =============================================================================
# IAM + LAMBDA - CUSTOMER DIGEST ORCHESTRATOR
# =============================================================================
resource "aws_iam_role" "customer_digest_orchestrator" {
  name               = "${local.name_prefix}-customer-digest-orchestrator"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "customer_digest_orchestrator" {
  statement {
    sid       = "ReadCustomerPreferences"
    actions   = ["dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.customer_preferences.arn, "${aws_dynamodb_table.customer_preferences.arn}/index/*"]
  }

  statement {
    sid       = "SendToQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.customer_digest.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "EmitCustomMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.customer_digest_orchestrator.arn}:*"]
  }
}

resource "aws_iam_role_policy" "customer_digest_orchestrator" {
  role   = aws_iam_role.customer_digest_orchestrator.id
  policy = data.aws_iam_policy_document.customer_digest_orchestrator.json
}

resource "aws_lambda_function" "customer_digest_orchestrator" {
  function_name    = "${local.name_prefix}-customer-digest-orchestrator"
  role             = aws_iam_role.customer_digest_orchestrator.arn
  runtime          = "python3.13"
  handler          = "customer_digest_orchestrator.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.customer_digest_orchestrator.output_path
  source_code_hash = data.archive_file.customer_digest_orchestrator.output_base64sha256
  timeout          = 60
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      CUSTOMER_PREFERENCES_TABLE = aws_dynamodb_table.customer_preferences.name
      CUSTOMER_DIGEST_QUEUE_URL  = aws_sqs_queue.customer_digest.url
      MAX_CUSTOMERS_PER_RUN      = tostring(var.customer_digest_max_customers_per_run)
      DEFAULT_LOCAL_HOUR         = tostring(var.customer_digest_default_local_hour)
      AWS_REGION_NAME            = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.customer_digest_orchestrator]
}

# =============================================================================
# IAM + LAMBDA - CUSTOMER DIGEST WORKER
# =============================================================================
resource "aws_iam_role" "customer_digest_worker" {
  name               = "${local.name_prefix}-customer-digest-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "customer_digest_worker" {
  statement {
    sid       = "BedrockInvoke"
    actions   = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.customer_digest_model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.customer_digest_foundation_model_id}",
    ]
  }

  statement {
    sid       = "BedrockGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [
      aws_bedrock_guardrail.customer_digest.arn,
      aws_bedrock_guardrail_version.customer_digest_v1.arn,
    ]
  }

  statement {
    sid       = "ReadApiSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.rmm.arn, aws_secretsmanager_secret.unsubscribe_signing.arn]
  }

  statement {
    sid       = "ConsumeQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.customer_digest.arn]
  }

  statement {
    sid       = "ReadCustomerPreferences"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.customer_preferences.arn]
  }

  statement {
    sid       = "WriteAlertHistory"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.customer_alert_history.arn]
  }

  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.customer_digest_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "customer_digest_worker" {
  role   = aws_iam_role.customer_digest_worker.id
  policy = data.aws_iam_policy_document.customer_digest_worker.json
}

resource "aws_lambda_function" "customer_digest_worker" {
  function_name    = "${local.name_prefix}-customer-digest-worker"
  role             = aws_iam_role.customer_digest_worker.arn
  runtime          = "python3.13"
  handler          = "customer_digest_worker.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.customer_digest_worker.output_path
  source_code_hash = data.archive_file.customer_digest_worker.output_base64sha256
  timeout          = 120
  memory_size      = 512

  tracing_config { mode = "Active" }

  environment {
    variables = {
      RMM_SECRET_NAME             = aws_secretsmanager_secret.rmm.name
      UNSUBSCRIBE_SECRET_NAME     = aws_secretsmanager_secret.unsubscribe_signing.name
      CUSTOMER_PREFERENCES_TABLE  = aws_dynamodb_table.customer_preferences.name
      ALERT_HISTORY_TABLE         = aws_dynamodb_table.customer_alert_history.name
      CUSTOMER_DIGEST_MODEL_ID    = var.customer_digest_model_id
      GUARDRAIL_ID                = aws_bedrock_guardrail.customer_digest.id
      GUARDRAIL_VERSION           = aws_bedrock_guardrail_version.customer_digest_v1.guardrail_version
      SENDER_EMAIL                = var.customer_digest_sender_email
      MIN_SEVERITY                = var.customer_digest_min_severity
      ALERT_HISTORY_RETENTION     = tostring(var.customer_digest_history_retention_days)
      UNSUBSCRIBE_BASE_URL        = var.unsubscribe_base_url
      MSP_DEFAULT_BRANDING        = jsonencode(var.msp_default_branding)
      AWS_REGION_NAME             = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.customer_digest_worker]
}

resource "aws_lambda_event_source_mapping" "customer_digest" {
  event_source_arn        = aws_sqs_queue.customer_digest.arn
  function_name          = aws_lambda_function.customer_digest_worker.arn
  batch_size             = 1
  maximum_concurrency    = 10
  function_response_types = ["ReportBatchItemFailures"]
}

# =============================================================================
# IAM + LAMBDA - UNSUBSCRIBE HANDLER
# =============================================================================
resource "aws_iam_role" "unsubscribe_handler" {
  name               = "${local.name_prefix}-unsubscribe"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "unsubscribe_handler" {
  statement {
    sid       = "ReadSigningSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.unsubscribe_signing.arn]
  }

  statement {
    sid       = "UpdateCustomerPreferences"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.customer_preferences.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.unsubscribe_handler.arn}:*"]
  }
}

resource "aws_iam_role_policy" "unsubscribe_handler" {
  role   = aws_iam_role.unsubscribe_handler.id
  policy = data.aws_iam_policy_document.unsubscribe_handler.json
}

resource "aws_lambda_function" "unsubscribe_handler" {
  function_name    = "${local.name_prefix}-unsubscribe"
  role             = aws_iam_role.unsubscribe_handler.arn
  runtime          = "python3.13"
  handler          = "unsubscribe.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.unsubscribe_handler.output_path
  source_code_hash = data.archive_file.unsubscribe_handler.output_base64sha256
  timeout          = 10
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      CUSTOMER_PREFERENCES_TABLE = aws_dynamodb_table.customer_preferences.name
      UNSUBSCRIBE_SECRET_NAME    = aws_secretsmanager_secret.unsubscribe_signing.name
      MSP_COMPANY_NAME           = var.msp_default_branding.company_name
      MSP_SUPPORT_EMAIL          = var.msp_default_branding.support_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.unsubscribe_handler]
}

# =============================================================================
# BEDROCK AGENT - AI IT CONCIERGE (UPDATED for increment 2)
# =============================================================================

resource "aws_iam_role" "bedrock_agent" {
  name = "${local.name_prefix}-bedrock-agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:agent/*"
        }
      }
    }]
  })
}

data "aws_iam_policy_document" "bedrock_agent" {
  statement {
    sid     = "InvokeActionGroupLambda"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.identity_tools.arn
    ]
  }

  statement {
    sid     = "InvokeFoundationModel"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.agent_model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.agent_foundation_model_id}",
    ]
  }

  statement {
    sid     = "ApplyGuardrail"
    actions = ["bedrock:ApplyGuardrail"]
    resources = [
      aws_bedrock_guardrail.agent.arn,
      aws_bedrock_guardrail_version.agent_v1.arn,
    ]
  }
}

resource "aws_iam_role_policy" "bedrock_agent" {
  role   = aws_iam_role.bedrock_agent.id
  policy = data.aws_iam_policy_document.bedrock_agent.json
}

# =============================================================================
# BEDROCK AGENT - AI IT CONCIERGE (Phase 4: Per-Tenant)
# Creates one agent instance per tenant for maximum isolation.
# =============================================================================
resource "aws_bedrockagent_agent" "it_concierge" {
  for_each = var.tenants

  agent_name                  = "${local.name_prefix}-it-concierge-${each.key}"
  agent_resource_role_arn     = aws_iam_role.bedrock_agent.arn
  foundation_model            = var.agent_model_id
  description                 = "AI IT Concierge for ${each.value.display_name}"
  idle_session_ttl_in_seconds = var.agent_idle_session_ttl_seconds

  instruction = <<-EOT
    You are an AI IT Concierge for ${var.msp_company_name_for_agent}. You help end users with identity and account operations via Microsoft Teams.
    
    YOUR CAPABILITIES:
    Read-only:
    - Look up user information (display name, job title, department, manager)
    - Verify a user's identity (MFA status, last sign-in, account status)
    - Check if an account is locked out
    
    Write operations (with confirmation):
    - Reset a user's password (SECURE: sends a one-time reset link via email)
    - Re-enable a disabled user account
    
    YOUR RULES:
    1. ALWAYS verify the user's identity first using verify_identity before discussing sensitive information or performing operations.
    2. Only perform operations on the user's OWN account. Never operate on other users' accounts.
    3. Be friendly, professional, and concise. Use plain language, not technical jargon.
    4. Never disclose internal system details, API endpoints, or implementation details.
    5. If a user asks about topics outside IT support, politely redirect them.
    6. If you're unsure about something, say so. Don't guess.
    
    SESSION ATTRIBUTES:
    The Teams bot passes your session attributes including:
    - user_aad_id: The cryptographically verified Azure AD object ID of the user (from Teams)
    - user_name: The user's display name
    
    When calling reset_password or unlock_account, you MUST include the user_aad_id parameter 
    with the value from the session attribute 'user_aad_id'. This is the cryptographically 
    verified identity of the user from Teams.
    
    CONFIRMATION FLOW FOR WRITE OPERATIONS:
    Before calling reset_password or unlock_account, you MUST:
    1. Verify the user's identity using verify_identity
    2. Explain clearly what you're about to do and the consequences
    3. Ask the user to reply with the exact word "CONFIRM" to proceed
    4. Wait for the user to reply with "CONFIRM"
    5. ONLY after receiving "CONFIRM", call the write operation with user_confirmed=true
    
    PASSWORD RESET FLOW (SECURE ONE-TIME LINK):
    
    When you execute a password reset, the system will:
    1. Generate a secure, single-use reset link
    2. Email the link directly to the user's registered email address
    3. The user clicks the link and sets their own password through a secure form
    
    IMPORTANT: You will NEVER see or transmit the user's password. The link is sent 
    directly to the user via email. You should tell the user:
    
    "A secure password reset link has been sent to your registered email address. 
    Please check your inbox (and spam folder) for an email titled 'Action Required: 
    Set Your New Password'. Click the link in that email to set your new password. 
    The link expires in 15 minutes and can only be used once."
    
    If the user reports not receiving the email:
    - Ask them to check their spam/junk folder
    - Offer to resend the link (this creates a new reset request)
    - If still not received, escalate to IT support
    
    NEVER ask the user to tell you their new password.
    NEVER ask the user to share the reset link with anyone else.
    
    ACCOUNT UNLOCK FLOW:
    - Account unlock: Re-enables a disabled account. Does NOT clear lockout from failed sign-in attempts (those are time-based). For lockout scenarios, recommend password reset instead.
    
    IMPORTANT NOTES ABOUT OPERATIONS:
    - Both operations are rate-limited to ${var.agent_rate_limit_per_hour} per hour per user.
    - Both operations are logged for security and compliance.
    - Password reset uses a secure one-time link — you never see the user's password.
    
    SCOPE ISOLATION:
    The tools will automatically verify that users can only modify their own accounts. If a user asks to modify another user's account, explain that this requires human IT support.
    
    TONE: Professional, helpful, empathetic. You're talking to end users who may be frustrated by IT issues.

    AGENT FEEDBACK AND CORRECTIONS:
    
    You will receive session attributes containing examples of correct behavior from past 
    corrections. These are labeled as "Example 1", "Example 2", etc. Each example shows:
    - A user input that was previously mishandled
    - The wrong behavior that occurred
    - The correct behavior you should follow
    - The rationale for why
    
    When you see similar user inputs in the future, follow the corrected behavior from 
    the examples. These examples take priority over your default behavior.
    
    If no examples are provided in your session attributes, proceed with your normal behavior.
  EOT

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.agent.id
    guardrail_version    = aws_bedrock_guardrail_version.agent_v1.guardrail_version
  }

  # Attach Knowledge Base if enabled (Phase 4 + KB)
  dynamic "knowledge_bases" {
    for_each = var.enable_knowledge_base ? [1] : []
    content {
      knowledge_base_id = aws_bedrockagent_knowledge_base.it_concierge[0].id
      description       = "Tenant-scoped knowledge base. ALWAYS include tenant_id filter in queries."
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "identity_tools" {
  for_each = var.tenants

  agent_id          = aws_bedrockagent_agent.it_concierge[each.key].agent_id
  agent_version     = aws_bedrockagent_agent.it_concierge[each.key].agent_version
  action_group_name = "identity_tools"
  description       = "Tools for looking up user information, verifying identity, checking account lockout, resetting passwords, and unlocking accounts"

  action_group_executor {
    lambda = aws_lambda_function.identity_tools.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.agent_schemas.id
      s3_object_key  = aws_s3_object.identity_tools_schema.key
    }
  }
}

resource "aws_lambda_permission" "agent_invoke_identity_tools" {
  for_each = var.tenants

  statement_id  = "AllowBedrockAgentInvokeIdentityTools-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.identity_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.it_concierge[each.key].agent_arn
}

# =============================================================================
# BEDROCK AGENT ACTION GROUPS - INCREMENT 3
# =============================================================================

resource "aws_bedrockagent_agent_action_group" "ticket_tools" {
  for_each = var.tenants

  agent_id          = aws_bedrockagent_agent.it_concierge[each.key].agent_id
  agent_version     = aws_bedrockagent_agent.it_concierge[each.key].agent_version
  action_group_name = "ticket_tools"
  description       = "Tools for creating and checking support tickets in ConnectWise"

  action_group_executor {
    lambda = aws_lambda_function.ticket_tools.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.agent_schemas.id
      s3_object_key  = aws_s3_object.ticket_tools_schema.key
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "device_tools" {
  for_each = var.tenants

  agent_id          = aws_bedrockagent_agent.it_concierge[each.key].agent_id
  agent_version     = aws_bedrockagent_agent.it_concierge[each.key].agent_version
  action_group_name = "device_tools"
  description       = "Tools for checking device status and alerts in NinjaOne"

  action_group_executor {
    lambda = aws_lambda_function.device_tools.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.agent_schemas.id
      s3_object_key  = aws_s3_object.device_tools_schema.key
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "calendar_tools" {
  for_each = var.tenants

  agent_id          = aws_bedrockagent_agent.it_concierge[each.key].agent_id
  agent_version     = aws_bedrockagent_agent.it_concierge[each.key].agent_version
  action_group_name = "calendar_tools"
  description       = "Tools for calendar operations including room booking"

  action_group_executor {
    lambda = aws_lambda_function.calendar_tools.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.agent_schemas.id
      s3_object_key  = aws_s3_object.calendar_tools_schema.key
    }
  }
}

resource "aws_lambda_permission" "agent_invoke_ticket_tools" {
  for_each = var.tenants

  statement_id  = "AllowBedrockAgentInvokeTicketTools-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ticket_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.it_concierge[each.key].agent_arn
}

resource "aws_lambda_permission" "agent_invoke_device_tools" {
  for_each = var.tenants

  statement_id  = "AllowBedrockAgentInvokeDeviceTools-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.device_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.it_concierge[each.key].agent_arn
}

resource "aws_lambda_permission" "agent_invoke_calendar_tools" {
  for_each = var.tenants

  statement_id  = "AllowBedrockAgentInvokeCalendarTools-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.calendar_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.it_concierge[each.key].agent_arn
}

resource "aws_bedrockagent_agent_alias" "latest" {
  for_each = var.tenants

  agent_alias_name = "latest"
  agent_id         = aws_bedrockagent_agent.it_concierge[each.key].agent_id
  description      = "Latest version of the IT Concierge agent for tenant ${each.key}"
}

# =============================================================================
# IAM + LAMBDA - IDENTITY TOOLS (UPDATED for increment 2)
# =============================================================================
resource "aws_iam_role" "identity_tools" {
  name               = "${local.name_prefix}-identity-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "identity_tools" {
  statement {
    sid       = "ReadEntraCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.entra_graph.arn]
  }

  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  # Rate limits: expanded for multi-window transactions
  statement {
    sid       = "RateLimitsTransact"
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:TransactWriteItems"]
    resources = [aws_dynamodb_table.agent_rate_limits.arn]
  }

  # Pending operations: full CRUD
  statement {
    sid       = "PendingOperations"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.agent_pending_operations.arn,
      "${aws_dynamodb_table.agent_pending_operations.arn}/index/*",
    ]
  }

  # Nonce table: PutItem ONLY — the tool cannot read nonces back
  statement {
    sid       = "WriteNonceOnly"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_confirmation_nonces.arn]
  }

  statement {
    sid       = "ReadConfirmationSigningKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.agent_confirmation_signing.arn]
  }

  statement {
    sid       = "SendNotifications"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.identity_tools.arn}:*"]
  }

  statement {
    sid       = "ReadTenantRegistry"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.tenant_registry.arn,
      "${aws_dynamodb_table.tenant_registry.arn}/index/*",
    ]
  }
}

resource "aws_iam_role_policy" "identity_tools" {
  role   = aws_iam_role.identity_tools.id
  policy = data.aws_iam_policy_document.identity_tools.json
  statement {
    sid       = "ResetTokens"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [
      aws_dynamodb_table.password_reset_tokens.arn,
      "${aws_dynamodb_table.password_reset_tokens.arn}/index/*",
    ]
  }

  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }
}

resource "aws_lambda_function" "identity_tools" {
  function_name    = "${local.name_prefix}-identity-tools"
  role             = aws_iam_role.identity_tools.arn
  runtime          = "python3.13"
  handler          = "identity_tools.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.identity_tools.output_path
  source_code_hash = data.archive_file.identity_tools.output_base64sha256
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      ENTRA_GRAPH_SECRET_NAME       = aws_secretsmanager_secret.entra_graph.name
      ENTRA_TENANT_ID               = var.entra_tenant_id
      ENTRA_APP_CLIENT_ID           = var.entra_app_client_id
      AUDIT_LOG_TABLE               = aws_dynamodb_table.agent_audit_log.name
      AUDIT_LOG_RETENTION           = tostring(var.agent_audit_log_retention_days)
      RATE_LIMIT_TABLE              = aws_dynamodb_table.agent_rate_limits.name
      PENDING_OPERATIONS_TABLE      = aws_dynamodb_table.agent_pending_operations.name
      CONFIRMATION_NONCES_TABLE     = aws_dynamodb_table.agent_confirmation_nonces.name
      CONFIRMATION_SECRET_NAME      = aws_secretsmanager_secret.agent_confirmation_signing.name
      CONFIRMATION_TTL_SECONDS      = tostring(var.agent_confirmation_ttl_seconds)
      ADMIN_GROUP_ID                = var.agent_admin_group_id
      ADMIN_CHECK_CACHE_SECONDS     = tostring(var.agent_admin_check_cache_seconds)
      SELF_RATE_LIMITS              = jsonencode(var.agent_self_rate_limits)
      ADMIN_RATE_LIMITS             = jsonencode(var.agent_admin_rate_limits)
      NOTIFICATION_SENDER_EMAIL     = var.agent_notification_sender_email
      SECURITY_NOTIFICATION_EMAIL   = var.agent_security_notification_email != null ? var.agent_security_notification_email : ""
      RESET_TOKENS_TABLE            = aws_dynamodb_table.password_reset_tokens.name
      TOKEN_TTL_SECONDS             = tostring(var.password_reset_token_ttl_seconds)
      PASSWORD_RESET_URL            = local.password_reset_public_url
      PASSWORD_RESET_SENDER         = var.password_reset_sender_email
      TENANT_REGISTRY_TABLE         = aws_dynamodb_table.tenant_registry.name
      DEFAULT_TENANT_ID             = var.default_tenant_id
      ENVIRONMENT                   = var.environment
      AWS_REGION_NAME               = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.identity_tools]
}

# =============================================================================
# IAM + LAMBDA - TICKET TOOLS (Increment 3)
# =============================================================================
resource "aws_iam_role" "ticket_tools" {
  name               = "${local.name_prefix}-ticket-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ticket_tools" {
  statement {
    sid       = "ReadPsaCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.psa.arn]
  }

  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  statement {
    sid       = "RateLimitsTransact"
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:TransactWriteItems"]
    resources = [aws_dynamodb_table.agent_rate_limits.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ticket_tools.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ticket_tools" {
  role   = aws_iam_role.ticket_tools.id
  policy = data.aws_iam_policy_document.ticket_tools.json
}

resource "aws_lambda_function" "ticket_tools" {
  function_name    = "${local.name_prefix}-ticket-tools"
  role             = aws_iam_role.ticket_tools.arn
  runtime          = "python3.13"
  handler          = "ticket_tools.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.ticket_tools.output_path
  source_code_hash = data.archive_file.ticket_tools.output_base64sha256
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      PSA_SECRET_NAME          = aws_secretsmanager_secret.psa.name
      AUDIT_LOG_TABLE          = aws_dynamodb_table.agent_audit_log.name
      AUDIT_LOG_RETENTION      = tostring(var.agent_audit_log_retention_days)
      RATE_LIMIT_TABLE         = aws_dynamodb_table.agent_rate_limits.name
      DEFAULT_BOARD_ID         = tostring(var.ticket_default_board_id)
      DEFAULT_STATUS_ID        = tostring(var.ticket_default_status_id)
      DEFAULT_TYPE_ID          = tostring(var.ticket_default_type_id)
      DEFAULT_PRIORITY_ID      = tostring(var.ticket_default_priority_id)
      AWS_REGION_NAME          = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.ticket_tools]
}

# =============================================================================
# IAM + LAMBDA - DEVICE TOOLS (Increment 3)
# =============================================================================
resource "aws_iam_role" "device_tools" {
  name               = "${local.name_prefix}-device-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "device_tools" {
  statement {
    sid       = "ReadRmmCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.rmm.arn]
  }

  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  statement {
    sid       = "RateLimitsTransact"
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:TransactWriteItems"]
    resources = [aws_dynamodb_table.agent_rate_limits.arn]
  }

  dynamic "statement" {
    for_each = var.ninjaone_device_mapping_table != "" ? [1] : []
    content {
      sid       = "ReadDeviceMapping"
      actions   = ["dynamodb:Query"]
      resources = [aws_dynamodb_table.device_ownership_mapping[0].arn]
    }
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.device_tools.arn}:*"]
  }
}

resource "aws_iam_role_policy" "device_tools" {
  role   = aws_iam_role.device_tools.id
  policy = data.aws_iam_policy_document.device_tools.json
}

resource "aws_lambda_function" "device_tools" {
  function_name    = "${local.name_prefix}-device-tools"
  role             = aws_iam_role.device_tools.arn
  runtime          = "python3.13"
  handler          = "device_tools.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.device_tools.output_path
  source_code_hash = data.archive_file.device_tools.output_base64sha256
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      RMM_SECRET_NAME          = aws_secretsmanager_secret.rmm.name
      AUDIT_LOG_TABLE          = aws_dynamodb_table.agent_audit_log.name
      AUDIT_LOG_RETENTION      = tostring(var.agent_audit_log_retention_days)
      RATE_LIMIT_TABLE         = aws_dynamodb_table.agent_rate_limits.name
      DEVICE_OWNER_FIELD       = var.ninjaone_device_owner_field
      DEVICE_MAPPING_TABLE     = var.ninjaone_device_mapping_table
      AWS_REGION_NAME          = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.device_tools]
}

# =============================================================================
# IAM + LAMBDA - CALENDAR TOOLS (Increment 3)
# =============================================================================
resource "aws_iam_role" "calendar_tools" {
  name               = "${local.name_prefix}-calendar-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "calendar_tools" {
  statement {
    sid       = "ReadEntraCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.entra_graph.arn]
  }

  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  statement {
    sid       = "RateLimitsTransact"
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:TransactWriteItems"]
    resources = [aws_dynamodb_table.agent_rate_limits.arn]
  }

  statement {
    sid       = "PendingOperations"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.agent_pending_operations.arn,
      "${aws_dynamodb_table.agent_pending_operations.arn}/index/*",
    ]
  }

  statement {
    sid       = "WriteNonceOnly"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_confirmation_nonces.arn]
  }

  statement {
    sid       = "ReadConfirmationSigningKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.agent_confirmation_signing.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.calendar_tools.arn}:*"]
  }
}

resource "aws_cloudwatch_log_group" "agent_feedback_handler" {
  name              = "/aws/lambda/${local.name_prefix}-agent-feedback-handler"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "agent_feedback_sync" {
  name              = "/aws/lambda/${local.name_prefix}-agent-feedback-sync"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role_policy" "calendar_tools" {
  role   = aws_iam_role.calendar_tools.id
  policy = data.aws_iam_policy_document.calendar_tools.json
}

resource "aws_lambda_function" "calendar_tools" {
  function_name    = "${local.name_prefix}-calendar-tools"
  role             = aws_iam_role.calendar_tools.arn
  runtime          = "python3.13"
  handler          = "calendar_tools.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.calendar_tools.output_path
  source_code_hash = data.archive_file.calendar_tools.output_base64sha256
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      ENTRA_GRAPH_SECRET_NAME       = aws_secretsmanager_secret.entra_graph.name
      ENTRA_TENANT_ID               = var.entra_tenant_id
      ENTRA_APP_CLIENT_ID           = var.entra_app_client_id
      AUDIT_LOG_TABLE               = aws_dynamodb_table.agent_audit_log.name
      AUDIT_LOG_RETENTION           = tostring(var.agent_audit_log_retention_days)
      RATE_LIMIT_TABLE              = aws_dynamodb_table.agent_rate_limits.name
      PENDING_OPERATIONS_TABLE      = aws_dynamodb_table.agent_pending_operations.name
      CONFIRMATION_NONCES_TABLE     = aws_dynamodb_table.agent_confirmation_nonces.name
      CONFIRMATION_SECRET_NAME      = aws_secretsmanager_secret.agent_confirmation_signing.name
      CONFIRMATION_TTL_SECONDS      = tostring(var.agent_confirmation_ttl_seconds)
      DEFAULT_TIMEZONE              = var.calendar_default_timezone
      ROOM_FILTER                   = var.bookable_room_filter
      AWS_REGION_NAME               = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.calendar_tools]
}

# =============================================================================
# IAM + LAMBDA - KB DOCUMENT PROCESSOR
# Triggered by S3 events when documents are uploaded to the KB bucket.
# =============================================================================
resource "aws_lambda_function" "kb_document_processor" {
  count = var.enable_knowledge_base ? 1 : 0

  function_name    = "${local.name_prefix}-kb-document-processor"
  role             = aws_iam_role.kb_ingestion[0].arn
  runtime          = "python3.13"
  handler          = "kb_document_processor.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.kb_document_processor[0].output_path
  source_code_hash = data.archive_file.kb_document_processor[0].output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.it_concierge[0].id
      DATA_SOURCE_ID    = aws_bedrockagent_data_source.kb_documents[0].id
      AWS_REGION_NAME   = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.kb_ingestion]
}

# S3 trigger: invoke Lambda on document upload
resource "aws_lambda_permission" "kb_s3_invoke" {
  count = var.enable_knowledge_base ? 1 : 0

  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kb_document_processor[0].function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.kb_documents[0].arn
}

resource "aws_s3_bucket_notification" "kb_documents" {
  count = var.enable_knowledge_base ? 1 : 0

  bucket = aws_s3_bucket.kb_documents[0].id

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_document_processor[0].arn
    events              = ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
    filter_prefix       = "tenants/"
  }

  depends_on = [aws_lambda_permission.kb_s3_invoke]
}

# =============================================================================
# SQS - TENANT PROVISIONING QUEUE
# =============================================================================
resource "aws_sqs_queue" "tenant_provisioning_dlq" {
  count                     = var.enable_onboarding_api ? 1 : 0
  name                      = "${local.name_prefix}-tenant-provisioning-dlq"
  message_retention_seconds = 1209600  # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "tenant_provisioning" {
  count                      = var.enable_onboarding_api ? 1 : 0
  name                       = "${local.name_prefix}-tenant-provisioning"
  visibility_timeout_seconds = 1800  # 30 minutes (agent creation can take 15+ min)
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.tenant_provisioning_dlq[0].arn
    maxReceiveCount     = 3
  })
}

# =============================================================================
# API GATEWAY - TENANT ONBOARDING API
# =============================================================================
resource "aws_apigatewayv2_api" "tenant_onboarding" {
  count         = var.enable_onboarding_api ? 1 : 0
  name          = "${local.name_prefix}-tenant-onboarding"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_stage" "tenant_onboarding_default" {
  count       = var.enable_onboarding_api ? 1 : 0
  api_id      = aws_apigatewayv2_api.tenant_onboarding[0].id
  name        = "$default"
  auto_deploy = true

  # Default throttling for all routes (conservative baseline)
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  # =================================================================
  # PER-ROUTE THROTTLING (Step 1: Rate Limiting)
  # Expensive status endpoints get stricter limits to prevent abuse.
  # =================================================================

  # Fast endpoints (onboarding/deprovisioning) — same as default
  route_settings {
    route_path           = "/tenants"
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  route_settings {
    route_path           = "/tenants/{tenant_id}"
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  # Status list endpoint — moderate limit
  route_settings {
    route_path           = "/status"
    throttling_burst_limit = var.status_api_burst_limit
    throttling_rate_limit  = var.status_api_requests_per_second
  }

  route_settings {
    route_path           = "/status/tenants"
    throttling_burst_limit = var.status_api_burst_limit
    throttling_rate_limit  = var.status_api_requests_per_second
  }

  route_settings {
    route_path           = "/status/tenants/{tenant_id}"
    throttling_burst_limit = var.status_api_burst_limit
    throttling_rate_limit  = var.status_api_requests_per_second
  }

  route_settings {
    route_path           = "/status/metrics"
    throttling_burst_limit = var.status_api_burst_limit
    throttling_rate_limit  = var.status_api_requests_per_second
  }

  # Deep health check — strictest limit (most expensive)
  route_settings {
    route_path           = "/status/tenants/{tenant_id}/health"
    throttling_burst_limit = var.status_deep_health_burst_limit
    throttling_rate_limit  = var.status_deep_health_requests_per_second
  }
}

# API Key for simple authentication
resource "aws_apigatewayv2_api_key" "onboarding" {
  count        = var.enable_onboarding_api && var.onboarding_api_auth_type == "api_key" ? 1 : 0
  name         = "${local.name_prefix}-onboarding-key"
  key_type     = "STANDARD"
  enabled      = true
}

# =============================================================================
# LAMBDA - TENANT ONBOARDING (FAST PATH)
# =============================================================================
data "archive_file" "tenant_onboarding" {
  count       = var.enable_onboarding_api ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_tenant_onboarding"
  output_path = "${path.module}/.build/tenant_onboarding.zip"
}

resource "aws_cloudwatch_log_group" "tenant_onboarding" {
  count             = var.enable_onboarding_api ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-tenant-onboarding"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "tenant_onboarding" {
  count              = var.enable_onboarding_api ? 1 : 0
  name               = "${local.name_prefix}-tenant-onboarding"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "tenant_onboarding" {
  count = var.enable_onboarding_api ? 1 : 0
  role  = aws_iam_role.tenant_onboarding[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "TenantRegistry"
        Effect = "Allow"
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.tenant_registry.arn,
          "${aws_dynamodb_table.tenant_registry.arn}/index/*"
        ]
      },
      {
        Sid = "SecretsManager"
        Effect = "Allow"
        Action = ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.environment}/tenants/*"
      },
      {
        Sid = "S3Folders"
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.agent_schemas.arn}/tenants/*",
          var.enable_knowledge_base ? "${aws_s3_bucket.kb_documents[0].arn}/tenants/*" : ""
        ]
      },
      {
        Sid = "SendToQueue"
        Effect = "Allow"
        Action = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.tenant_provisioning[0].arn]
      },
      {
        Sid = "GenerateSecrets"
        Effect = "Allow"
        Action = ["secretsmanager:GetRandomPassword"]
        Resource = "*"
      },
      {
        Sid = "WriteLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.tenant_onboarding[0].arn}:*"]
      },
      {
        Sid = "StatusCache"
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.status_cache[0].arn
      },
      {
        Sid = "StatusComputation"
        Effect = "Allow"
        Action = [
          "bedrock:GetAgent",
          "bedrock:ListAgents",
          "bedrock:ListAgentActionGroups",
          "bedrock:ListAgentAliases",
          "bedrock:ListAgentKnowledgeBases",
          "s3:ListBucket",
          "s3:GetObject",
          "secretsmanager:DescribeSecret",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:PutMetricData"
       },
       {
        Sid = "ReadAnalyticsTables"
        Effect = "Allow"
        Action = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
        Resources = var.enable_advanced_analytics ? [
          aws_dynamodb_table.webhook_delivery_log[0].arn,
          "${aws_dynamodb_table.webhook_delivery_log[0].arn}/index/*",
          aws_dynamodb_table.rule_effectiveness_log[0].arn,
          aws_dynamodb_table.analytics_summary[0].arn,
        ] : []
      },
      {
        Sid = "WriteWebhookDeliveryLog"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resources = var.enable_advanced_analytics ? [
          aws_dynamodb_table.webhook_delivery_log[0].arn,
        ] : []
      }
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_lambda_function" "tenant_onboarding" {
  count = var.enable_onboarding_api ? 1 : 0

  function_name    = "${local.name_prefix}-tenant-onboarding"
  role             = aws_iam_role.tenant_onboarding[0].arn
  runtime          = "python3.13"
  handler          = "tenant_onboarding.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.tenant_onboarding[0].output_path
  source_code_hash = data.archive_file.tenant_onboarding[0].output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      TENANT_REGISTRY_TABLE    = aws_dynamodb_table.tenant_registry.name
      PROVISIONING_QUEUE_URL   = aws_sqs_queue.tenant_provisioning[0].url
      AGENT_SCHEMAS_BUCKET     = aws_s3_bucket.agent_schemas.id
      KB_DOCUMENTS_BUCKET      = var.enable_knowledge_base ? aws_s3_bucket.kb_documents[0].id : ""
      ENVIRONMENT              = var.environment
      AWS_REGION_NAME          = var.aws_region
      ADMIN_EMAIL              = var.onboarding_admin_email
      DEFAULT_AGENT_MODEL      = var.agent_model_id
      ENABLE_KB                = tostring(var.enable_knowledge_base)
      STATUS_CACHE_TABLE       = aws_dynamodb_table.status_cache[0].name
      STATUS_CACHE_TTL         = tostring(var.status_cache_ttl_seconds)
      ENABLE_STATUS_METRICS      = tostring(var.enable_status_cloudwatch_metrics)
      STATUS_METRICS_NAMESPACE   = var.status_metrics_namespace
      WEBHOOK_DELIVERY_LOG_TABLE = var.enable_advanced_analytics ? aws_dynamodb_table.webhook_delivery_log[0].name : ""
      ANALYTICS_SUMMARY_TABLE    = var.enable_advanced_analytics ? aws_dynamodb_table.analytics_summary[0].name : ""
    }
  }

  depends_on = [aws_cloudwatch_log_group.tenant_onboarding]
}

# =============================================================================
# LAMBDA - STATUS HISTORY SNAPSHOT (Sub-Phase 1)
# =============================================================================
data "archive_file" "status_history_snapshot" {
  count       = var.enable_status_history ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_status_history_snapshot"
  output_path = "${path.module}/.build/status_history_snapshot.zip"
}

resource "aws_cloudwatch_log_group" "status_history_snapshot" {
  count             = var.enable_status_history ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-status-history-snapshot"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "status_history_snapshot" {
  count              = var.enable_status_history ? 1 : 0
  name               = "${local.name_prefix}-status-history-snapshot"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "status_history_snapshot" {
  count = var.enable_status_history ? 1 : 0
  statement {
    sid       = "ReadTenantRegistry"
    actions   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.tenant_registry.arn,
      "${aws_dynamodb_table.tenant_registry.arn}/index/*",
    ]
  }

  statement {
    sid       = "WriteStatusHistory"
    actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
    resources = [aws_dynamodb_table.status_history[0].arn]
  }

  statement {
    sid       = "ReadStatusCache"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.status_cache[0].arn]
  }

  statement {
    sid       = "StatusComputation"
    actions   = [
      "bedrock:GetAgent",
      "bedrock:ListAgents",
      "bedrock:ListAgentActionGroups",
      "bedrock:ListAgentAliases",
      "s3:ListBucket",
      "s3:GetObject",
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue"
    ]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.status_history_snapshot[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "status_history_snapshot" {
  count  = var.enable_status_history ? 1 : 0
  role   = aws_iam_role.status_history_snapshot[0].id
  policy = data.aws_iam_policy_document.status_history_snapshot[0].json
  statement {
    sid = "InvokeWebhookNotifier"
    effect = "Allow"
    action = ["lambda:InvokeFunction"]
    resource = var.enable_webhook_notifications ? [aws_lambda_function.webhook_notifier[0].arn] : []
  }
  statement {
    sid = "ReadCustomHealthRules"
    effect = "Allow"
    action = ["dynamodb:Query"]
    resources = var.enable_custom_health_checks ? [
      aws_dynamodb_table.custom_health_rules[0].arn,
      "${aws_dynamodb_table.custom_health_rules[0].arn}/index/*",
    ] : []
  }
}

resource "aws_lambda_function" "status_history_snapshot" {
  count = var.enable_status_history ? 1 : 0

  function_name    = "${local.name_prefix}-status-history-snapshot"
  role             = aws_iam_role.status_history_snapshot[0].arn
  runtime          = "python3.13"
  handler          = "status_history_snapshot.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.status_history_snapshot[0].output_path
  source_code_hash = data.archive_file.status_history_snapshot[0].output_base64sha256
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      TENANT_REGISTRY_TABLE = aws_dynamodb_table.tenant_registry.name
      STATUS_HISTORY_TABLE  = aws_dynamodb_table.status_history[0].name
      STATUS_CACHE_TABLE    = aws_dynamodb_table.status_cache[0].name
      AGENT_SCHEMAS_BUCKET  = aws_s3_bucket.agent_schemas.id
      KB_DOCUMENTS_BUCKET   = var.enable_knowledge_base ? aws_s3_bucket.kb_documents[0].id : ""
      ENVIRONMENT           = var.environment
      ENABLE_KB             = tostring(var.enable_knowledge_base)
      RETENTION_DAYS        = tostring(var.status_history_retention_days)
      AWS_REGION_NAME       = var.aws_region
      WEBHOOK_NOTIFIER_FUNCTION = var.enable_webhook_notifications ? aws_lambda_function.webhook_notifier[0].function_name : ""
      CUSTOM_RULES_TABLE       = var.enable_custom_health_checks ? aws_dynamodb_table.custom_health_rules[0].name : ""
      MAX_SCORE_IMPACT         = tostring(var.custom_health_max_score_impact)
      RULE_EFFECTIVENESS_LOG_TABLE = var.enable_advanced_analytics ? aws_dynamodb_table.rule_effectiveness_log[0].name : ""
    }
  }

  depends_on = [aws_cloudwatch_log_group.status_history_snapshot]
}

# =============================================================================
# EVENTBRIDGE - DAILY STATUS SNAPSHOT
# =============================================================================
resource "aws_cloudwatch_event_rule" "daily_status_snapshot" {
  count               = var.enable_status_history ? 1 : 0
  name                = "${local.name_prefix}-daily-status-snapshot"
  description         = "Takes daily status snapshots for trend analysis"
  schedule_expression = "cron(${var.status_history_snapshot_hour_utc} * * * ? *)"
}

resource "aws_cloudwatch_event_target" "status_history_snapshot" {
  count     = var.enable_status_history ? 1 : 0
  rule      = aws_cloudwatch_event_rule.daily_status_snapshot[0].name
  target_id = "status-history-snapshot"
  arn       = aws_lambda_function.status_history_snapshot[0].arn
}

resource "aws_lambda_permission" "eventbridge_status_history" {
  count         = var.enable_status_history ? 1 : 0
  statement_id  = "AllowEventBridgeInvokeStatusHistory"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.status_history_snapshot[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_status_snapshot[0].arn
}

# =============================================================================
# DYNAMODB - WEBHOOK CONFIGS (Sub-Phase 2)
# Stores per-tenant webhook configurations.
# =============================================================================
resource "aws_dynamodb_table" "webhook_configs" {
  count        = var.enable_webhook_notifications ? 1 : 0
  name         = "${local.name_prefix}-webhook-configs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "webhook_id"

  attribute { name = "tenant_id";  type = "S" }
  attribute { name = "webhook_id"; type = "S" }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "WebhookConfigs" }
}

# =============================================================================
# DYNAMODB - WEBHOOK COOLDOWNS (Sub-Phase 2)
# Tracks last alert time per tenant+issue to prevent alert fatigue.
# =============================================================================
resource "aws_dynamodb_table" "webhook_cooldowns" {
  count        = var.enable_webhook_notifications ? 1 : 0
  name         = "${local.name_prefix}-webhook-cooldowns"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cooldown_key"

  attribute { name = "cooldown_key"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }
  tags = { Purpose = "WebhookCooldowns" }
}

# =============================================================================
# DYNAMODB - CUSTOM HEALTH RULES (Sub-Phase 3)
# Stores tenant-defined custom health check rules.
# =============================================================================
resource "aws_dynamodb_table" "custom_health_rules" {
  count        = var.enable_custom_health_checks ? 1 : 0
  name         = "${local.name_prefix}-custom-health-rules"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "rule_id"

  attribute { name = "tenant_id"; type = "S" }
  attribute { name = "rule_id";   type = "S" }

  point_in_time_recovery { enabled = var.environment == "prod" }
  tags = { Purpose = "CustomHealthRules" }
}

# =============================================================================
# API GATEWAY - CUSTOM HEALTH RULES MANAGEMENT
# =============================================================================
resource "aws_apigatewayv2_api" "custom_health_rules" {
  count         = var.enable_custom_health_checks ? 1 : 0
  name          = "${local.name_prefix}-custom-health-rules"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_stage" "custom_health_rules_default" {
  count       = var.enable_custom_health_checks ? 1 : 0
  api_id      = aws_apigatewayv2_api.custom_health_rules[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

# =============================================================================
# COGNITO USER POOL - TENANT PORTAL AUTHENTICATION
# =============================================================================
resource "aws_cognito_user_pool" "tenant_portal" {
  count = var.enable_tenant_portal ? 1 : 0
  name  = "${local.name_prefix}-tenant-portal"

  # Username attributes (email-based login)
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Password policy
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  # MFA (optional but recommended)
  mfa_configuration = "OPTIONAL"

  # Account recovery
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Schema: add custom attribute for tenant_id
  schema {
    name                = "tenant_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  # Token configuration
  access_token_validity  = 1   # hours
  id_token_validity      = 1   # hours
  refresh_token_validity = 30  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  tags = { Purpose = "TenantPortalAuth" }
}

# Cognito User Pool Client (for the portal SPA)
resource "aws_cognito_user_pool_client" "tenant_portal" {
  count        = var.enable_tenant_portal ? 1 : 0
  name         = "${local.name_prefix}-portal-client"
  user_pool_id = aws_cognito_user_pool.tenant_portal[0].id

  # OAuth flows
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  # Callback URLs (portal domain)
  callback_urls = var.portal_domain_name != "" ? [
    "https://${var.portal_domain_name}/callback.html"
  ] : ["http://localhost:3000/callback.html"]

  logout_urls = var.portal_domain_name != "" ? [
    "https://${var.portal_domain_name}/"
  ] : ["http://localhost:3000/"]

  supported_identity_providers = ["COGNITO"]

  # Security
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  # Token validity (override pool defaults for SPA)
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# Cognito domain (for hosted UI)
resource "aws_cognito_user_pool_domain" "tenant_portal" {
  count      = var.enable_tenant_portal ? 1 : 0
  domain     = "${local.name_prefix}-portal"
  user_pool_id = aws_cognito_user_pool.tenant_portal[0].id
}

# =============================================================================
# S3 - TENANT PORTAL STATIC SITE
# =============================================================================
resource "aws_s3_bucket" "tenant_portal" {
  count  = var.enable_tenant_portal ? 1 : 0
  bucket = "${local.name_prefix}-tenant-portal-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "tenant_portal" {
  count                   = var.enable_tenant_portal ? 1 : 0
  bucket                  = aws_s3_bucket.tenant_portal[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "tenant_portal" {
  count  = var.enable_tenant_portal ? 1 : 0
  bucket = aws_s3_bucket.tenant_portal[0].id
  versioning_configuration { status = "Enabled" }
}

# =============================================================================
# CLOUDFRONT - TENANT PORTAL DISTRIBUTION
# =============================================================================
resource "aws_cloudfront_distribution" "tenant_portal" {
  count           = var.enable_tenant_portal ? 1 : 0
  enabled         = true
  is_ipv6_enabled = true
  comment         = "Tenant Self-Service Portal"
  price_class     = "PriceClass_100"  # North America + Europe

  aliases = var.portal_domain_name != "" ? [var.portal_domain_name] : []

  origin {
    domain_name = aws_s3_bucket.tenant_portal[0].bucket_regional_domain_name
    origin_id   = "S3-tenant-portal"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.tenant_portal[0].cloudfront_access_identity_path
    }
  }

  # Default cache behavior (static assets)
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-tenant-portal"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 86400

    # Security headers
    response_headers_policy = aws_cloudfront_response_headers_policy.tenant_portal[0].id
  }

  # API proxy behavior (forward to API Gateway)
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "API-tenant-portal"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Origin", "Accept"]
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # API Gateway origin
  origin {
    domain_name = aws_apigatewayv2_api.tenant_portal_api[0].api_endpoint
    origin_id   = "API-tenant-portal"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Restrictions
  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  # SSL certificate
  viewer_certificate {
    acm_certificate_arn      = var.portal_domain_name != "" ? aws_acm_certificate.tenant_portal[0].arn : null
    ssl_support_method       = var.portal_domain_name != "" ? "sni-only" : null
    minimum_protocol_version = var.portal_domain_name != "" ? "TLSv1.2_2021" : "TLSv1"
    cloudfront_default_certificate = var.portal_domain_name == "" ? true : false
  }

  # Custom error responses (SPA routing)
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  tags = { Purpose = "TenantPortal" }
}

resource "aws_cloudfront_origin_access_identity" "tenant_portal" {
  count   = var.enable_tenant_portal ? 1 : 0
  comment = "OAI for tenant portal S3 bucket"
}

resource "aws_cloudfront_response_headers_policy" "tenant_portal" {
  count   = var.enable_tenant_portal ? 1 : 0
  name    = "${local.name_prefix}-portal-security-headers"

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self' https://*.amazoncognito.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://*.amazoncognito.com https://*.execute-api.${var.aws_region}.amazonaws.com; frame-ancestors 'none';"
      override                = true
    }
    content_type_options { override = true }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
    xss_protection {
      protection = false  # Modern browsers prefer CSP
      override   = true
    }
  }
}

# ACM certificate for portal domain
resource "aws_acm_certificate" "tenant_portal" {
  count             = var.enable_tenant_portal && var.portal_domain_name != "" ? 1 : 0
  provider          = aws.cloudfront  # Must be in us-east-1
  domain_name       = var.portal_domain_name
  validation_method = "DNS"

  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "tenant_portal_cert_validation" {
  for_each = var.enable_tenant_portal && var.portal_domain_name != "" ? {
    for dvo in aws_acm_certificate.tenant_portal[0].domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  } : {}

  zone_id         = var.portal_hosted_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "tenant_portal" {
  count                   = var.enable_tenant_portal && var.portal_domain_name != "" ? 1 : 0
  provider                = aws.cloudfront
  certificate_arn         = aws_acm_certificate.tenant_portal[0].arn
  validation_record_fqdns = [for record in aws_route53_record.tenant_portal_cert_validation : record.fqdn]
}

resource "aws_route53_record" "tenant_portal" {
  count   = var.enable_tenant_portal && var.portal_domain_name != "" ? 1 : 0
  zone_id = var.portal_hosted_zone_id
  name    = var.portal_domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.tenant_portal[0].domain_name
    zone_id                = aws_cloudfront_distribution.tenant_portal[0].hosted_zone_id
    evaluate_target_health = false
  }
}

# =============================================================================
# S3 BUCKET POLICY - TENANT PORTAL (OAI ACCESS + TLS-ONLY)
# =============================================================================
resource "aws_s3_bucket_policy" "tenant_portal" {
  count  = var.enable_tenant_portal ? 1 : 0
  bucket = aws_s3_bucket.tenant_portal[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontOAI"
        Effect    = "Allow"
        Principal = { AWS = aws_cloudfront_origin_access_identity.tenant_portal[0].iam_arn }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.tenant_portal[0].arn}/*"
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tenant_portal[0].arn,
          "${aws_s3_bucket.tenant_portal[0].arn}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# =============================================================================
# API GATEWAY - TENANT PORTAL API
# =============================================================================
resource "aws_apigatewayv2_api" "tenant_portal_api" {
  count         = var.enable_tenant_portal ? 1 : 0
  name          = "${local.name_prefix}-tenant-portal-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = true
    allow_origins = var.portal_domain_name != "" ? [
      "https://${var.portal_domain_name}"
    ] : ["http://localhost:3000"]
    allow_headers = ["authorization", "content-type"]
    allow_methods = ["DELETE", "GET", "POST", "PUT"]
    max_age       = 3600
  }
}

# Cognito authorizer
resource "aws_apigatewayv2_authorizer" "tenant_portal" {
  count         = var.enable_tenant_portal ? 1 : 0
  api_id        = aws_apigatewayv2_api.tenant_portal_api[0].id
  authorizer_type = "JWT"
  name          = "cognito-authorizer"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.tenant_portal[0].id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.tenant_portal[0].id}"
  }
}

resource "aws_apigatewayv2_stage" "tenant_portal_api_default" {
  count       = var.enable_tenant_portal ? 1 : 0
  api_id      = aws_apigatewayv2_api.tenant_portal_api[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }
}

# =============================================================================
# DYNAMODB - ANALYTICS TABLES
# =============================================================================

resource "aws_dynamodb_table" "webhook_delivery_log" {
  count        = var.enable_advanced_analytics ? 1 : 0
  name         = "${local.name_prefix}-webhook-delivery-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "delivery_id"
  range_key    = "timestamp"

  attribute { name = "delivery_id"; type = "S" }
  attribute { name = "timestamp";   type = "S" }

  global_secondary_index {
    name            = "tenant-index"
    hash_key        = "tenant_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl"; enabled = true }
  tags = { Purpose = "WebhookDeliveryLog" }
}

resource "aws_dynamodb_table" "rule_effectiveness_log" {
  count        = var.enable_advanced_analytics ? 1 : 0
  name         = "${local.name_prefix}-rule-effectiveness-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "evaluation_date"

  attribute { name = "tenant_id";        type = "S" }
  attribute { name = "evaluation_date";  type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }
  tags = { Purpose = "RuleEffectivenessLog" }
}

resource "aws_dynamodb_table" "analytics_summary" {
  count        = var.enable_advanced_analytics ? 1 : 0
  name         = "${local.name_prefix}-analytics-summary"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "summary_type"
  range_key    = "summary_date"

  attribute { name = "summary_type"; type = "S" }
  attribute { name = "summary_date"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }
  tags = { Purpose = "AnalyticsSummary" }
}

# =============================================================================
# LAMBDA - ANALYTICS AGGREGATION
# =============================================================================

data "archive_file" "analytics_aggregation" {
  count       = var.enable_advanced_analytics ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_analytics_aggregation"
  output_path = "${path.module}/.build/analytics_aggregation.zip"
}

resource "aws_cloudwatch_log_group" "analytics_aggregation" {
  count             = var.enable_advanced_analytics ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-analytics-aggregation"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "analytics_aggregation" {
  count              = var.enable_advanced_analytics ? 1 : 0
  name               = "${local.name_prefix}-analytics-aggregation"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "analytics_aggregation" {
  count = var.enable_advanced_analytics ? 1 : 0
  statement {
    sid       = "ReadAnalyticsTables"
    actions   = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [
      aws_dynamodb_table.webhook_delivery_log[0].arn,
      "${aws_dynamodb_table.webhook_delivery_log[0].arn}/index/*",
      aws_dynamodb_table.rule_effectiveness_log[0].arn,
      aws_dynamodb_table.status_history[0].arn,
      "${aws_dynamodb_table.status_history[0].arn}/index/*",
    ]
  }

  statement {
    sid       = "WriteAnalyticsSummary"
    actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.analytics_summary[0].arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.analytics_aggregation[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "analytics_aggregation" {
  count  = var.enable_advanced_analytics ? 1 : 0
  role   = aws_iam_role.analytics_aggregation[0].id
  policy = data.aws_iam_policy_document.analytics_aggregation[0].json
}

resource "aws_lambda_function" "analytics_aggregation" {
  count = var.enable_advanced_analytics ? 1 : 0

  function_name    = "${local.name_prefix}-analytics-aggregation"
  role             = aws_iam_role.analytics_aggregation[0].arn
  runtime          = "python3.13"
  handler          = "analytics_aggregation.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.analytics_aggregation[0].output_path
  source_code_hash = data.archive_file.analytics_aggregation[0].output_base64sha256
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      WEBHOOK_DELIVERY_LOG_TABLE = aws_dynamodb_table.webhook_delivery_log[0].name
      RULE_EFFECTIVENESS_LOG_TABLE = aws_dynamodb_table.rule_effectiveness_log[0].name
      STATUS_HISTORY_TABLE = aws_dynamodb_table.status_history[0].name
      ANALYTICS_SUMMARY_TABLE = aws_dynamodb_table.analytics_summary[0].name
      RETENTION_DAYS = tostring(var.analytics_retention_days)
      AWS_REGION_NAME = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.analytics_aggregation]
}

# EventBridge rule for daily aggregation
resource "aws_cloudwatch_event_rule" "daily_analytics_aggregation" {
  count               = var.enable_advanced_analytics ? 1 : 0
  name                = "${local.name_prefix}-daily-analytics-aggregation"
  description         = "Trigger daily analytics aggregation"
  schedule_expression = "cron(0 7 * * ? *)"  # 7 AM UTC daily
}

resource "aws_cloudwatch_event_target" "analytics_aggregation" {
  count     = var.enable_advanced_analytics ? 1 : 0
  rule      = aws_cloudwatch_event_rule.daily_analytics_aggregation[0].name
  target_id = "analytics-aggregation"
  arn       = aws_lambda_function.analytics_aggregation[0].arn
}

resource "aws_lambda_permission" "eventbridge_analytics_aggregation" {
  count         = var.enable_advanced_analytics ? 1 : 0
  statement_id  = "AllowEventBridgeInvokeAnalyticsAggregation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analytics_aggregation[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_analytics_aggregation[0].arn
}

# =============================================================================
# API GATEWAY - ANALYTICS ENDPOINTS
# =============================================================================

resource "aws_apigatewayv2_route" "analytics_health_trends" {
  count             = var.enable_advanced_analytics ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key         = "GET /analytics/health-trends"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "analytics_webhook_delivery" {
  count             = var.enable_advanced_analytics ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key         = "GET /analytics/webhook-delivery"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "analytics_rule_effectiveness" {
  count             = var.enable_advanced_analytics ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key         = "GET /analytics/rule-effectiveness"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "analytics_executive_summary" {
  count             = var.enable_advanced_analytics ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key         = "GET /analytics/executive-summary"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

# =============================================================================
# LAMBDA - TENANT PORTAL BACKEND
# =============================================================================
data "archive_file" "tenant_portal_api" {
  count       = var.enable_tenant_portal ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_tenant_portal_api"
  output_path = "${path.module}/.build/tenant_portal_api.zip"
}

resource "aws_cloudwatch_log_group" "tenant_portal_api" {
  count             = var.enable_tenant_portal ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-tenant-portal-api"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "tenant_portal_api" {
  count              = var.enable_tenant_portal ? 1 : 0
  name               = "${local.name_prefix}-tenant-portal-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "tenant_portal_api" {
  count = var.enable_tenant_portal ? 1 : 0
  statement {
    sid       = "TenantDataAccess"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.tenant_registry.arn,
      aws_dynamodb_table.custom_health_rules[0].arn,
      aws_dynamodb_table.webhook_configs[0].arn,
      aws_dynamodb_table.status_history[0].arn,
      aws_dynamodb_table.agent_audit_log.arn,
    ]
  }

  statement {
    sid       = "ReadSecrets"
    actions   = ["secretsmanager:DescribeSecret"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.environment}/tenants/*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.tenant_portal_api[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "tenant_portal_api" {
  count  = var.enable_tenant_portal ? 1 : 0
  role   = aws_iam_role.tenant_portal_api[0].id
  policy = data.aws_iam_policy_document.tenant_portal_api[0].json
}

resource "aws_lambda_function" "tenant_portal_api" {
  count = var.enable_tenant_portal ? 1 : 0

  function_name    = "${local.name_prefix}-tenant-portal-api"
  role             = aws_iam_role.tenant_portal_api[0].arn
  runtime          = "python3.13"
  handler          = "tenant_portal_api.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.tenant_portal_api[0].output_path
  source_code_hash = data.archive_file.tenant_portal_api[0].output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      TENANT_REGISTRY_TABLE    = aws_dynamodb_table.tenant_registry.name
      CUSTOM_RULES_TABLE       = var.enable_custom_health_checks ? aws_dynamodb_table.custom_health_rules[0].name : ""
      WEBHOOK_CONFIGS_TABLE    = var.enable_webhook_notifications ? aws_dynamodb_table.webhook_configs[0].name : ""
      STATUS_HISTORY_TABLE     = var.enable_status_history ? aws_dynamodb_table.status_history[0].name : ""
      AUDIT_LOG_TABLE          = aws_dynamodb_table.agent_audit_log.name
      COGNITO_USER_POOL_ID     = aws_cognito_user_pool.tenant_portal[0].id
      AWS_REGION_NAME          = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.tenant_portal_api]
}

resource "aws_lambda_permission" "tenant_portal_apigw" {
  count         = var.enable_tenant_portal ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tenant_portal_api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.tenant_portal_api[0].execution_arn}/*"
}

# API routes
resource "aws_apigatewayv2_integration" "tenant_portal_lambda" {
  count                  = var.enable_tenant_portal ? 1 : 0
  api_id                 = aws_apigatewayv2_api.tenant_portal_api[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.tenant_portal_api[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "portal_me" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_me_update" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "PUT /me"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_status" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me/status"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_history" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me/history"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_rules" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me/rules"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_rules_create" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "POST /me/rules"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_rules_delete" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "DELETE /me/rules/{rule_id}"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_webhooks" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me/webhooks"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_webhooks_create" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "POST /me/webhooks"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_webhooks_delete" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "DELETE /me/webhooks/{webhook_id}"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

resource "aws_apigatewayv2_route" "portal_audit" {
  count             = var.enable_tenant_portal ? 1 : 0
  api_id            = aws_apigatewayv2_api.tenant_portal_api[0].id
  route_key         = "GET /me/audit"
  target            = "integrations/${aws_apigatewayv2_integration.tenant_portal_lambda[0].id}"
  authorization_type = "JWT"
  authorizer_id     = aws_apigatewayv2_authorizer.tenant_portal[0].id
}

# =============================================================================
# LAMBDA - CUSTOM HEALTH RULES MANAGER (Sub-Phase 3)
# =============================================================================
data "archive_file" "custom_health_rules_manager" {
  count       = var.enable_custom_health_checks ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_custom_health_rules"
  output_path = "${path.module}/.build/custom_health_rules.zip"
}

resource "aws_cloudwatch_log_group" "custom_health_rules_manager" {
  count             = var.enable_custom_health_checks ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-custom-health-rules"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "custom_health_rules_manager" {
  count              = var.enable_custom_health_checks ? 1 : 0
  name               = "${local.name_prefix}-custom-health-rules-manager"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "custom_health_rules_manager" {
  count = var.enable_custom_health_checks ? 1 : 0
  statement {
    sid       = "ReadWriteRules"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.custom_health_rules[0].arn,
      "${aws_dynamodb_table.custom_health_rules[0].arn}/index/*",
    ]
  }

  statement {
    sid       = "ReadTenantRegistry"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.tenant_registry.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.custom_health_rules_manager[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "custom_health_rules_manager" {
  count  = var.enable_custom_health_checks ? 1 : 0
  role   = aws_iam_role.custom_health_rules_manager[0].id
  policy = data.aws_iam_policy_document.custom_health_rules_manager[0].json
}

resource "aws_lambda_function" "custom_health_rules_manager" {
  count = var.enable_custom_health_checks ? 1 : 0

  function_name    = "${local.name_prefix}-custom-health-rules-manager"
  role             = aws_iam_role.custom_health_rules_manager[0].arn
  runtime          = "python3.13"
  handler          = "custom_health_rules.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.custom_health_rules_manager[0].output_path
  source_code_hash = data.archive_file.custom_health_rules_manager[0].output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      CUSTOM_RULES_TABLE     = aws_dynamodb_table.custom_health_rules[0].name
      TENANT_REGISTRY_TABLE  = aws_dynamodb_table.tenant_registry.name
      MAX_RULES_PER_TENANT   = tostring(var.custom_health_max_rules_per_tenant)
      MAX_SCORE_IMPACT       = tostring(var.custom_health_max_score_impact)
      AWS_REGION_NAME        = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.custom_health_rules_manager]
}

# API Gateway integration
resource "aws_apigatewayv2_integration" "custom_health_rules_lambda" {
  count                  = var.enable_custom_health_checks ? 1 : 0
  api_id                 = aws_apigatewayv2_api.custom_health_rules[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.custom_health_rules_manager[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "custom_health_rules_post" {
  count     = var.enable_custom_health_checks ? 1 : 0
  api_id    = aws_apigatewayv2_api.custom_health_rules[0].id
  route_key = "POST /tenants/{tenant_id}/rules"
  target    = "integrations/${aws_apigatewayv2_integration.custom_health_rules_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "custom_health_rules_get" {
  count     = var.enable_custom_health_checks ? 1 : 0
  api_id    = aws_apigatewayv2_api.custom_health_rules[0].id
  route_key = "GET /tenants/{tenant_id}/rules"
  target    = "integrations/${aws_apigatewayv2_integration.custom_health_rules_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "custom_health_rules_delete" {
  count     = var.enable_custom_health_checks ? 1 : 0
  api_id    = aws_apigatewayv2_api.custom_health_rules[0].id
  route_key = "DELETE /tenants/{tenant_id}/rules/{rule_id}"
  target    = "integrations/${aws_apigatewayv2_integration.custom_health_rules_lambda[0].id}"
}

resource "aws_lambda_permission" "custom_health_rules_apigw" {
  count         = var.enable_custom_health_checks ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.custom_health_rules_manager[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.custom_health_rules[0].execution_arn}/*"
}

# =============================================================================
# SECRETS - WEBHOOK URLS (Sub-Phase 2)
# Stores webhook URLs securely (not in plain text).
# =============================================================================
resource "aws_secretsmanager_secret" "webhook_urls" {
  count                   = var.enable_webhook_notifications ? 1 : 0
  name                    = "${local.name_prefix}-webhook-urls"
  description             = "Webhook URLs for tenant notifications (JSON: {webhook_id: url})"
  recovery_window_in_days = var.secret_recovery_window_days
}

# =============================================================================
# LAMBDA - WEBHOOK NOTIFIER (Sub-Phase 2)
# =============================================================================
data "archive_file" "webhook_notifier" {
  count       = var.enable_webhook_notifications ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_webhook_notifier"
  output_path = "${path.module}/.build/webhook_notifier.zip"
}

resource "aws_cloudwatch_log_group" "webhook_notifier" {
  count             = var.enable_webhook_notifications ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-webhook-notifier"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "webhook_notifier" {
  count              = var.enable_webhook_notifications ? 1 : 0
  name               = "${local.name_prefix}-webhook-notifier"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "webhook_notifier" {
  count = var.enable_webhook_notifications ? 1 : 0
  statement {
    sid       = "ReadWebhookConfigs"
    actions   = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [
      aws_dynamodb_table.webhook_configs[0].arn,
      "${aws_dynamodb_table.webhook_configs[0].arn}/index/*",
    ]
  }

  statement {
    sid       = "ReadWriteCooldowns"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.webhook_cooldowns[0].arn]
  }

  statement {
    sid       = "ReadStatusHistory"
    actions   = ["dynamodb:Query", "dynamodb:GetItem"]
    resources = [
      aws_dynamodb_table.status_history[0].arn,
      "${aws_dynamodb_table.status_history[0].arn}/index/*",
    ]
  }

  statement {
    sid       = "ReadWebhookUrls"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.webhook_urls[0].arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.webhook_notifier[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "webhook_notifier" {
  count  = var.enable_webhook_notifications ? 1 : 0
  role   = aws_iam_role.webhook_notifier[0].id
  policy = data.aws_iam_policy_document.webhook_notifier[0].json
}

resource "aws_lambda_function" "webhook_notifier" {
  count = var.enable_webhook_notifications ? 1 : 0

  function_name    = "${local.name_prefix}-webhook-notifier"
  role             = aws_iam_role.webhook_notifier[0].arn
  runtime          = "python3.13"
  handler          = "webhook_notifier.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.webhook_notifier[0].output_path
  source_code_hash = data.archive_file.webhook_notifier[0].output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      WEBHOOK_CONFIGS_TABLE = aws_dynamodb_table.webhook_configs[0].name
      WEBHOOK_COOLDOWNS_TABLE = aws_dynamodb_table.webhook_cooldowns[0].name
      STATUS_HISTORY_TABLE  = aws_dynamodb_table.status_history[0].name
      WEBHOOK_URLS_SECRET   = aws_secretsmanager_secret.webhook_urls[0].name
      COOLDOWN_SECONDS      = tostring(var.webhook_cooldown_seconds)
      RETRY_ATTEMPTS        = tostring(var.webhook_retry_attempts)
      AWS_REGION_NAME       = var.aws_region
      WEBHOOK_DELIVERY_LOG_TABLE = var.enable_advanced_analytics ? aws_dynamodb_table.webhook_delivery_log[0].name : ""
    }
  }

  depends_on = [aws_cloudwatch_log_group.webhook_notifier]
}

# =============================================================================
# UPDATE STATUS HISTORY SNAPSHOT TO TRIGGER WEBHOOK NOTIFIER
# =============================================================================
# Add permission for status_history_snapshot to invoke webhook_notifier
resource "aws_lambda_permission" "status_history_invoke_webhook" {
  count         = var.enable_webhook_notifications && var.enable_status_history ? 1 : 0
  statement_id  = "AllowStatusHistoryInvokeWebhook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_notifier[0].function_name
  principal     = "lambda.amazonaws.com"
  source_arn    = aws_lambda_function.status_history_snapshot[0].arn
}

# API Gateway integration
resource "aws_apigatewayv2_integration" "tenant_onboarding_lambda" {
  count                  = var.enable_onboarding_api ? 1 : 0
  api_id                 = aws_apigatewayv2_api.tenant_onboarding[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.tenant_onboarding[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "tenant_onboarding_post" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "POST /tenants"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_onboarding_get" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /tenants/{tenant_id}"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_onboarding_list" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /tenants"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_onboarding_delete" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "DELETE /tenants/{tenant_id}"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

# =============================================================================
# API GATEWAY ROUTES - STATUS ENDPOINTS (Phase C)
# =============================================================================

resource "aws_apigatewayv2_route" "tenant_status_system" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /status"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_status_list" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /status/tenants"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_status_detail" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /status/tenants/{tenant_id}"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_status_health" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /status/tenants/{tenant_id}/health"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "tenant_status_metrics" {
  count     = var.enable_onboarding_api ? 1 : 0
  api_id    = aws_apigatewayv2_api.tenant_onboarding[0].id
  route_key = "GET /status/metrics"
  target    = "integrations/${aws_apigatewayv2_integration.tenant_onboarding_lambda[0].id}"
}

resource "aws_lambda_permission" "tenant_onboarding_apigw" {
  count         = var.enable_onboarding_api ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tenant_onboarding[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.tenant_onboarding[0].execution_arn}/*"
}

# =============================================================================
# LAMBDA - TENANT PROVISIONING WORKER (SLOW PATH)
# =============================================================================
data "archive_file" "tenant_provisioning_worker" {
  count       = var.enable_onboarding_api ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/src_tenant_provisioning_worker"
  output_path = "${path.module}/.build/tenant_provisioning_worker.zip"
}

resource "aws_cloudwatch_log_group" "tenant_provisioning_worker" {
  count             = var.enable_onboarding_api ? 1 : 0
  name              = "/aws/lambda/${local.name_prefix}-tenant-provisioning-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "tenant_provisioning_worker" {
  count              = var.enable_onboarding_api ? 1 : 0
  name               = "${local.name_prefix}-tenant-provisioning-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "tenant_provisioning_worker" {
  count = var.enable_onboarding_api ? 1 : 0
  role  = aws_iam_role.tenant_provisioning_worker[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "TenantRegistry"
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.tenant_registry.arn
      },
      {
        Sid = "BedrockAgentManagement"
        Effect = "Allow"
        Action = [
          "bedrock:CreateAgent",
          "bedrock:UpdateAgent",
          "bedrock:DeleteAgent",
          "bedrock:GetAgent",
          "bedrock:PrepareAgent",
          "bedrock:CreateAgentAlias",
          "bedrock:UpdateAgentAlias",
          "bedrock:DeleteAgentAlias",
          "bedrock:GetAgentAlias",
          "bedrock:CreateAgentActionGroup",
          "bedrock:UpdateAgentActionGroup",
          "bedrock:DeleteAgentActionGroup",
          "bedrock:AssociateAgentKnowledgeBase",
          "bedrock:DisassociateAgentKnowledgeBase"
      ,{
        Sid    = "PurgeTenantS3Data"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketVersions",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion"
        ]
        Resource = [
          aws_s3_bucket.agent_schemas.arn,
          "${aws_s3_bucket.agent_schemas.arn}/*",
          aws_s3_bucket.few_shot_examples.arn,
          "${aws_s3_bucket.few_shot_examples.arn}/*",
          aws_s3_bucket.customer_branding.arn,
          "${aws_s3_bucket.customer_branding.arn}/*"
        ]
      },
      {
        Sid    = "PurgeTenantKBDocuments"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketVersions",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion"
        ]
        Resource = var.enable_knowledge_base ? [
          aws_s3_bucket.kb_documents[0].arn,
          "${aws_s3_bucket.kb_documents[0].arn}/*"
        ] : []
      },
      {
        Sid      = "StartKBReingestion"
        Effect   = "Allow"
        Action   = ["bedrock:StartIngestionJob"]
        Resource = var.enable_knowledge_base ? [
          aws_bedrockagent_knowledge_base.it_concierge[0].arn
        ] : []
      }
        ]
        Resource = "*"
      },
      {
        Sid = "BedrockIAMPassThrough"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [aws_iam_role.bedrock_agent.arn]
      },
      {
        Sid = "ConsumeQueue"
        Effect = "Allow"
        Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        Resource = aws_sqs_queue.tenant_provisioning[0].arn
      },
      {
        Sid = "WriteLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.tenant_provisioning_worker[0].arn}:*"]
      }
    ]
  })
}

resource "aws_lambda_function" "tenant_provisioning_worker" {
  count = var.enable_onboarding_api ? 1 : 0

  function_name    = "${local.name_prefix}-tenant-provisioning-worker"
  role             = aws_iam_role.tenant_provisioning_worker[0].arn
  runtime          = "python3.13"
  handler          = "tenant_provisioning_worker.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.tenant_provisioning_worker[0].output_path
  source_code_hash = data.archive_file.tenant_provisioning_worker[0].output_base64sha256
  timeout          = 900  # 15 minutes (agent creation can be slow)
  memory_size      = 512

  environment {
    variables = {
      TENANT_REGISTRY_TABLE    = aws_dynamodb_table.tenant_registry.name
      BEDROCK_AGENT_ROLE_ARN   = aws_iam_role.bedrock_agent.arn
      AGENT_MODEL_ID           = var.agent_model_id
      GUARDRAIL_ID             = aws_bedrock_guardrail.agent.id
      GUARDRAIL_VERSION        = aws_bedrock_guardrail_version.agent_v1.guardrail_version
      AGENT_SCHEMAS_BUCKET     = aws_s3_bucket.agent_schemas.id
      DEFAULT_INSTRUCTION      = var.default_agent_instruction
      IDLE_SESSION_TTL         = tostring(var.agent_idle_session_ttl_seconds)
      ENABLE_KB                = tostring(var.enable_knowledge_base)
      DRAIN_SECONDS            = tostring(var.deprovision_drain_seconds)
      AWS_REGION_NAME          = var.aws_region
      # S3 purge coverage (all tenant-scoped buckets)
      FEW_SHOT_EXAMPLES_BUCKET = aws_s3_bucket.few_shot_examples.id
      CUSTOMER_BRANDING_BUCKET = aws_s3_bucket.customer_branding.id
      KB_DOCUMENTS_BUCKET      = var.enable_knowledge_base ? aws_s3_bucket.kb_documents[0].id : ""

      # KB vector purge
      KNOWLEDGE_BASE_ID = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.it_concierge[0].id : ""
      DATA_SOURCE_ID    = var.enable_knowledge_base ? aws_bedrockagent_data_source.kb_documents[0].data_source_id : ""
    }
  }

  depends_on = [aws_cloudwatch_log_group.tenant_provisioning_worker]
}

resource "aws_lambda_event_source_mapping" "tenant_provisioning" {
  count                            = var.enable_onboarding_api ? 1 : 0
  event_source_arn                 = aws_sqs_queue.tenant_provisioning[0].arn
  function_name                    = aws_lambda_function.tenant_provisioning_worker[0].arn
  batch_size                       = 1
  maximum_concurrency              = 2  # Limit concurrent provisioning
  function_response_types          = ["ReportBatchItemFailures"]
}

# =============================================================================
# IAM + LAMBDA - CUSTOMER INSIGHTS ORCHESTRATOR (NEW)
# =============================================================================
resource "aws_iam_role" "customer_insights_orchestrator" {
  name               = "${local.name_prefix}-customer-insights-orchestrator"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "customer_insights_orchestrator" {
  statement {
    sid       = "ReadCustomerInsightsPreferences"
    actions   = ["dynamodb:Query", "dynamodb:Scan"]
    resources = [
      aws_dynamodb_table.customer_insights_preferences.arn,
      "${aws_dynamodb_table.customer_insights_preferences.arn}/index/*",
    ]
  }

  statement {
    sid       = "SendToQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.customer_insights.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "EmitCustomMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.customer_insights_orchestrator.arn}:*"]
  }
}

resource "aws_iam_role_policy" "customer_insights_orchestrator" {
  role   = aws_iam_role.customer_insights_orchestrator.id
  policy = data.aws_iam_policy_document.customer_insights_orchestrator.json
}

resource "aws_lambda_function" "customer_insights_orchestrator" {
  function_name    = "${local.name_prefix}-customer-insights-orchestrator"
  role             = aws_iam_role.customer_insights_orchestrator.arn
  runtime          = "python3.13"
  handler          = "customer_insights_orchestrator.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.customer_insights_orchestrator.output_path
  source_code_hash = data.archive_file.customer_insights_orchestrator.output_base64sha256
  timeout          = 60
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      CUSTOMER_INSIGHTS_TABLE = aws_dynamodb_table.customer_insights_preferences.name
      INSIGHTS_QUEUE_URL      = aws_sqs_queue.customer_insights.url
      MAX_CUSTOMERS_PER_RUN   = tostring(var.customer_insights_max_customers_per_run)
      DEFAULT_LOCAL_DAY       = tostring(var.customer_insights_default_local_day)
      DEFAULT_LOCAL_HOUR      = tostring(var.customer_insights_default_local_hour)
      AWS_REGION_NAME         = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.customer_insights_orchestrator]
}

# =============================================================================
# IAM + LAMBDA - CUSTOMER INSIGHTS WORKER (NEW)
# =============================================================================
resource "aws_iam_role" "customer_insights_worker" {
  name               = "${local.name_prefix}-customer-insights-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "customer_insights_worker" {
  statement {
    sid       = "BedrockInvoke"
    actions   = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.customer_insights_model_id}",
      "arn:aws:bedrock:us-*::foundation-model/${var.customer_insights_foundation_model_id}",
    ]
  }

  statement {
    sid       = "BedrockGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [
      aws_bedrock_guardrail.customer_insights.arn,
      aws_bedrock_guardrail_version.customer_insights_v1.arn,
    ]
  }

  statement {
    sid       = "ReadApiSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.rmm.arn,
      aws_secretsmanager_secret.psa.arn,
      aws_secretsmanager_secret.unsubscribe_signing.arn,
    ]
  }

  statement {
    sid       = "ConsumeQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.customer_insights.arn]
  }

  statement {
    sid       = "ReadCustomerInsightsPreferences"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.customer_insights_preferences.arn]
  }

  statement {
    sid       = "ReadAlertHistory"
    actions   = ["dynamodb:Query"]
    resources = [aws_dynamodb_table.customer_alert_history.arn]
  }

  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.customer_insights_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "customer_insights_worker" {
  role   = aws_iam_role.customer_insights_worker.id
  policy = data.aws_iam_policy_document.customer_insights_worker.json
}

resource "aws_lambda_function" "customer_insights_worker" {
  function_name    = "${local.name_prefix}-customer-insights-worker"
  role             = aws_iam_role.customer_insights_worker.arn
  runtime          = "python3.13"
  handler          = "customer_insights_worker.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.customer_insights_worker.output_path
  source_code_hash = data.archive_file.customer_insights_worker.output_base64sha256
  timeout          = 300  # 5 minutes (reports take longer than digest)
  memory_size      = 512

  tracing_config { mode = "Active" }

  environment {
    variables = {
      RMM_SECRET_NAME          = aws_secretsmanager_secret.rmm.name
      PSA_SECRET_NAME          = aws_secretsmanager_secret.psa.name
      UNSUBSCRIBE_SECRET_NAME  = aws_secretsmanager_secret.unsubscribe_signing.name
      ALERT_HISTORY_TABLE      = aws_dynamodb_table.customer_alert_history.name
      CUSTOMER_INSIGHTS_TABLE  = aws_dynamodb_table.customer_insights_preferences.name
      INSIGHTS_MODEL_ID        = var.customer_insights_model_id
      GUARDRAIL_ID             = aws_bedrock_guardrail.customer_insights.id
      GUARDRAIL_VERSION        = aws_bedrock_guardrail_version.customer_insights_v1.guardrail_version
      SENDER_EMAIL             = var.customer_insights_sender_email
      HISTORY_DAYS             = tostring(var.customer_insights_history_days)
      UNSUBSCRIBE_BASE_URL     = var.customer_insights_unsubscribe_base_url
      MSP_DEFAULT_BRANDING     = jsonencode(var.msp_default_branding)
      AWS_REGION_NAME          = var.aws_region
    }
  }

  depends_on = [aws_cloudwatch_log_group.customer_insights_worker]
}

resource "aws_lambda_event_source_mapping" "customer_insights" {
  event_source_arn        = aws_sqs_queue.customer_insights.arn
  function_name          = aws_lambda_function.customer_insights_worker.arn
  batch_size             = 1
  maximum_concurrency    = 5  # Lower than digest (reports are heavier)
  function_response_types = ["ReportBatchItemFailures"]
}

# =============================================================================
# IAM + LAMBDA - CUSTOMER INSIGHTS UNSUBSCRIBE HANDLER (NEW)
# =============================================================================
resource "aws_iam_role" "customer_insights_unsubscribe" {
  name               = "${local.name_prefix}-customer-insights-unsubscribe"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "customer_insights_unsubscribe" {
  statement {
    sid       = "ReadSigningSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.unsubscribe_signing.arn]
  }

  statement {
    sid       = "UpdateCustomerInsightsPreferences"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.customer_insights_preferences.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.customer_insights_unsubscribe.arn}:*"]
  }
}

resource "aws_iam_role_policy" "customer_insights_unsubscribe" {
  role   = aws_iam_role.customer_insights_unsubscribe.id
  policy = data.aws_iam_policy_document.customer_insights_unsubscribe.json
}

resource "aws_lambda_function" "customer_insights_unsubscribe" {
  function_name    = "${local.name_prefix}-customer-insights-unsubscribe"
  role             = aws_iam_role.customer_insights_unsubscribe.arn
  runtime          = "python3.13"
  handler          = "customer_insights_unsubscribe.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.customer_insights_unsubscribe.output_path
  source_code_hash = data.archive_file.customer_insights_unsubscribe.output_base64sha256
  timeout          = 10
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      CUSTOMER_INSIGHTS_TABLE = aws_dynamodb_table.customer_insights_preferences.name
      UNSUBSCRIBE_SECRET_NAME = aws_secretsmanager_secret.unsubscribe_signing.name
      MSP_COMPANY_NAME        = var.msp_default_branding.company_name
      MSP_SUPPORT_EMAIL       = var.msp_default_branding.support_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.customer_insights_unsubscribe]
}

# =============================================================================
# IAM + LAMBDA - AGENT FEEDBACK HANDLER
# =============================================================================
resource "aws_iam_role" "agent_feedback_handler" {
  name               = "${local.name_prefix}-agent-feedback-handler"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "agent_feedback_handler" {
  statement {
    sid       = "ReadWriteFeedback"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.agent_feedback.arn,
      "${aws_dynamodb_table.agent_feedback.arn}/index/*",
    ]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.agent_feedback_handler.arn}:*"]
  }
}

resource "aws_iam_role_policy" "agent_feedback_handler" {
  role   = aws_iam_role.agent_feedback_handler.id
  policy = data.aws_iam_policy_document.agent_feedback_handler.json
}

resource "aws_lambda_function" "agent_feedback_handler" {
  function_name    = "${local.name_prefix}-agent-feedback-handler"
  role             = aws_iam_role.agent_feedback_handler.arn
  runtime          = "python3.13"
  handler          = "agent_feedback.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.agent_feedback_handler.output_path
  source_code_hash = data.archive_file.agent_feedback_handler.output_base64sha256
  timeout          = 10
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      FEEDBACK_TABLE        = aws_dynamodb_table.agent_feedback.name
      FEEDBACK_RETENTION    = tostring(var.agent_feedback_retention_days)
      AWS_REGION_NAME       = var.aws_region
      TENANT_REGISTRY_TABLE = aws_dynamodb_table.tenant_registry.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.agent_feedback_handler]
}

# =============================================================================
# IAM + LAMBDA - AGENT FEEDBACK SYNC
# =============================================================================
resource "aws_iam_role" "agent_feedback_sync" {
  name               = "${local.name_prefix}-agent-feedback-sync"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "agent_feedback_sync" {
  statement {
    sid       = "ReadWriteFeedback"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.agent_feedback.arn,
      "${aws_dynamodb_table.agent_feedback.arn}/index/*",
    ]
  }

  statement {
    sid       = "ReadWriteAgentExamples"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.agent_schemas.arn}/tenants/*/agent-examples.json"]
  }

  # Allow listing tenant prefixes (needed to discover all tenants)
  statement {
    sid       = "ListTenantPrefixes"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.agent_schemas.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["tenants/*"]
    }
  }

  # Read tenant registry to discover active tenants
  statement {
    sid       = "ReadTenantRegistry"
    actions   = ["dynamodb:Query", "dynamodb:Scan"]
    resources = [
      aws_dynamodb_table.tenant_registry.arn,
      "${aws_dynamodb_table.tenant_registry.arn}/index/*",
    ]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.agent_feedback_sync.arn}:*"]
  }
}

resource "aws_iam_role_policy" "agent_feedback_sync" {
  role   = aws_iam_role.agent_feedback_sync.id
  policy = data.aws_iam_policy_document.agent_feedback_sync.json
}

resource "aws_lambda_function" "agent_feedback_sync" {
  function_name    = "${local.name_prefix}-agent-feedback-sync"
  role             = aws_iam_role.agent_feedback_sync.arn
  runtime          = "python3.13"
  handler          = "agent_feedback_sync.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.agent_feedback_sync.output_path
  source_code_hash = data.archive_file.agent_feedback_sync.output_base64sha256
  timeout          = 60
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      FEEDBACK_TABLE            = aws_dynamodb_table.agent_feedback.name
      AGENT_EXAMPLES_BUCKET     = aws_s3_bucket.agent_schemas.id
      AGENT_EXAMPLES_KEY        = "agent-examples.json"
      MAX_AGENT_EXAMPLES        = tostring(var.agent_max_examples_in_context)
      AWS_REGION_NAME           = var.aws_region
      TENANT_REGISTRY_TABLE = aws_dynamodb_table.tenant_registry.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.agent_feedback_sync]
}

# =============================================================================
# IAM + LAMBDA - RESET PASSWORD (secure one-time link flow)
# =============================================================================
resource "aws_iam_role" "reset_password" {
  name               = "${local.name_prefix}-reset-password"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "reset_password" {
  # Read Entra credentials for Graph API calls (to actually set the password)
  statement {
    sid       = "ReadEntraCredentials"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.entra_graph.arn]
  }

  # Read/write reset tokens
  statement {
    sid       = "ResetTokens"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.password_reset_tokens.arn,
      "${aws_dynamodb_table.password_reset_tokens.arn}/index/*",
    ]
  }

  # Write audit log
  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  # Send notification emails
  statement {
    sid       = "SendEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["*"]
  }

  # X-Ray tracing
  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  # CloudWatch Logs
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.reset_password.arn}:*"]
  }
}

resource "aws_iam_role_policy" "reset_password" {
  role   = aws_iam_role.reset_password.id
  policy = data.aws_iam_policy_document.reset_password.json
}

resource "aws_lambda_function" "reset_password" {
  function_name    = "${local.name_prefix}-reset-password"
  role             = aws_iam_role.reset_password.arn
  runtime          = "python3.13"
  handler          = "reset_password.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.reset_password.output_path
  source_code_hash = data.archive_file.reset_password.output_base64sha256
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  environment {
    variables = {
      ENTRA_GRAPH_SECRET_NAME    = aws_secretsmanager_secret.entra_graph.name
      ENTRA_TENANT_ID            = var.entra_tenant_id
      ENTRA_APP_CLIENT_ID        = var.entra_app_client_id
      RESET_TOKENS_TABLE         = aws_dynamodb_table.password_reset_tokens.name
      AUDIT_LOG_TABLE            = aws_dynamodb_table.agent_audit_log.name
      TOKEN_TTL_SECONDS          = tostring(var.password_reset_token_ttl_seconds)
      MAX_ATTEMPTS_PER_TOKEN     = tostring(var.password_reset_max_attempts_per_token)
      SENDER_EMAIL               = var.password_reset_sender_email
      SUPPORT_EMAIL              = var.password_reset_support_email
      MSP_COMPANY_NAME           = var.msp_default_branding.company_name
      AWS_REGION_NAME            = var.aws_region
      TENANT_REGISTRY_TABLE = aws_dynamodb_table.tenant_registry.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.reset_password]
}

# =============================================================================
# IAM + LAMBDA - TEAMS BOT
# =============================================================================
resource "aws_iam_role" "teams_bot" {
  name               = "${local.name_prefix}-teams-bot"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "teams_bot" {
  statement {
    sid       = "InvokeAgent"
    actions   = ["bedrock:InvokeAgent"]
    resources = [
      aws_bedrockagent_agent.it_concierge.agent_arn,
      "${aws_bedrockagent_agent.it_concierge.agent_arn}/alias/*"
    ]
  }

  statement {
    sid       = "ReadBotSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.teams_bot_secret.arn]
  }

  statement {
    sid       = "ReadWriteConversations"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.agent_conversations.arn]
  }

  statement {
    sid       = "WriteAuditLog"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.agent_audit_log.arn]
  }

  # NEW: read pending operations to attach approval cards
  statement {
    sid       = "ReadPendingOperations"
    actions   = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.agent_pending_operations.arn,
      "${aws_dynamodb_table.agent_pending_operations.arn}/index/*",
    ]
  }

  # NEW: consume nonces (read + delete)
  statement {
    sid       = "ConsumeNonce"
    actions   = ["dynamodb:GetItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.agent_confirmation_nonces.arn]
  }

  statement {
    sid       = "ReadConfirmationSigningKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.agent_confirmation_signing.arn]
  }

  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.teams_bot.arn}:*"]
  }

  statement {
    sid       = "ReadTenantRegistry"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      aws_dynamodb_table.tenant_registry.arn,
      "${aws_dynamodb_table.tenant_registry.arn}/index/*",
    ]
  }

  statement {
    sid       = "InvokeFeedbackHandler"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.agent_feedback_handler.arn]
  }

  statement {
    sid       = "ReadAgentExamples"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.agent_schemas.arn}/tenants/*/agent-examples.json"]
  }
}

resource "aws_iam_role_policy" "teams_bot" {
  role   = aws_iam_role.teams_bot.id
  policy = data.aws_iam_policy_document.teams_bot.json
}

resource "aws_lambda_function" "teams_bot" {
  function_name    = "${local.name_prefix}-teams-bot"
  role             = aws_iam_role.teams_bot.arn
  runtime          = "python3.13"
  handler          = "teams_bot.lambda_handler"
  architectures    = ["arm64"]
  filename         = data.archive_file.teams_bot.output_path
  source_code_hash = data.archive_file.teams_bot.output_base64sha256
  timeout          = 60
  memory_size      = 512

  # NEW: Attach the JWT validation layer
  layers = [aws_lambda_layer_version.bot_framework_jwt.arn]

  tracing_config { mode = "Active" }

  environment {
    variables = {
      AGENT_ID                    = aws_bedrockagent_agent.it_concierge.agent_id
      AGENT_ALIAS_ID              = aws_bedrockagent_agent_alias.latest.agent_alias_id
      BOT_APP_ID                  = var.bot_app_id
      BOT_SECRET_NAME             = aws_secretsmanager_secret.teams_bot_secret.name
      CONVERSATIONS_TABLE         = aws_dynamodb_table.agent_conversations.name
      AUDIT_LOG_TABLE             = aws_dynamodb_table.agent_audit_log.name
      PENDING_OPERATIONS_TABLE    = aws_dynamodb_table.agent_pending_operations.name
      CONFIRMATION_NONCES_TABLE   = aws_dynamodb_table.agent_confirmation_nonces.name
      ENTRA_GRAPH_SECRET_NAME     = aws_secretsmanager_secret.entra_graph.name
      ENTRA_TENANT_ID             = var.entra_tenant_id
      ENTRA_APP_CLIENT_ID         = var.entra_app_client_id
      AUDIT_LOG_RETENTION         = tostring(var.agent_audit_log_retention_days)
      TENANT_REGISTRY_TABLE       = aws_dynamodb_table.tenant_registry.name
      DEFAULT_TENANT_ID           = var.default_tenant_id
      AWS_REGION_NAME             = var.aws_region
      AGENT_FEEDBACK_HANDLER    = aws_lambda_function.agent_feedback_handler.function_name
      AGENT_EXAMPLES_BUCKET     = aws_s3_bucket.agent_schemas.id
      AGENT_EXAMPLES_KEY        = "agent-examples.json"
      MAX_AGENT_EXAMPLES        = tostring(var.agent_max_examples_in_context)
      AGENT_EXAMPLES_CACHE_TTL  = tostring(var.agent_examples_cache_ttl_seconds)
      TENANT_REGISTRY_TABLE     = aws_dynamodb_table.tenant_registry.name
      DEFAULT_TENANT_ID         = var.default_tenant_id
      # was: aws_s3_bucket.few_shot_examples.id
      AGENT_EXAMPLES_BUCKET = aws_s3_bucket.agent_schemas.id
      AGENT_EXAMPLES_KEY    = "agent-examples.json"
    }
  }

  depends_on = [aws_cloudwatch_log_group.teams_bot]
}

# =============================================================================
# API GATEWAY - WEBHOOK (ticket triage)
# =============================================================================
resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name_prefix}-webhook"
  protocol_type = "HTTP"
}

resource "aws_lambda_permission" "authorizer" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/authorizers/*"
}

resource "aws_apigatewayv2_authorizer" "token" {
  api_id                            = aws_apigatewayv2_api.webhook.id
  name                              = "psa-shared-token"
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.${var.webhook_header_name}"]
  authorizer_result_ttl_in_seconds  = var.authorizer_cache_ttl_seconds
}

data "aws_iam_policy_document" "apigw_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apigw_sqs" {
  name               = "${local.name_prefix}-apigw-sqs"
  assume_role_policy = data.aws_iam_policy_document.apigw_assume.json
}

resource "aws_iam_role_policy" "apigw_sqs" {
  role = aws_iam_role.apigw_sqs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.tickets.arn
    }]
  })
}

resource "aws_apigatewayv2_integration" "enqueue" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_subtype    = "SQS-SendMessage"
  credentials_arn        = aws_iam_role.apigw_sqs.arn
  payload_format_version = "1.0"

  request_parameters = {
    QueueUrl    = aws_sqs_queue.tickets.url
    MessageBody = "$request.body"
  }
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id             = aws_apigatewayv2_api.webhook.id
  route_key          = "POST /webhooks/psa"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.token.id
  target             = "integrations/${aws_apigatewayv2_integration.enqueue.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigw.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      sourceIp       = "$context.identity.sourceIp"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      authError      = "$context.authorizer.error"
      integrationErr = "$context.integration.error"
    })
  }
}

# =============================================================================
# API GATEWAY - UNSUBSCRIBE
# =============================================================================
resource "aws_apigatewayv2_api" "unsubscribe" {
  name          = "${local.name_prefix}-unsubscribe"
  protocol_type = "HTTP"
}

resource "aws_lambda_permission" "unsubscribe_apigw" {
  statement_id  = "AllowUnsubscribeAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.unsubscribe_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.unsubscribe.execution_arn}/*"
}

resource "aws_apigatewayv2_integration" "unsubscribe_lambda" {
  api_id                 = aws_apigatewayv2_api.unsubscribe.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.unsubscribe_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "unsubscribe_get" {
  api_id    = aws_apigatewayv2_api.unsubscribe.id
  route_key = "GET /unsubscribe"
  target    = "integrations/${aws_apigatewayv2_integration.unsubscribe_lambda.id}"
}

resource "aws_apigatewayv2_stage" "unsubscribe_default" {
  api_id      = aws_apigatewayv2_api.unsubscribe.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.unsubscribe_apigw.arn
    format = jsonencode({
      requestId = "$context.requestId"
      sourceIp  = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
    })
  }
}

# =============================================================================
# API GATEWAY - CUSTOMER INSIGHTS UNSUBSCRIBE (NEW)
# =============================================================================
resource "aws_apigatewayv2_api" "customer_insights_unsubscribe" {
  name          = "${local.name_prefix}-customer-insights"
  protocol_type = "HTTP"
}

resource "aws_lambda_permission" "customer_insights_unsubscribe_apigw" {
  statement_id  = "AllowCustomerInsightsUnsubscribeAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.customer_insights_unsubscribe.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.customer_insights_unsubscribe.execution_arn}/*"
}

resource "aws_apigatewayv2_integration" "customer_insights_unsubscribe_lambda" {
  api_id                 = aws_apigatewayv2_api.customer_insights_unsubscribe.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.customer_insights_unsubscribe.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "customer_insights_unsubscribe_get" {
  api_id    = aws_apigatewayv2_api.customer_insights_unsubscribe.id
  route_key = "GET /unsubscribe-insights"
  target    = "integrations/${aws_apigatewayv2_integration.customer_insights_unsubscribe_lambda.id}"
}

resource "aws_apigatewayv2_stage" "customer_insights_unsubscribe_default" {
  api_id      = aws_apigatewayv2_api.customer_insights_unsubscribe.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.customer_insights_apigw.arn
    format = jsonencode({
      requestId = "$context.requestId"
      sourceIp  = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
    })
  }
}

# =============================================================================
# API GATEWAY - TEAMS BOT
# =============================================================================
resource "aws_apigatewayv2_api" "teams_bot" {
  name          = "${local.name_prefix}-teams-bot"
  protocol_type = "HTTP"
}

resource "aws_lambda_permission" "teams_bot_apigw" {
  statement_id  = "AllowTeamsBotAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.teams_bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.teams_bot.execution_arn}/*"
}

resource "aws_apigatewayv2_integration" "teams_bot_lambda" {
  api_id                 = aws_apigatewayv2_api.teams_bot.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.teams_bot.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "teams_bot_post" {
  api_id    = aws_apigatewayv2_api.teams_bot.id
  route_key = "POST /api/messages"
  target    = "integrations/${aws_apigatewayv2_integration.teams_bot_lambda.id}"
}

resource "aws_apigatewayv2_stage" "teams_bot_default" {
  api_id      = aws_apigatewayv2_api.teams_bot.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.teams_bot_apigw.arn
    format = jsonencode({
      requestId = "$context.requestId"
      sourceIp  = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
    })
  }
}

# =============================================================================
# API GATEWAY - PASSWORD RESET (public-facing, for user self-service)
# =============================================================================
resource "aws_apigatewayv2_api" "reset_password" {
  name          = "${local.name_prefix}-password-reset"
  protocol_type = "HTTP"
}

resource "aws_lambda_permission" "reset_password_apigw" {
  statement_id  = "AllowPasswordResetAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reset_password.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.reset_password.execution_arn}/*"
}

resource "aws_apigatewayv2_integration" "reset_password_lambda" {
  api_id                 = aws_apigatewayv2_api.reset_password.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.reset_password.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "reset_password_get" {
  api_id    = aws_apigatewayv2_api.reset_password.id
  route_key = "GET /set-password"
  target    = "integrations/${aws_apigatewayv2_integration.reset_password_lambda.id}"
}

resource "aws_apigatewayv2_route" "reset_password_post" {
  api_id    = aws_apigatewayv2_api.reset_password.id
  route_key = "POST /set-password"
  target    = "integrations/${aws_apigatewayv2_integration.reset_password_lambda.id}"
}

resource "aws_apigatewayv2_stage" "reset_password_default" {
  api_id      = aws_apigatewayv2_api.reset_password.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.reset_password.arn
    format = jsonencode({
      requestId = "$context.requestId"
      sourceIp  = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
    })
  }
}

# =============================================================================
# ACM CERTIFICATE - PASSWORD RESET CUSTOM DOMAIN
# Note: Certificate must be in the same region as the API Gateway (regional endpoint).
# =============================================================================
resource "aws_acm_certificate" "password_reset" {
  domain_name       = var.password_reset_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Purpose = "PasswordResetCustomDomain"
  }
}

resource "aws_route53_record" "password_reset_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.password_reset.domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = var.password_reset_hosted_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "password_reset" {
  certificate_arn = aws_acm_certificate.password_reset.arn

  validation_record_fqdns = [
    for record in aws_route53_record.password_reset_cert_validation :
    record.fqdn
  ]
}

# =============================================================================
# API GATEWAY CUSTOM DOMAIN - PASSWORD RESET
# =============================================================================
resource "aws_apigatewayv2_domain_name" "password_reset" {
  domain_name = var.password_reset_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.password_reset.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = {
    Purpose = "PasswordResetCustomDomain"
  }
}

resource "aws_apigatewayv2_api_mapping" "password_reset" {
  api_id      = aws_apigatewayv2_api.reset_password.id
  domain_name = aws_apigatewayv2_domain_name.password_reset.id
  stage       = aws_apigatewayv2_stage.reset_password_default.id
}

# =============================================================================
# ROUTE 53 - PASSWORD RESET CUSTOM DOMAIN
# =============================================================================
resource "aws_route53_record" "password_reset_a" {
  zone_id = var.password_reset_hosted_zone_id
  name    = var.password_reset_domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.password_reset.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.password_reset.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "password_reset_aaaa" {
  zone_id = var.password_reset_hosted_zone_id
  name    = var.password_reset_domain_name
  type    = "AAAA"

  alias {
    name                   = aws_apigatewayv2_domain_name.password_reset.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.password_reset.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

# =============================================================================
# EVENTBRIDGE - SCHEDULES
# =============================================================================
resource "aws_cloudwatch_event_rule" "weekly_report" {
  name                = "${local.name_prefix}-weekly-metrics-report"
  description         = "Triggers weekly metrics report every Monday at 8 AM UTC"
  schedule_expression = "cron(0 8 ? * MON *)"
}

resource "aws_cloudwatch_event_target" "metrics_reporter" {
  rule      = aws_cloudwatch_event_rule.weekly_report.name
  target_id = "metrics-reporter"
  arn       = aws_lambda_function.metrics_reporter.arn
}

resource "aws_lambda_permission" "eventbridge_metrics" {
  statement_id  = "AllowEventBridgeInvokeMetricsReporter"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.metrics_reporter.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_report.arn
}

resource "aws_cloudwatch_event_rule" "daily_feedback_collection" {
  name                = "${local.name_prefix}-daily-feedback-collection"
  description         = "Collects Incorrect tickets from ConnectWise daily at 2 AM UTC"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "feedback_collector" {
  rule      = aws_cloudwatch_event_rule.daily_feedback_collection.name
  target_id = "feedback-collector"
  arn       = aws_lambda_function.feedback_collector.arn
}

resource "aws_lambda_permission" "eventbridge_feedback" {
  statement_id  = "AllowEventBridgeInvokeFeedbackCollector"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.feedback_collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_feedback_collection.arn
}

resource "aws_cloudwatch_event_rule" "daily_feedback_sync" {
  name                = "${local.name_prefix}-daily-feedback-sync"
  description         = "Syncs approved feedback corrections to few-shot examples daily at 3 AM UTC"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_rule" "daily_agent_feedback_sync" {
  name                = "${local.name_prefix}-daily-agent-feedback-sync"
  description         = "Syncs approved agent feedback to few-shot examples daily at 4 AM UTC"
  schedule_expression = "cron(0 4 * * ? *)"
}

resource "aws_cloudwatch_event_target" "agent_feedback_sync" {
  rule      = aws_cloudwatch_event_rule.daily_agent_feedback_sync.name
  target_id = "agent-feedback-sync"
  arn       = aws_lambda_function.agent_feedback_sync.arn
}

resource "aws_lambda_permission" "eventbridge_agent_feedback_sync" {
  statement_id  = "AllowEventBridgeInvokeAgentFeedbackSync"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent_feedback_sync.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_agent_feedback_sync.arn
}

resource "aws_cloudwatch_event_target" "feedback_sync" {
  rule      = aws_cloudwatch_event_rule.daily_feedback_sync.name
  target_id = "feedback-sync"
  arn       = aws_lambda_function.feedback_sync.arn
}

resource "aws_lambda_permission" "eventbridge_feedback_sync" {
  statement_id  = "AllowEventBridgeInvokeFeedbackSync"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.feedback_sync.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_feedback_sync.arn
}

resource "aws_cloudwatch_event_rule" "hourly_customer_digest" {
  name                = "${local.name_prefix}-hourly-customer-digest"
  description         = "Evaluates customer local times hourly and fans out digests at each customer's local morning"
  schedule_expression = "cron(5 * * * ? *)"
}

resource "aws_cloudwatch_event_target" "customer_digest_orchestrator" {
  rule      = aws_cloudwatch_event_rule.hourly_customer_digest.name
  target_id = "customer-digest-orchestrator"
  arn       = aws_lambda_function.customer_digest_orchestrator.arn
}

resource "aws_lambda_permission" "eventbridge_customer_digest" {
  statement_id  = "AllowEventBridgeInvokeCustomerDigestOrchestrator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.customer_digest_orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_customer_digest.arn
}

# =============================================================================
# EVENTBRIDGE - HOURLY CUSTOMER INSIGHTS EVALUATION (NEW)
# Runs hourly; the orchestrator filters to customers whose local time matches
# their configured report day/hour.
# =============================================================================
resource "aws_cloudwatch_event_rule" "hourly_customer_insights" {
  name                = "${local.name_prefix}-hourly-customer-insights"
  description         = "Evaluates customer local times hourly and fans out insights reports at each customer's configured day/hour"
  schedule_expression = "cron(15 * * * ? *)"  # 15 minutes past every hour
}

resource "aws_cloudwatch_event_target" "customer_insights_orchestrator" {
  rule      = aws_cloudwatch_event_rule.hourly_customer_insights.name
  target_id = "customer-insights-orchestrator"
  arn       = aws_lambda_function.customer_insights_orchestrator.arn
}

resource "aws_lambda_permission" "eventbridge_customer_insights" {
  statement_id  = "AllowEventBridgeInvokeCustomerInsightsOrchestrator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.customer_insights_orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_customer_insights.arn
}

# =============================================================================
# ALARMS
# =============================================================================
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${local.name_prefix}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-orchestrator-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.orchestrator.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "guardrail_interventions" {
  alarm_name          = "${local.name_prefix}-guardrail-interventions"
  namespace           = "AWS/Bedrock"
  metric_name         = "GuardrailInterventions"
  dimensions          = { GuardrailId = aws_bedrock_guardrail.triage.id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "idempotency_throttles" {
  alarm_name          = "${local.name_prefix}-idempotency-throttles"
  namespace           = "AWS/DynamoDB"
  metric_name         = "ThrottledRequests"
  dimensions          = { TableName = aws_dynamodb_table.idempotency.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "metrics_reporter_errors" {
  alarm_name          = "${local.name_prefix}-metrics-reporter-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.metrics_reporter.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "feedback_collector_errors" {
  alarm_name          = "${local.name_prefix}-feedback-collector-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.feedback_collector.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "feedback_sync_errors" {
  alarm_name          = "${local.name_prefix}-feedback-sync-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.feedback_sync.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "high_fallback_usage" {
  alarm_name          = "${local.name_prefix}-high-fallback-usage"
  namespace           = "Custom/MSP-Triage"
  metric_name         = "FallbackTriggered"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "feedback_backlog" {
  alarm_name          = "${local.name_prefix}-feedback-backlog"
  namespace           = "Custom/MSP-Triage"
  metric_name         = "PendingFeedbackCount"
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 20
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "orchestrator_high_latency" {
  alarm_name          = "${local.name_prefix}-orchestrator-high-latency"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.orchestrator.function_name }
  statistic           = "p99"
  period              = 300
  evaluation_periods  = 3
  threshold           = 30000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_digest_orchestrator_errors" {
  alarm_name          = "${local.name_prefix}-customer-digest-orchestrator-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.customer_digest_orchestrator.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_digest_worker_errors" {
  alarm_name          = "${local.name_prefix}-customer-digest-worker-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.customer_digest_worker.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_digest_dlq_not_empty" {
  alarm_name          = "${local.name_prefix}-customer-digest-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.customer_digest_dlq.name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "unsubscribe_errors" {
  alarm_name          = "${local.name_prefix}-unsubscribe-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.unsubscribe_handler.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# =============================================================================
# ALARMS - TENANT HEALTH (Step 2)
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "unhealthy_tenants" {
  alarm_name          = "${local.name_prefix}-unhealthy-tenants"
  namespace           = var.status_metrics_namespace
  metric_name         = "UnhealthyTenants"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  alarm_description = "One or more tenants have dropped to 'unhealthy' status (health score < 50)."
}

resource "aws_cloudwatch_metric_alarm" "degraded_tenants" {
  alarm_name          = "${local.name_prefix}-degraded-tenants"
  namespace           = var.status_metrics_namespace
  metric_name         = "DegradedTenants"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  alarm_description = "One or more tenants have dropped to 'degraded' status (health score 50-79) for 15+ minutes."
}

resource "aws_cloudwatch_metric_alarm" "status_api_throttled" {
  alarm_name          = "${local.name_prefix}-status-api-throttled"
  namespace           = "AWS/ApiGateway"
  metric_name         = "4xx"
  dimensions = {
    ApiName = "${local.name_prefix}-tenant-onboarding"
    Stage   = "$default"
  }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  alarm_description = "Status API is being throttled (rate limit exceeded). Consider increasing limits or investigating abuse."
}

# =============================================================================
# ALARMS - CUSTOMER INSIGHTS (NEW)
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "customer_insights_orchestrator_errors" {
  alarm_name          = "${local.name_prefix}-customer-insights-orchestrator-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.customer_insights_orchestrator.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_insights_worker_errors" {
  alarm_name          = "${local.name_prefix}-customer-insights-worker-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.customer_insights_worker.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_insights_dlq_not_empty" {
  alarm_name          = "${local.name_prefix}-customer-insights-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.customer_insights_dlq.name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "customer_insights_unsubscribe_errors" {
  alarm_name          = "${local.name_prefix}-customer-insights-unsubscribe-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.customer_insights_unsubscribe.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "identity_tools_errors" {
  alarm_name          = "${local.name_prefix}-identity-tools-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.identity_tools.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "teams_bot_errors" {
  alarm_name          = "${local.name_prefix}-teams-bot-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.teams_bot.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "ticket_tools_errors" {
  alarm_name          = "${local.name_prefix}-ticket-tools-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.ticket_tools.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "device_tools_errors" {
  alarm_name          = "${local.name_prefix}-device-tools-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.device_tools.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "calendar_tools_errors" {
  alarm_name          = "${local.name_prefix}-calendar-tools-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.calendar_tools.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "reset_password_errors" {
  alarm_name          = "${local.name_prefix}-reset-password-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.reset_password.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "reset_password_token_abuse" {
  alarm_name          = "${local.name_prefix}-reset-password-token-abuse"
  namespace           = "Custom/MSP-Agent"
  metric_name         = "ResetTokenAbuseAttempts"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "agent_feedback_handler_errors" {
  alarm_name          = "${local.name_prefix}-agent-feedback-handler-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.agent_feedback_handler.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "agent_feedback_sync_errors" {
  alarm_name          = "${local.name_prefix}-agent-feedback-sync-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.agent_feedback_sync.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# =============================================================================
# OUTPUTS
# =============================================================================
output "webhook_url" {
  value = "${aws_apigatewayv2_stage.default.invoke_url}/webhooks/psa"
}

output "unsubscribe_base_url" {
  value = aws_apigatewayv2_stage.unsubscribe_default.invoke_url
}

output "teams_bot_endpoint" {
  value       = "${aws_apigatewayv2_stage.teams_bot_default.invoke_url}/api/messages"
  description = "Teams bot messaging endpoint URL"
}

output "agent_id" {
  value       = aws_bedrockagent_agent.it_concierge.agent_id
  description = "Bedrock Agent ID"
}

output "agent_alias_id" {
  value       = aws_bedrockagent_agent_alias.latest.agent_alias_id
  description = "Bedrock Agent Alias ID"
}

output "secret_names" {
  value = {
    psa                 = aws_secretsmanager_secret.psa.name
    rmm                 = aws_secretsmanager_secret.rmm.name
    webhook             = aws_secretsmanager_secret.webhook.name
    unsubscribe_signing = aws_secretsmanager_secret.unsubscribe_signing.name
    teams_bot           = aws_secretsmanager_secret.teams_bot_secret.name
    entra_graph         = aws_secretsmanager_secret.entra_graph.name
}

output "customer_insights_unsubscribe_url" {
  value       = aws_apigatewayv2_stage.customer_insights_unsubscribe_default.invoke_url
  description = "Customer insights unsubscribe API base URL"
}

output "password_reset_url" {
  value       = local.password_reset_public_url
  description = "Public custom-domain URL for the secure password reset form"
}

output "agent_feedback_table" {
  value       = aws_dynamodb_table.agent_feedback.name
  description = "DynamoDB table for agent feedback"
}

output "tenant_agent_mappings" {
  description = "Map of tenant_id to agent_id and agent_alias_id for seeding the tenant registry"
  value = {
    for k, v in var.tenants : k => {
      agent_id       = aws_bedrockagent_agent.it_concierge[k].agent_id
      agent_alias_id = aws_bedrockagent_agent_alias.latest[k].agent_alias_id
    }
  }
}

output "knowledge_base_id" {
  value       = var.enable_knowledge_base ? aws_bedrockagent_knowledge_base.it_concierge[0].id : null
  description = "Bedrock Knowledge Base ID (null if KB is disabled)"
}

output "kb_documents_bucket" {
  value       = var.enable_knowledge_base ? aws_s3_bucket.kb_documents[0].id : null
  description = "S3 bucket for KB documents (null if KB is disabled)"
}

output "portal_url" {
  value       = var.enable_tenant_portal && var.portal_domain_name != "" ? "https://${var.portal_domain_name}" : (var.enable_tenant_portal ? "https://${aws_cloudfront_distribution.tenant_portal[0].domain_name}" : null)
  description = "Tenant portal URL"
}

output "portal_bucket_name" {
  value       = var.enable_tenant_portal ? aws_s3_bucket.tenant_portal[0].id : null
  description = "S3 bucket for portal static site"
}

output "cognito_user_pool_id" {
  value       = var.enable_tenant_portal ? aws_cognito_user_pool.tenant_portal[0].id : null
  description = "Cognito User Pool ID for portal authentication"
}

output "cognito_client_id" {
  value       = var.enable_tenant_portal ? aws_cognito_user_pool_client.tenant_portal[0].id : null
  description = "Cognito User Pool Client ID"
}

output "cognito_domain" {
  value       = var.enable_tenant_portal ? aws_cognito_user_pool_domain.tenant_portal[0].domain : null
  description = "Cognito domain for hosted UI"
}

output "portal_api_url" {
  value       = var.enable_tenant_portal ? "https://${aws_apigatewayv2_api.tenant_portal_api[0].id}.execute-api.${var.aws_region}.amazonaws.com" : null
  description = "Portal API URL"
}

output "cloudfront_distribution_id" {
  value       = var.enable_tenant_portal ? aws_cloudfront_distribution.tenant_portal[0].id : null
  description = "CloudFront distribution ID for cache invalidation"
}

# =============================================================================
# CLOUDWATCH DASHBOARDS
# =============================================================================

# ------------------------------------------------------------------------------
# Dashboard 1: Executive Overview
# Audience: Leadership
# Purpose: High-level health, accuracy, cost — the "one glance" view
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "executive_overview" {
  count          = var.enable_cloudwatch_dashboards ? 1 : 0
  dashboard_name = "${local.name_prefix}-executive-overview"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Key numbers (top line)
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 6
        height = 4
        properties = {
          metrics = [
            [{ expression = "SUM(SEARCH('{AWS/Lambda,FunctionName} Errors', 'Sum', 86400))", label = "Total Errors (24h)", id = "e1" }]
          ]
          view    = "singleValue"
          title   = "Lambda Errors (Last 24h)"
          region  = var.aws_region
          period  = 86400
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },
      {
        type   = "metric"
        x      = 6
        y      = 0
        width  = 6
        height = 4
        properties = {
          metrics = [
            ["Custom/MSP-Triage", "CustomerDigestSentCount", { stat = "Sum", period = 604800 }]
          ]
          view    = "singleValue"
          title   = "Customer Digests Sent (Last 7 days)"
          region  = var.aws_region
          period  = 604800
          setPeriodToTimeRange = true
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 6
        height = 4
        properties = {
          metrics = [
            ["Custom/MSP-Triage", "FallbackTriggered", { stat = "Sum", period = 604800 }]
          ]
          view    = "singleValue"
          title   = "Fallback Model Triggers (Last 7 days)"
          region  = var.aws_region
          period  = 604800
          setPeriodToTimeRange = true
        }
      },
      {
        type   = "metric"
        x      = 18
        y      = 0
        width  = 6
        height = 4
        properties = {
          metrics = [
            ["AWS/Bedrock", "GuardrailInterventions", "GuardrailId", aws_bedrock_guardrail.triage.id, { stat = "Sum", period = 604800 }]
          ]
          view    = "singleValue"
          title   = "Guardrail Interventions (Last 7 days)"
          region  = var.aws_region
          period  = 604800
          setPeriodToTimeRange = true
        }
      },

      # Row 2: Ticket throughput trend
      {
        type   = "metric"
        x      = 0
        y      = 4
        width  = 12
        height = 6
        properties = {
          metrics = [
            [{ expression = "SUM(SEARCH('{AWS/Lambda,FunctionName} Invocations', 'Sum', 3600))", label = "Total Invocations (hourly)", id = "e1", period = 3600 }]
          ]
          view    = "timeSeries"
          title   = "System Throughput (Last 7 days)"
          region  = var.aws_region
          period  = 3600
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 2 right: Alarm status
      {
        type   = "alarm"
        x      = 12
        y      = 4
        width  = 12
        height = 6
        properties = {
          title  = "Active Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.dlq_not_empty.arn,
            aws_cloudwatch_metric_alarm.lambda_errors.arn,
            aws_cloudwatch_metric_alarm.guardrail_interventions.arn,
            aws_cloudwatch_metric_alarm.feedback_backlog.arn,
            aws_cloudwatch_metric_alarm.high_fallback_usage.arn,
            aws_cloudwatch_metric_alarm.customer_digest_dlq_not_empty.arn,
            aws_cloudwatch_metric_alarm.customer_insights_dlq_not_empty.arn,
          ]
        }
      },

      # Row 3: Model usage breakdown (pie)
      {
        type   = "metric"
        x      = 0
        y      = 10
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InputTokenCount", { stat = "Sum", period = 86400, label = "Input Tokens (24h)" }],
            ["AWS/Bedrock", "OutputTokenCount", { stat = "Sum", period = 86400, label = "Output Tokens (24h)" }]
          ]
          view    = "pie"
          title   = "Bedrock Token Usage (Last 24h)"
          region  = var.aws_region
          period  = 86400
          setPeriodToTimeRange = true
        }
      },

      # Row 3: Error rate trend
      {
        type   = "metric"
        x      = 8
        y      = 10
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.orchestrator.function_name, { label = "Triage Orchestrator" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { label = "Digest Worker" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { label = "Insights Worker" }],
            ["...", aws_lambda_function.teams_bot.function_name, { label = "Teams Bot" }]
          ]
          view    = "timeSeries"
          title   = "Error Rate by Function (Last 24h)"
          region  = var.aws_region
          period  = 300
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 3 right: Recent log errors
      {
        type   = "log"
        x      = 16
        y      = 10
        width  = 8
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-orchestrator' | SOURCE '/aws/lambda/${local.name_prefix}-teams-bot' | SOURCE '/aws/lambda/${local.name_prefix}-customer-insights-worker' | fields @timestamp, @logStream, @message | filter @message like /Error/ or @message like /Exception/ or @level = \"ERROR\" | sort @timestamp desc | limit 20"
          region = var.aws_region
          title  = "Recent Errors (Last 1h)"
          view   = "table"
        }
      },

      # Row 4: Text widget with context
      {
        type   = "text"
        x      = 0
        y      = 16
        width  = 24
        height = 2
        properties = {
          markdown = "## 📊 Executive Overview\nThis dashboard provides a high-level view of system health. **Green numbers = healthy. Red numbers = investigate.** For detailed operational metrics, see the Operations dashboard. For security events, see the Security & Compliance dashboard."
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Dashboard 2: Operations
# Audience: Engineering
# Purpose: Throughput, latency, errors, queue depths — "is anything broken?"
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "operations" {
  count          = var.enable_cloudwatch_dashboards ? 1 : 0
  dashboard_name = "${local.name_prefix}-operations"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Lambda invocations
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.orchestrator.function_name, { label = "Triage Orchestrator" }],
            ["...", aws_lambda_function.customer_digest_orchestrator.function_name, { label = "Digest Orchestrator" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { label = "Digest Worker" }],
            ["...", aws_lambda_function.customer_insights_orchestrator.function_name, { label = "Insights Orchestrator" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { label = "Insights Worker" }],
            ["...", aws_lambda_function.teams_bot.function_name, { label = "Teams Bot" }],
            ["...", aws_lambda_function.identity_tools.function_name, { label = "Identity Tools" }],
            ["...", aws_lambda_function.feedback_collector.function_name, { label = "Feedback Collector" }],
            ["...", aws_lambda_function.feedback_sync.function_name, { label = "Feedback Sync" }]
          ]
          view    = "timeSeries"
          title   = "Lambda Invocations (Last 24h)"
          region  = var.aws_region
          period  = 300
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 1 right: Lambda errors
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.orchestrator.function_name, { label = "Triage Orchestrator" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { label = "Digest Worker" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { label = "Insights Worker" }],
            ["...", aws_lambda_function.teams_bot.function_name, { label = "Teams Bot" }],
            ["...", aws_lambda_function.identity_tools.function_name, { label = "Identity Tools" }]
          ]
          view    = "timeSeries"
          title   = "Lambda Errors (Last 24h)"
          region  = var.aws_region
          period  = 300
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 2: Lambda duration p99
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.orchestrator.function_name, { stat = "p99", label = "Triage Orchestrator (p99)" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { stat = "p99", label = "Digest Worker (p99)" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { stat = "p99", label = "Insights Worker (p99)" }],
            ["...", aws_lambda_function.teams_bot.function_name, { stat = "p99", label = "Teams Bot (p99)" }]
          ]
          view    = "timeSeries"
          title   = "Lambda Duration p99 (Last 24h, ms)"
          region  = var.aws_region
          period  = 300
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 2 right: SQS queue depths
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.tickets.name, { label = "Tickets Queue" }],
            ["...", aws_sqs_queue.dlq.name, { label = "Triage DLQ" }],
            ["...", aws_sqs_queue.customer_digest.name, { label = "Digest Queue" }],
            ["...", aws_sqs_queue.customer_digest_dlq.name, { label = "Digest DLQ" }],
            ["...", aws_sqs_queue.customer_insights.name, { label = "Insights Queue" }],
            ["...", aws_sqs_queue.customer_insights_dlq.name, { label = "Insights DLQ" }]
          ]
          view    = "timeSeries"
          title   = "SQS Queue Depths (Last 24h)"
          region  = var.aws_region
          period  = 300
          stacked = false
          stat    = "Maximum"
          setPeriodToTimeRange = true
        }
      },

      # Row 3: DynamoDB throttles
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", aws_dynamodb_table.idempotency.name, { label = "Idempotency" }],
            ["...", aws_dynamodb_table.metrics.name, { label = "Metrics" }],
            ["...", aws_dynamodb_table.feedback.name, { label = "Feedback" }],
            ["...", aws_dynamodb_table.agent_rate_limits.name, { label = "Agent Rate Limits" }],
            ["...", aws_dynamodb_table.agent_pending_operations.name, { label = "Pending Operations" }],
            ["...", aws_dynamodb_table.password_reset_tokens.name, { label = "Password Reset Tokens" }]
          ]
          view    = "timeSeries"
          title   = "DynamoDB Throttles (Last 24h)"
          region  = var.aws_region
          period  = 300
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 3 middle: Bedrock invocation latency
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InvocationLatency", { stat = "p99", period = 300, label = "Bedrock p99 Latency (ms)" }]
          ]
          view    = "timeSeries"
          title   = "Bedrock Invocation Latency p99 (Last 24h)"
          region  = var.aws_region
          period  = 300
          setPeriodToTimeRange = true
        }
      },

      # Row 3 right: All alarms
      {
        type   = "alarm"
        x      = 16
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "All Active Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.dlq_not_empty.arn,
            aws_cloudwatch_metric_alarm.lambda_errors.arn,
            aws_cloudwatch_metric_alarm.guardrail_interventions.arn,
            aws_cloudwatch_metric_alarm.idempotency_throttles.arn,
            aws_cloudwatch_metric_alarm.metrics_reporter_errors.arn,
            aws_cloudwatch_metric_alarm.feedback_collector_errors.arn,
            aws_cloudwatch_metric_alarm.feedback_sync_errors.arn,
            aws_cloudwatch_metric_alarm.high_fallback_usage.arn,
            aws_cloudwatch_metric_alarm.feedback_backlog.arn,
            aws_cloudwatch_metric_alarm.orchestrator_high_latency.arn,
            aws_cloudwatch_metric_alarm.customer_digest_orchestrator_errors.arn,
            aws_cloudwatch_metric_alarm.customer_digest_worker_errors.arn,
            aws_cloudwatch_metric_alarm.customer_digest_dlq_not_empty.arn,
            aws_cloudwatch_metric_alarm.unsubscribe_errors.arn,
            aws_cloudwatch_metric_alarm.identity_tools_errors.arn,
            aws_cloudwatch_metric_alarm.teams_bot_errors.arn,
            aws_cloudwatch_metric_alarm.ticket_tools_errors.arn,
            aws_cloudwatch_metric_alarm.device_tools_errors.arn,
            aws_cloudwatch_metric_alarm.calendar_tools_errors.arn,
            aws_cloudwatch_metric_alarm.reset_password_errors.arn,
            aws_cloudwatch_metric_alarm.reset_password_token_abuse.arn,
            aws_cloudwatch_metric_alarm.agent_feedback_handler_errors.arn,
            aws_cloudwatch_metric_alarm.agent_feedback_sync_errors.arn,
            aws_cloudwatch_metric_alarm.customer_insights_orchestrator_errors.arn,
            aws_cloudwatch_metric_alarm.customer_insights_worker_errors.arn,
            aws_cloudwatch_metric_alarm.customer_insights_dlq_not_empty.arn,
            aws_cloudwatch_metric_alarm.customer_insights_unsubscribe_errors.arn,
          ]
        }
      },

      # Row 4: Recent operational logs
      {
        type   = "log"
        x      = 0
        y      = 18
        width  = 24
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-orchestrator' | SOURCE '/aws/lambda/${local.name_prefix}-teams-bot' | SOURCE '/aws/lambda/${local.name_prefix}-identity-tools' | SOURCE '/aws/lambda/${local.name_prefix}-customer-insights-worker' | fields @timestamp, @logStream, @message | filter @level = \"ERROR\" or @message like /Exception/ | sort @timestamp desc | limit 50"
          region = var.aws_region
          title  = "Recent Operational Errors (Last 1h)"
          view   = "table"
        }
      }
      ,{
        type   = "metric"
        x      = 0
        y      = 24
        width  = 24
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH('{${var.status_metrics_namespace},tenant_id} MetricName=\"HealthScore\"', 'Average', 300)", label = "Tenant Health Score", id = "e1" }]
          ]
          view    = "timeSeries"
          title   = "Tenant Health Scores (Last 24h)"
          region  = var.aws_region
          period  = 300
          stat    = "Average"
          setPeriodToTimeRange = true
          yAxis = {
            left = {
              min = 0
              max = 100
              label = "Health Score"
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 30
        width  = 12
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH('{${var.status_metrics_namespace},tenant_id} MetricName=\"UnhealthyTenants\"', 'Sum', 300)", label = "Unhealthy Tenants", id = "e1" }]
          ]
          view    = "singleValue"
          title   = "Unhealthy Tenants (Last 1h)"
          region  = var.aws_region
          period  = 3600
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 30
        width  = 12
        height = 6
        properties = {
          metrics = [
            [{ expression = "SEARCH('{${var.status_metrics_namespace}} MetricName=\"StatusApiRequests\"', 'Sum', 300)", label = "Status API Requests", id = "e1" }]
          ]
          view    = "timeSeries"
          title   = "Status API Request Volume (Last 24h)"
          region  = var.aws_region
          period  = 300
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Dashboard 3: Security & Compliance
# Audience: Security / IT Leadership
# Purpose: Guardrail effectiveness, auth failures, audit activity
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "security_compliance" {
  count          = var.enable_cloudwatch_dashboards ? 1 : 0
  dashboard_name = "${local.name_prefix}-security-compliance"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Guardrail metrics
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "GuardrailInterventions", "GuardrailId", aws_bedrock_guardrail.triage.id, { label = "Triage Guardrail" }],
            ["...", aws_bedrock_guardrail.customer_digest.id, { label = "Digest Guardrail" }],
            ["...", aws_bedrock_guardrail.agent.id, { label = "Agent Guardrail" }],
            ["...", aws_bedrock_guardrail.customer_insights.id, { label = "Insights Guardrail" }]
          ]
          view    = "timeSeries"
          title   = "Guardrail Interventions by Guardrail (Last 7 days)"
          region  = var.aws_region
          period  = 3600
          stacked = false
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 1 middle: Password reset token abuse
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["Custom/MSP-Agent", "ResetTokenAbuseAttempts", { stat = "Sum", period = 3600, label = "Token Abuse Attempts" }]
          ]
          view    = "timeSeries"
          title   = "Password Reset Token Abuse (Last 7 days)"
          region  = var.aws_region
          period  = 3600
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 1 right: Custom security metrics
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          metrics = [
            [{ expression = "SUM(SEARCH('{Custom/MSP-Agent} MetricName', 'Sum', 3600))", label = "All Agent Security Events", id = "e1", period = 3600 }]
          ]
          view    = "singleValue"
          title   = "Agent Security Events (Last 24h)"
          region  = var.aws_region
          period  = 86400
          stat    = "Sum"
          setPeriodToTimeRange = true
        }
      },

      # Row 2: Audit log activity
      {
        type   = "log"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-identity-tools' | SOURCE '/aws/lambda/${local.name_prefix}-reset-password' | SOURCE '/aws/lambda/${local.name_prefix}-teams-bot' | fields @timestamp, @logStream, @message | filter @message like /audit/ or @message like /Audit/ or @message like /security/ | sort @timestamp desc | limit 50"
          region = var.aws_region
          title  = "Recent Audit Log Activity (Last 1h)"
          view   = "table"
        }
      },

      # Row 2 right: Write operations breakdown
      {
        type   = "log"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-identity-tools' | fields @timestamp, @message | filter @message like /Password reset/ or @message like /Account unlock/ or @message like /admin_override/ | stats count() as operation_count by bin(1h) | sort @timestamp desc"
          region = var.aws_region
          title  = "Write Operations per Hour (Last 24h)"
          view   = "timeSeries"
        }
      },

      # Row 3: Scope isolation violations
      {
        type   = "log"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-identity-tools' | fields @timestamp, @message | filter @message like /Scope isolation violation/ | sort @timestamp desc | limit 20"
          region = var.aws_region
          title  = "Scope Isolation Violations (Last 7 days)"
          view   = "table"
        }
      },

      # Row 3 right: Admin overrides
      {
        type   = "log"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          query = "SOURCE '/aws/lambda/${local.name_prefix}-identity-tools' | fields @timestamp, @message | filter @message like /admin/ or @message like /Admin/ | sort @timestamp desc | limit 20"
          region = var.aws_region
          title  = "Admin Override Activity (Last 7 days)"
          view   = "table"
        }
      },

      # Row 4: Context text
      {
        type   = "text"
        x      = 0
        y      = 18
        width  = 24
        height = 2
        properties = {
          markdown = "## 🔒 Security & Compliance\nThis dashboard tracks security-relevant events across the system. **Any non-zero values in the abuse/violation widgets warrant investigation.** Audit logs are retained for 365 days. For detailed audit trail queries, use CloudWatch Logs Insights."
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Dashboard 4: Cost & Usage
# Audience: Finance / Engineering
# Purpose: Model usage breakdown, Lambda invocations, estimated spend
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "cost_usage" {
  count          = var.enable_cloudwatch_dashboards ? 1 : 0
  dashboard_name = "${local.name_prefix}-cost-usage"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Bedrock token usage by model
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Bedrock", "InputTokenCount", { stat = "Sum", period = 86400, label = "Input Tokens" }],
            ["AWS/Bedrock", "OutputTokenCount", { stat = "Sum", period = 86400, label = "Output Tokens" }]
          ]
          view    = "timeSeries"
          title   = "Bedrock Token Usage (Last 7 days)"
          region  = var.aws_region
          period  = 86400
          stacked = true
          setPeriodToTimeRange = true
        }
      },

      # Row 1 right: Lambda invocations by function
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.orchestrator.function_name, { stat = "Sum", period = 86400, label = "Triage Orchestrator" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { stat = "Sum", period = 86400, label = "Digest Worker" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { stat = "Sum", period = 86400, label = "Insights Worker" }],
            ["...", aws_lambda_function.teams_bot.function_name, { stat = "Sum", period = 86400, label = "Teams Bot" }],
            ["...", aws_lambda_function.identity_tools.function_name, { stat = "Sum", period = 86400, label = "Identity Tools" }],
            ["...", aws_lambda_function.ticket_tools.function_name, { stat = "Sum", period = 86400, label = "Ticket Tools" }],
            ["...", aws_lambda_function.device_tools.function_name, { stat = "Sum", period = 86400, label = "Device Tools" }],
            ["...", aws_lambda_function.calendar_tools.function_name, { stat = "Sum", period = 86400, label = "Calendar Tools" }]
          ]
          view    = "pie"
          title   = "Lambda Invocations by Function (Last 24h)"
          region  = var.aws_region
          period  = 86400
          setPeriodToTimeRange = true
        }
      },

      # Row 2: Lambda duration (cost driver)
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.orchestrator.function_name, { stat = "Average", label = "Triage Orchestrator (avg)" }],
            ["...", aws_lambda_function.customer_digest_worker.function_name, { stat = "Average", label = "Digest Worker (avg)" }],
            ["...", aws_lambda_function.customer_insights_worker.function_name, { stat = "Average", label = "Insights Worker (avg)" }],
            ["...", aws_lambda_function.teams_bot.function_name, { stat = "Average", label = "Teams Bot (avg)" }]
          ]
          view    = "timeSeries"
          title   = "Lambda Average Duration (Last 24h, ms)"
          region  = var.aws_region
          period  = 3600
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 2 right: DynamoDB read/write units
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.metrics.name, { stat = "Sum", period = 3600, label = "Metrics (read)" }],
            ["...", aws_dynamodb_table.feedback.name, { stat = "Sum", period = 3600, label = "Feedback (read)" }],
            ["...", aws_dynamodb_table.agent_audit_log.name, { stat = "Sum", period = 3600, label = "Audit Log (read)" }],
            ["...", aws_dynamodb_table.customer_alert_history.name, { stat = "Sum", period = 3600, label = "Alert History (read)" }]
          ]
          view    = "timeSeries"
          title   = "DynamoDB Read Capacity (Last 24h)"
          region  = var.aws_region
          period  = 3600
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 3: SES email volume
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/SES", "Send", { stat = "Sum", period = 86400, label = "Emails Sent" }],
            ["AWS/SES", "Delivery", { stat = "Sum", period = 86400, label = "Emails Delivered" }],
            ["AWS/SES", "Bounce", { stat = "Sum", period = 86400, label = "Emails Bounced" }]
          ]
          view    = "timeSeries"
          title   = "SES Email Volume (Last 7 days)"
          region  = var.aws_region
          period  = 86400
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 3 middle: S3 requests
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/S3", "GetRequests", "BucketName", aws_s3_bucket.few_shot_examples.bucket, { stat = "Sum", period = 86400, label = "Few-Shot Gets" }],
            ["...", aws_s3_bucket.agent_schemas.bucket, { stat = "Sum", period = 86400, label = "Schema Gets" }],
            ["AWS/S3", "PutRequests", "BucketName", aws_s3_bucket.few_shot_examples.bucket, { stat = "Sum", period = 86400, label = "Few-Shot Puts" }],
            ["...", aws_s3_bucket.agent_schemas.bucket, { stat = "Sum", period = 86400, label = "Schema Puts" }]
          ]
          view    = "timeSeries"
          title   = "S3 Requests (Last 7 days)"
          region  = var.aws_region
          period  = 86400
          stacked = false
          setPeriodToTimeRange = true
        }
      },

      # Row 3 right: Cost estimation text
      {
        type   = "text"
        x      = 16
        y      = 12
        width  = 8
        height = 6
        properties = {
          markdown = "## 💰 Estimated Daily Cost\n\n**Bedrock:**\n- Sonnet 5.5: ~$0.013/ticket\n- Haiku 4.5: ~$0.003/ticket\n\n**Lambda:**\n- ~$0.00002/invocation\n- ~$0.00001/GB-second\n\n**DynamoDB:**\n- ~$0.25/million RCUs\n- ~$1.25/million WCUs\n\n**SES:**\n- $0.10/1000 emails\n\n*See AWS Cost Explorer for actual spend.*"
        }
      },

      # Row 4: Context
      {
        type   = "text"
        x      = 0
        y      = 18
        width  = 24
        height = 2
        properties = {
          markdown = "## 💵 Cost & Usage\nThis dashboard helps you understand where your AWS spend is going. **Bedrock model usage is typically the largest cost driver.** Monitor token counts and consider tuning `max_few_shot_examples` or switching more tickets to Haiku if costs grow. For precise billing, use AWS Cost Explorer with service-level granularity."
        }
      }
    ]
  })
}

# =============================================================================
# CLOUDWATCH LOGS INSIGHTS - SAVED QUERIES
# =============================================================================
# Note: Terraform doesn't natively support saved queries, but we document
# the most useful ones here as outputs for easy copy-paste into the console.

output "useful_logs_insights_queries" {
  description = "Useful CloudWatch Logs Insights queries for operational debugging"
  value = {
    "find_all_guardrail_blocks" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-orchestrator'
| SOURCE '/aws/lambda/${local.name_prefix}-customer-insights-worker'
| fields @timestamp, @logStream, @message
| filter @message like /Guardrail BLOCKED/
| sort @timestamp desc
| limit 100
EOT

    "find_all_scope_isolation_violations" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-identity-tools'
| fields @timestamp, @message
| filter @message like /Scope isolation violation/
| sort @timestamp desc
| limit 50
EOT

    "find_password_reset_failures" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-identity-tools'
| SOURCE '/aws/lambda/${local.name_prefix}-reset-password'
| fields @timestamp, @logStream, @message
| filter @message like /password reset/ and @message like /failed/
| sort @timestamp desc
| limit 50
EOT

    "find_rate_limit_breaches" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-identity-tools'
| fields @timestamp, @message
| filter @message like /Rate limit/ and @message like /breached/
| sort @timestamp desc
| limit 50
EOT

    "find_agent_feedback_patterns" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-agent-feedback-handler'
| fields @timestamp, @message
| filter @message like /Stored feedback/
| stats count() as feedback_count by bin(1d)
| sort @timestamp desc
EOT

    "find_slow_lambda_invocations" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-orchestrator'
| SOURCE '/aws/lambda/${local.name_prefix}-teams-bot'
| fields @timestamp, @logStream, @duration
| filter @duration > 10000
| sort @duration desc
| limit 20
EOT

    "find_bedrock_model_failures" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-orchestrator'
| fields @timestamp, @message
| filter @message like /model/ and (@message like /failed/ or @message like /error/)
| sort @timestamp desc
| limit 50
EOT

    "find_all_dlq_messages" = <<EOT
SOURCE '/aws/lambda/${local.name_prefix}-orchestrator'
| fields @timestamp, @message
| filter @message like /batchItemFailures/ or @message like /DLQ/
| sort @timestamp desc
| limit 50
EOT
  }
}