# =============================================================================
# MSP Triage Infrastructure - Environment Variables (ACTUAL VALUES)
# =============================================================================
# WARNING: This file contains sensitive credentials.
# DO NOT commit this file to git!
# =============================================================================

# =============================================================================
# AWS Configuration
# =============================================================================
AWS_PROFILE=dev
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012
AWS_ENDPOINT_URL=

# =============================================================================
# Terraform Configuration
# =============================================================================
TF_VAR_project=msp-triage
TF_VAR_environment=dev
TF_VAR_aws_region=us-east-1

# =============================================================================
# Microsoft Entra ID Configuration
# =============================================================================
TF_VAR_entra_tenant_id=12345678-1234-1234-1234-123456789012
TF_VAR_entra_app_client_id=87654321-4321-4321-4321-210987654321
TF_VAR_agent_admin_group_id=abcdef12-3456-7890-abcd-ef1234567890
TF_VAR_bot_app_id=bot-app-id-here

# =============================================================================
# Multi-Tenant Configuration
# =============================================================================
TF_VAR_default_tenant_id=default

# =============================================================================
# Email Configuration
# =============================================================================
TF_VAR_alert_email=alerts@yourmsp.com
TF_VAR_metrics_report_sender_email=reports@yourmsp.com
TF_VAR_metrics_report_recipient_email=leadership@yourmsp.com
TF_VAR_customer_digest_sender_email=digest@yourmsp.com
TF_VAR_customer_insights_sender_email=insights@yourmsp.com
TF_VAR_password_reset_sender_email=passwords@yourmsp.com
TF_VAR_agent_notification_sender_email=notifications@yourmsp.com
TF_VAR_agent_security_notification_email=security@yourmsp.com
TF_VAR_password_reset_support_email=support@yourmsp.com

# =============================================================================
# Custom Domains
# =============================================================================
TF_VAR_password_reset_domain_name=reset.yourmsp.com
TF_VAR_password_reset_hosted_zone_id=Z1234567890ABC
TF_VAR_unsubscribe_base_url=https://api.yourmsp.com
TF_VAR_customer_insights_unsubscribe_base_url=https://api.yourmsp.com

# =============================================================================
# Tenant Portal Configuration
# =============================================================================
TF_VAR_portal_domain_name=portal.yourmsp.com
TF_VAR_portal_hosted_zone_id=Z1234567890ABC
TF_VAR_portal_entra_tenant_id=
TF_VAR_portal_allowed_admin_emails=["admin@yourmsp.com"]

# =============================================================================
# Knowledge Base Configuration
# =============================================================================
TF_VAR_kb_embedding_model_id=amazon.titan-embed-text-v2:0
TF_VAR_kb_chunk_size=500
TF_VAR_kb_chunk_overlap=100
TF_VAR_kb_documents_bucket_name=

# =============================================================================
# Bedrock Agent Configuration
# =============================================================================
TF_VAR_agent_model_id=us.anthropic.claude-sonnet-5-5-v1:0
TF_VAR_agent_foundation_model_id=anthropic.claude-sonnet-5-5-v1:0
TF_VAR_agent_idle_session_ttl_seconds=1800
TF_VAR_msp_company_name_for_agent=Your MSP

# =============================================================================
# Ticket Triage Configuration
# =============================================================================
TF_VAR_model_id=us.anthropic.claude-sonnet-5-5-v1:0
TF_VAR_foundation_model_id=anthropic.claude-sonnet-5-5-v1:0
TF_VAR_fallback_model_id=us.anthropic.claude-sonnet-5-v1:0
TF_VAR_fallback_foundation_model_id=anthropic.claude-sonnet-5-v1:0
TF_VAR_haiku_model_id=us.anthropic.claude-haiku-4-5-v1:0
TF_VAR_haiku_foundation_model_id=anthropic.claude-haiku-4-5-v1:0
TF_VAR_ai_accuracy_field_id=999
TF_VAR_ai_correction_notes_field_id=998

# =============================================================================
# NinjaOne & Calendar Configuration
# =============================================================================
TF_VAR_ninjaone_device_owner_field=assignedUser
TF_VAR_calendar_default_timezone=America/New_York
TF_VAR_bookable_room_filter=

# =============================================================================
# ConnectWise Ticket Defaults
# =============================================================================
TF_VAR_ticket_default_board_id=1
TF_VAR_ticket_default_status_id=1
TF_VAR_ticket_default_type_id=1
TF_VAR_ticket_default_priority_id=1

# =============================================================================
# Rate Limits & Quotas
# =============================================================================
TF_VAR_agent_self_rate_limits={"per_operation_hourly": 3, "per_operation_daily": 5, "requests_hourly": 10}
TF_VAR_agent_admin_rate_limits={"per_operation_hourly": 20, "per_operation_daily": 50, "per_target_daily": 3, "requests_hourly": 30}

# =============================================================================
# Feature Flags
# =============================================================================
TF_VAR_enable_cost_optimization=true
TF_VAR_enable_knowledge_base=false
TF_VAR_enable_onboarding_api=false
TF_VAR_enable_status_history=true
TF_VAR_enable_webhook_notifications=false
TF_VAR_enable_custom_health_checks=false
TF_VAR_enable_tenant_portal=false
TF_VAR_enable_advanced_analytics=false
TF_VAR_enable_cloudwatch_dashboards=true

# =============================================================================
# Security & Compliance
# =============================================================================
TF_VAR_secret_recovery_window_days=7
TF_VAR_agent_audit_log_retention_days=365
TF_VAR_metrics_retention_days=90
TF_VAR_feedback_retention_days=365
TF_VAR_agent_feedback_retention_days=365
TF_VAR_customer_digest_history_retention_days=90
TF_VAR_customer_insights_retention_days=730
TF_VAR_password_reset_token_ttl_seconds=900
TF_VAR_password_reset_max_attempts_per_token=5
TF_VAR_agent_confirmation_ttl_seconds=600

# =============================================================================
# Performance & Scaling
# =============================================================================
TF_VAR_lambda_timeout_seconds=60
TF_VAR_lambda_memory_mb=512
TF_VAR_max_concurrency=5
TF_VAR_max_retries=3
TF_VAR_retry_base_delay_ms=1000
TF_VAR_simple_ticket_confidence_threshold=0.7
TF_VAR_simple_ticket_max_tokens=512

# =============================================================================
# Monitoring & Analytics
# =============================================================================
TF_VAR_status_metrics_namespace=Custom/MSP-Tenant-Status
TF_VAR_status_cache_ttl_seconds=60
TF_VAR_status_api_requests_per_second=5
TF_VAR_status_api_burst_limit=10
TF_VAR_status_deep_health_requests_per_second=1
TF_VAR_status_deep_health_burst_limit=2
TF_VAR_analytics_retention_days=365

# =============================================================================
# Webhook Configuration
# =============================================================================
TF_VAR_webhook_cooldown_seconds=3600
TF_VAR_webhook_retry_attempts=3
SLACK_WEBHOOK_URL=
TF_STATE_BACKUP_BUCKET=

# =============================================================================
# Customer Digest Configuration
# =============================================================================
TF_VAR_customer_digest_schedule_hour_utc=11
TF_VAR_customer_digest_default_local_hour=7
TF_VAR_customer_digest_min_severity=warning
TF_VAR_customer_digest_max_customers_per_run=500
TF_VAR_customer_digest_model_id=us.anthropic.claude-haiku-4-5-v1:0
TF_VAR_customer_digest_foundation_model_id=anthropic.claude-haiku-4-5-v1:0

# =============================================================================
# Customer Insights Configuration
# =============================================================================
TF_VAR_customer_insights_default_local_day=6
TF_VAR_customer_insights_default_local_hour=9
TF_VAR_customer_insights_max_customers_per_run=500
TF_VAR_customer_insights_history_days=7
TF_VAR_customer_insights_model_id=us.anthropic.claude-sonnet-5-5-v1:0
TF_VAR_customer_insights_foundation_model_id=anthropic.claude-sonnet-5-5-v1:0

# =============================================================================
# Feedback Loop Configuration
# =============================================================================
TF_VAR_max_few_shot_examples=5
TF_VAR_agent_max_examples_in_context=5
TF_VAR_few_shot_examples_cache_ttl_seconds=300
TF_VAR_agent_examples_cache_ttl_seconds=300

# =============================================================================
# Deprovisioning Configuration
# =============================================================================
TF_VAR_deprovision_drain_seconds=60
TF_VAR_deprovision_require_confirmation=true

# =============================================================================
# Custom Health Checks Configuration
# =============================================================================
TF_VAR_custom_health_max_rules_per_tenant=10
TF_VAR_custom_health_max_score_impact=30

# =============================================================================
# Branding
# =============================================================================
TF_VAR_msp_default_branding={"company_name": "Your MSP", "logo_url": "", "primary_color": "#2c3e50", "support_email": "support@yourmsp.com", "support_phone": "+1-555-0100"}

# =============================================================================
# Multi-Tenant Configuration
# =============================================================================
TF_VAR_tenants={"default": {"display_name": "Default MSP Tenant", "entra_tenant_id": "12345678-1234-1234-1234-123456789012", "admin_group_id": "abcdef12-3456-7890-abcd-ef1234567890", "agent_instruction": ""}}
TF_VAR_default_agent_instruction=You are an AI IT Concierge. Help users with identity and account operations.

# =============================================================================
# Local Development
# =============================================================================
LOCALSTACK_HOST=localhost
LOCALSTACK_PORT=4566