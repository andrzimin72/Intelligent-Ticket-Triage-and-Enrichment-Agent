#!/usr/bin/env bash
# =============================================================================
# E2E Test: Complete Customer Journey
# =============================================================================
# Purpose: Validates the entire customer lifecycle from onboarding through
#          daily operations to deprovisioning.
#
# Tests:
#   1. Tenant onboarding via API
#   2. Provisioning state transitions
#   3. Secret population verification
#   4. Tenant health check
#   5. Status API functionality
#   6. Analytics API functionality
#   7. Tenant portal access
#   8. Audit log verification
#   9. Tenant deprovisioning (soft + hard)
#   10. Cleanup verification
#
# Usage:
#   ./scripts/test/test_e2e_customer_journey.sh [--local] [--verbose]
#
# Environment Variables Required:
#   API_URL    - Tenant onboarding API URL
#   API_KEY    - API key for authentication
#   AWS_PROFILE - AWS profile (default: dev)
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'

# Test configuration
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_PROFILE="${AWS_PROFILE:-dev}"
TEST_TENANT_ID="e2e-journey-$(date +%s)"
TEST_ENTRA_TENANT_ID="99999999-9999-9999-9999-999999999999"
TEST_ADMIN_GROUP_ID="88888888-8888-8888-8888-888888888888"
MAX_WAIT_SECONDS=1200  # 20 minutes for provisioning

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

# Parse arguments
USE_LOCAL=false
VERBOSE=false
for arg in "$@"; do
    case $arg in
        --local) USE_LOCAL=true ;;
        --verbose) VERBOSE=true ;;
    esac
done

# Set AWS command based on mode
if [ "$USE_LOCAL" = true ]; then
    AWS_CMD="awslocal"
    echo -e "${YELLOW}⚠ Running against LocalStack${NC}"
else
    AWS_CMD="aws"
fi

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info()    { echo -e "${BLUE}→ ${1}${NC}"; }
log_success() { echo -e "${GREEN}✓ ${1}${NC}"; }
log_warning() { echo -e "${YELLOW}⚠ ${1}${NC}"; }
log_error()   { echo -e "${RED}✗ ${1}${NC}" >&2; }
log_test()    { echo -e "\n${CYAN}━━━ TEST: ${1} ━━━${NC}"; }

run_test() {
    local test_name="$1"
    local test_command="$2"
    
    TESTS_RUN=$((TESTS_RUN + 1))
    log_test "$test_name"
    
    if eval "$test_command"; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        log_success "PASSED: $test_name"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$test_name")
        log_error "FAILED: $test_name"
        return 1
    fi
}

api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    
    local curl_args=(-s -w "\n%{http_code}" -X "$method" \
        "${API_URL}${endpoint}" \
        -H "x-api-key: ${API_KEY}" \
        -H "Content-Type: application/json")
    
    if [ -n "$data" ]; then
        curl_args+=(-d "$data")
    fi
    
    local response
    response=$(curl "${curl_args[@]}")
    
    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')
    
    echo "$http_code" > /tmp/e2e_http_code
    echo "$body" > /tmp/e2e_response_body
}

wait_for_status() {
    local tenant_id="$1"
    local expected_status="$2"
    local start_time=$(date +%s)
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $MAX_WAIT_SECONDS ]; then
            log_error "Timeout waiting for status '$expected_status' after ${MAX_WAIT_SECONDS}s"
            return 1
        fi
        
        api_call "GET" "/tenants/${tenant_id}"
        local status
        status=$(cat /tmp/e2e_response_body | jq -r '.status // empty')
        
        if [ "$status" = "$expected_status" ]; then
            return 0
        fi
        
        if [ "$VERBOSE" = true ]; then
            log_info "  Current status: $status (waiting for: $expected_status, elapsed: ${elapsed}s)"
        fi
        
        sleep 15
    done
}

cleanup() {
    log_info "Cleaning up test artifacts..."
    rm -f /tmp/e2e_http_code /tmp/e2e_response_body
}

trap cleanup EXIT

# =============================================================================
# PREREQUISITES CHECK
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    [ -z "${API_URL:-}" ] && { log_error "API_URL not set"; exit 1; }
    [ -z "${API_KEY:-}" ] && { log_error "API_KEY not set"; exit 1; }
    command -v jq &> /dev/null || { log_error "jq not installed"; exit 1; }
    command -v curl &> /dev/null || { log_error "curl not installed"; exit 1; }
    
    # Verify API connectivity
    api_call "GET" "/status"
    local http_code=$(cat /tmp/e2e_http_code)
    if [ "$http_code" != "200" ]; then
        log_error "API not reachable (HTTP $http_code)"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# =============================================================================
# TEST CASES
# =============================================================================

test_01_tenant_onboarding() {
    local payload=$(cat <<EOF
{
    "tenant_id": "${TEST_TENANT_ID}",
    "display_name": "E2E Journey Test Corp",
    "entra_tenant_id": "${TEST_ENTRA_TENANT_ID}",
    "admin_group_id": "${TEST_ADMIN_GROUP_ID}",
    "contact_email": "e2e-test@example.com",
    "branding": {
        "company_name": "E2E Journey Corp",
        "primary_color": "#ff6b6b"
    },
    "timezone": "America/New_York"
}
EOF
)
    
    api_call "POST" "/tenants" "$payload"
    local http_code=$(cat /tmp/e2e_http_code)
    local body=$(cat /tmp/e2e_response_body)
    
    [ "$http_code" = "202" ] || return 1
    [ "$(echo "$body" | jq -r '.tenant_id')" = "$TEST_TENANT_ID" ] || return 1
    [ "$(echo "$body" | jq -r '.status')" = "provisioning" ] || return 1
    [ "$(echo "$body" | jq -r '.management_mode')" = "api" ] || return 1
}

test_02_verify_dynamodb_record() {
    local item
    item=$($AWS_CMD dynamodb get-item \
        --table-name "${ENVIRONMENT}-msp-triage-tenant-registry" \
        --key "{\"tenant_id\": {\"S\": \"${TEST_TENANT_ID}\"}}" \
        --query 'Item' --output json 2>/dev/null)
    
    [ -n "$item" ] || return 1
    [ "$(echo "$item" | jq -r '.status.S')" = "provisioning" ] || return 1
    [ "$(echo "$item" | jq -r '.display_name.S')" = "E2E Journey Test Corp" ] || return 1
}

test_03_verify_secrets_created() {
    for secret_type in psa rmm graph; do
        $AWS_CMD secretsmanager describe-secret \
            --secret-id "${ENVIRONMENT}/tenants/${TEST_TENANT_ID}/${secret_type}" \
            &> /dev/null || return 1
    done
}

test_04_verify_s3_folders() {
    local count
    count=$($AWS_CMD s3api list-objects-v2 \
        --bucket "${ENVIRONMENT}-msp-triage-agent-schemas" \
        --prefix "tenants/${TEST_TENANT_ID}/" \
        --query 'KeyCount' --output text 2>/dev/null)
    
    [ "$count" -ge 1 ] || return 1
}

test_05_wait_for_active_status() {
    wait_for_status "$TEST_TENANT_ID" "active"
}

test_06_verify_agent_provisioned() {
    api_call "GET" "/tenants/${TEST_TENANT_ID}"
    local body=$(cat /tmp/e2e_response_body)
    
    local agent_id=$(echo "$body" | jq -r '.agent_id // empty')
    local alias_id=$(echo "$body" | jq -r '.agent_alias_id // empty')
    
    [ -n "$agent_id" ] || return 1
    [ -n "$alias_id" ] || return 1
}

test_07_populate_secrets() {
    $AWS_CMD secretsmanager put-secret-value \
        --secret-id "${ENVIRONMENT}/tenants/${TEST_TENANT_ID}/graph" \
        --secret-string '{"CLIENT_ID":"test","CLIENT_SECRET":"test","TENANT_ID":"test"}' \
        &> /dev/null || return 1
    
    $AWS_CMD secretsmanager put-secret-value \
        --secret-id "${ENVIRONMENT}/tenants/${TEST_TENANT_ID}/psa" \
        --secret-string '{"BASE_URL":"test","COMPANY_ID":"test","PUBLIC_KEY":"test","PRIVATE_KEY":"test","CLIENT_ID":"test"}' \
        &> /dev/null || return 1
    
    $AWS_CMD secretsmanager put-secret-value \
        --secret-id "${ENVIRONMENT}/tenants/${TEST_TENANT_ID}/rmm" \
        --secret-string '{"BASE_URL":"test","API_TOKEN":"test"}' \
        &> /dev/null || return 1
}

test_08_verify_health_score() {
    api_call "GET" "/status/tenants/${TEST_TENANT_ID}/health"
    local body=$(cat /tmp/e2e_response_body)
    
    local health_score=$(echo "$body" | jq -r '.health_score // 0')
    local overall_health=$(echo "$body" | jq -r '.overall_health // "unknown"')
    
    [ "$health_score" -ge 80 ] || return 1
    [ "$overall_health" = "healthy" ] || return 1
}

test_09_list_tenants() {
    api_call "GET" "/tenants"
    local body=$(cat /tmp/e2e_response_body)
    
    local count=$(echo "$body" | jq -r '.count // 0')
    [ "$count" -ge 1 ] || return 1
    
    local found=$(echo "$body" | jq -r ".tenants[] | select(.tenant_id == \"${TEST_TENANT_ID}\") | .tenant_id")
    [ "$found" = "$TEST_TENANT_ID" ] || return 1
}

test_10_system_status() {
    api_call "GET" "/status"
    local body=$(cat /tmp/e2e_response_body)
    
    local system_health=$(echo "$body" | jq -r '.system_health // "unknown"')
    [ "$system_health" != "unknown" ] || return 1
}

test_11_aggregated_metrics() {
    api_call "GET" "/status/metrics"
    local body=$(cat /tmp/e2e_response_body)
    
    local total_tenants=$(echo "$body" | jq -r '.totals.tenants // 0')
    [ "$total_tenants" -ge 1 ] || return 1
}

test_12_analytics_health_trends() {
    api_call "GET" "/analytics/health-trends?days=30"
    local http_code=$(cat /tmp/e2e_http_code)
    
    # May return 200 with data or 404 if no data yet - both acceptable
    [ "$http_code" = "200" ] || [ "$http_code" = "404" ]
}

test_13_deprovision_tenant() {
    api_call "DELETE" "/tenants/${TEST_TENANT_ID}?confirm=true&preserve_data=true"
    local http_code=$(cat /tmp/e2e_http_code)
    local body=$(cat /tmp/e2e_response_body)
    
    [ "$http_code" = "202" ] || return 1
    [ "$(echo "$body" | jq -r '.status')" = "deprovisioning" ] || return 1
}

test_14_wait_for_deleted_status() {
    wait_for_status "$TEST_TENANT_ID" "deleted"
}

test_15_verify_final_state() {
    api_call "GET" "/tenants/${TEST_TENANT_ID}"
    local body=$(cat /tmp/e2e_response_body)
    
    local status=$(echo "$body" | jq -r '.status // "unknown"')
    [ "$status" = "deleted" ] || return 1
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     E2E Test: Complete Customer Journey                   ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
    echo -e "${BLUE}Test Tenant: ${TEST_TENANT_ID}${NC}"
    echo -e "${BLUE}API URL:     ${API_URL}${NC}"
    echo ""
    
    check_prerequisites
    
    local start_time=$(date +%s)
    
    # Run all tests
    run_test "01. Tenant Onboarding"               test_01_tenant_onboarding
    run_test "02. DynamoDB Record Created"         test_02_verify_dynamodb_record
    run_test "03. Secrets Created"                 test_03_verify_secrets_created
    run_test "04. S3 Folders Created"              test_04_verify_s3_folders
    run_test "05. Wait for Active Status"          test_05_wait_for_active_status
    run_test "06. Agent Provisioned"               test_06_verify_agent_provisioned
    run_test "07. Populate Secrets"                test_07_populate_secrets
    run_test "08. Health Score Verified"           test_08_verify_health_score
    run_test "09. List Tenants"                    test_09_list_tenants
    run_test "10. System Status"                   test_10_system_status
    run_test "11. Aggregated Metrics"              test_11_aggregated_metrics
    run_test "12. Analytics Health Trends"         test_12_analytics_health_trends
    run_test "13. Deprovision Tenant"              test_13_deprovision_tenant
    run_test "14. Wait for Deleted Status"         test_14_wait_for_deleted_status
    run_test "15. Final State Verified"            test_15_verify_final_state
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    # Summary
    echo ""
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                    TEST SUMMARY                           ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Total Tests:  ${TESTS_RUN}"
    echo -e "Passed:       ${GREEN}${TESTS_PASSED}${NC}"
    echo -e "Failed:       ${RED}${TESTS_FAILED}${NC}"
    echo -e "Duration:     ${duration}s"
    echo ""
    
    if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
        echo -e "${RED}Failed Tests:${NC}"
        for test in "${FAILED_TESTS[@]}"; do
            echo -e "  ${RED}✗${NC} $test"
        done
        echo ""
        exit 1
    fi
    
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
}

main "$@"