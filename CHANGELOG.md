```markdown
# Changelog

All notable changes to the MSP AI Platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive IEEE 1471-2000 compliant architectural description documents.
- Advanced analytics aggregation Lambda for health trends and webhook delivery metrics.
- Custom health rules API for tenant-specific monitoring criteria.
- `audit_orphaned_s3.sh` script for identifying and cleaning up unassociated tenant data.

### Changed
- Upgraded Python runtime target to 3.13 for all Lambda functions.
- Enhanced `tenant_resolver.py` with thread-safe in-memory caching and comprehensive error handling.
- Improved S3 purge logic in `tenant_provisioning_worker.py` to handle versioned buckets correctly.

### Fixed
- Resolved PlantUML rendering issues in C4 architecture diagrams by standardizing include syntax.
- Fixed edge case in password reset token validation where max attempts were not properly enforced.

### Security
- Enforced TLS 1.2+ via S3 bucket policies for all tenant-scoped storage.
- Added `gitleaks` pre-commit hook to prevent accidental secret commits.

---

## [1.0.0] - 2026-11-23

### Added
- **Core AI Workflows**: Intelligent ticket triage, IT concierge agent, customer digests, and strategic insights.
- **Multi-Tenancy**: Per-tenant Bedrock agents, isolated DynamoDB/S3 resources, and hybrid mode for Terraform-managed tenants.
- **Security**: Zero-trust authentication, two-phase approval for sensitive operations, Bedrock Guardrails, and comprehensive audit logging.
- **Observability**: 4 CloudWatch dashboards, health scoring, historical tracking, and webhook notifications.
- **Self-Service**: Tenant portal with SSO, custom rules management, and audit log viewing.
- **Lifecycle Management**: Automated API-driven onboarding (<15 mins) and safe deprovisioning with data retention options.
- **DevOps**: GitHub Actions CI/CD pipeline with OIDC, pre-commit hooks, and comprehensive test suites.
- **Documentation**: Complete operational runbook, risk register, compliance mapping, and technical whitepaper.

### Changed
- Migrated from shared AI models to dedicated per-tenant Bedrock agents for strict data isolation.
- Optimized ticket triage costs by implementing confidence-based model routing (Haiku vs. Sonnet).

### Fixed
- Resolved cold start latency in Lambda functions by switching to ARM64 architecture and optimizing package sizes.
- Fixed race conditions in concurrent tenant provisioning by implementing SQS-based async processing.

### Security
- Implemented HMAC-SHA256 signed, time-limited password reset tokens.
- Added strict IAM least-privilege policies for all Lambda execution roles.
- Configured 365-day retention for audit logs with tamper-evident design.

---

## [0.9.0] - 2026-11-01

### Added
- Initial implementation of the Teams Bot adapter with JWT validation.
- Basic tenant onboarding API and DynamoDB registry.
- LocalStack integration for local development and testing.

### Changed
- Restructured project directory to separate shared modules from Lambda-specific code.

---

## [0.1.0] - 2026-10-15

### Added
- Initial repository setup.
- Base Terraform configuration for AWS infrastructure.
- Core Python dependencies and `Makefile` for common tasks.
