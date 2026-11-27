#!/usr/bin/env bash
# =============================================================================
# Load Test: API Performance
# =============================================================================
# Purpose: Validates API performance under load, measuring latency, throughput,
#          and error rates across different endpoints.
#
# Tests:
#   1. Status API (lightweight, cached)
#   2. Tenant listing (moderate load)
#   3. Deep health check (heavy, uncached)
#   4. Analytics endpoints
#   5. Concurrent tenant onboarding
#   6. Sustained load test
#
# Prerequisites:
#   - 'hey' load testing tool (https://github.com/rakyll/hey)
#     Install: brew install hey (macOS) or go install github.com/rakyll/hey@latest
#
# Usage:
#   ./scripts/test/test_load_api.sh [--quick] [--sustained]
#
# Environment Variables:
#   API_URL, API_KEY, ENVIRONMENT
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

ENVIRONMENT="${ENVIRONMENT:-dev}"

# Test configuration
QUICK_MODE=false
SUSTAINED_MODE=false

for arg in "$@"; do
    case $arg in
        --quick) QUICK_MODE=true ;;
        --sustained) SUSTAINED_MODE=true ;;
    esac
done

# Adjust test parameters based on mode
if [ "$QUICK_MODE" = true ]; then
    STATUS_REQUESTS=200
    STATUS_CONCURRENCY=20
    LIST_REQUESTS=100
    LIST_CONCURRENCY=10
    HEALTH_REQUESTS=50
    HEALTH_CONCURRENCY=5
else
    STATUS_REQUESTS=1000
    STATUS_CONCURRENCY=50
    LIST_REQUESTS=500
    LIST_CONCURRENCY=25
    HEALTH_REQUESTS=200
    HEALTH_CONCURRENCY=10
fi

# Performance thresholds (milliseconds)
declare -A LATENCY_THRESHOLDS=(
    ["status_p50"]=200
    ["status_p95"]=500
    ["status_p99"]=1000
    ["list_p50"]=500
    ["list_p95"]=1000
    ["list_p99"]=2000
    ["health_p50"]=2000
    ["health_p95"]=5000
    ["health_p99"]=10000
)

# Error rate threshold (percentage)
MAX_ERROR_RATE=1.0

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info()    { echo -e "${BLUE}→ ${1}${NC}"; }
log_success() { echo -e "${GREEN}✓ ${1}${NC}"; }
log_warning() { echo -e "${YELLOW}⚠ ${1}${NC}"; }
log_error()   { echo -e "${RED}✗ ${1}${NC}" >&2; }
log_test()    { echo -e "\n${CYAN}━━━ TEST: ${1} ━━━${NC}"; }

check_tool() {
    if ! command -v hey &> /dev/null; then
        log_error "'hey' load testing tool not found."
        log_info "Install with:"
        echo "  macOS:   brew install hey"
        echo "  Linux:   go install github.com/rakyll/hey@latest"
        echo "  Windows: scoop install hey"
        exit 1
    fi
}

parse_hey_output() {
    local output="$1"
    
    # Extract key metrics from hey output
    local summary=$(echo "$output" | grep -A 20 "Summary:")
    
    local total=$(echo "$output" | grep "Total:" | awk '{print $2}' | sed 's/[secs]//g')
    local requests=$(echo "$output" | grep "Requests/sec:" | awk '{print $2}')
    local p50=$(echo "$output" | grep -A 10 "Latency distribution" | grep "50%" | awk '{print $2}' | sed 's/[s]//g')
    local p95=$(echo "$output" | grep -A 10 "Latency distribution" | grep "95%" | awk '{print $2}' | sed 's/[s]//g')
    local p99=$(echo "$output" | grep -A 10 "Latency distribution" | grep "99%" | awk '{print $2}' | sed 's/[s]//g')
    local errors=$(echo "$output" | grep -A 5 "Status code distribution" | grep -v "200" | grep -oE "[0-9]+ \[" | awk '{sum+=$1} END {print sum+0}')
    local total_req=$(echo "$output" | grep -A 5 "Status code distribution" | grep -oE "[0-9]+ responses" | awk '{sum+=$1} END {print sum+0}')
    
    # Convert seconds to milliseconds
    p50=$(echo "$p50 * 1000" | bc -l | cut -d. -f1)
    p95=$(echo "$p95 * 1000" | bc -l | cut -d. -f1)
    p99=$(echo "$p99 * 1000" | bc -l | cut -d. -f1)
    
    # Calculate error rate
    local error_rate=0
    if [ "$total_req" -gt 0 ]; then
        error_rate=$(echo "scale=2; $errors * 100 / $total_req" | bc -l)
    fi
    
    echo "${total}|${requests}|${p50:-0}|${p95:-0}|${p99:-0}|${errors:-0}|${error_rate:-0}"
}

run_load_test() {
    local test_name="$1"
    local url="$2"
    local requests="$3"
    local concurrency="$4"
    local p50_threshold="$5"
    local p95_threshold="$6"
    local p99_threshold="$7"
    
    log_test "$test_name"
    log_info "Requests: $requests, Concurrency: $concurrency"
    log_info "Thresholds - P50: ${p50_threshold}ms, P95: ${p95_threshold}ms, P99: ${p99_threshold}ms"
    echo ""
    
    local output
    output=$(hey -n "$requests" -c "$concurrency" \
        -H "x-api-key: ${API_KEY}" \
        "$url" 2>&1)
    
    # Save full output for debugging
    echo "$output" > "/tmp/load_test_$(echo "$test_name" | tr ' ' '_').log"
    
    # Parse results
    local metrics
    metrics=$(parse_hey_output "$output")
    
    IFS='|' read -r total rps p50 p95 p99 errors error_rate <<< "$metrics"
    
    # Display results
    echo -e "${BLUE}Results:${NC}"
    echo -e "  Total Time:    ${total}s"
    echo -e "  Throughput:    ${rps} req/sec"
    echo -e "  P50 Latency:   ${p50}ms ${GREEN}$( [ "$p50" -le "$p50_threshold" ] && echo "✓" || echo "✗")${NC}"
    echo -e "  P95 Latency:   ${p95}ms ${GREEN}$( [ "$p95" -le "$p95_threshold" ] && echo "✓" || echo "✗")${NC}"
    echo -e "  P99 Latency:   ${p99}ms ${GREEN}$( [ "$p99" -le "$p99_threshold" ] && echo "✓" || echo "✗")${NC}"
    echo -e "  Errors:        ${errors} (${error_rate}%)"
    echo ""
    
    # Validate against thresholds
    local passed=true
    
    if [ "$p50" -gt "$p50_threshold" ]; then
        log_error "P50 latency (${p50}ms) exceeds threshold (${p50_threshold}ms)"
        passed=false
    fi
    
    if [ "$p95" -gt "$p95_threshold" ]; then
        log_error "P95 latency (${p95}ms) exceeds threshold (${p95_threshold}ms)"
        passed=false
    fi
    
    if [ "$p99" -gt "$p99_threshold" ]; then
        log_error "P99 latency (${p99}ms) exceeds threshold (${p99_threshold}ms)"
        passed=false
    fi
    
    if (( $(echo "$error_rate > $MAX_ERROR_RATE" | bc -l) )); then
        log_error "Error rate (${error_rate}%) exceeds threshold (${MAX_ERROR_RATE}%)"
        passed=false
    fi
    
    if [ "$passed" = true ]; then
        log_success "PASSED: $test_name"
        return 0
    else
        log_error "FAILED: $test_name"
        return 1
    fi
}

# =============================================================================
# PREREQUISITES
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    [ -z "${API_URL:-}" ] && { log_error "API_URL not set"; exit 1; }
    [ -z "${API_KEY:-}" ] && { log_error "API_KEY not set"; exit 1; }
    
    check_tool
    
    # Verify API is reachable
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        -X GET "${API_URL}/status" \
        -H "x-api-key: ${API_KEY}")
    
    if [ "$code" != "200" ]; then
        log_error "API not reachable (HTTP $code)"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# =============================================================================
# TEST CASES
# =============================================================================

test_01_status_api_load() {
    run_load_test \
        "Status API (Cached)" \
        "${API_URL}/status" \
        "$STATUS_REQUESTS" \
        "$STATUS_CONCURRENCY" \
        "${LATENCY_THRESHOLDS[status_p50]}" \
        "${LATENCY_THRESHOLDS[status_p95]}" \
        "${LATENCY_THRESHOLDS[status_p99]}"
}

test_02_tenant_listing_load() {
    run_load_test \
        "Tenant Listing" \
        "${API_URL}/tenants" \
        "$LIST_REQUESTS" \
        "$LIST_CONCURRENCY" \
        "${LATENCY_THRESHOLDS[list_p50]}" \
        "${LATENCY_THRESHOLDS[list_p95]}" \
        "${LATENCY_THRESHOLDS[list_p99]}"
}

test_03_deep_health_check_load() {
    # First, ensure we have at least one tenant to test against
    local tenant_id
    tenant_id=$(curl -s "${API_URL}/tenants" \
        -H "x-api-key: ${API_KEY}" | \
        jq -r '.tenants[0].tenant_id // empty')
    
    if [ -z "$tenant_id" ]; then
        log_warning "No tenants found, skipping deep health check test"
        return 0
    fi
    
    run_load_test \
        "Deep Health Check" \
        "${API_URL}/status/tenants/${tenant_id}/health" \
        "$HEALTH_REQUESTS" \
        "$HEALTH_CONCURRENCY" \
        "${LATENCY_THRESHOLDS[health_p50]}" \
        "${LATENCY_THRESHOLDS[health_p95]}" \
        "${LATENCY_THRESHOLDS[health_p99]}"
}

test_04_analytics_endpoints_load() {
    run_load_test \
        "Analytics Executive Summary" \
        "${API_URL}/analytics/executive-summary" \
        "100" \
        "10" \
        "500" \
        "1000" \
        "2000"
}

test_05_concurrent_onboarding() {
    log_test "Concurrent Tenant Onboarding"
    log_info "Creating 10 tenants concurrently..."
    
    local start_time=$(date +%s)
    local success_count=0
    local fail_count=0
    
    # Create 10 tenants in parallel
    for i in {1..10}; do
        (
            local tenant_id="load-test-$(date +%s)-${i}"
            local payload=$(cat <<EOF
{
    "tenant_id": "${tenant_id}",
    "display_name": "Load Test Tenant ${i}",
    "entra_tenant_id": "$(printf '%08x-%04x-%04x-%04x-%012x' $RANDOM $RANDOM $RANDOM $RANDOM $RANDOM)",
    "admin_group_id": "$(printf '%08x-%04x-%04x-%04x-%012x' $RANDOM $RANDOM $RANDOM $RANDOM $RANDOM)",
    "contact_email": "load-test-${i}@example.com"
}
EOF
)
            local code
            code=$(curl -s -o /dev/null -w "%{http_code}" \
                -X POST "${API_URL}/tenants" \
                -H "x-api-key: ${API_KEY}" \
                -H "Content-Type: application/json" \
                -d "$payload")
            
            if [ "$code" = "202" ]; then
                echo "SUCCESS" > "/tmp/load_tenant_${i}.result"
            else
                echo "FAILED:$code" > "/tmp/load_tenant_${i}.result"
            fi
        ) &
    done
    
    # Wait for all to complete
    wait
    
    # Count results
    for i in {1..10}; do
        local result=$(cat "/tmp/load_tenant_${i}.result" 2>/dev/null || echo "UNKNOWN")
        if [ "$result" = "SUCCESS" ]; then
            success_count=$((success_count + 1))
        else
            fail_count=$((fail_count + 1))
        fi
        rm -f "/tmp/load_tenant_${i}.result"
    done
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo -e "${BLUE}Results:${NC}"
    echo -e "  Success:       ${success_count}/10"
    echo -e "  Failed:        ${fail_count}/10"
    echo -e "  Duration:      ${duration}s"
    echo ""
    
    # Cleanup created tenants
    log_info "Cleaning up load test tenants..."
    for tenant_id in $(curl -s "${API_URL}/tenants" \
        -H "x-api-key: ${API_KEY}" | \
        jq -r '.tenants[] | select(.tenant_id | startswith("load-test-")) | .tenant_id'); do
        curl -s -X DELETE "${API_URL}/tenants/${tenant_id}?confirm=true&preserve_data=false" \
            -H "x-api-key: ${API_KEY}" > /dev/null 2>&1 || true
    done
    
    # At least 80% should succeed
    [ $success_count -ge 8 ]
}

test_06_sustained_load() {
    if [ "$SUSTAINED_MODE" = false ]; then
        log_warning "Skipping sustained load test (use --sustained to enable)"
        return 0
    fi
    
    log_test "Sustained Load Test (60 seconds)"
    log_info "Running continuous load for 60 seconds..."
    
    local output
    output=$(hey -z 60s -c 20 \
        -H "x-api-key: ${API_KEY}" \
        "${API_URL}/status" 2>&1)
    
    echo "$output" > "/tmp/load_test_sustained.log"
    
    local metrics
    metrics=$(parse_hey_output "$output")
    
    IFS='|' read -r total rps p50 p95 p99 errors error_rate <<< "$metrics"
    
    echo -e "${BLUE}Results (60s sustained):${NC}"
    echo -e "  Total Requests: $(echo "$rps * $total" | bc | cut -d. -f1)"
    echo -e "  Avg Throughput: ${rps} req/sec"
    echo -e "  P50 Latency:    ${p50}ms"
    echo -e "  P95 Latency:    ${p95}ms"
    echo -e "  P99 Latency:    ${p99}ms"
    echo -e "  Error Rate:     ${error_rate}%"
    echo ""
    
    # For sustained test, we're more lenient
    [ "$p95" -lt 2000 ] && (( $(echo "$error_rate < 5.0" | bc -l) ))
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║           Load Test: API Performance                      ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
    echo -e "${BLUE}API URL:     ${API_URL}${NC}"
    echo -e "${BLUE}Mode:        $( [ "$QUICK_MODE" = true ] && echo "Quick" || echo "Standard" )${NC}"
    echo ""
    
    check_prerequisites
    
    local start_time=$(date +%s)
    local tests_passed=0
    local tests_failed=0
    
    # Run all load tests
    if test_01_status_api_load; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    if test_02_tenant_listing_load; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    if test_03_deep_health_check_load; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    if test_04_analytics_endpoints_load; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    if test_05_concurrent_onboarding; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    if test_06_sustained_load; then tests_passed=$((tests_passed + 1)); else tests_failed=$((tests_failed + 1)); fi
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    # Summary
    echo ""
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                    TEST SUMMARY                           ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Total Tests:  $((tests_passed + tests_failed))"
    echo -e "Passed:       ${GREEN}${tests_passed}${NC}"
    echo -e "Failed:       ${RED}${tests_failed}${NC}"
    echo -e "Duration:     ${duration}s"
    echo ""
    
    if [ $tests_failed -gt 0 ]; then
        log_error "Some tests failed. Check /tmp/load_test_*.log for details."
        exit 1
    fi
    
    log_success "All load tests passed!"
    exit 0
}

main "$@"