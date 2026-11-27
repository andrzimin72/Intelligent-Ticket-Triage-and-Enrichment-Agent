variable "project" {
  description = "Project name prefix"
  type        = string
  default     = "msp-triage"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "agent_model_id" {
  description = "Bedrock model ID for agents"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "agent_foundation_model_id" {
  description = "Foundation model ID (without region prefix)"
  type        = string
  default     = "anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "kb_embedding_model_id" {
  description = "Embedding model for Knowledge Base"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "default_agent_instruction" {
  description = "Base instruction for the Bedrock Agent"
  type        = string
  default     = "You are an AI IT Concierge. Help users with identity and account operations."
}

variable "agent_idle_session_ttl_seconds" {
  description = "Agent session timeout"
  type        = number
  default     = 1800
}

variable "enable_knowledge_base" {
  description = "Enable Knowledge Base features"
  type        = bool
  default     = false
}

variable "aoss_collection_arn" {
  description = "ARN of the OpenSearch Serverless collection (required if enable_knowledge_base is true)"
  type        = string
  default     = ""
}

variable "enable_guardrails" {
  description = "Enable Bedrock Guardrails"
  type        = bool
  default     = true
}

variable "guardrail_id" {
  description = "Bedrock Guardrail ID"
  type        = string
  default     = ""
}

variable "guardrail_version" {
  description = "Bedrock Guardrail Version"
  type        = string
  default     = "DRAFT"
}

variable "enable_xray_tracing" {
  description = "Enable AWS X-Ray tracing"
  type        = bool
  default     = true
}

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window"
  type        = number
  default     = 7
}

variable "enable_tenant_portal" {
  description = "Enable Cognito User Pool for portal"
  type        = bool
  default     = false
}

variable "portal_callback_url" {
  description = "OAuth callback URL for portal"
  type        = string
  default     = "http://localhost:3000/callback"
}

variable "portal_logout_url" {
  description = "OAuth logout URL for portal"
  type        = string
  default     = "http://localhost:3000"
}