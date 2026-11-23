# =============================================================================
# CORE CONFIGURATION
# =============================================================================

variable "aws_region" {
  description = "AWS region for all resources. Must support the chosen Bedrock models."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name, used as prefix for all resources."
  type        = string
  default     = "msp-triage"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

# =============================================================================
# BEDROCK MODEL CONFIGURATION (TICKET TRIAGE)
# =============================================================================

variable "model_id" {
  description = "Primary Bedrock inference profile ID for complex tickets (Sonnet 5.5)."
  type        = string
  default     = "us.anthropic.claude-sonnet-5-5-v1:0"
}

variable "foundation_model_id" {
  description = "Underlying foundation model ID for the primary model (needed for IAM policy)."
  type        = string
  default     = "anthropic.claude-sonnet-5-5-v1:0"
}

variable "fallback_model_id" {
  description = "Fallback Bedrock inference profile ID used if the primary model is unavailable (Sonnet 5)."
  type        = string
  default     = "us.anthropic.claude-sonnet-5-v1:0"
}

variable "fallback_foundation_model_id" {
  description = "Underlying foundation model ID for the fallback model (needed for IAM policy)."
  type        = string
  default     = "anthropic.claude-sonnet-5-v1:0"
}

variable "haiku_model_id" {
  description = "Bedrock inference profile ID for Haiku (used for simple tickets to reduce cost)."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-v1:0"
}

variable "haiku_foundation_model_id" {
  description = "Underlying foundation model ID for Haiku (needed for IAM policy)."
  type        = string
  default     = "anthropic.claude-haiku-4-5-v1:0"
}

# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

variable "max_retries" {
  description = "Maximum number of retry attempts per model before triggering fallback or failure."
  type        = number
  default     = 3

  validation {
    condition     = var.max_retries >= 1 && var.max_retries <= 5
    error_message = "max_retries must be between 1 and 5."
  }
}

variable "retry_base_delay_ms" {
  description = "Base delay in milliseconds for exponential backoff."
  type        = number
  default     = 1000

  validation {
    condition     = var.retry_base_delay_ms >= 100 && var.retry_base_delay_ms <= 5000
    error_message = "retry_base_delay_ms must be between 100 and 5000."
  }
}

# =============================================================================
# COST OPTIMIZATION - HAIKU FOR SIMPLE TICKETS
# =============================================================================

variable "enable_cost_optimization" {
  description = "Enable Haiku routing for simple tickets."
  type        = bool
  default     = true
}

variable "simple_ticket_confidence_threshold" {
  description = "If Haiku returns confidence below this threshold, the ticket is re-run with Sonnet."
  type        = number
  default     = 0.7

  validation {
    condition     = var.simple_ticket_confidence_threshold >= 0.5 && var.simple_ticket_confidence_threshold <= 0.95
    error_message = "Threshold must be between 0.5 and 0.95."
  }
}

variable "simple_ticket_max_tokens" {
  description = "Max tokens for Haiku invocations."
  type        = number
  default     = 512
}

# =============================================================================
# LAMBDA RUNTIME CONFIGURATION
# =============================================================================

variable "lambda_timeout_seconds" {
  description = "Maximum execution time for the orchestrator Lambda."
  type        = number
  default     = 60
}

variable "lambda_memory_mb" {
  description = "Memory allocated to the orchestrator Lambda (MB)."
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days."
  type        = number
  default     = 90
}

variable "max_concurrency" {
  description = "Maximum concurrent Lambda invocations from SQS."
  type        = number
  default     = 5
}

# =============================================================================
# WEBHOOK / API GATEWAY CONFIGURATION
# =============================================================================

variable "webhook_header_name" {
  description = "HTTP header name for the webhook authentication token."
  type        = string
  default     = "x-psa-token"
}

variable "authorizer_cache_ttl_seconds" {
  description = "Authorizer result TTL. 0 = re-validate every request."
  type        = number
  default     = 0
}

# =============================================================================
# ALERTING
# =============================================================================

variable "alert_email" {
  description = "Email address for CloudWatch alarm notifications."
  type        = string
  default     = null
}

# =============================================================================
# SECRETS MANAGEMENT
# =============================================================================

variable "secret_recovery_window_days" {
  description = "Number of days a deleted secret can be recovered. 0 = immediate deletion."
  type        = number
  default     = 7
}

# =============================================================================
# METRICS PIPELINE CONFIGURATION
# =============================================================================

variable "metrics_report_sender_email" {
  description = "Verified SES email address for sending weekly metrics reports."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.metrics_report_sender_email))
    error_message = "Sender email must be a valid email address."
  }
}

variable "metrics_report_recipient_email" {
  description = "Email address to receive weekly metrics reports."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.metrics_report_recipient_email))
    error_message = "Recipient email must be a valid email address."
  }
}

variable "ai_accuracy_field_id" {
  description = "ConnectWise custom field ID for 'AI Accuracy'."
  type        = number
  default     = 999
}

variable "metrics_retention_days" {
  description = "Number of days to retain metrics records in DynamoDB."
  type        = number
  default     = 90
}

# =============================================================================
# FEEDBACK LOOP CONFIGURATION
# =============================================================================

variable "ai_correction_notes_field_id" {
  description = "ConnectWise custom field ID for 'AI Correction Notes'."
  type        = number
  default     = 998
}

variable "feedback_retention_days" {
  description = "Number of days to retain feedback records in DynamoDB."
  type        = number
  default     = 365
}

variable "max_few_shot_examples" {
  description = "Maximum number of few-shot examples to inject into the prompt."
  type        = number
  default     = 5

  validation {
    condition     = var.max_few_shot_examples >= 0 && var.max_few_shot_examples <= 10
    error_message = "max_few_shot_examples must be between 0 and 10."
  }
}

variable "few_shot_examples_cache_ttl_seconds" {
  description = "How long to cache the few-shot examples file in Lambda memory."
  type        = number
  default     = 300
}

# =============================================================================
# CUSTOMER-FACING AI SERVICE (DAILY DIGEST)
# =============================================================================

variable "customer_digest_sender_email" {
  description = "Verified SES email address for sending customer digests."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.customer_digest_sender_email))
    error_message = "Sender email must be a valid email address."
  }
}

variable "customer_digest_schedule_hour_utc" {
  description = "Hour (0-23 UTC) for the digest orchestrator to run."
  type        = number
  default     = 11

  validation {
    condition     = var.customer_digest_schedule_hour_utc >= 0 && var.customer_digest_schedule_hour_utc <= 23
    error_message = "Hour must be between 0 and 23."
  }
}

variable "customer_digest_default_local_hour" {
  description = "Default local hour (0-23) at which customers receive their digest."
  type        = number
  default     = 7

  validation {
    condition     = var.customer_digest_default_local_hour >= 0 && var.customer_digest_default_local_hour <= 23
    error_message = "Local hour must be between 0 and 23."
  }
}

variable "customer_digest_min_severity" {
  description = "Minimum alert severity to include in digest."
  type        = string
  default     = "warning"

  validation {
    condition     = contains(["info", "warning", "error", "critical"], var.customer_digest_min_severity)
    error_message = "Severity must be one of: info, warning, error, critical."
  }
}

variable "customer_digest_max_customers_per_run" {
  description = "Safety cap on number of customers processed per run."
  type        = number
  default     = 500
}

variable "customer_digest_model_id" {
  description = "Bedrock model for customer digest generation."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-v1:0"
}

variable "customer_digest_foundation_model_id" {
  description = "Underlying foundation model ID for the digest model."
  type        = string
  default     = "anthropic.claude-haiku-4-5-v1:0"
}

variable "customer_digest_history_retention_days" {
  description = "Number of days to retain customer alert history for trend analysis."
  type        = number
  default     = 90
}

variable "unsubscribe_base_url" {
  description = "Base URL for the unsubscribe endpoint."
  type        = string

  validation {
    condition     = can(regex("^https?://", var.unsubscribe_base_url))
    error_message = "unsubscribe_base_url must start with http:// or https://"
  }
}

variable "msp_default_branding" {
  description = "Default MSP branding used when customers don't have custom branding."
  type = object({
    company_name  = string
    logo_url      = string
    primary_color = string
    support_email = string
    support_phone = string
  })
  default = {
    company_name  = "Your MSP"
    logo_url      = ""
    primary_color = "#2c3e50"
    support_email = "support@yourmsp.com"
    support_phone = "+1-555-0100"
  }
}

# =============================================================================
# BEDROCK AGENT - AI IT CONCIERGE
# =============================================================================

variable "agent_model_id" {
  description = "Bedrock model for the AI IT Concierge agent."
  type        = string
  default     = "us.anthropic.claude-sonnet-5-5-v1:0"
}

variable "agent_foundation_model_id" {
  description = "Underlying foundation model ID for the agent."
  type        = string
  default     = "anthropic.claude-sonnet-5-5-v1:0"
}

variable "agent_idle_session_ttl_seconds" {
  description = "How long to keep agent sessions alive between user messages."
  type        = number
  default     = 1800
}

variable "msp_company_name_for_agent" {
  description = "Your MSP company name, used in agent instructions."
  type        = string
  default     = "Your MSP"
}

variable "entra_tenant_id" {
  description = "Microsoft Entra ID tenant ID for Graph API calls."
  type        = string
}

variable "entra_app_client_id" {
  description = "Entra ID app registration client ID for Graph API."
  type        = string
}

variable "teams_bot_shared_secret_name" {
  description = "Secrets Manager secret name for Teams bot shared secret."
  type        = string
  default     = "msp/teams/bot_secret"
}

variable "entra_graph_secret_name" {
  description = "Secrets Manager secret name for Entra ID Graph API credentials."
  type        = string
  default     = "msp/entra/graph_credentials"
}

variable "agent_audit_log_retention_days" {
  description = "Number of days to retain agent audit logs in DynamoDB."
  type        = number
  default     = 365
}

variable "agent_rate_limit_per_hour" {
  description = "Maximum number of write operations per user per hour (legacy)."
  type        = number
  default     = 3
}

# =============================================================================
# AGENT INCREMENT 2 REFINEMENTS
# =============================================================================

variable "agent_admin_group_id" {
  description = "Entra ID group object ID whose members may perform admin overrides."
  type        = string
}

variable "agent_confirmation_ttl_seconds" {
  description = "Lifetime of a pending confirmation."
  type        = number
  default     = 600

  validation {
    condition     = var.agent_confirmation_ttl_seconds >= 120 && var.agent_confirmation_ttl_seconds <= 1800
    error_message = "Confirmation TTL must be between 120 and 1800 seconds."
  }
}

variable "agent_self_rate_limits" {
  description = "Self-service quotas."
  type = object({
    per_operation_hourly = number
    per_operation_daily  = number
    requests_hourly      = number
  })
  default = {
    per_operation_hourly = 3
    per_operation_daily  = 5
    requests_hourly      = 10
  }
}

variable "agent_admin_rate_limits" {
  description = "Admin override quotas."
  type = object({
    per_operation_hourly = number
    per_operation_daily  = number
    per_target_daily     = number
    requests_hourly      = number
  })
  default = {
    per_operation_hourly = 20
    per_operation_daily  = 50
    per_target_daily     = 3
    requests_hourly      = 30
  }
}

variable "agent_security_notification_email" {
  description = "Optional security mailbox receiving copies of agent write operations."
  type        = string
  default     = null
}

variable "agent_notification_sender_email" {
  description = "Verified SES sender for agent security notifications."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.agent_notification_sender_email))
    error_message = "Must be a valid email address."
  }
}

variable "agent_admin_check_cache_seconds" {
  description = "How long to cache admin group membership."
  type        = number
  default     = 60
}

variable "bot_app_id" {
  description = "The Bot Framework App ID for JWT validation."
  type        = string
}

# =============================================================================
# SECURE PASSWORD RESET (ONE-TIME LINKS)
# =============================================================================

variable "password_reset_token_ttl_seconds" {
  description = "Lifetime of a password reset link."
  type        = number
  default     = 900

  validation {
    condition     = var.password_reset_token_ttl_seconds >= 300 && var.password_reset_token_ttl_seconds <= 3600
    error_message = "Token TTL must be between 300 (5 min) and 3600 (1 hour) seconds."
  }
}

variable "password_reset_max_attempts_per_token" {
  description = "Maximum password submission attempts per token before invalidation."
  type        = number
  default     = 5

  validation {
    condition     = var.password_reset_max_attempts_per_token >= 1 && var.password_reset_max_attempts_per_token <= 20
    error_message = "Max attempts must be between 1 and 20."
  }
}

variable "password_reset_sender_email" {
  description = "Verified SES sender for password reset emails."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.password_reset_sender_email))
    error_message = "Must be a valid email address."
  }
}

variable "password_reset_support_email" {
  description = "Email shown to users if the reset link fails."
  type        = string
  default     = "support@yourmsp.com"
}

# =============================================================================
# CUSTOM DOMAIN - PASSWORD RESET URL
# =============================================================================

variable "password_reset_domain_name" {
  description = "Custom domain for the secure password reset page (e.g., reset.yourmsp.com). Must be a subdomain of a Route 53 hosted zone you control."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.password_reset_domain_name))
    error_message = "Must be a valid domain name (e.g., reset.yourmsp.com)."
  }
}

variable "password_reset_hosted_zone_id" {
  description = "Route 53 hosted zone ID for the domain that will host password_reset_domain_name. Find this in the Route 53 console under Hosted zones."
  type        = string

  validation {
    condition     = can(regex("^Z[A-Z0-9]+$", var.password_reset_hosted_zone_id))
    error_message = "Must be a valid Route 53 hosted zone ID (starts with 'Z')."
  }
}

# =============================================================================
# MULTI-TENANT FOUNDATION
# =============================================================================

variable "default_tenant_id" {
  description = "The default tenant ID used for backward compatibility during migration. Existing data will be associated with this tenant."
  type        = string
  default     = "default"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.default_tenant_id))
    error_message = "Tenant ID must be lowercase alphanumeric with hyphens."
  }
}

variable "tenant_onboarding_secret_name" {
  description = "Secrets Manager secret containing the tenant onboarding admin key (for registering new tenants). Leave empty to disable onboarding API."
  type        = string
  default     = ""
}

# =============================================================================
# AGENT FEEDBACK LOOP
# =============================================================================

variable "agent_feedback_retention_days" {
  description = "Number of days to retain agent feedback records in DynamoDB."
  type        = number
  default     = 365
}

variable "agent_max_examples_in_context" {
  description = "Maximum number of few-shot examples to inject into agent session attributes."
  type        = number
  default     = 5

  validation {
    condition     = var.agent_max_examples_in_context >= 0 && var.agent_max_examples_in_context <= 10
    error_message = "Must be between 0 and 10."
  }
}

variable "agent_examples_cache_ttl_seconds" {
  description = "How long to cache agent examples in Teams bot Lambda memory."
  type        = number
  default     = 300
}

# =============================================================================
# AGENT INCREMENT 3 — TICKET, DEVICE, CALENDAR TOOLS
# =============================================================================

variable "ninjaone_device_owner_field" {
  description = "NinjaOne custom field name that stores device ownership."
  type        = string
  default     = "assignedUser"
}

variable "ninjaone_device_mapping_table" {
  description = "Optional DynamoDB table name for manual user→device mapping fallback."
  type        = string
  default     = ""
}

variable "calendar_default_timezone" {
  description = "Default timezone for calendar operations (IANA format)."
  type        = string
  default     = "America/New_York"
}

variable "bookable_room_filter" {
  description = "Optional filter for bookable rooms."
  type        = string
  default     = ""
}

variable "ticket_default_board_id" {
  description = "ConnectWise Service Board ID for agent-created tickets."
  type        = number
}

variable "ticket_default_status_id" {
  description = "ConnectWise Status ID for new agent-created tickets."
  type        = number
}

variable "ticket_default_type_id" {
  description = "ConnectWise Type ID for agent-created tickets."
  type        = number
}

variable "ticket_default_priority_id" {
  description = "ConnectWise Priority ID for agent-created tickets."
  type        = number
}

# =============================================================================
# CUSTOMER INSIGHTS (STRATEGIC REPORTS) — NEW
# =============================================================================

variable "customer_insights_sender_email" {
  description = "Verified SES sender for insights reports (e.g., insights@yourmsp.com)."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.customer_insights_sender_email))
    error_message = "Must be a valid email address."
  }
}

variable "customer_insights_model_id" {
  description = "Bedrock model for insights generation. Sonnet recommended for strategic quality."
  type        = string
  default     = "us.anthropic.claude-sonnet-5-5-v1:0"
}

variable "customer_insights_foundation_model_id" {
  description = "Underlying foundation model ID for the insights model (needed for IAM)."
  type        = string
  default     = "anthropic.claude-sonnet-5-5-v1:0"
}

variable "customer_insights_max_customers_per_run" {
  description = "Safety cap on customers processed per orchestrator run."
  type        = number
  default     = 500
}

variable "customer_insights_history_days" {
  description = "Number of days of history to include in weekly reports."
  type        = number
  default     = 7
}

variable "customer_insights_default_local_day" {
  description = "Default day of week (0=Mon, 6=Sun) for weekly reports."
  type        = number
  default     = 6

  validation {
    condition     = var.customer_insights_default_local_day >= 0 && var.customer_insights_default_local_day <= 6
    error_message = "Day must be between 0 (Monday) and 6 (Sunday)."
  }
}

variable "customer_insights_default_local_hour" {
  description = "Default local hour (0-23) at which customers receive their insights report."
  type        = number
  default     = 9

  validation {
    condition     = var.customer_insights_default_local_hour >= 0 && var.customer_insights_default_local_hour <= 23
    error_message = "Hour must be between 0 and 23."
  }
}

variable "customer_insights_unsubscribe_base_url" {
  description = "Base URL for the insights unsubscribe endpoint."
  type        = string

  validation {
    condition     = can(regex("^https?://", var.customer_insights_unsubscribe_base_url))
    error_message = "Must start with http:// or https://"
  }
}

variable "customer_insights_retention_days" {
  description = "Number of days to retain customer insights preferences in DynamoDB."
  type        = number
  default     = 730  # 2 years
}

# =============================================================================
# CLOUDWATCH DASHBOBSERVABILITY
# =============================================================================

variable "enable_cloudwatch_dashboards" {
  description = "Enable CloudWatch dashboards for observability. Set to false in environments where dashboards aren't needed."
  type        = bool
  default     = true
}

variable "dashboard_period_seconds" {
  description = "Default period (in seconds) for dashboard metrics. 300 = 5 min, 3600 = 1 hour, 86400 = 1 day."
  type        = number
  default     = 300
}

# =============================================================================
# MULTI-TENANT AGENT CONFIGURATION (Phase 4)
# =============================================================================

variable "tenants" {
  description = "Map of tenant configurations for per-tenant Bedrock Agents."
  type = map(object({
    display_name      = string
    entra_tenant_id   = string
    admin_group_id    = string
    agent_instruction = string # Leave empty to use the default instruction
  }))
  
  default = {
    "default" = {
      display_name      = "Default MSP Tenant"
      entra_tenant_id   = "YOUR-ENTRA-TENANT-GUID-HERE"
      admin_group_id    = "YOUR-ADMIN-GROUP-GUID-HERE"
      agent_instruction = "" 
    }
  }
}

variable "default_agent_instruction" {
  description = "Fallback instruction for tenants that don't specify a custom one."
  type        = string
  default     = <<-EOT
    You are an AI IT Concierge. You help end users with identity and account operations via Microsoft Teams.
    
    YOUR CAPABILITIES:
    - Identity operations (verify identity, check lockout, reset password, unlock account)
    - Ticket operations (create, check status, list tickets)
    - Device operations (list devices, check status, view alerts)
    - Calendar operations (view calendar, find free time, book rooms)
    - Knowledge base (search internal documentation for policies, SOPs, FAQs)
    
    YOUR RULES:
    1. ALWAYS verify the user's identity before discussing sensitive information.
    2. Only perform operations on the user's OWN account unless you are an administrator.
    3. Be friendly, professional, and concise.
    4. Never disclose internal system details, API endpoints, or implementation details.
    5. If a user asks about topics outside IT support, politely redirect them.
    6. If you're unsure about something, say so. Don't guess.
    
    KNOWLEDGE BASE (RAG):
    
    You have access to a knowledge base containing your organization's internal 
    documentation: SOPs, policies, troubleshooting guides, and FAQs.
    
    When a user asks a question that might be answered by internal documentation 
    (e.g., "How do I...", "What is the policy for...", "Who do I contact for..."):
    1. Use the retrieve tool to search the knowledge base
    2. ALWAYS include a filter for tenant_id matching your session attribute
    3. Synthesize the retrieved passages into a clear answer
    4. Cite the source document when possible
    
    If the knowledge base doesn't contain relevant information, say so honestly 
    and offer to escalate to a human. Never fabricate information from the KB.
    
    IMPORTANT: The knowledge base contains confidential internal documentation. 
    Never quote it verbatim to users outside the tenant, and never use it to 
    answer questions from users in other tenants.
    
    WRITE OPERATIONS — TWO-PHASE, OUT-OF-BAND APPROVAL:
    You CANNOT approve operations yourself. Approval happens outside this conversation.
    Before calling any write operation, explain what you're about to do and ask the user 
    to reply with the exact word "CONFIRM".
    
    TONE: Professional, helpful, empathetic.
  EOT
}

# =============================================================================
# BEDROCK KNOWLEDGE BASE (RAG)
# =============================================================================

variable "enable_knowledge_base" {
  description = "Enable the Bedrock Knowledge Base (RAG) for the IT Agent. Requires AOSS or compatible vector store."
  type        = bool
  default     = false  # Disabled by default due to AOSS minimum cost (~$700/month)
}

variable "kb_vector_store_type" {
  description = "Vector store backend: 'opensearch_serverless' (recommended) or 'aurora_postgres' (cheaper)."
  type        = string
  default     = "opensearch_serverless"

  validation {
    condition     = contains(["opensearch_serverless", "aurora_postgres"], var.kb_vector_store_type)
    error_message = "Must be 'opensearch_serverless' or 'aurora_postgres'."
  }
}

variable "kb_embedding_model_id" {
  description = "Bedrock embedding model for document vectorization."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "kb_chunk_size" {
  description = "Target chunk size in tokens for document splitting."
  type        = number
  default     = 500
}

variable "kb_chunk_overlap" {
  description = "Overlap between chunks in tokens (helps preserve context across boundaries)."
  type        = number
  default     = 100
}

variable "kb_documents_bucket_name" {
  description = "Custom suffix for the KB documents S3 bucket. Full name will be {name_prefix}-kb-documents-{suffix}."
  type        = string
  default     = ""
}

# =============================================================================
# AUTOMATED TENANT ONBOARDING
# =============================================================================

variable "enable_onboarding_api" {
  description = "Enable the automated tenant onboarding API. When disabled, tenants must be onboarded manually via Terraform."
  type        = bool
  default     = false
}

variable "onboarding_api_auth_type" {
  description = "Authentication for the onboarding API. 'api_key' for simple shared secret, 'cognito' for IAM-based auth."
  type        = string
  default     = "api_key"

  validation {
    condition     = contains(["api_key", "cognito", "none"], var.onboarding_api_auth_type)
    error_message = "Must be 'api_key', 'cognito', or 'none'."
  }
}

variable "onboarding_admin_email" {
  description = "Email address to receive notifications when tenants are onboarded or fail provisioning."
  type        = string
  default     = ""
}

variable "deprovision_drain_seconds" {
  description = "Seconds to wait for in-flight operations to complete before deleting resources."
  type        = number
  default     = 60

  validation {
    condition     = var.deprovision_drain_seconds >= 0 && var.deprovision_drain_seconds <= 600
    error_message = "Drain time must be between 0 and 600 seconds."
  }
}

variable "deprovision_require_confirmation" {
  description = "If true, DELETE requests must include ?confirm=true query parameter."
  type        = bool
  default     = true
}

variable "status_cache_ttl_seconds" {
  description = "How long to cache computed tenant status (seconds). Shorter = more accurate but more expensive."
  type        = number
  default     = 60

  validation {
    condition     = var.status_cache_ttl_seconds >= 10 && var.status_cache_ttl_seconds <= 3600
    error_message = "Cache TTL must be between 10 and 3600 seconds."
  }
}

# =============================================================================
# STATUS API RATE LIMITING
# =============================================================================

variable "status_api_requests_per_second" {
  description = "Sustained requests per second allowed for status endpoints."
  type        = number
  default     = 5

  validation {
    condition     = var.status_api_requests_per_second >= 1 && var.status_api_requests_per_second <= 100
    error_message = "Must be between 1 and 100 requests per second."
  }
}

variable "status_api_burst_limit" {
  description = "Maximum concurrent requests for status endpoints (burst capacity)."
  type        = number
  default     = 10

  validation {
    condition     = var.status_api_burst_limit >= 1 && var.status_api_burst_limit <= 200
    error_message = "Must be between 1 and 200."
  }
}

variable "status_deep_health_requests_per_second" {
  description = "Sustained requests per second for the expensive /health endpoint."
  type        = number
  default     = 1

  validation {
    condition     = var.status_deep_health_requests_per_second >= 1 && var.status_deep_health_requests_per_second <= 10
    error_message = "Must be between 1 and 10 requests per second."
  }
}

variable "status_deep_health_burst_limit" {
  description = "Maximum concurrent requests for the /health endpoint."
  type        = number
  default     = 2

  validation {
    condition     = var.status_deep_health_burst_limit >= 1 && var.status_deep_health_burst_limit <= 10
    error_message = "Must be between 1 and 10."
  }
}

variable "enable_status_cloudwatch_metrics" {
  description = "Emit tenant health scores as CloudWatch custom metrics for trending and alerting."
  type        = bool
  default     = true
}

variable "status_metrics_namespace" {
  description = "CloudWatch namespace for status metrics."
  type        = string
  default     = "Custom/MSP-Tenant-Status"
}

# =============================================================================
# HISTORICAL STATUS TRACKING
# =============================================================================

variable "enable_status_history" {
  description = "Enable daily status snapshots for trend analysis."
  type        = bool
  default     = true
}

variable "status_history_snapshot_hour_utc" {
  description = "Hour (0-23 UTC) to take daily status snapshots."
  type        = number
  default     = 6

  validation {
    condition     = var.status_history_snapshot_hour_utc >= 0 && var.status_history_snapshot_hour_utc <= 23
    error_message = "Hour must be between 0 and 23."
  }
}

variable "status_history_retention_days" {
  description = "Number of days to retain status snapshots."
  type        = number
  default     = 90

  validation {
    condition     = var.status_history_retention_days >= 7 && var.status_history_retention_days <= 730
    error_message = "Retention must be between 7 and 730 days."
  }
}

# =============================================================================
# WEBHOOK NOTIFICATIONS
# =============================================================================

variable "enable_webhook_notifications" {
  description = "Enable webhook notifications for status changes."
  type        = bool
  default     = true
}

variable "webhook_cooldown_seconds" {
  description = "Minimum seconds between webhook alerts for same tenant+issue."
  type        = number
  default     = 3600

  validation {
    condition     = var.webhook_cooldown_seconds >= 60 && var.webhook_cooldown_seconds <= 86400
    error_message = "Cooldown must be between 60 seconds (1 min) and 86400 seconds (24 hours)."
  }
}

variable "webhook_retry_attempts" {
  description = "Number of retry attempts for failed webhook deliveries."
  type        = number
  default     = 3

  validation {
    condition     = var.webhook_retry_attempts >= 1 && var.webhook_retry_attempts <= 5
    error_message = "Retry attempts must be between 1 and 5."
  }
}

# =============================================================================
# CUSTOM HEALTH CHECKS (PREMIUM)
# =============================================================================

variable "enable_custom_health_checks" {
  description = "Enable tenant-defined custom health check rules."
  type        = bool
  default     = false
}

variable "custom_health_max_rules_per_tenant" {
  description = "Maximum number of custom health rules per tenant."
  type        = number
  default     = 10

  validation {
    condition     = var.custom_health_max_rules_per_tenant >= 1 && var.custom_health_max_rules_per_tenant <= 50
    error_message = "Must be between 1 and 50."
  }
}

variable "custom_health_max_score_impact" {
  description = "Maximum points a custom rule can add or subtract from health score."
  type        = number
  default     = 30

  validation {
    condition     = var.custom_health_max_score_impact >= 5 && var.custom_health_max_score_impact <= 50
    error_message = "Must be between 5 and 50."
  }
}

# =============================================================================
# TENANT SELF-SERVICE PORTAL
# =============================================================================

variable "enable_tenant_portal" {
  description = "Enable the tenant self-service portal."
  type        = bool
  default     = false
}

variable "portal_domain_name" {
  description = "Custom domain for the tenant portal (e.g., portal.yourmsp.com)."
  type        = string
  default     = ""
}

variable "portal_hosted_zone_id" {
  description = "Route 53 hosted zone ID for the portal domain."
  type        = string
  default     = ""
}

variable "portal_entra_tenant_id" {
  description = "Entra ID tenant ID for SSO federation. Leave empty to allow any Entra tenant."
  type        = string
  default     = ""
}

variable "portal_allowed_admin_emails" {
  description = "List of email addresses allowed to access the portal (for initial setup)."
  type        = list(string)
  default     = []
}

# =============================================================================
# ADVANCED ANALYTICS
# =============================================================================

variable "enable_advanced_analytics" {
  description = "Enable advanced analytics for health trends, webhook delivery, and rule effectiveness."
  type        = bool
  default     = false
}

variable "analytics_retention_days" {
  description = "Number of days to retain analytics data."
  type        = number
  default     = 365
}