# MSP AI Platform — Risk Register

**Document Owner:** Platform Engineering Team  
**Version:** 1.0  
**Last Updated:** 2026-11-22  
**Review Frequency:** Monthly (or after major incidents/changes)  
**Next Review Date:** 2026-12-22

---

## Risk Scoring Methodology

### Likelihood Scale (1-5)
| Score | Label | Description |
|-------|-------|-------------|
| 1 | Rare | May occur only in exceptional circumstances (<1% per year) |
| 2 | Unlikely | Could occur but not expected (1-5% per year) |
| 3 | Possible | Might occur at some time (5-50% per year) |
| 4 | Likely | Will probably occur in most circumstances (50-90% per year) |
| 5 | Almost Certain | Expected to occur in most circumstances (>90% per year) |

### Impact Scale (1-5)
| Score | Label | Description |
|-------|-------|-------------|
| 1 | Negligible | Minor inconvenience, no customer impact |
| 2 | Minor | Limited impact on a small number of users |
| 3 | Moderate | Noticeable impact on multiple tenants, requires manual intervention |
| 4 | Major | Significant service degradation, customer-facing outage |
| 5 | Catastrophic | Complete service outage, data breach, or regulatory violation |

### Risk Level Matrix
| Likelihood \ Impact | 1 (Negligible) | 2 (Minor) | 3 (Moderate) | 4 (Major) | 5 (Catastrophic) |
|---------------------|----------------|-----------|--------------|-----------|------------------|
| **5 (Almost Certain)** | Medium (5) | High (10) | High (15) | Critical (20) | Critical (25) |
| **4 (Likely)** | Low (4) | Medium (8) | High (12) | High (16) | Critical (20) |
| **3 (Possible)** | Low (3) | Medium (6) | Medium (9) | High (12) | High (15) |
| **2 (Unlikely)** | Low (2) | Low (4) | Medium (6) | Medium (8) | High (10) |
| **1 (Rare)** | Low (1) | Low (2) | Low (3) | Medium (5) | Medium (5) |

### Risk Levels
- **Low (1-4):** Accept and monitor
- **Medium (5-9):** Mitigate with standard controls
- **High (10-15):** Requires active mitigation plan and management attention
- **Critical (16-25):** Requires immediate executive attention and dedicated resources

---

## Risk Categories

### SEC — Security Risks
### OPS — Operational Risks
### COM — Compliance Risks
### TEC — Technical Risks
### FIN — Financial Risks
### BUS — Business Risks
### TPR — Third-Party / Vendor Risks

---

## Risk Register

### SEC-001: Cross-Tenant Data Leakage via LLM Context

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-001 |
| **Category** | Security |
| **Description** | The LLM might inadvertently include data from Tenant A in responses to Tenant B due to prompt injection, context confusion, or a bug in tenant isolation logic. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 10 (High) |
| **Current Controls** | Per-tenant Bedrock Agents (Phase 4), tenant_id in session attributes, tenant-scoped S3 paths, tenant-scoped secrets |
| **Mitigation Actions** | 1. Quarterly red-team testing of tenant isolation<br>2. Automated tests verifying tenant_id propagation<br>3. Audit log monitoring for cross-tenant access patterns<br>4. Customer-facing SLA with data isolation guarantees |
| **Risk Owner** | CISO / Security Engineer |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |
| **Next Review** | 2027-02-22 |

---

### SEC-002: JWT Token Compromise in Teams Bot

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-002 |
| **Category** | Security |
| **Description** | An attacker could forge or replay Bot Framework JWT tokens to impersonate legitimate Teams requests, gaining unauthorized access to tenant operations. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | Bot Framework JWT validation via `jwt_validator.py`, BOT_APP_ID verification, short token expiry |
| **Mitigation Actions** | 1. Regular rotation of BOT_APP_ID credentials<br>2. Monitoring for invalid JWT attempts in CloudWatch<br>3. Rate limiting on bot endpoint<br>4. Annual security audit of JWT validation logic |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### SEC-003: Password Reset Token Brute Force

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-003 |
| **Category** | Security |
| **Description** | An attacker could attempt to guess password reset tokens, potentially gaining unauthorized password reset capability. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | 256-bit tokens (unguessable), 15-minute TTL, 5-attempt limit per token, token invalidation on excess attempts, CloudWatch abuse metrics |
| **Mitigation Actions** | 1. WAF rate limiting on reset endpoint<br>2. IP-based blocking after repeated failures<br>3. Security alerts on abuse metric spikes<br>4. Consider adding CAPTCHA after 3 failed attempts |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### SEC-004: Prompt Injection via Teams Messages

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-004 |
| **Category** | Security |
| **Description** | A malicious user could craft Teams messages containing prompt injection attacks to manipulate the Bedrock Agent into performing unauthorized actions or revealing sensitive information. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 4 (Major) |
| **Risk Score** | 12 (High) |
| **Current Controls** | Bedrock Guardrails, server-side identity extraction (never from LLM), two-phase approval for write operations, tenant_id from trusted Teams activity |
| **Mitigation Actions** | 1. Regular prompt injection testing in CI/CD pipeline<br>2. Update guardrail configurations quarterly<br>3. Monitor for unusual agent behavior patterns<br>4. Maintain "break-glass" procedures for compromised agent scenarios |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### SEC-005: Secrets Manager Credential Exposure

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-005 |
| **Category** | Security |
| **Description** | Tenant API credentials (ConnectWise, NinjaOne, Graph) stored in Secrets Manager could be exposed through Lambda logs, error messages, or IAM misconfiguration. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 10 (High) |
| **Current Controls** | Secrets never logged (redaction in audit logs), least-privilege IAM, per-tenant secret paths, 7-day recovery window |
| **Mitigation Actions** | 1. Automated secret scanning in CI/CD<br>2. Quarterly IAM policy reviews<br>3. CloudTrail monitoring for secret access anomalies<br>4. Automatic rotation schedule for tenant credentials |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### SEC-006: Bedrock Agent Hallucination Leading to Wrong Actions

| Field | Value |
|-------|-------|
| **Risk ID** | SEC-006 |
| **Category** | Security |
| **Description** | The Bedrock Agent could hallucinate and instruct a user to perform an incorrect or harmful action, or invoke tools with wrong parameters. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | Two-phase approval for all write operations, server-side parameter validation, tenant-scoped tool schemas, feedback loop for corrections |
| **Mitigation Actions** | 1. Continuous improvement via feedback loop<br>2. Few-shot examples for edge cases<br>3. User-facing "Are you sure?" confirmations<br>4. Regular review of agent corrections in audit logs |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-001: AOSS Collection Outage (Knowledge Base Unavailable)

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-001 |
| **Category** | Operational |
| **Description** | The OpenSearch Serverless collection backing the Knowledge Base could become unavailable, causing RAG queries to fail for all tenants. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 6 (Medium) |
| **Current Controls** | AOSS is a managed service with AWS SLA, agent continues to work with tools even without KB |
| **Mitigation Actions** | 1. CloudWatch alarm on AOSS availability<br>2. Graceful degradation: agent informs user KB is temporarily unavailable<br>3. Document KB outage in operational runbook<br>4. Consider multi-AZ deployment if critical |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-002: DynamoDB Throttling Under Load

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-002 |
| **Category** | Operational |
| **Description** | High-volume operations (e.g., analytics aggregation, status snapshots) could exceed DynamoDB provisioned throughput, causing throttling and degraded performance. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | PAY_PER_REQUEST billing mode (auto-scaling), exponential backoff in retry logic, CloudWatch alarms on throttling metrics |
| **Mitigation Actions** | 1. Monitor ConsumedRead/WriteCapacityUnits metrics<br>2. Implement request batching where possible<br>3. Schedule heavy operations during off-peak hours<br>4. Consider reserved capacity for predictable workloads |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-003: Lambda Cold Start Latency

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-003 |
| **Category** | Operational |
| **Description** | Infrequently-invoked Lambda functions (especially those with large deployment packages) could experience cold start latency >5 seconds, degrading user experience. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 2 (Minor) |
| **Risk Score** | 6 (Medium) |
| **Current Controls** | ARM64 architecture (faster cold starts), minimal package sizes, X-Ray tracing for latency monitoring |
| **Mitigation Actions** | 1. Consider Provisioned Concurrency for critical paths (Teams bot)<br>2. Optimize package sizes by removing unused dependencies<br>3. Monitor P99 latency in CloudWatch<br>4. Implement client-side retry with exponential backoff |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-004: SQS Dead Letter Queue Overflow

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-004 |
| **Category** | Operational |
| **Description** | Failed messages could accumulate in DLQs without detection, leading to lost tenant provisioning jobs, digest jobs, or webhook deliveries. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | DLQs configured for all critical queues, 14-day message retention, CloudWatch alarms on DLQ depth |
| **Mitigation Actions** | 1. CloudWatch alarm when DLQ depth > 0<br>2. Automated DLQ monitoring dashboard<br>3. Operational runbook for DLQ triage<br>4. Weekly DLQ review in operations meeting |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-005: Bedrock API Throttling / Quota Exhaustion

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-005 |
| **Category** | Operational |
| **Description** | AWS Bedrock could throttle requests or hit account-level quotas during peak usage, causing agent responses to fail. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 4 (Major) |
| **Risk Score** | 12 (High) |
| **Current Controls** | Retry logic with exponential backoff, fallback model configuration, request rate limiting per tenant |
| **Mitigation Actions** | 1. Request quota increases proactively<br>2. Implement request queuing for burst traffic<br>3. Monitor Bedrock throttling metrics<br>4. Document fallback procedures in runbook |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### OPS-006: Graph API Rate Limiting

| Field | Value |
|-------|-------|
| **Risk ID** | OPS-006 |
| **Category** | Operational |
| **Description** | Microsoft Graph API could rate-limit requests from identity tools, causing user lookups or operations to fail. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | Token caching (5-minute TTL), retry logic, request batching where possible |
| **Mitigation Actions** | 1. Monitor Graph API throttling headers<br>2. Implement adaptive rate limiting<br>3. Cache frequently-accessed user data<br>4. Request higher Graph API limits from Microsoft if needed |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### COM-001: Incomplete Data Deletion on Tenant Offboarding

| Field | Value |
|-------|-------|
| **Risk ID** | COM-001 |
| **Category** | Compliance |
| **Description** | When a tenant is deprovisioned, some data might remain in DynamoDB tables, S3 buckets, or CloudWatch logs, violating GDPR/CCPA right-to-deletion requirements. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 10 (High) |
| **Current Controls** | Deprovisioning API with `preserve_data=false` option, DynamoDB TTLs, S3 lifecycle policies, CloudWatch log retention |
| **Mitigation Actions** | 1. Automated post-deprovision verification scan<br>2. Deletion certificate generation<br>3. Legal review of retention periods<br>4. Regular compliance audits |
| **Risk Owner** | CISO / Legal |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### COM-002: PII Exposure in Logs

| Field | Value |
|-------|-------|
| **Risk ID** | COM-002 |
| **Category** | Compliance |
| **Description** | Personally identifiable information (user names, emails, passwords) could be inadvertently logged to CloudWatch, creating a compliance and privacy risk. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | Secret redaction in audit logs, structured logging, no password logging in reset flow |
| **Mitigation Actions** | 1. Automated PII scanning in log pipelines<br>2. Code review checklist for logging statements<br>3. CloudWatch metric filters for PII patterns<br>4. Regular log audits |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### COM-003: Audit Log Gaps

| Field | Value |
|-------|-------|
| **Risk ID** | COM-003 |
| **Category** | Compliance |
| **Description** | Some operations might not be properly logged, creating gaps in the audit trail required for compliance and security investigations. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 6 (Medium) |
| **Current Controls** | Centralized audit logging via `agent_security.write_audit()`, tenant-scoped audit entries, 365-day retention |
| **Mitigation Actions** | 1. Code review checklist requiring audit logging for all write operations<br>2. Automated tests verifying audit log creation<br>3. Quarterly audit log completeness review<br>4. CloudWatch alarm on audit log write failures |
| **Risk Owner** | Security Engineer |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### COM-004: Cross-Border Data Transfer Issues

| Field | Value |
|-------|-------|
| **Risk ID** | COM-004 |
| **Category** | Compliance |
| **Description** | Tenant data might be processed in AWS regions that don't comply with data residency requirements for certain customers (e.g., EU data in US region). |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | Single-region deployment (us-east-1), documented data flow in architecture |
| **Mitigation Actions** | 1. Document data residency requirements per tenant<br>2. Consider multi-region deployment for EU customers<br>3. Update tenant onboarding to capture residency requirements<br>4. Legal review of data processing agreements |
| **Risk Owner** | CISO / Legal |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### COM-005: Retention Policy Violations

| Field | Value |
|-------|-------|
| **Risk ID** | COM-005 |
| **Category** | Compliance |
| **Description** | Data might be retained longer than required by policy (e.g., audit logs beyond 7 years) or deleted sooner than required, violating regulatory requirements. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 6 (Medium) |
| **Current Controls** | DynamoDB TTLs configured per table, CloudWatch log retention policies, S3 lifecycle policies |
| **Mitigation Actions** | 1. Annual retention policy review<br>2. Automated TTL verification tests<br>3. Document retention schedule per data type<br>4. Legal sign-off on retention periods |
| **Risk Owner** | CISO / Legal |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### TEC-001: Terraform State Corruption

| Field | Value |
|-------|-------|
| **Risk ID** | TEC-001 |
| **Category** | Technical |
| **Description** | The Terraform state file could become corrupted or lost, making it impossible to manage infrastructure or causing accidental resource deletion. |
| **Likelihood** | 1 (Rare) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 5 (Medium) |
| **Current Controls** | S3 backend with versioning, state locking via DynamoDB, regular state backups |
| **Mitigation Actions** | 1. Daily automated state backups to separate S3 bucket<br>2. Document state recovery procedures in runbook<br>3. Restrict state file access to senior engineers<br>4. Test state recovery quarterly |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### TEC-002: Python 3.13 Compatibility Issues

| Field | Value |
|-------|-------|
| **Risk ID** | TEC-002 |
| **Category** | Technical |
| **Description** | Python 3.13 is bleeding edge; some dependencies might not have wheels or might have breaking changes, causing Lambda deployment failures. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | Pinned dependency versions in requirements.txt, Docker-based layer building for native dependencies |
| **Mitigation Actions** | 1. Test all dependencies in CI before deployment<br>2. Maintain fallback to Python 3.12 if needed<br>3. Monitor Python release notes for breaking changes<br>4. Use `--only-binary :all:` in pip installs |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### TEC-003: Bedrock Model Deprecation

| Field | Value |
|-------|-------|
| **Risk ID** | TEC-003 |
| **Category** | Technical |
| **Description** | AWS could deprecate the Bedrock models we're using (Sonnet 5.5, Haiku 4.5), requiring migration to new models with potential behavior changes. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | Model IDs configurable via environment variables, fallback model configuration |
| **Mitigation Actions** | 1. Monitor AWS Bedrock deprecation announcements<br>2. Maintain model migration playbook<br>3. Test new models in staging before production rollout<br>4. Document model-specific behaviors |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### TEC-004: AWS Vendor Lock-in

| Field | Value |
|-------|-------|
| **Risk ID** | TEC-004 |
| **Category** | Technical |
| **Description** | Heavy reliance on AWS-specific services (Bedrock, AOSS, DynamoDB) could make migration to other cloud providers prohibitively expensive or technically difficult. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 6 (Medium) |
| **Current Controls** | Terraform for infrastructure-as-code, Python for application logic (portable) |
| **Mitigation Actions** | 1. Document AWS-specific dependencies<br>2. Abstract cloud-specific logic where possible<br>3. Maintain exit strategy documentation<br>4. Regular cost-benefit analysis of multi-cloud |
| **Risk Owner** | CTO |
| **Status** | Accepted — Strategic decision |
| **Last Reviewed** | 2026-11-22 |

---

### TEC-005: Technical Debt from Rapid Development

| Field | Value |
|-------|-------|
| **Risk ID** | TEC-005 |
| **Category** | Technical |
| **Description** | Rapid development across multiple phases could accumulate technical debt (duplicated code, inconsistent patterns, insufficient tests), making maintenance harder. |
| **Likelihood** | 4 (Likely) |
| **Impact** | 2 (Minor) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | CI/CD pipeline with linting and tests, code review process, shared modules (tenant_resolver) |
| **Mitigation Actions** | 1. Quarterly technical debt sprints<br>2. Code coverage targets in CI/CD<br>3. Architecture decision records (ADRs)<br>4. Refactoring as part of feature work |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Mitigating |
| **Last Reviewed** | 2026-11-22 |

---

### FIN-001: Unexpected AWS Cost Spikes

| Field | Value |
|-------|-------|
| **Risk ID** | FIN-001 |
| **Category** | Financial |
| **Description** | Unexpected usage patterns (e.g., runaway LLM calls, excessive DynamoDB reads) could cause AWS bills to spike dramatically. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | AWS Budgets with alerts, per-tenant rate limiting, cost optimization via Haiku routing |
| **Mitigation Actions** | 1. Set up AWS Budgets with 50%, 80%, 100% alerts<br>2. Daily cost monitoring dashboard<br>3. Implement hard spending caps where possible<br>4. Monthly cost review with finance |
| **Risk Owner** | FinOps / Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### FIN-002: AOSS Minimum Cost ($700/month)

| Field | Value |
|-------|-------|
| **Risk ID** | FIN-002 |
| **Category** | Financial |
| **Description** | OpenSearch Serverless has a ~$700/month minimum cost regardless of usage, which could be unjustifiable for small deployments or low KB usage. |
| **Likelihood** | 4 (Likely) |
| **Impact** | 2 (Minor) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | KB feature is optional (`enable_knowledge_base = false` by default), Aurora pgvector alternative documented |
| **Mitigation Actions** | 1. Monitor KB usage vs. cost<br>2. Consider Aurora pgvector for low-usage scenarios<br>3. Share AOSS cost across multiple tenants<br>4. Regular cost-benefit review |
| **Risk Owner** | FinOps |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### FIN-003: Bedrock Token Costs Scaling with Usage

| Field | Value |
|-------|-------|
| **Risk ID** | FIN-003 |
| **Category** | Financial |
| **Description** | As tenant count and usage grow, Bedrock token costs could scale non-linearly, impacting margins. |
| **Likelihood** | 4 (Likely) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 12 (High) |
| **Current Controls** | Model routing (Haiku for simple, Sonnet for complex), token limits per request, cost optimization via caching |
| **Mitigation Actions** | 1. Monitor cost-per-tenant metrics<br>2. Optimize prompt sizes<br>3. Implement response caching<br>4. Negotiate enterprise pricing with AWS at scale<br>5. Pass through costs in tenant pricing |
| **Risk Owner** | FinOps / CTO |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### BUS-001: Single Point of Failure in Engineering Team

| Field | Value |
|-------|-------|
| **Risk ID** | BUS-001 |
| **Category** | Business |
| **Description** | Critical platform knowledge concentrated in one or two engineers could create a bus factor risk, making the platform vulnerable if key personnel leave. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 4 (Major) |
| **Risk Score** | 12 (High) |
| **Current Controls** | Comprehensive documentation (runbook, architecture docs), CI/CD pipeline, code in version control |
| **Mitigation Actions** | 1. Cross-training program for team members<br>2. Pair programming on critical components<br>3. Regular knowledge sharing sessions<br>4. External documentation reviews |
| **Risk Owner** | Engineering Manager |
| **Status** | Active — Mitigating |
| **Last Reviewed** | 2026-11-22 |

---

### BUS-002: Tenant Onboarding Complexity Limiting Growth

| Field | Value |
|-------|-------|
| **Risk ID** | BUS-002 |
| **Category** | Business |
| **Description** | Despite the onboarding API, the process of setting up a new tenant (credentials, KB docs, testing) could remain complex, limiting sales velocity. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | Automated onboarding API, hybrid mode for existing tenants, self-service portal |
| **Mitigation Actions** | 1. Create tenant onboarding wizard in portal<br>2. Document step-by-step onboarding guide<br>3. Automate credential setup where possible<br>4. Track onboarding time-to-value metric |
| **Risk Owner** | Product Manager |
| **Status** | Active — Mitigating |
| **Last Reviewed** | 2026-11-22 |

---

### BUS-003: Reputation Damage from Security Incident

| Field | Value |
|-------|-------|
| **Risk ID** | BUS-003 |
| **Category** | Business |
| **Description** | A security incident (data breach, tenant data leakage) could severely damage the platform's reputation and lead to customer churn. |
| **Likelihood** | 1 (Rare) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 5 (Medium) |
| **Current Controls** | Comprehensive security controls, audit trails, break-glass procedures, operational runbook |
| **Mitigation Actions** | 1. Incident response plan documented and tested<br>2. Cyber insurance coverage<br>3. PR/communications plan for incidents<br>4. Regular security audits and penetration testing<br>5. Transparent security reporting to customers |
| **Risk Owner** | CISO / CEO |
| **Status** | Active — Controls in place |
| **Last Reviewed** | 2026-11-22 |

---

### TPR-001: AWS Service Outage

| Field | Value |
|-------|-------|
| **Risk ID** | TPR-001 |
| **Category** | Third-Party |
| **Description** | A major AWS outage (us-east-1 region or specific services like Bedrock, DynamoDB) could take the entire platform offline. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 5 (Catastrophic) |
| **Risk Score** | 10 (High) |
| **Current Controls** | AWS SLA, multi-AZ deployment (inherent in managed services) |
| **Mitigation Actions** | 1. Monitor AWS Health Dashboard<br>2. Document multi-region disaster recovery plan<br>3. Regular DR testing (annual)<br>4. Customer communication plan for outages<br>5. Consider multi-region deployment for critical customers |
| **Risk Owner** | CTO |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### TPR-002: Microsoft API Changes or Deprecation

| Field | Value |
|-------|-------|
| **Risk ID** | TPR-002 |
| **Category** | Third-Party |
| **Description** | Microsoft could change or deprecate Graph API endpoints, Bot Framework protocols, or Entra ID features, breaking integrations. |
| **Likelihood** | 2 (Unlikely) |
| **Impact** | 4 (Major) |
| **Risk Score** | 8 (Medium) |
| **Current Controls** | Abstraction layers for Microsoft APIs, versioned API usage |
| **Mitigation Actions** | 1. Subscribe to Microsoft developer announcements<br>2. Maintain abstraction layers for easy updates<br>3. Test against Microsoft beta APIs in staging<br>4. Document Microsoft API dependencies |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

### TPR-003: ConnectWise / NinjaOne API Downtime

| Field | Value |
|-------|-------|
| **Risk ID** | TPR-003 |
| **Category** | Third-Party |
| **Description** | ConnectWise or NinjaOne API outages could prevent ticket creation, device lookups, or other PSA/RMM operations. |
| **Likelihood** | 3 (Possible) |
| **Impact** | 3 (Moderate) |
| **Risk Score** | 9 (Medium) |
| **Current Controls** | Retry logic, graceful error messages to users, tenant-specific credentials |
| **Mitigation Actions** | 1. Monitor PSA/RMM API status pages<br>2. Implement request caching for read operations<br>3. Queue failed operations for retry<br>4. Document fallback procedures in runbook |
| **Risk Owner** | Platform Engineering Lead |
| **Status** | Active — Monitoring |
| **Last Reviewed** | 2026-11-22 |

---

## Risk Summary Dashboard

### By Risk Level
| Level | Count | Percentage |
|-------|-------|------------|
| Critical (16-25) | 0 | 0% |
| High (10-15) | 5 | 17% |
| Medium (5-9) | 19 | 63% |
| Low (1-4) | 6 | 20% |
| **Total** | **30** | **100%** |

### By Category
| Category | Count |
|----------|-------|
| Security (SEC) | 6 |
| Operational (OPS) | 6 |
| Compliance (COM) | 5 |
| Technical (TEC) | 5 |
| Financial (FIN) | 3 |
| Business (BUS) | 3 |
| Third-Party (TPR) | 3 |

### Top 5 Risks (by score)
1. **SEC-001** — Cross-tenant data leakage (Score: 10, High)
2. **SEC-005** — Secrets Manager credential exposure (Score: 10, High)
3. **COM-001** — Incomplete data deletion on offboarding (Score: 10, High)
4. **TPR-001** — AWS service outage (Score: 10, High)
5. **OPS-005** — Bedrock API throttling (Score: 12, High)
6. **BUS-001** — Single point of failure in engineering team (Score: 12, High)
7. **FIN-003** — Bedrock token costs scaling (Score: 12, High)
8. **SEC-004** — Prompt injection via Teams (Score: 12, High)

---

## Risk Response Strategies

### Accept
Risks that are low severity or where mitigation costs exceed potential impact. Document the rationale.

### Mitigate
Implement controls to reduce likelihood or impact. Most risks in this register use this strategy.

### Transfer
Shift risk to a third party (e.g., cyber insurance for security incidents, AWS SLA for outages).

### Avoid
Eliminate the risk by not performing the activity that creates it (rarely used in production).

---

## Maintenance Process

### Monthly Review
- Risk owners update status of their assigned risks
- New risks identified from incidents, changes, or audits are added
- Closed risks are archived with resolution notes

### Quarterly Review
- Full risk register review with engineering leadership
- Risk scores recalibrated based on recent experience
- Mitigation action progress tracked
- Risk register shared with executive team

### Annual Review
- Complete risk assessment refresh
- External audit of risk management process
- Update risk appetite and tolerance levels
- Review insurance coverage adequacy

---

## Change Log

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-11-22 | 1.0 | Platform Team | Initial risk register creation |