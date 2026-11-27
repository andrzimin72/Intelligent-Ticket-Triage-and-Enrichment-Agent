# =============================================================================
# MSP AI Platform - Default Variable Values
# =============================================================================
# NOTE: Do not put real secrets or production IDs here. 
# Use terraform.tfvars.dev, .staging, or .prod for environment-specific values.
# =============================================================================

# -----------------------------------------------------------------------------
# CORE CONFIGURATION
# -----------------------------------------------------------------------------
project     = "msp-triage"
environment = "dev" # Overridden by environment-specific files
aws_region  = "us-east-1"

# -----------------------------------------------------------------------------
# MICROSOFT INTEGRATION (Placeholders)
# -----------------------------------------------------------------------------
entra_tenant_id      = "00000000-0000-0000-0000-000000000000"
entra_app_client_id  = "00000000-0000-0000-0000-000000000000"
agent_admin_group_id = "00000000-0000-0000-0000-000000000000"
bot_app_id           = "00000000-0000-0000-0000-000000000000"

# -----------------------------------------------------------------------------
# AI / BEDROCK CONFIGURATION
# -----------------------------------------------------------------------------
agent_model_id            = "us.anthropic.claude-sonnet-3-5-20241022-v2:0"
agent_foundation_model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
haiku_model_id            = "us.anthropic.claude-3-haiku-20240307-v1:0"
haiku_foundation_model_id = "anthropic.claude-3-haiku-20240307-v1:0"
kb_embedding_model_id     = "amazon.titan-embed-text-v2:0"

default_agent_instruction = "You are an AI IT Concierge. Help users with identity and account operations."
agent_idle_session_ttl_seconds = 1800

# -----------------------------------------------------------------------------
# KNOWLEDGE BASE
# -----------------------------------------------------------------------------
enable_knowledge_base = false
kb_chunk_size         = 500
kb_chunk_overlap      = 100
aoss_collection_arn   = "" # Required if enable_knowledge_base = true

# -----------------------------------------------------------------------------
# SECURITY & COMPLIANCE
# -----------------------------------------------------------------------------
secret_recovery_window_days = 7
enable_guardrails           = true
guardrail_id                = ""
guardrail_version           = "DRAFT"
enable_xray_tracing         = true

# Retention Periods (Days)
log_retention_days                    = 90
agent_audit_log_retention_days        = 365
metrics_retention_days                = 90
feedback_retention_days               = 365
status_history_retention_days         = 90
analytics_retention_days              = 365

# Password Reset Security
password_reset_token_ttl_seconds      = 900
password_reset_max_attempts_per_token = 5
agent_confirmation_ttl_seconds        = 600

# -----------------------------------------------------------------------------
# PERFORMANCE & LIMITS
# -----------------------------------------------------------------------------
lambda_timeout_seconds = 60
lambda_memory_mb       = 512
max_concurrency        = 5

simple_ticket_confidence_threshold = 0.7
simple_ticket_max_tokens           = 512

# Rate Limits
agent_self_rate_limits = {
  per_operation_hourly = 3
  per_operation_daily  = 5
  requests_hourly      = 10
}
agent_admin_rate_limits = {
  per_operation_hourly = 20
  per_operation_daily  = 50
  per_target_daily     = 3
  requests_hourly      = 30
}

# -----------------------------------------------------------------------------
# COMMUNICATION & DOMAINS
# -----------------------------------------------------------------------------
alert_email                         = "alerts@yourmsp.com"
password_reset_sender_email         = "passwords@yourmsp.com"
password_reset_domain_name          = ""
password_reset_hosted_zone_id       = ""
portal_domain_name                  = ""
portal_hosted_zone_id               = ""
portal_callback_url                 = "http://localhost:3000/callback"
portal_logout_url                   = "http://localhost:3000"

# -----------------------------------------------------------------------------
# FEATURE FLAGS
# -----------------------------------------------------------------------------
enable_tenant_portal        = false
enable_advanced_analytics   = false
enable_custom_health_checks = false
enable_webhook_notifications= false