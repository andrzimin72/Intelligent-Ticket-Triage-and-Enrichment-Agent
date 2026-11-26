#!/usr/bin/env bash
# =============================================================================
# Terraform State Backup Script
# =============================================================================
# Purpose: Safely backs up the current Terraform state to an encrypted S3 
#          bucket before critical operations (e.g., production deployments, 
#          major refactors, or state migrations).
#
# Features:
#   - Automatic cleanup of local temporary files (via trap)
#   - Server-Side Encryption (SSE) for S3 uploads
#   - Git commit hash embedding for traceability
#   - Dry-run mode for safe testing
#   - Strict error handling (set -euo pipefail)
#
# Usage: 
#   ./scripts/backup-state.sh [environment] [--dry-run]
#
# Examples:
#   ./scripts/backup-state.sh prod
#   ./scripts/backup-state.sh staging --dry-run
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION & VARIABLES
# =============================================================================

# Colors for terminal output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Default values
ENVIRONMENT="${1:-dev}"
DRY_RUN=false
STATE_FILE=""

# Parse optional flags
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            # Ignore positional args already handled
            ;;
    esac
done

# Dynamic values
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
STATE_FILE="terraform-state-${ENVIRONMENT}-${TIMESTAMP}-${GIT_COMMIT}.tfstate"

# Required environment variable
BACKUP_BUCKET="${TF_STATE_BACKUP_BUCKET:-}"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info() {
    echo -e "${BLUE}→ ${1}${NC}"
}

log_success() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

log_error() {
    echo -e "${RED}✗ ${1}${NC}" >&2
}

cleanup() {
    # This function runs on EXIT (success or failure) to ensure no temp files are left behind
    if [[ -n "${STATE_FILE}" && -f "${STATE_FILE}" ]]; then
        log_info "Cleaning up temporary state file: ${STATE_FILE}"
        rm -f "${STATE_FILE}"
    fi
}

# Register the cleanup trap to ensure it runs on exit, interrupt, or error
trap cleanup EXIT INT TERM

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    echo -e "${BLUE}===========================================================${NC}"
    echo -e "${BLUE}  Terraform State Backup: ${ENVIRONMENT}${NC}"
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}  MODE: DRY RUN (No actual changes will be made)${NC}"
    fi
    echo -e "${BLUE}===========================================================${NC}"

    # 1. Validate Prerequisites
    log_info "Validating prerequisites..."
    
    if ! command -v terraform &> /dev/null; then
        log_error "Terraform is not installed or not in PATH."
        exit 1
    fi

    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed or not in PATH."
        exit 1
    fi

    if [[ -z "$BACKUP_BUCKET" ]]; then
        log_error "TF_STATE_BACKUP_BUCKET environment variable is not set."
        log_info "Please set it before running this script:"
        echo -e "   export TF_STATE_BACKUP_BUCKET='your-secure-backup-bucket-name'"
        exit 1
    fi

    # Verify bucket accessibility
    if ! aws s3 ls "s3://${BACKUP_BUCKET}" &> /dev/null; then
        log_error "Cannot access S3 bucket: s3://${BACKUP_BUCKET}"
        log_info "Check your AWS credentials (aws sts get-caller-identity) and bucket permissions."
        exit 1
    fi

    # 2. Verify Terraform Initialization
    log_info "Verifying Terraform initialization..."
    if [[ ! -d ".terraform" ]]; {
        log_warning "Terraform not initialized. Running 'terraform init'..."
        terraform init -input=false -backend=true
    }

    # 3. Pull Current State
    log_info "Pulling current Terraform state..."
    
    # terraform state pull automatically handles state locking in Terraform 1.x
    if ! terraform state pull > "${STATE_FILE}"; then
        log_error "Failed to pull Terraform state."
        log_info "Ensure you are in the correct directory and have valid AWS credentials."
        exit 1
    fi

    # Verify the pulled file is not empty and contains valid JSON
    if [[ ! -s "${STATE_FILE}" ]]; then
        log_error "Pulled state file is empty. Aborting backup to prevent data loss."
        exit 1
    fi

    if ! jq empty "${STATE_FILE}" &> /dev/null; then
        log_error "Pulled state file is not valid JSON. Aborting backup."
        exit 1
    fi

    local file_size
    file_size=$(du -h "${STATE_FILE}" | awk '{print $1}')
    log_success "State pulled successfully (${file_size})"

    # 4. Upload to S3
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would upload to: s3://${BACKUP_BUCKET}/${STATE_FILE}"
        log_info "[DRY RUN] Would apply Server-Side Encryption (AES256)"
        log_success "Dry run completed successfully. No files were uploaded."
        exit 0
    fi

    log_info "Uploading to S3 with Server-Side Encryption..."
    if aws s3 cp "${STATE_FILE}" "s3://${BACKUP_BUCKET}/${STATE_FILE}" \
        --sse AES256 \
        --metadata "environment=${ENVIRONMENT},git-commit=${GIT_COMMIT},timestamp=${TIMESTAMP}"; then
        
        log_success "State backup completed successfully!"
        echo -e "${BLUE}  Location: s3://${BACKUP_BUCKET}/${STATE_FILE}${NC}"
        echo -e "${BLUE}  Git Commit: ${GIT_COMMIT}${NC}"
    else
        log_error "Failed to upload state to S3."
        exit 1
    fi
}

# Execute main function
main "$@"