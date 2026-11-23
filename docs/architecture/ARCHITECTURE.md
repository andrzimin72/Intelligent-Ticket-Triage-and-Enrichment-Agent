# MSP AI Platform - Architecture Documentation

This document provides comprehensive architecture documentation using the C4 Model.

## Table of Contents

1. [Overview](#overview)
2. [C4 Model Diagrams](#c4-model-diagrams)
3. [System Context](#system-context)
4. [Container Architecture](#container-architecture)
5. [Component Details](#component-details)
6. [Deployment Architecture](#deployment-architecture)
7. [Data Flow](#data-flow)
8. [Security Architecture](#security-architecture)
9. [Multi-Tenancy Model](#multi-tenancy-model)

## Overview

The MSP AI Platform is a multi-tenant, AI-powered IT service automation system built on AWS. It provides:

- **Automated ticket triage** with self-improving accuracy
- **AI IT concierge** accessible via Microsoft Teams
- **Proactive customer insights** with weekly strategic reports
- **Secure password reset** with one-time links
- **Self-service tenant portal** for MSP customers
- **Comprehensive analytics** for platform operations

### Key Design Principles

1. **Tenant Isolation** - Each MSP customer gets fully isolated resources
2. **Security First** - Zero-trust architecture with audit trails
3. **Scalability** - Serverless design handles variable loads
4. **Cost Optimization** - Model routing based on task complexity
5. **Observability** - Comprehensive monitoring and alerting

## C4 Model Diagrams

All diagrams are available in multiple formats:

| Format | File | Use Case |
|--------|------|----------|
| PlantUML | `c4-*.puml` | Professional documentation, IDE rendering |
| Mermaid | `c4-mermaid.md` | GitHub/GitLab rendering, easy sharing |
| ASCII | Inline below | Quick reference, no tools needed |

### Rendering PlantUML

```bash
# Install PlantUML
brew install plantuml  # macOS
# or
apt-get install plantuml  # Ubuntu

# Render diagrams
plantuml docs/architecture/c4-context.puml
plantuml docs/architecture/c4-container.puml
```

### Rendering Mermaid

Mermaid diagrams render automatically in:
- GitHub Markdown
- GitLab Markdown
- Notion
- Obsidian
- VS Code (with Mermaid extension)

## System Context

### Actors

| Actor | Description | Interactions |
|-------|-------------|--------------|
| **MSP IT Staff** | Internal team managing the platform | Deploys, monitors, maintains |
| **MSP Technician** | Handles support tickets | Provides feedback on triage |
| **MSP Leadership** | Reviews analytics | Views executive summaries |
| **End User** | Employee of MSP customer | Chats with IT concierge |
| **Customer IT Liaison** | Receives insights reports | Reviews weekly reports |

### External Systems

| System | Purpose | Integration |
|--------|---------|-------------|
| **Microsoft Teams** | Communication platform | Bot Framework |
| **Microsoft Entra ID** | Identity management | Graph API |
| **ConnectWise PSA** | Ticket management | REST API |
| **NinjaOne RMM** | Device monitoring | REST API |
| **Amazon Bedrock** | AI/ML services | AWS SDK |
| **Amazon SES** | Email delivery | SMTP |
| **Slack / PagerDuty** | Alerting | Webhooks |

## Container Architecture

### API Layer

| Container | Technology | Responsibility |
|-----------|-----------|----------------|
| Tenant Onboarding API | API Gateway + Lambda | Tenant lifecycle, status, analytics |
| Password Reset API | API Gateway + Lambda | Secure one-time reset links |
| Tenant Portal API | API Gateway + Lambda | Self-service endpoints |
| Webhooks API | API Gateway | Receives ConnectWise webhooks |

### AI Services

| Container | Technology | Responsibility |
|-----------|-----------|----------------|
| Teams Bot Adapter | AWS Lambda | Bridges Teams to Bedrock |
| Per-Tenant Bedrock Agents | Amazon Bedrock | Isolated AI agents |
| Knowledge Base | Bedrock KB + AOSS | Tenant-scoped RAG |

### Core Lambda Functions

| Container | Responsibility |
|-----------|----------------|
| Identity Tools | User lookup, password reset, account unlock |
| Ticket Tools | Create/check ConnectWise tickets |
| Device Tools | Query NinjaOne device data |
| Calendar Tools | Calendar operations via Graph API |
| Triage Orchestrator | Routes tickets to appropriate model |
| Triage Worker | Processes tickets with Bedrock |

### Data Stores

| Store | Technology | Purpose |
|-------|-----------|---------|
| Tenant Registry | DynamoDB | Tenant metadata and configuration |
| Status History | DynamoDB | Daily health snapshots (90-day retention) |
| Analytics Summary | DynamoDB | Pre-computed analytics |
| Audit Log | DynamoDB | Tamper-evident audit trail |
| Feedback DB | DynamoDB | Technician and user feedback |
| Password Tokens | DynamoDB | One-time reset tokens |
| Agent Schemas | S3 | Tool schemas and few-shot examples |
| KB Documents | S3 | Tenant-scoped documentation |
| Provisioning Queue | SQS | Async tenant provisioning |
| Digest Queue | SQS | Customer digest jobs |
| Secrets | Secrets Manager | Tenant-scoped API credentials |

## Component Details

### Tenant Onboarding API Components

```
┌─────────────────────────────────────────────────────────────┐
│ Tenant Onboarding API                                        │
├─────────────────────────────────────────────────────────────┤
│ Request Router                                               │
│  ├─ Onboarding Handler (POST /tenants)                      │
│  │   ├─ Tenant Resolver                                     │
│  │   └─ Hybrid Mode Logic                                   │
│  ├─ Deprovision Handler (DELETE /tenants/{id})              │
│  ├─ Status Computation (GET /status/*)                      │
│  │   ├─ Status Cache (60s TTL)                              │
│  │   └─ CloudWatch Metrics Emitter                          │
│  └─ Analytics Handlers (GET /analytics/*)                   │
│      ├─ Health Trends                                       │
│      ├─ Webhook Delivery Stats                              │
│      ├─ Rule Effectiveness                                  │
│      └─ Executive Summary                                   │
└─────────────────────────────────────────────────────────────┘
```

### Teams Bot Adapter Components

```
┌─────────────────────────────────────────────────────────────┐
│ Teams Bot Adapter                                            │
├─────────────────────────────────────────────────────────────┤
│ JWT Validator → Tenant Resolver → Email Resolver            │
│                                                              │
│ Message Processing:                                          │
│  └─ Message Handler → Agent Invoker → Reply Sender          │
│                                                              │
│ Invoke Handling:                                             │
│  ├─ Approval Handler                                        │
│  └─ Feedback Handler                                        │
│                                                              │
│ Adaptive Cards:                                              │
│  ├─ Feedback Card Builder                                   │
│  ├─ Approval Card Builder                                   │
│  └─ Detailed Feedback Card                                  │
│                                                              │
│ Session Management:                                          │
│  ├─ Session Store                                           │
│  ├─ Examples Loader (tenant-scoped)                         │
│  └─ Audit Logger                                            │
└─────────────────────────────────────────────────────────────┘
```

## Deployment Architecture

### AWS Services Used

| Service | Purpose | Count |
|---------|---------|-------|
| Lambda | Compute | ~30 functions |
| API Gateway | REST APIs | 4 APIs |
| DynamoDB | NoSQL database | ~15 tables |
| S3 | Object storage | 5 buckets |
| SQS | Message queues | 6 queues |
| Secrets Manager | Credential storage | Per-tenant secrets |
| Bedrock | AI/ML | Per-tenant agents |
| OpenSearch Serverless | Vector store | 1 collection |
| CloudFront | CDN | 2 distributions |
| Cognito | Authentication | 1 user pool |
| CloudWatch | Monitoring | 4 dashboards |
| X-Ray | Tracing | Enabled on all Lambdas |
| SES | Email | Verified senders |

### Cost Breakdown (Estimated Monthly)

| Component | Cost | Notes |
|-----------|------|-------|
| Lambda | $50-200 | Pay-per-invocation |
| DynamoDB | $20-100 | Pay-per-request |
| S3 | $5-20 | Minimal storage |
| Bedrock | $200-1000 | Depends on usage |
| OpenSearch Serverless | $700 | Fixed minimum |
| API Gateway | $10-50 | Pay-per-request |
| CloudWatch | $20-50 | Logs + metrics |
| **Total** | **$1000-2100** | For small MSP |

## Data Flow

### Password Reset Flow

```
User → Teams → Bot → Agent → Identity Tools → Graph API
                                    ↓
                              Generate Token
                                    ↓
                              Store in DynamoDB
                                    ↓
                              Send Email (SES)
                                    ↓
                              User clicks link
                                    ↓
                              Reset Lambda validates
                                    ↓
                              User sets new password
                                    ↓
                              Graph API updates
                                    ↓
                              Confirmation email sent
```

### Ticket Triage Flow

```
ConnectWise → Webhook → Orchestrator → SQS → Worker
                                            ↓
                                      Classify complexity
                                            ↓
                                      ┌─────┴─────┐
                                      ↓           ↓
                                   Simple      Complex
                                      ↓           ↓
                                   Haiku       Sonnet
                                      ↓           ↓
                                   └─────┬─────┘
                                         ↓
                                   Confidence check
                                         ↓
                                   ┌─────┴─────┐
                                   ↓           ↓
                                High        Low
                                   ↓           ↓
                                Accept      Retry with Sonnet
                                   ↓
                              Update ticket
                                   ↓
                              Record metrics
```

## Security Architecture

### Authentication & Authorization

```
┌─────────────────────────────────────────────────────────────┐
│ Authentication Layer                                         │
├─────────────────────────────────────────────────────────────┤
│ Bot Framework JWT Validation                                │
│  └─ Validates Teams requests cryptographically              │
│                                                              │
│ Cognito + Entra ID Federation                               │
│  └─ SSO for tenant portal                                   │
│                                                              │
│ API Keys                                                    │
│  └─ For onboarding API (admin access)                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Authorization Layer                                          │
├─────────────────────────────────────────────────────────────┤
│ Tenant Isolation                                            │
│  └─ All operations scoped by tenant_id                      │
│                                                              │
│ Server-Side Admin Verification                              │
│  └─ Entra ID group membership checked server-side           │
│                                                              │
│ Two-Phase Approval                                          │
│  └─ Write operations require out-of-band approval           │
│                                                              │
│ Scope Isolation                                             │
│  └─ Users can only operate on their own accounts            │
└─────────────────────────────────────────────────────────────┘
```

### Data Protection

- **Encryption at Rest**: All DynamoDB tables, S3 buckets, Secrets Manager
- **Encryption in Transit**: TLS 1.2+ for all API calls
- **Secrets Management**: All credentials in Secrets Manager, never in code
- **Audit Trail**: All operations logged with tamper-evident records
- **PII Redaction**: Guardrails redact PII before processing

## Multi-Tenancy Model

### Isolation Levels

| Resource | Isolation Method |
|----------|------------------|
| Bedrock Agent | **Physical** - Separate agent per tenant |
| Secrets | **Physical** - Separate secret per tenant |
| S3 Examples | **Logical** - Tenant-scoped prefixes |
| S3 KB Docs | **Logical** - Tenant-scoped prefixes |
| DynamoDB Tables | **Logical** - tenant_id partition key |
| SQS Queues | **Shared** - Messages tagged with tenant_id |

### Tenant Lifecycle

```
┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
│provisioning│───▶│   active   │───▶│deprovisioning│──▶│  deleted   │
└────────────┘    └────────────┘    └────────────┘    └────────────┘
                        │                   │
                        │                   │ (preserve_data=true)
                        │                   ▼
                        │              ┌──────────┐
                        └─────────────▶│ disabled │
                                       └──────────┘
```

### Adding a New Tenant

1. Call `POST /tenants` with tenant details
2. Onboarding API creates secrets, S3 folders, registry entry
3. Provisioning Worker creates Bedrock agent (5-15 min)
4. Tenant status transitions to "active"
5. Admin populates credentials in Secrets Manager
6. Tenant can start using the platform

## Additional Resources

- [Operations Runbook](../OPERATIONS_RUNBOOK.md)
- [Security Model](../SECURITY.md)
- [API Documentation](../API.md)
- [Deployment Guide](../DEPLOYMENT.md)

## Diagram Maintenance

When updating architecture:

1. Update the relevant `.puml` file
2. Update the Mermaid version in `c4-mermaid.md`
3. Re-render diagrams: `plantuml docs/architecture/*.puml`
4. Commit both source and rendered files
5. Update this documentation if needed

## Contact

For architecture questions: architecture@yourmsp.com