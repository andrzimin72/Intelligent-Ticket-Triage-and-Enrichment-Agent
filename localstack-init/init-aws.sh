#!/bin/bash
# =============================================================================
# LocalStack Initialization Script
# =============================================================================
# This script runs automatically when LocalStack starts.
# It creates the required AWS resources for local testing.
# =============================================================================

echo "Initializing LocalStack resources..."

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
until curl -s http://localhost:4566/_localstack/health | jq -e '.services.dynamodb == "running"' > /dev/null; do
    sleep 2
done
echo "LocalStack is ready!"

# Set AWS endpoint
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test

# -----------------------------------------------------------------------------
# Create DynamoDB Tables
# -----------------------------------------------------------------------------
echo "Creating DynamoDB tables..."

# Tenant Registry
awslocal dynamodb create-table \
    --table-name dev-msp-triage-tenant-registry \
    --attribute-definitions \
        AttributeName=tenant_id,AttributeType=S \
        AttributeName=entra_tenant_id,AttributeType=S \
        AttributeName=enabled,AttributeType=N \
    --key-schema AttributeName=tenant_id,KeyType=HASH \
    --global-secondary-indexes \
        '[
            {
                "IndexName": "entra-tenant-index",
                "KeySchema": [{"AttributeName": "entra_tenant_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "enabled-index",
                "KeySchema": [{"AttributeName": "enabled", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]' \
    --billing-mode PAY_PER_REQUEST

# Status Cache
awslocal dynamodb create-table \
    --table-name dev-msp-triage-status-cache \
    --attribute-definitions AttributeName=cache_key,AttributeType=S \
    --key-schema AttributeName=cache_key,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --sse-specification Enabled=true

# Agent Feedback
awslocal dynamodb create-table \
    --table-name dev-msp-triage-agent-feedback \
    --attribute-definitions \
        AttributeName=feedback_id,AttributeType=S \
        AttributeName=status,AttributeType=S \
        AttributeName=created_at,AttributeType=S \
        AttributeName=tenant_id,AttributeType=S \
    --key-schema AttributeName=feedback_id,KeyType=HASH \
    --global-secondary-indexes \
        '[
            {
                "IndexName": "status-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "tenant-status-index",
                "KeySchema": [
                    {"AttributeName": "tenant_id", "KeyType": "HASH"},
                    {"AttributeName": "status", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]' \
    --billing-mode PAY_PER_REQUEST

echo "✓ DynamoDB tables created"

# -----------------------------------------------------------------------------
# Create S3 Buckets
# -----------------------------------------------------------------------------
echo "Creating S3 buckets..."

awslocal s3 mb s3://dev-msp-triage-agent-schemas
awslocal s3 mb s3://dev-msp-triage-kb-documents
awslocal s3 mb s3://dev-msp-triage-tenant-portal

# Create initial folder structure
awslocal s3 cp /dev/null s3://dev-msp-triage-agent-schemas/tenants/default/agent-examples.json
awslocal s3 cp /dev/null s3://dev-msp-triage-kb-documents/tenants/default/.keep

echo "✓ S3 buckets created"

# -----------------------------------------------------------------------------
# Create SQS Queues
# -----------------------------------------------------------------------------
echo "Creating SQS queues..."

awslocal sqs create-queue --queue-name dev-msp-triage-tenant-provisioning
awslocal sqs create-queue --queue-name dev-msp-triage-tenant-provisioning-dlq
awslocal sqs create-queue --queue-name dev-msp-triage-customer-digest
awslocal sqs create-queue --queue-name dev-msp-triage-customer-insights

echo "✓ SQS queues created"

# -----------------------------------------------------------------------------
# Create Secrets
# -----------------------------------------------------------------------------
echo "Creating secrets..."

awslocal secretsmanager create-secret \
    --name dev/tenants/default/graph \
    --secret-string '{"CLIENT_ID": "test-client-id", "CLIENT_SECRET": "test-client-secret", "TENANT_ID": "test-tenant-id"}'

awslocal secretsmanager create-secret \
    --name dev/msp/teams/bot_secret \
    --secret-string '{"BOT_APP_ID": "test-bot-app-id", "BOT_APP_PASSWORD": "test-bot-password"}'

awslocal secretsmanager create-secret \
    --name dev/msp/agent/confirmation_signing_key \
    --secret-string '{"SIGNING_KEY": "test-signing-key-12345"}'

echo "✓ Secrets created"

# -----------------------------------------------------------------------------
# Seed Default Tenant
# -----------------------------------------------------------------------------
echo "Seeding default tenant..."

awslocal dynamodb put-item \
    --table-name dev-msp-triage-tenant-registry \
    --item '{
        "tenant_id": {"S": "default"},
        "enabled": {"N": "1"},
        "entra_tenant_id": {"S": "12345678-1234-1234-1234-123456789012"},
        "admin_group_id": {"S": "87654321-4321-4321-4321-210987654321"},
        "display_name": {"S": "Default MSP Tenant"},
        "contact_email": {"S": "admin@example.com"},
        "status": {"S": "active"},
        "management_mode": {"S": "hybrid"}
    }'

echo "✓ Default tenant seeded"

echo ""
echo "=========================================="
echo "LocalStack initialization complete!"
echo "=========================================="
echo ""
echo "Services available at: http://localhost:4566"
echo "Web UI available at: http://localhost:8080"
echo ""
echo "Next steps:"
echo "  1. Run tests: make test-local"
echo "  2. Check status: make localstack-status"
echo "  3. View logs: make localstack-logs"
echo ""