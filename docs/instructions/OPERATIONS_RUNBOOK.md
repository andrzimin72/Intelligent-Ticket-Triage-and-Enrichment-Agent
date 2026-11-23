# MSP AI Platform — Operational Runbook

**Version:** 1.0  
**Last Updated:** 2026-11-20  
**Owner:** Platform Engineering Team  
**Review Cycle:** Quarterly

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [On-Call Procedures](#on-call-procedures)
3. [Break-Glass Emergency Procedures](#break-glass-emergency-procedures)
4. [Alarm Response Playbooks](#alarm-response-playbooks)
5. [Tenant Lifecycle Procedures](#tenant-lifecycle-procedures)
6. [Secret Rotation Procedures](#secret-rotation-procedures)
7. [Data Retention & Compliance](#data-retention--compliance)
8. [Common Troubleshooting](#common-troubleshooting)
9. [Escalation Matrix](#escalation-matrix)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        External Interfaces                       │
├─────────────────────────────────────────────────────────────────┤
│  Microsoft Teams Bot  │  ConnectWise Webhook  │  Onboarding API │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API Gateway + JWT Auth                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Lambda Functions                          │
├─────────────────────────────────────────────────────────────────┤
│  teams_bot  │  identity_tools  │  ticket_tools  │  ...         │
│  orchestrator  │  customer_digest_worker  │  customer_insights  │
│  tenant_onboarding  │  status_history_snapshot  │  webhook_notif│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data & AI Services                          │
├─────────────────────────────────────────────────────────────────┤
│  DynamoDB  │  S3  │  Bedrock Agent  │  Bedrock KB (AOSS)       │
│  Secrets Manager  │  SQS  │  SES  │  CloudWatch                │
└─────────────────────────────────────────────────────────────────┘
```

### Critical Data Flows

| Flow | Components | SLA |
|------|-----------|-----|
| Teams message → Agent response | Teams Bot → Bedrock Agent → Tool Lambdas | < 30s |
| Ticket triage | SQS → Orchestrator → Bedrock | < 60s |
| Password reset | Identity Tools → Reset Lambda → User email | < 5s + user action |
| Tenant onboarding | API → SQS → Provisioning Worker | < 15 min |
| Daily status snapshot | EventBridge → Snapshot Lambda → History table | < 10 min |

---

## On-Call Procedures

### On-Call Rotation

- **Primary:** Platform Engineer (weekday business hours)
- **Secondary:** Senior Engineer (after hours, weekends)
- **Escalation:** Engineering Manager → CTO

### On-Call Tools

- **Alerts:** PagerDuty (critical), Slack (warnings)
- **Dashboards:** CloudWatch Operations Dashboard
- **Logs:** CloudWatch Logs Insights
- **State:** Terraform Cloud / S3 backend

### First 15 Minutes of an Incident

1. **Acknowledge** the alert in PagerDuty
2. **Assess** severity using the matrix below
3. **Communicate** in `#incident-response` Slack channel
4. **Investigate** using the relevant playbook below
5. **Mitigate** using break-glass procedures if needed
6. **Resolve** and document in post-mortem

### Severity Matrix

| Severity | Criteria | Response Time | Example |
|----------|----------|---------------|---------|
| **SEV-1** | Complete service outage, data breach | Immediate | All tenants unable to use bot |
| **SEV-2** | Major feature broken, single tenant | 15 min | Password reset failing for all users |
| **SEV-3** | Degraded performance, minor feature | 1 hour | Agent responses slow (>60s) |
| **SEV-4** | Cosmetic issue, non-blocking | Next business day | Dashboard widget not rendering |

---

## Break-Glass Emergency Procedures

⚠️ **These procedures bypass normal security controls. Use ONLY in genuine emergencies. Every use requires a post-mortem within 24 hours.**

### Procedure BG-1: Force-Reset a User's Password

**When to use:** User is completely locked out, automated reset flow is broken, and user has a critical business need.

**Prerequisites:**
- On-call engineer with admin access to AWS Console
- User's AAD object ID (from IT ticket)
- Approval from Engineering Manager (via Slack/Teams)

**Steps:**

```bash
# 1. Generate a temporary password
TEMP_PASSWORD=$(openssl rand -base64 16)
echo "Temporary password: $TEMP_PASSWORD"

# 2. Get a Graph API token (using the tenant's credentials)
# Note: This requires access to the tenant's Graph secret
aws secretsmanager get-secret-value \
  --secret-id dev/tenants/<TENANT_ID>/graph \
  --query 'SecretString' --output text > /tmp/graph_creds.json

# 3. Call Graph API directly to reset password
# (Use Postman, curl, or a temporary script)
curl -X PATCH "https://graph.microsoft.com/v1.0/users/<USER_AAD_ID>" \
  -H "Authorization: Bearer <GRAPH_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{
    \"passwordProfile\": {
      \"password\": \"$TEMP_PASSWORD\",
      \"forceChangePasswordNextSignIn\": true
    }
  }"

# 4. Communicate the temp password to the user via SECURE channel
#    (phone call, encrypted message — NEVER email or chat)

# 5. Log the break-glass action
aws dynamodb put-item \
  --table-name dev-msp-triage-agent-audit-log \
  --item '{
    "audit_id": {"S": "breakglass-<UUID>"},
    "timestamp": {"S": "<ISO_TIMESTAMP>"},
    "tenant_id": {"S": "<TENANT_ID>"},
    "user_id": {"S": "<ENGINEER_AAD_ID>"},
    "tool_name": {"S": "break_glass_password_reset"},
    "operation_type": {"S": "break_glass"},
    "parameters": {"S": "{\"target_user_id\": \"<USER_AAD_ID>\", \"reason\": \"<TICKET_ID>\"}"},
    "result_summary": {"S": "{\"success\": true}"},
    "ttl": {"N": "<EPOCH_1_YEAR>"}
  }'
```

**Post-incident:**
- [ ] User has changed their password
- [ ] Audit log entry created
- [ ] Post-mortem scheduled within 24 hours
- [ ] Root cause of automated flow failure identified and fixed

### Procedure BG-2: Disable a Compromised Tenant

**When to use:** Suspected tenant compromise, malicious activity detected.

**Steps:**

```bash
# 1. Immediately disable the tenant
aws dynamodb update-item \
  --table-name dev-msp-triage-tenant-registry \
  --key '{"tenant_id": {"S": "<TENANT_ID>"}}' \
  --update-expression "SET enabled = :e, disabled_at = :t, disabled_reason = :r" \
  --expression-attribute-values '{
    ":e": {"N": "0"},
    ":t": {"S": "<ISO_TIMESTAMP>"},
    ":r": {"S": "Security incident - compromised tenant"}
  }'

# 2. Revoke all active sessions (invalidate tokens)
# This requires application-specific logic

# 3. Notify the tenant contact
aws ses send-email \
  --from "security@yourmsp.com" \
  --to "<TENANT_CONTACT_EMAIL>" \
  --subject "URGENT: Your account has been temporarily disabled" \
  --text "..."

# 4. Preserve evidence
aws s3 cp s3://dev-msp-triage-agent-audit-logs/ \
  s3://dev-msp-triage-forensics/incident-<DATE>/ \
  --recursive --exclude "*" --include "*<TENANT_ID>*"

# 5. Rotate all tenant secrets
aws secretsmanager rotate-secret \
  --secret-id dev/tenants/<TENANT_ID>/graph
aws secretsmanager rotate-secret \
  --secret-id dev/tenants/<TENANT_ID>/psa
aws secretsmanager rotate-secret \
  --secret-id dev/tenants/<TENANT_ID>/rmm
```

### Procedure BG-3: Emergency Rollback of Terraform Deployment

**When to use:** Recent deployment caused SEV-1 or SEV-2 incident.

**Steps:**

```bash
# 1. Identify the last known good state
aws s3 ls s3://<TF_STATE_BACKUP_BUCKET>/backups/ | tail -5

# 2. Download the backup state
aws s3 cp s3://<TF_STATE_BACKUP_BUCKET>/backups/backup-<TIMESTAMP>.tfstate ./

# 3. Push the backup state
terraform state push backup-<TIMESTAMP>.tfstate

# 4. Verify the plan shows only the rollback changes
terraform plan -var-file="terraform.tfvars.prod"

# 5. Apply the rollback
terraform apply -var-file="terraform.tfvars.prod"

# 6. Verify service is restored
# Run smoke tests, check dashboards
```

---

## Alarm Response Playbooks

### Alarm: `dev-unhealthy-tenants`

**Meaning:** One or more tenants have health score < 50.

**Investigation:**

```bash
# 1. Get the list of unhealthy tenants
curl -X GET "https://<API_URL>/status/tenants" \
  -H "x-api-key: $API_KEY" | \
  jq '.tenants[] | select(.overall_health == "unhealthy")'

# 2. For each unhealthy tenant, get detailed health
curl -X GET "https://<API_URL>/status/tenants/<TENANT_ID>/health" \
  -H "x-api-key: $API_KEY" | jq

# 3. Check CloudWatch logs for errors
aws logs tail /aws/lambda/dev-msp-triage-tenant-onboarding \
  --since 1h | grep -i error
```

**Common causes:**
- Tenant secrets not populated → Contact tenant to populate
- Bedrock agent in FAILED state → Check Bedrock console, may need re-provisioning
- Missing action groups → Re-run provisioning worker

**Resolution time:** 15-60 minutes depending on cause

### Alarm: `dev-customer-insights-dlq-not-empty`

**Meaning:** Customer insights reports are failing to generate.

**Investigation:**

```bash
# 1. Check DLQ messages
aws sqs receive-message \
  --queue-url <DLQ_URL> \
  --max-number-of-messages 10

# 2. Check worker logs
aws logs tail /aws/lambda/dev-msp-triage-customer-insights-worker \
  --since 1h | grep -E "ERROR|Exception"

# 3. Check Bedrock quotas
aws service-quotas get-service-quota \
  --service-code bedrock \
  --quota-code L-7PD75B6M4T  # Invoke model TPM
```

**Common causes:**
- Bedrock throttling → Request quota increase
- Sonnet model unavailable → Check AWS Health Dashboard
- Tenant data missing → Investigate specific tenant

### Alarm: `dev-reset-password-token-abuse`

**Meaning:** Password reset tokens are being brute-forced.

**Investigation:**

```bash
# 1. Get abuse details from audit log
aws dynamodb scan \
  --table-name dev-msp-triage-agent-audit-log \
  --filter-expression "tool_name = :t AND operation_type = :o" \
  --expression-attribute-values '{
    ":t": {"S": "reset_password"},
    ":o": {"S": "token_abuse"}
  }'

# 2. Identify source IPs
# Check CloudWatch logs for the reset_password Lambda
aws logs tail /aws/lambda/dev-msp-triage-reset-password \
  --since 1h | grep -i "invalidated"
```

**Response:**
- If isolated to one IP: Block at WAF/CloudFront level
- If widespread: Temporarily disable password reset, investigate
- Notify security team if pattern suggests targeted attack

### Alarm: `dev-status-api-throttled`

**Meaning:** Status API is being rate-limited, possibly due to abuse or misconfigured client.

**Investigation:**

```bash
# 1. Check API Gateway access logs
aws logs tail /aws/apigateway/dev-msp-triage-tenant-onboarding \
  --since 1h | grep "429"

# 2. Identify source IPs
# Parse access logs for repeated 429s from same IP

# 3. Check if it's a legitimate high-traffic scenario
# (e.g., dashboard polling too frequently)
```

**Response:**
- Legitimate high traffic → Increase rate limits temporarily
- Abuse → Block IP at WAF level
- Misconfigured client → Contact client owner

---

## Tenant Lifecycle Procedures

### Procedure TL-1: Onboard a New Tenant

**Prerequisites:**
- Tenant's Entra tenant ID
- Tenant's admin group ID
- Tenant's contact email
- Branding information (optional)

**Steps:**

```bash
# 1. Call the onboarding API
curl -X POST "https://<API_URL>/tenants" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "<TENANT_ID>",
    "display_name": "<DISPLAY_NAME>",
    "entra_tenant_id": "<ENTRA_TENANT_ID>",
    "admin_group_id": "<ADMIN_GROUP_ID>",
    "contact_email": "<CONTACT_EMAIL>",
    "branding": {
      "company_name": "<COMPANY_NAME>",
      "primary_color": "#1e88e5"
    }
  }'

# 2. Monitor provisioning status
watch -n 30 'curl -s "https://<API_URL>/tenants/<TENANT_ID>" \
  -H "x-api-key: $API_KEY" | jq .status'

# 3. Once status is "active", populate secrets
aws secretsmanager put-secret-value \
  --secret-id dev/tenants/<TENANT_ID>/graph \
  --secret-string '{
    "CLIENT_ID": "<CLIENT_ID>",
    "CLIENT_SECRET": "<CLIENT_SECRET>",
    "TENANT_ID": "<ENTRA_TENANT_ID>"
  }'

# Repeat for psa and rmm secrets

# 4. Verify tenant health
curl -X GET "https://<API_URL>/status/tenants/<TENANT_ID>/health" \
  -H "x-api-key: $API_KEY" | jq

# 5. Send welcome email to tenant contact
# (Use your email client or SES)
```

**Verification checklist:**
- [ ] Tenant status is "active"
- [ ] Health score is 100
- [ ] All secrets are populated
- [ ] Bedrock agent is PREPARED
- [ ] Test conversation in Teams works

### Procedure TL-2: Deprovision a Tenant

**Prerequisites:**
- Tenant ID
- Confirmation from account manager
- Decision on data retention (preserve or delete)

**Steps:**

```bash
# 1. Verify tenant exists and is active
curl -X GET "https://<API_URL>/tenants/<TENANT_ID>" \
  -H "x-api-key: $API_KEY" | jq

# 2. Initiate deprovisioning (with data preservation)
curl -X DELETE "https://<API_URL>/tenants/<TENANT_ID>?confirm=true&preserve_data=true" \
  -H "x-api-key: $API_KEY"

# OR for hard deletion (GDPR/CCPA compliance):
curl -X DELETE "https://<API_URL>/tenants/<TENANT_ID>?confirm=true&preserve_data=false" \
  -H "x-api-key: $API_KEY"

# 3. Monitor deprovisioning
watch -n 30 'curl -s "https://<API_URL>/tenants/<TENANT_ID>" \
  -H "x-api-key: $API_KEY" | jq .status'

# 4. Verify completion (status should be "deleted")
# 5. Verify resources are cleaned up
aws bedrock list-agents | jq '.agentSummaries[] | select(.agentName | contains("<TENANT_ID>"))'
# Should return empty

# 6. For hard deletion, verify data is purged
aws dynamodb scan \
  --table-name dev-msp-triage-agent-audit-log \
  --filter-expression "tenant_id = :tid" \
  --expression-attribute-values '{":tid": {"S": "<TENANT_ID>"}}' \
  --select COUNT
# Should return Count: 0
```

### Procedure TL-3: Migrate Terraform Tenant to API Management

See `scripts/migrate_tenants_to_api.py` documentation.

---

## Secret Rotation Procedures

### Procedure SR-1: Rotate Tenant Graph Credentials

**Frequency:** Every 90 days (or immediately if compromised)

**Steps:**

```bash
# 1. Generate new credentials in Entra ID portal
#    (App registrations → <App> → Certificates & secrets → New client secret)

# 2. Update the secret in AWS Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id dev/tenants/<TENANT_ID>/graph \
  --secret-string '{
    "CLIENT_ID": "<EXISTING_CLIENT_ID>",
    "CLIENT_SECRET": "<NEW_CLIENT_SECRET>",
    "TENANT_ID": "<EXISTING_TENANT_ID>"
  }'

# 3. Verify the new credentials work
# Trigger a test operation that uses Graph API
curl -X POST "https://<API_URL>/tenants/<TENANT_ID>/test-graph" \
  -H "x-api-key: $API_KEY"

# 4. Monitor for errors
aws logs tail /aws/lambda/dev-msp-triage-identity-tools \
  --since 5m | grep -i "graph"
```

### Procedure SR-2: Rotate Webhook URLs Secret

**Steps:**

```bash
# 1. Get current webhook URLs
aws secretsmanager get-secret-value \
  --secret-id dev-msp-triage-webhook-urls \
  --query 'SecretString' --output text | jq

# 2. Update with new URLs
aws secretsmanager put-secret-value \
  --secret-id dev-msp-triage-webhook-urls \
  --secret-string '{
    "slack-ops": "https://hooks.slack.com/services/NEW/URL",
    "pagerduty-critical": "https://events.pagerduty.com/v2/NEW/KEY"
  }'

# 3. Test webhooks
# Trigger a test notification via the webhook notifier
aws lambda invoke \
  --function-name dev-msp-triage-webhook-notifier \
  --payload '{"test": true}' \
  response.json
```

---

## Data Retention & Compliance

### Retention Schedule

| Data Type | Retention | Cleanup Method |
|-----------|-----------|----------------|
| Audit logs | 365 days | DynamoDB TTL |
| Agent feedback | 365 days | DynamoDB TTL |
| Status history | 90 days | DynamoDB TTL |
| Status cache | 2 minutes | DynamoDB TTL |
| Webhook cooldowns | 2 hours | DynamoDB TTL |
| Conversation state | 1 hour | DynamoDB TTL |
| Password reset tokens | 1 hour | DynamoDB TTL |
| S3 agent examples | Until tenant deletion | Manual/S3 lifecycle |
| S3 KB documents | Until tenant deletion | Manual/S3 lifecycle |
| CloudWatch logs | 90 days | Log group retention |

### GDPR/CCPA Data Deletion Request

**When a customer requests complete data deletion:**

1. **Initiate hard deprovisioning** (see TL-2 with `preserve_data=false`)
2. **Verify all DynamoDB tables** are purged of tenant data
3. **Verify S3 buckets** are purged of tenant objects
4. **Verify CloudWatch logs** — these cannot be selectively deleted; document the retention period
5. **Verify Secrets Manager** — secrets are marked for deletion (7-day recovery window)
6. **Generate deletion certificate** with timestamps and evidence
7. **Send confirmation** to customer within 30 days (GDPR requirement)

### Backup & Recovery

| Component | Backup Method | RPO | RTO |
|-----------|---------------|-----|-----|
| DynamoDB tables | PITR (prod), on-demand backups | 1 hour | 1 hour |
| S3 buckets | Versioning + cross-region replication | 15 min | 1 hour |
| Terraform state | S3 versioning + manual backups | 1 deployment | 30 min |
| Secrets Manager | Automatic (7-day recovery window) | Immediate | 5 min |

---

## Common Troubleshooting

### Issue: Agent responses are slow (>30s)

**Diagnosis:**

```bash
# 1. Check Lambda duration
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=dev-msp-triage-teams-bot \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average p99

# 2. Check Bedrock latency
aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock \
  --metric-name InvocationLatency \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average p99

# 3. Check for throttling
aws logs tail /aws/lambda/dev-msp-triage-teams-bot \
  --since 1h | grep -i "throttl"
```

**Common causes:**
- Cold starts → Increase provisioned concurrency
- Bedrock throttling → Request quota increase
- Large knowledge base queries → Optimize chunking
- Network latency → Check VPC configuration

### Issue: Tenant can't receive password reset emails

**Diagnosis:**

```bash
# 1. Check SES sending status
aws ses get-send-statistics

# 2. Check if sender is verified
aws ses get-identity-verification-attributes \
  --identities "password-reset@yourmsp.com"

# 3. Check SES sandbox status
aws ses get-account-sending-enabled

# 4. Check recent bounces
aws ses list-identities --identity-type MailFrom
```

**Common causes:**
- SES in sandbox mode → Request production access
- Sender not verified → Verify the email address
- Domain not verified → Add DNS records
- Bounce rate too high → Clean up email list

### Issue: Webhook notifications not being delivered

**Diagnosis:**

```bash
# 1. Check webhook notifier logs
aws logs tail /aws/lambda/dev-msp-triage-webhook-notifier \
  --since 1h | grep -E "ERROR|Webhook"

# 2. Check webhook URLs secret
aws secretsmanager get-secret-value \
  --secret-id dev-msp-triage-webhook-urls \
  --query 'SecretString' --output text | jq

# 3. Check cooldowns
aws dynamodb scan \
  --table-name dev-msp-triage-webhook-cooldowns \
  --output table
```

**Common causes:**
- Webhook URL changed → Update secret
- Cooldown active → Wait or manually clear cooldown
- Network/firewall blocking → Check security groups
- Invalid payload format → Check platform-specific formatter

---

## Escalation Matrix

| Issue Type | Primary | Secondary | External |
|------------|---------|-----------|----------|
| AWS service outage | On-call engineer | Engineering Manager | AWS Support (Enterprise) |
| Security incident | Security Engineer | CISO | Legal, Law Enforcement |
| Data breach | CISO | Legal | Forensics firm, Regulators |
| Tenant data loss | Platform Engineer | Engineering Manager | AWS Support |
| Billing anomaly | FinOps | Engineering Manager | AWS Support |
| Compliance question | Legal | CISO | External auditor |

### AWS Support Contacts

- **Enterprise Support:** Case creation via AWS Console
- **Severity 1 (production down):** Phone: +1-206-266-4064
- **Security issues:** aws-security@amazon.com

---

## Appendix A: Useful CLI Commands

```bash
# List all tenants with health scores
curl -s "https://<API_URL>/status/tenants" -H "x-api-key: $API_KEY" | \
  jq -r '.tenants[] | "\(.tenant_id)\t\(.health_score)\t\(.overall_health)"'

# Get recent audit events for a tenant
aws dynamodb query \
  --table-name dev-msp-triage-agent-audit-log \
  --index-name tenant-index \
  --key-condition-expression "tenant_id = :tid" \
  --expression-attribute-values '{":tid": {"S": "<TENANT_ID>"}}' \
  --scan-index-forward false \
  --limit 10

# Check SQS queue depths
for queue in tickets customer-digest customer-insights tenant-provisioning; do
  aws sqs get-queue-attributes \
    --queue-url "https://sqs.<REGION>.amazonaws.com/<ACCOUNT>/dev-msp-triage-$queue" \
    --attribute-names ApproximateNumberOfMessages
done

# Tail all critical Lambda logs simultaneously
aws logs tail \
  /aws/lambda/dev-msp-triage-teams-bot \
  /aws/lambda/dev-msp-triage-identity-tools \
  /aws/lambda/dev-msp-triage-tenant-onboarding \
  --since 5m --follow
```

## Appendix B: Contact List

| Role | Name | Email | Phone |
|------|------|-------|-------|
| Platform Engineering Lead | TBD | platform-lead@yourmsp.com | TBD |
| Security Engineer | TBD | security@yourmsp.com | TBD |
| Engineering Manager | TBD | eng-manager@yourmsp.com | TBD |
| AWS TAM | TBD | tam@amazon.com | TBD |
| Microsoft Support | - | - | +1-800-MICROSOFT |

---

**Document Control:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-11-20 | Platform Team | Initial version |