#!/bin/bash
# =============================================================================
# Cleanup Test Data Script
# =============================================================================
# Purpose: Safely removes test data created during local development or 
#          integration testing from AWS or LocalStack.
#
# WARNING: This script deletes data. Use with caution, especially in non-local
#          environments.
#
# Usage: ./scripts/cleanup_test_data.sh [--local] [--force]
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

LOCAL_ONLY=false
FORCE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --local) LOCAL_ONLY=true ;;
        --force) FORCE=true ;;
    esac
done

AWS_CMD="aws"
if [ "$LOCAL_ONLY" = true ]; then
    AWS_CMD="awslocal"
    echo -e "${YELLOW}⚠ Running in LocalStack mode (--local)${NC}"
else
    echo -e "${RED}⚠ WARNING: This will delete data from your configured AWS profile!${NC}"
fi

if [ "$FORCE" = false ]; then
    echo -e "${YELLOW}Are you sure you want to delete test data? (yes/no)${NC}"
    read -r CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo -e "${BLUE}Cleanup aborted.${NC}"
        exit 0
    fi
fi

echo -e "${BLUE}===========================================================${NC}"
echo -e "${BLUE}  Cleaning Up Test Data${NC}"
echo -e "${BLUE}===========================================================${NC}"

# 1. Delete test tenants from DynamoDB
echo -e "${BLUE}→ Cleaning DynamoDB tenant registry...${NC}"
TENANTS=$($AWS_CMD dynamodb scan \
  --table-name dev-msp-triage-tenant-registry \
  --filter-expression "begins_with(tenant_id, :prefix)" \
  --expression-attribute-values '{":prefix": {"S": "test-"}}' \
  --query 'Items[*].tenant_id.S' --output text 2>/dev/null || echo "")

if [ -n "$TENANTS" ]; then
    for tenant in $TENANTS; do
        echo "  Deleting tenant: $tenant"
        $AWS_CMD dynamodb delete-item \
          --table-name dev-msp-triage-tenant-registry \
          --key "{\"tenant_id\": {\"S\": \"$tenant\"}}" > /dev/null
    done
    echo -e "${GREEN}✓ Test tenants deleted${NC}"
else
    echo -e "${BLUE}  No test tenants found${NC}"
fi

# 2. Delete test S3 objects
echo -e "${BLUE}→ Cleaning S3 test objects...${NC}"
BUCKETS=("dev-msp-triage-agent-schemas" "dev-msp-triage-kb-documents")
for bucket in "${BUCKETS[@]}"; do
    # Check if bucket exists
    if $AWS_CMD s3api head-bucket --bucket "$bucket" 2>/dev/null; then
        $AWS_CMD s3 rm "s3://${bucket}/tenants/test-" --recursive 2>/dev/null || true
    fi
done
echo -e "${GREEN}✓ Test S3 objects deleted${NC}"

# 3. Purge SQS queues
echo -e "${BLUE}→ Purging SQS queues...${NC}"
QUEUES=$($AWS_CMD sqs list-queues --query 'QueueUrls[*]' --output text 2>/dev/null | grep "dev-msp-triage" || echo "")
if [ -n "$QUEUES" ]; then
    for queue in $QUEUES; do
        $AWS_CMD sqs purge-queue --queue-url "$queue" > /dev/null 2>&1 || true
    done
    echo -e "${GREEN}✓ SQS queues purged${NC}"
fi

echo -e "${BLUE}===========================================================${NC}"
echo -e "${GREEN}✓ Test data cleanup complete!${NC}"
echo -e "${BLUE}===========================================================${NC}"