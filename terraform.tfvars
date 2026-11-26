# =============================================================================
# MSP AI Platform - Default Terraform Variables
# =============================================================================
# These are the baseline values. Environment-specific files
# (terraform.tfvars.dev, .staging, .prod) override these values.
# =============================================================================

# -----------------------------------------------------------------------------
# CORE CONFIGURATION
# -----------------------------------------------------------------------------
project     = "msp-triage"
environment = "dev"
aws_region  = "us-east-1"

# -----------------------------------------------------------------------------
# MICROSOFT INTEGRATION
# -----------------------------------------------------------------------------
# Must be overridden per environment
entra_tenant_id      = "REPLACE-WITH-ENTRA-TENANT-ID"
entra_app_client_id  = "REPLACE-WITH-APP-CLIENT-ID"
agent_admin_group_id = "REPLACE-WITH-ADMIN-GROUP-ID"
bot_app_id           = "REPLACE-WITH-BOT-APP-ID"

# -----------------------------------------------------------------------------
# BEDROCK MODEL CONFIGURATION
# -----------------------------------------------------------------------------
# Complex tasks (triage, insights, concierge)
agent_model_id            = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
agent_foundation_model_id = "anthropic.claude-sonnet-4-5-20250929-v1:0"

# Cost optimization for simple tasks
haiku_model_id            = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
haiku_foundation_model_id = "anthropic.claude-haiku-4-5-20251001-v1:0"

# Fallback model (for triage)
fallback_model_id            = "us.anthropic.claude-sonnet-4-20250514-v1:0"
fallback_foundation_model_id = "anthropic.claude-sonnet-4-20250514-v1:0"

# Embedding model for Knowledge Base
kb_embedding_model_id = "amazon.titan-embed-text-v2:0"

# -----------------------------------------------------------------------------
# KNOWLEDGE BASE CONFIGURATION
# -----------------------------------------------------------------------------
kb_chunk_size    = 500
kb_chunk_overlap = 100
kb_documents_bucket_name = ""  # Auto-generated if empty

# -----------------------------------------------------------------------------
# AGENT CONFIGURATION
# -----------------------------------------------------------------------------
agent_idle_session_ttl_seconds = 1800
msp_company_name_for_agent     = "Your MSP"
default_agent_instruction      = "You are an AI IT Concierge. Help users with identity and account operations. Always be professional and helpful."

# -----------------------------------------------------------------------------
# EMAIL CONFIGURATION
# -----------------------------------------------------------------------------
# Must be verified in SES before use
alert_email                         = "alerts@yourmsp.com"
metrics_report_sender_email         = "reports@yourmsp.com"
metrics_report_recipient_email      = "leadership@yourmsp.com"
customer_digest_sender_email        = "digest@yourmsp.com"
customer_insights_sender_email      = "insights@yourmsp.com"
password_reset_sender_email         = "passwords@yourmsp.com"
agent_notification_sender_email     = "notifications@yourmsp.com"
agent_security_notification_email  = "security@yourmsp.com"
password_reset_support_email        = "support@yourmsp.com"

# -----------------------------------------------------------------------------
# DOMAIN CONFIGURATION
# -----------------------------------------------------------------------------
# Custom domains (set to empty to skip)
password_reset_domain_name = ""
portal_domain_name         = ""

# Route 53 hosted zone IDs (required if domains are set)
password_reset_hosted_zone_id = ""
portal_hosted_zone_id         = ""

# Unsubscribe base URLs
unsubscribe_base_url                    = ""
customer_insights_unsubscribe_base_url  = ""

# -----------------------------------------------------------------------------
# CONNECTWISE INTEGRATION
# -----------------------------------------------------------------------------
# Custom field IDs in ConnectWise for AI metadata
ai_accuracy_field_id        = 999
ai_correction_notes_field_id = 998

# Default ticket fields
ticket_default_board_id     = 1
ticket_default_status_id    = 1
ticket_default_type_id      = 1
ticket_default_priority_id  = 1

# -----------------------------------------------------------------------------
# NINJAONE INTEGRATION
# -----------------------------------------------------------------------------
ninjaone_device_owner_field = "assignedUser"

# -----------------------------------------------------------------------------
# CALENDAR CONFIGURATION
# -----------------------------------------------------------------------------
calendar_default_timezone = "America/New_York"
bookable_room_filter      = ""

# -----------------------------------------------------------------------------
# RATE LIMITS
# -----------------------------------------------------------------------------
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
# SECURITY & RETENTION
# -----------------------------------------------------------------------------
secret_recovery_window_days = 7

# Retention periods (days)
agent_audit_log_retention_days            = 365
metrics_retention_days                    = 90
feedback_retention_days                   = 365
agent_feedback_retention_days             = 365
customer_digest_history_retention_days    = 90
customer_insights_retention_days          = 730

# Password reset
password_reset_token_ttl_seconds        = 900
password_reset_max_attempts_per_token   = 5

# Confirmation
agent_confirmation_ttl_seconds = 600

# -----------------------------------------------------------------------------
# PERFORMANCE
# -----------------------------------------------------------------------------
lambda_timeout_seconds = 60
lambda_memory_mb       = 512
max_concurrency        = 5
max_retries            = 3
retry_base_delay_ms    = 1000

# Cost optimization
simple_ticket_confidence_threshold = 0.7
simple_ticket_max_tokens           = 512

# -----------------------------------------------------------------------------
# OBSERVABILITY
# -----------------------------------------------------------------------------
status_metrics_namespace = "Custom/MSP-Tenant-Status"
status_cache_ttl_seconds = 60

# Status API rate limits
status_api_requests_per_second          = 5
status_api_burst_limit                  = 10
status_deep_health_requests_per_second  = 1
status_deep_health_burst_limit          = 2

# Analytics retention (days)
analytics_retention_days = 365

# -----------------------------------------------------------------------------
# WEBHOOKS
# -----------------------------------------------------------------------------
webhook_cooldown_seconds = 3600
webhook_retry_attempts   = 3

# -----------------------------------------------------------------------------
# CUSTOMER DIGEST
# -----------------------------------------------------------------------------
customer_digest_schedule_hour_utc       = 11
customer_digest_default_local_hour      = 7
customer_digest_min_severity            = "warning"
customer_digest_max_customers_per_run   = 500
customer_digest_model_id            = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
customer_digest_foundation_model_id = "anthropic.claude-haiku-4-5-20251001-v1:0"

# -----------------------------------------------------------------------------
# CUSTOMER INSIGHTS
# -----------------------------------------------------------------------------
customer_insights_default_local_day      = 6  # Sunday
customer_insights_default_local_hour     = 9
customer_insights_max_customers_per_run  = 500
customer_insights_history_days           = 7
customer_insights_model_id            = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
customer_insights_foundation_model_id = "anthropic.claude-sonnet-4-5-20250929-v1:0"

# -----------------------------------------------------------------------------
# FEEDBACK LOOP
# -----------------------------------------------------------------------------
max_few_shot_examples               = 5
agent_max_examples_in_context       = 5
few_shot_examples_cache_ttl_seconds = 300
agent_examples_cache_ttl_seconds    = 300

# -----------------------------------------------------------------------------
# DEPROVISIONING
# -----------------------------------------------------------------------------
deprovision_drain_seconds       = 60
deprovision_require_confirmation = true

# -----------------------------------------------------------------------------
# CUSTOM HEALTH CHECKS
# -----------------------------------------------------------------------------
custom_health_max_rules_per_tenant = 10
custom_health_max_score_impact     = 30

# -----------------------------------------------------------------------------
# STATUS HISTORY
# -----------------------------------------------------------------------------
status_history_snapshot_hour_utc = 6
status_history_retention_days    = 90

# -----------------------------------------------------------------------------
# BRANDING
# -----------------------------------------------------------------------------
msp_default_branding = {
  company_name   = "Your MSP"
  logo_url       = ""
  primary_color  = "#2c3e50"
  support_email  = "support@yourmsp.com"
  support_phone  = "+1-555-0100"
}

# -----------------------------------------------------------------------------
# FEATURE FLAGS
# -----------------------------------------------------------------------------
enable_cost_optimization       = true
enable_knowledge_base          = false
enable_onboarding_api          = true
enable_status_history          = true
enable_webhook_notifications   = false
enable_custom_health_checks    = false
enable_tenant_portal           = false
enable_advanced_analytics      = false
enable_cloudwatch_dashboards   = true
enable_microsoft_teams_bot     = true
enable_password_reset          = true
enable_customer_digest         = true
enable_customer_insights       = false
enable_feedback_loop           = true
enable_xray_tracing            = true

# -----------------------------------------------------------------------------
# LOG RETENTION
# -----------------------------------------------------------------------------
log_retention_days = 90

# -----------------------------------------------------------------------------
# TENANTS (Phase 4 Multi-Tenancy)
# -----------------------------------------------------------------------------
# Default tenant (can be empty after migration to API management)
tenants = {}

default_tenant_id = ""