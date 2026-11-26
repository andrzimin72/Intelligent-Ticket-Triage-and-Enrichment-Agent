#!/bin/bash
# =============================================================================
# Audit Orphaned S3 Data Script
# =============================================================================
# Purpose: Identifies S3 prefixes (representing tenant data) that do not have
#          a corresponding active tenant in the DynamoDB registry.
#
# Usage: ./scripts/audit_orphaned_s3.sh [environment]
# Example: ./scripts/audit_orphaned_s3.sh dev
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ENVIRONMENT=${1:-dev}
TABLE_NAME="${ENVIRONMENT}-msp-triage-tenant-registry"
BUCKETS=("dev-msp-triage-agent-schemas" "dev-msp-triage-kb-documents" "dev-msp-triage-customer-branding")

echo -e "${BLUE}===========================================================${NC}"
echo -e "${BLUE}  Auditing Orphaned S3 Data (${ENVIRONMENT})${NC}"
echo -e "${BLUE}===========================================================${NC}"

# 1. Get list of active tenants from DynamoDB
echo -e "${BLUE}→ Fetching active tenants from DynamoDB...${NC}"
ACTIVE_TENANTS=$(aws dynamodb scan \
  --table-name "$TABLE_NAME" \
  --filter-expression "#s = :status AND enabled = :enabled" \
  --expression-attribute-names '{"#s": "status"}' \
  --expression-attribute-values '{":status": {"S": "active"}, ":enabled": {"N": "1"}}' \
  --query 'Items[*].tenant_id.S' \
  --output text 2>/dev/null || echo "")

if [ -z "$ACTIVE_TENANTS" ]; then
    echo -e "${YELLOW}⚠ No active tenants found in registry. Proceeding with caution.${NC}"
fi

# Convert to array for easier searching
read -ra ACTIVE_ARRAY <<< "$ACTIVE_TENANTS"

ORPHAN_COUNT=0

# 2. Check each bucket for orphaned prefixes
for bucket in "${BUCKETS[@]}"; do
    echo -e "${BLUE}→ Checking bucket: ${bucket}${NC}"
    
    # Check if bucket exists
    if ! aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
        echo -e "${YELLOW}  Bucket does not exist, skipping.${NC}"
        continue
 a prefix doesn't match any active tenant
            IS_ORPHAN=true
            for active_tenant in "${ACTIVE_ARRAY[@]}"; do
                if [[ "$prefix" == "$active_tenant" || "$prefix" == "tenants/$active_tenant" || "$prefix" == "tenants/$active_tenant/" ]]; then
                    IS_ORPHAN=false
                    break
                fi
            done
            
            if [ "$IS_ORPHAN" = true ]; then
                echo -e "${RED}  [ORPHANED] ${prefix}${NC}"
                ((ORPHAN_COUNT++))
            fi
        done
    fi
done

echo -e "${BLUE}===========================================================${NC}"
if [ "$ORPH_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✓ No orphaned S3 data found. All prefixes match active tenants.${NC}"
else
    echo -e "${RED}✗ Found ${ORPHAN_COUNT} orphaned S3 prefixes.${NC}"
    echo -e "${YELLOW}  Review the list above. To delete, use:${NC}"
    echo -e "${YELLOW}  aws s3 rm s3://<bucket>/<orphaned-prefix> --recursive${NC}"
fi
echo -e "${BLUE}===========================================================${NC}"