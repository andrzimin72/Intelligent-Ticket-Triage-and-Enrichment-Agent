#!/bin/bash
# =============================================================================
# Initialize LocalStack Resources
# =============================================================================
# Purpose: Creates the necessary mock AWS resources in LocalStack for local
#          development and integration testing.
#
# Usage: ./scripts/init-localstack.sh
# =============================================================================

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}===========================================================${NC}"
echo -e "${BLUE}  Initializing LocalStack Resources${NC}"
echo -e "${BLUE}===========================================================${NC}"

# Check if LocalStack is running
if ! curl -s http://localhost:4566/_localstack/health | grep -q '"dynamodb": "running"'; then
    echo -e "${RED}✗ LocalStack is not running or not ready.${NC}"
    echo -e "   Start it with: make localstack-up"
    exit 1
fi

echo -e "${BLUE}→ Waiting for LocalStack to be fully ready...${NC}"
sleep 5

# 1. Create DynamoDB Tables
echo -e "${BLUE}→ Creating DynamoDB tables...${NC}"

awslocal dynamodb create-table \
  --table-name dev-msp-triage-tenant-registry \
  --attribute-definitions \
    AttributeName=tenant_id,AttributeType=S \
    AttributeName=entra_tenant_id,AttributeType=S \
  --key-schema AttributeName=tenant_id,KeyType=HASH \
  --global-secondary-indexes '[{
    "IndexName": "entra-tenant-index",
    "KeySchema": [{"AttributeName": "entra_tenant_id", "KeyType": "HASH"}],
    "Projection": {"ProjectionType": "ALL"}
  }]' \
  --billing-mode PAY_PER_REQUEST > /dev/null

awslocal dynamodb create-table \
  --table-name dev-msp-triage-agent-audit-log \
  --attribute-definitions \
    AttributeName=audit_id,AttributeType=S \
    AttributeName=timestamp,AttributeType=S \
    AttributeName=tenant_id,AttributeType=S \
  --key-schema AttributeName=audit_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE \
  --global-secondary-indexes '[{
    "IndexName": "tenant-index",
    "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"}, {"AttributeName": "timestamp", "KeyType": "RANGE"}],
    "Projection": {"ProjectionType": "ALL"}
  }]' \
  --billing-mode PAY_PER_REQUEST > /dev/null

awslocal dynamodb create-table \
  --table-name dev-msp-triage-status-cache \
  --attribute-definitions AttributeName=cache_key,AttributeType=S \
  --key-schema AttributeName=cache_key,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST > /dev/null

echo -e "${GREEN}✓ DynamoDB tables created${NC}"

# 2. Create S3 Buckets
echo -e "${BLUE}→ Creating S3 buckets...${NC}"
awslocal s3 mb s3://dev-msp-triage-agent-schemas > /dev/null
awslocal s3 mb s3://dev-msp-triage-kb-documents > /dev/null
awslocal s3 mb s3://dev-msp-triage-customer-branding > /dev/null
awslocal s3 mb s3://dev-msp-triage-tenant-portal > /dev/null
echo -e "${GREEN}✓ S3 buckets created${NC}"

# 3. Create SQS Queues
echo -e "${BLUE}→ Creating SQS queues...${NC}"
awslocal sqs create-queue --queue-name dev-msp-triage-tenant-provisioning > /dev/null
awslocal sqs create-queue --queue-name dev-msp-triage-tenant-provisioning-dlq > /dev/null
awslocal sqs create-queue --queue-name dev-msp-triage-customer-digest > /dev/null
awslocal sqs create-queue --queue-name dev-msp-triage-customer-insights > /dev/null
echo -e "${GREEN}✓ SQS queues created${NC}"

# 4. Create Mock Secrets
echo -e "${BLUE}→ Creating mock Secrets Manager entries...${NC}"
awslocal secretsmanager create-secret \
  --name dev/msp/teams/bot_secret \
  --secret-string '{"BOT_APP_ID": "local-test-app-id", "BOT_APP_PASSWORD": "local-test-password"}' > /dev/null

awslocal secretsmanager create-secret \
  --name dev/msp/agent/confirmation_signing_key \
  --secret-string '{"SIGNING_KEY": "local-test-signing-key-1234567890"}' > /dev/null

echo -e "${GREEN}✓ Mock secrets created${NC}"

echo -e "${BLUE}===========================================================${NC}"
echo -e "${GREEN}✓ LocalStack initialization complete!${NC}"
echo -e "${BLUE}You can now run: make test-local${NC}"
echo -e "${BLUE}===========================================================${NC}"