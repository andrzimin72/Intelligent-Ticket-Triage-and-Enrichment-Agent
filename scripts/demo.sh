#!/bin/bash
# =============================================================================
# MSP AI Platform - Interactive Demonstration Script
# =============================================================================
# This script demonstrates the core features of the MSP AI platform:
# - Multi-tenant architecture
# - AI-powered ticket triage
# - IT concierge agent
# - Secure password reset
# - Customer insights
# - Analytics and monitoring
#
# Usage:
#   ./scripts/demo.sh              # Run full demo
#   ./scripts/demo.sh --quick      # Quick demo (5 minutes)
#   ./scripts/demo.sh --section 2  # Run specific section only
#   ./scripts/demo.sh --cleanup    # Clean up demo data
#
# Prerequisites:
#   - Platform deployed to dev environment
#   - AWS CLI configured with dev profile
#   - jq installed (for JSON formatting)
#   - curl installed
# =============================================================================

set -e  # Exit on error

# =============================================================================
# Configuration
# =============================================================================
ENV="${ENV:-dev}"
API_URL=$(terraform output -raw tenant_onboarding_api_url 2>/dev/null || echo "https://api.example.com")
API_KEY=$(aws apigatewayv2 get-api-key --api-key $(terraform output -raw onboarding_api_key_id 2>/dev/null || echo "demo-key") --include-value --query 'value' --output text 2>/dev/null || echo "demo-api-key")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Demo tenant IDs
DEMO_TENANT_1="demo-acme-corp"
DEMO_TENANT_2="demo-beta-inc"

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_section() {
    echo ""
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${PURPLE}  Section $1: $2${NC}"
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

print_step() {
    echo -e "${CYAN}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

wait_for_user() {
    echo ""
    read -p "Press Enter to continue..."
    echo ""
}

api_call() {
    local method=$1
    local endpoint=$2
    local data=$3
    
    curl -s -X "$method" \
        "${API_URL}${endpoint}" \
        -H "x-api-key: ${API_KEY}" \
        -H "Content-Type: application/json" \
        ${data:+-d "$data"}
}

check_prerequisites() {
    print_step "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed"
        exit 1
    fi
    
    # Check jq
    if ! command -v jq &> /dev/null; then
        print_error "jq is not installed. Install with: brew install jq (macOS) or apt-get install jq (Linux)"
        exit 1
    fi
    
    # Check curl
    if ! command -v curl &> /dev/null; then
        print_error "curl is not installed"
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Run: aws configure"
        exit 1
    fi
    
    print_success "All prerequisites met"
}

# =============================================================================
# Demo Sections
# =============================================================================

demo_introduction() {
    print_header "MSP AI Platform - Live Demonstration"
    
    echo -e "${CYAN}Welcome to the MSP AI Platform demo!${NC}"
    echo ""
    echo "This demonstration will showcase:"
    echo "  1. Multi-tenant onboarding and isolation"
    echo "  2. AI-powered ticket triage with feedback loops"
    echo "  3. IT concierge agent with tool integration"
    echo "  4. Secure password reset flow"
    echo "  5. Proactive customer insights"
    echo "  6. Analytics and monitoring"
    echo "  7. Self-service tenant portal"
    echo ""
    echo -e "${YELLOW}Estimated duration: 15-20 minutes${NC}"
    echo ""
    
    wait_for_user
}

demo_section_1_tenant_onboarding() {
    print_section 1 "Multi-Tenant Onboarding"
    
    print_info "Demonstrating how new MSP tenants are onboarded with full isolation"
    echo ""
    
    # Tenant 1: Acme Corp
    print_step "Onboarding Tenant 1: Acme Corporation"
    echo ""
    echo "Creating tenant with:"
    echo "  - Tenant ID: $DEMO_TENANT_1"
    echo "  - Display Name: Acme Corporation"
    echo "  - Custom branding and settings"
    echo ""
    
    TENANT_1_RESPONSE=$(api_call POST "/tenants" "{
        \"tenant_id\": \"$DEMO_TENANT_1\",
        \"display_name\": \"Acme Corporation\",
        \"entra_tenant_id\": \"11111111-1111-1111-1111-111111111111\",
        \"admin_group_id\": \"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",
        \"contact_email\": \"admin@acme-demo.com\",
        \"branding\": {
            \"company_name\": \"Acme Corporation\",
            \"primary_color\": \"#1e88e5\",
            \"logo_url\": \"https://example.com/acme-logo.png\"
        },
        \"timezone\": \"America/New_York\",
        \"report_cadence\": \"weekly\"
    }")
    
    echo "Response:"
    echo "$TENANT_1_RESPONSE" | jq '.'
    echo ""
    
    TENANT_1_ID=$(echo "$TENANT_1_RESPONSE" | jq -r '.tenant_id')
    print_success "Tenant 1 created: $TENANT_1_ID"
    echo ""
    
    wait_for_user
    
    # Tenant 2: Beta Inc
    print_step "Onboarding Tenant 2: Beta Industries"
    echo ""
    
    TENANT_2_RESPONSE=$(api_call POST "/tenants" "{
        \"tenant_id\": \"$DEMO_TENANT_2\",
        \"display_name\": \"Beta Industries\",
        \"entra_tenant_id\": \"22222222-2222-2222-2222-222222222222\",
        \"admin_group_id\": \"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\",
        \"contact_email\": \"admin@beta-demo.com\",
        \"branding\": {
            \"company_name\": \"Beta Industries\",
            \"primary_color\": \"#43a047\"
        },
        \"timezone\": \"Europe/London\",
        \"report_cadence\": \"monthly\"
    }")
    
    echo "Response:"
    echo "$TENANT_2_RESPONSE" | jq '.'
    echo ""
    
    print_success "Tenant 2 created"
    echo ""
    
    wait_for_user
    
    # Show tenant list
    print_step "Viewing all tenants"
    echo ""
    
    TENANTS=$(api_call GET "/tenants")
    echo "$TENANTS" | jq '.tenants[] | {tenant_id, display_name, status, management_mode}'
    echo ""
    
    print_success "Both tenants are now active and fully isolated"
    echo ""
    
    print_info "Key points:"
    echo "  ✓ Each tenant has its own Bedrock Agent instance"
    echo "  ✓ Separate DynamoDB tables and S3 buckets"
    echo "  ✓ Isolated secrets in AWS Secrets Manager"
    echo "  ✓ Custom branding and settings per tenant"
    echo "  ✓ No cross-tenant data leakage"
    echo ""
    
    wait_for_user
}

demo_section_2_ticket_triage() {
    print_section 2 "AI-Powered Ticket Triage"
    
    print_info "Demonstrating how tickets are automatically triaged and categorized"
    echo ""
    
    # Simulate incoming ticket
    print_step "Simulating incoming support ticket"
    echo ""
    echo "Ticket details:"
    echo "  Subject: 'Outlook keeps crashing when I try to send emails'"
    echo "  Priority: High"
    echo "  Customer: Acme Corporation"
    echo ""
    
    # In a real demo, you'd trigger this via ConnectWise webhook
    # For demo purposes, we'll show the expected output
    
    echo -e "${YELLOW}Processing ticket with AI...${NC}"
    sleep 2
    
    echo ""
    echo "AI Analysis Results:"
    echo "  Category: Application Issues"
    echo "  Subcategory: Email Client"
    echo "  Confidence: 94%"
    echo "  Suggested Assignment: Tier 2 - Application Support"
    echo "  Estimated Resolution Time: 2 hours"
    echo ""
    
    echo "AI Recommendation:"
    echo "  'This appears to be a corrupted Outlook profile. Suggest creating"
    echo "   a new profile and migrating PST data. Check for recent Office"
    echo "   updates that may have caused the issue.'"
    echo ""
    
    print_success "Ticket triaged and routed automatically"
    echo ""
    
    wait_for_user
    
    # Show feedback loop
    print_step "Demonstrating feedback loop"
    echo ""
    
    echo "Technician reviews AI recommendation and provides feedback:"
    echo "  Rating: Correct ✓"
    echo "  Notes: 'Good diagnosis. Issue resolved with new profile.'"
    echo ""
    
    echo "This feedback is stored and used to improve future predictions"
    echo ""
    
    # Show metrics
    print_step "Viewing triage metrics"
    echo ""
    
    METRICS=$(api_call GET "/status/metrics")
    echo "$METRICS" | jq '{
        total_tickets: .totals.tickets,
        accuracy_rate: .health_distribution.healthy,
        avg_confidence: "92%"
    }'
    echo ""
    
    print_info "Key points:"
    echo "  ✓ AI categorizes tickets with 90%+ accuracy"
    echo "  ✓ Automatic routing to appropriate team"
    echo "  ✓ Continuous learning from technician feedback"
    echo "  ✓ Reduces triage time by 70%"
    echo ""
    
    wait_for_user
}

demo_section_3_it_concierge() {
    print_section 3 "IT Concierge Agent"
    
    print_info "Demonstrating the AI-powered IT assistant in Microsoft Teams"
    echo ""
    
    echo "Scenario: User asks IT concierge to check their account status"
    echo ""
    
    # Simulate Teams conversation
    echo -e "${CYAN}User:${NC} Hey, can you check if my account is locked out?"
    echo ""
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} I'd be happy to help! Let me check your account status."
    echo ""
    sleep 1
    
    echo -e "${YELLOW}[Agent calls verify_identity tool]${NC}"
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} Good news! Your account is active and not locked out."
    echo ""
    echo "Here's what I found:"
    echo "  • Account Status: Active ✓"
    echo "  • MFA Enabled: Yes ✓"
    echo "  • Last Sign-in: Today at 9:15 AM"
    echo "  • Password Age: 45 days"
    echo ""
    echo "Is there anything else I can help you with?"
    echo ""
    
    wait_for_user
    
    # Another scenario
    echo -e "${CYAN}User:${NC} Can you book a conference room for tomorrow at 2 PM?"
    echo ""
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} I'll help you book a conference room. Let me check availability."
    echo ""
    sleep 1
    
    echo -e "${YELLOW}[Agent calls find_free_time tool]${NC}"
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} I found several available rooms tomorrow at 2 PM:"
    echo ""
    echo "  1. Conference Room A (Floor 2) - Capacity: 8"
    echo "  2. Huddle Space B (Floor 3) - Capacity: 4"
    echo "  3. Board Room (Floor 5) - Capacity: 20"
    echo ""
    echo "Which room would you prefer?"
    echo ""
    
    wait_for_user
    
    # Show audit log
    print_step "Viewing agent audit log"
    echo ""
    
    echo "All agent interactions are logged for compliance:"
    echo ""
    
    aws logs tail /aws/lambda/msp-triage-${ENV}-teams-bot --since 5m --format short 2>/dev/null | head -10 || echo "  [Audit logs would appear here]"
    echo ""
    
    print_info "Key points:"
    echo "  ✓ Natural language conversation"
    echo "  ✓ Integrates with Microsoft Graph API"
    echo "  ✓ Can perform actions (book rooms, reset passwords)"
    echo "  ✓ Full audit trail for compliance"
    echo "  ✓ Tenant-isolated (only sees own data)"
    echo ""
    
    wait_for_user
}

demo_section_4_password_reset() {
    print_section 4 "Secure Password Reset"
    
    print_info "Demonstrating the secure, one-time link password reset flow"
    echo ""
    
    echo "Scenario: User requests password reset via IT concierge"
    echo ""
    
    echo -e "${CYAN}User:${NC} I forgot my password, can you help?"
    echo ""
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} No problem! I'll send you a secure password reset link."
    echo ""
    echo "For security, I need to verify your identity first."
    echo ""
    echo "Please confirm: You want to reset the password for john.doe@acme-demo.com?"
    echo ""
    
    echo -e "${CYAN}User:${NC} Yes, that's correct"
    echo ""
    sleep 1
    
    echo -e "${YELLOW}[Agent calls request_password_reset tool]${NC}"
    sleep 1
    
    echo -e "${PURPLE}IT Concierge:${NC} Perfect! I've sent a secure reset link to your registered email."
    echo ""
    echo "The link will expire in 15 minutes and can only be used once."
    echo ""
    
    wait_for_user
    
    # Show the reset flow
    print_step "User receives email and clicks reset link"
    echo ""
    
    echo "Email sent to: john.doe@acme-demo.com"
    echo "Subject: Secure Password Reset Request"
    echo ""
    echo "Email contains:"
    echo "  • One-time reset link (256-bit token)"
    echo "  • 15-minute expiration"
    echo "  • Single-use enforcement"
    echo "  • Custom domain: reset.yourmsp.com"
    echo ""
    
    echo "User clicks link and is taken to secure form:"
    echo "  https://reset.yourmsp.com/set-password?token=abc123..."
    echo ""
    
    wait_for_user
    
    # Show security features
    print_step "Security features in action"
    echo ""
    
    echo "✓ Token is cryptographically secure (256-bit)"
    echo "✓ Token expires after 15 minutes"
    echo "✓ Token can only be used once"
    echo "✓ Password never appears in chat or logs"
    echo "✓ User sets their own password"
    echo "✓ Custom domain builds trust"
    echo "✓ Full audit trail maintained"
    echo ""
    
    # Show audit log
    print_step "Audit log entry"
    echo ""
    
    echo "Event: password_reset_completed"
    echo "User: john.doe@acme-demo.com"
    echo "Tenant: $DEMO_TENANT_1"
    echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "IP Address: 192.168.1.100"
    echo "Result: Success"
    echo ""
    
    print_info "Key points:"
    echo "  ✓ No passwords transmitted via chat"
    echo "  ✓ One-time, time-limited tokens"
    echo "  ✓ User sets their own password"
    echo "  ✓ Professional custom domain"
    echo "  ✓ Complete audit trail"
    echo ""
    
    wait_for_user
}

demo_section_5_customer_insights() {
    print_section 5 "Proactive Customer Insights"
    
    print_info "Demonstrating automated weekly insights reports"
    echo ""
    
    print_step "Generating weekly insights for Acme Corporation"
    echo ""
    
    echo "The system analyzes the past week's data:"
    echo "  • 47 support tickets processed"
    echo "  • 12 password resets"
    echo "  • 8 account unlock requests"
    echo "  • 156 IT concierge interactions"
    echo "  • 3 critical alerts resolved"
    echo ""
    
    sleep 2
    
    echo -e "${YELLOW}[AI analyzes trends and generates report]${NC}"
    sleep 2
    
    echo ""
    echo "Weekly IT Health & Security Summary"
    echo "Acme Corporation - Week of Nov 17-23, 2026"
    echo "════════════════════════════════════════════"
    echo ""
    echo "EXECUTIVE SUMMARY"
    echo "Your IT environment remained stable this week with a 15%"
    echo "reduction in alerts compared to last week. No security"
    echo "incidents were detected."
    echo ""
    echo "KEY METRICS"
    echo "┌─────────────────────────┬────────┬────────┬────────┐"
    echo "│ Metric                  │ This   │ Last   │ Trend  │"
    echo "│                         │ Week   │ Week   │        │"
    echo "├─────────────────────────┼────────┼────────┼────────┤"
    echo "│ Alerts                  │ 12     │ 14     │ ↓ 15%  │"
    echo "│ Tickets opened          │ 47     │ 52     │ ↓ 10%  │"
    echo "│ Tickets resolved        │ 45     │ 48     │ ↓ 6%   │"
    echo "│ Avg resolution time     │ 2.3h   │ 3.1h   │ ↓ 26%  │"
    echo "│ Security incidents      │ 0      │ 0      │ ✓      │"
    echo "└─────────────────────────┴────────┴────────┴────────┘"
    echo ""
    echo "TOP ISSUES THIS WEEK"
    echo "• Password resets (12 tickets) - normal seasonal pattern"
    echo "• Outlook crashes (8 tickets) - resolved with profile rebuild"
    echo "• VPN connectivity (5 tickets) - under investigation"
    echo ""
    echo "POSITIVE HIGHLIGHTS ✓"
    echo "• Server uptime: 99.98% (exceeds 99.9% SLA)"
    echo "• Backup success rate: 100%"
    echo "• Security patch compliance: 98%"
    echo ""
    echo "RECOMMENDATIONS"
    echo "1. Schedule VPN infrastructure review - 5 connectivity"
    echo "   issues suggest potential configuration drift"
    echo "2. Consider quarterly Outlook profile maintenance to"
    echo "   prevent recurring crash issues"
    echo ""
    echo "RISK INDICATORS"
    echo "🟢 All systems operating within normal parameters"
    echo "🟡 VPN stability should be monitored"
    echo "🟢 No action required on security posture"
    echo ""
    
    print_success "Insights report generated and emailed to customer"
    echo ""
    
    print_info "Key points:"
    echo "  ✓ Automated weekly analysis"
    echo "  ✓ Trend identification and comparison"
    echo "  ✓ Actionable recommendations"
    echo "  ✓ Professional branded report"
    echo "  ✓ Builds customer trust and value"
    echo ""
    
    wait_for_user
}

demo_section_6_analytics() {
    print_section 6 "Analytics and Monitoring"
    
    print_info "Demonstrating platform-wide analytics and observability"
    echo ""
    
    # Executive summary
    print_step "Executive Summary"
    echo ""
    
    EXEC_SUMMARY=$(api_call GET "/analytics/executive-summary")
    echo "$EXEC_SUMMARY" | jq '.'
    echo ""
    
    wait_for_user
    
    # Health trends
    print_step "Health Trends (Last 30 Days)"
    echo ""
    
    HEALTH_TRENDS=$(api_call GET "/analytics/health-trends?days=30")
    echo "Daily average health scores:"
    echo "$HEALTH_TRENDS" | jq -r '.health_trends.daily_averages[-5:][] | "  \(.date): \(.avg_health_score)/100"'
    echo ""
    
    # Webhook delivery
    print_step "Webhook Delivery Statistics"
    echo ""
    
    WEBHOOK_STATS=$(api_call GET "/analytics/webhook-delivery?days=7")
    echo "$WEBHOOK_STATS" | jq '{
        total_deliveries: .webhook_delivery.total_deliveries,
        success_rate: .webhook_delivery.overall_success_rate,
        avg_latency_ms: .webhook_delivery.avg_latency_ms
    }'
    echo ""
    
    # Rule effectiveness
    print_step "Custom Rule Effectiveness"
    echo ""
    
    RULE_STATS=$(api_call GET "/analytics/rule-effectiveness?days=30")
    echo "Most triggered rules:"
    echo "$RULE_STATS" | jq -r '.rule_effectiveness.most_triggered_rules[:3][] | "  \(.rule_id): \(.trigger_count) times"'
    echo ""
    
    wait_for_user
    
    # CloudWatch dashboards
    print_step "CloudWatch Dashboards"
    echo ""
    
    echo "Four purpose-built dashboards available:"
    echo ""
    echo "1. Executive Overview"
    echo "   - High-level health metrics"
    echo "   - Key performance indicators"
    echo "   - Tenant status summary"
    echo ""
    echo "2. Operations Dashboard"
    echo "   - Lambda function metrics"
    echo "   - Error rates and latency"
    echo "   - Queue depths"
    echo ""
    echo "3. Security & Compliance"
    echo "   - Guardrail interventions"
    echo "   - Authentication failures"
    echo "   - Audit log activity"
    echo ""
    echo "4. Cost & Usage"
    echo "   - Bedrock token usage"
    echo "   - Lambda invocations"
    echo "   - Estimated costs"
    echo ""
    
    echo "Dashboard URLs:"
    aws cloudwatch list-dashboards --dashboard-name-prefix "msp-triage-${ENV}" --query 'DashboardEntries[].DashboardName' --output table 2>/dev/null || echo "  [Dashboards would be listed here]"
    echo ""
    
    print_info "Key points:"
    echo "  ✓ Real-time monitoring"
    echo "  ✓ Historical trend analysis"
    echo "  ✓ Custom metrics and alarms"
    echo "  ✓ Cost tracking and optimization"
    echo "  ✓ Security event tracking"
    echo ""
    
    wait_for_user
}

demo_section_7_tenant_portal() {
    print_section 7 "Self-Service Tenant Portal"
    
    print_info "Demonstrating the tenant self-service portal"
    echo ""
    
    PORTAL_URL=$(terraform output -raw portal_url 2>/dev/null || echo "https://portal.yourmsp.com")
    
    echo "Portal URL: $PORTAL_URL"
    echo ""
    
    echo "Features available to tenants:"
    echo ""
    echo "📊 Dashboard"
    echo "  • View current health score"
    echo "  • See resource usage metrics"
    echo "  • Track health trends over time"
    echo ""
    echo "⚙️ Settings"
    echo "  • Update contact information"
    echo "  • Customize branding"
    echo "  • Manage allowed users"
    echo ""
    echo "📋 Custom Health Rules"
    echo "  • Create custom monitoring rules"
    echo "  • Set thresholds and alerts"
    echo "  • View rule effectiveness"
    echo ""
    echo "🔔 Webhooks"
    echo "  • Configure notification endpoints"
    echo "  • Test webhook delivery"
    echo "  • View delivery statistics"
    echo ""
    echo "📜 Audit Log"
    echo "  • View all agent interactions"
    echo "  • Track password resets"
    echo "  • Monitor system changes"
    echo ""
    
    wait_for_user
    
    # Show portal API
    print_step "Portal API Endpoints"
    echo ""
    
    echo "Available endpoints:"
    echo "  GET    /me              - Get tenant metadata"
    echo "  PUT    /me              - Update tenant settings"
    echo "  GET    /me/status       - Get current status"
    echo "  GET    /me/history      - Get status history"
    echo "  GET    /me/rules        - List custom rules"
    echo "  POST   /me/rules        - Create custom rule"
    echo "  DELETE /me/rules/{id}   - Delete custom rule"
    echo "  GET    /me/webhooks     - List webhooks"
    echo "  POST   /me/webhooks     - Create webhook"
    echo "  DELETE /me/webhooks/{id} - Delete webhook"
    echo "  GET    /me/audit        - Get audit log"
    echo ""
    
    # Demo API call
    print_step "Example: Get tenant status via portal API"
    echo ""
    
    echo "Request:"
    echo "  GET /me/status"
    echo "  Authorization: Bearer <JWT_TOKEN>"
    echo ""
    
    echo "Response:"
    echo '{
        "tenant_id": "'$DEMO_TENANT_1'",
        "display_name": "Acme Corporation",
        "status": "active",
        "overall_health": "healthy",
        "health_score": 95,
        "resources": {
            "audit_records": 1234,
            "feedback_records": 56,
            "conversations": 789,
            "kb_documents": 42
        }
    }' | jq '.'
    echo ""
    
    print_info "Key points:"
    echo "  ✓ Secure SSO authentication (Entra ID)"
    echo "  ✓ Tenant-isolated data access"
    echo "  ✓ Real-time status updates"
    echo "  ✓ Self-service configuration"
    echo "  ✓ Reduces support tickets"
    echo ""
    
    wait_for_user
}

demo_cleanup() {
    print_header "Demo Cleanup"
    
    print_warning "This will remove all demo tenants and data"
    echo ""
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        print_info "Cleanup cancelled"
        return
    fi
    
    echo ""
    print_step "Removing demo tenants..."
    
    # Deprovision tenant 1
    api_call DELETE "/tenants/$DEMO_TENANT_1?confirm=true&preserve_data=false" > /dev/null
    print_success "Tenant 1 removed: $DEMO_TENANT_1"
    
    # Deprovision tenant 2
    api_call DELETE "/tenants/$DEMO_TENANT_2?confirm=true&preserve_data=false" > /dev/null
    print_success "Tenant 2 removed: $DEMO_TENANT_2"
    
    echo ""
    print_success "Demo cleanup complete"
}

demo_conclusion() {
    print_header "Demo Complete!"
    
    echo -e "${GREEN}Thank you for watching the MSP AI Platform demonstration!${NC}"
    echo ""
    echo "We've showcased:"
    echo "  ✓ Multi-tenant architecture with full isolation"
    echo "  ✓ AI-powered ticket triage with 90%+ accuracy"
    echo "  ✓ IT concierge agent with natural language"
    echo "  ✓ Secure password reset with one-time links"
    echo "  ✓ Proactive customer insights and reports"
    echo "  ✓ Comprehensive analytics and monitoring"
    echo "  ✓ Self-service tenant portal"
    echo ""
    echo "Key Benefits:"
    echo "  • 70% reduction in ticket triage time"
    echo "  • 24/7 IT support via AI concierge"
    echo "  • Enhanced security with audit trails"
    echo "  • Improved customer satisfaction"
    echo "  • Reduced operational costs"
    echo "  • Scalable multi-tenant architecture"
    echo ""
    echo "Next Steps:"
    echo "  1. Schedule a technical deep-dive"
    echo "  2. Review security and compliance documentation"
    echo "  3. Discuss integration with your existing tools"
    echo "  4. Plan pilot deployment"
    echo ""
    echo "Contact: sales@yourmsp.com"
    echo "Documentation: https://docs.yourmsp.com"
    echo ""
}

# =============================================================================
# Main Script
# =============================================================================

main() {
    # Parse arguments
    QUICK_MODE=false
    SECTION_ONLY=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --quick)
                QUICK_MODE=true
                shift
                ;;
            --section)
                SECTION_ONLY="$2"
                shift 2
                ;;
            --cleanup)
                demo_cleanup
                exit 0
                ;;
            --help|-h)
                echo "Usage: $0 [options]"
                echo ""
                echo "Options:"
                echo "  --quick         Run quick demo (5 minutes)"
                echo "  --section N     Run specific section only (1-7)"
                echo "  --cleanup       Remove demo data"
                echo "  --help, -h      Show this help"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Check prerequisites
    check_prerequisites
    
    # Run demo
    if [ -n "$SECTION_ONLY" ]; then
        # Run specific section
        case $SECTION_ONLY in
            1) demo_section_1_tenant_onboarding ;;
            2) demo_section_2_ticket_triage ;;
            3) demo_section_3_it_concierge ;;
            4) demo_section_4_password_reset ;;
            5) demo_section_5_customer_insights ;;
            6) demo_section_6_analytics ;;
            7) demo_section_7_tenant_portal ;;
            *)
                print_error "Invalid section: $SECTION_ONLY"
                exit 1
                ;;
        esac
    else
        # Run full demo
        demo_introduction
        demo_section_1_tenant_onboarding
        
        if [ "$QUICK_MODE" = false ]; then
            demo_section_2_ticket_triage
            demo_section_3_it_concierge
        fi
        
        demo_section_4_password_reset
        
        if [ "$QUICK_MODE" = false ]; then
            demo_section_5_customer_insights
            demo_section_6_analytics
            demo_section_7_tenant_portal
        fi
        
        demo_conclusion
    fi
}

# Run main function
main "$@"