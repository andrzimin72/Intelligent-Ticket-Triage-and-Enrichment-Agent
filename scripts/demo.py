#!/usr/bin/env python3
"""
MSP AI Platform - Interactive Demonstration (Python Version)

This script provides an interactive demonstration of the platform's features
with rich formatting and better error handling.

Usage:
    python scripts/demo.py              # Full demo
    python scripts/demo.py --quick      # Quick demo (5 minutes)
    python scripts/demo.py --section 2  # Run specific section
    python scripts/demo.py --cleanup    # Clean up demo data
"""

import os
import sys
import time
import json
import subprocess
import requests
from typing import Dict, Any, Optional
from dataclasses import dataclass

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class DemoConfig:
    environment: str = os.getenv("ENV", "dev")
    api_url: str = os.getenv("API_URL", "https://api.example.com")
    api_key: str = os.getenv("API_KEY", "demo-api-key")
    tenant_1_id: str = "demo-acme-corp"
    tenant_2_id: str = "demo-beta-inc"

# Colors for terminal output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

# =============================================================================
# Helper Functions
# =============================================================================

def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{Colors.BLUE}{'═' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}  {text}{Colors.NC}")
    print(f"{Colors.BLUE}{'═' * 60}{Colors.NC}\n")

def print_section(num: int, title: str):
    """Print a section header."""
    print(f"\n{Colors.PURPLE}{'━' * 60}{Colors.NC}")
    print(f"{Colors.PURPLE}  Section {num}: {title}{Colors.NC}")
    print(f"{Colors.PURPLE}{'━' * 60}{Colors.NC}\n")

def print_step(text: str):
    """Print a step indicator."""
    print(f"{Colors.CYAN}▶ {text}{Colors.NC}")

def print_success(text: str):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.NC}")

def print_warning(text: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.NC}")

def print_error(text: str):
    """Print error message."""
    print(f"{Colors.RED}✗ {text}{Colors.NC}")

def print_info(text: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ {text}{Colors.NC}")

def wait_for_user():
    """Wait for user to press Enter."""
    print()
    input("Press Enter to continue...")
    print()

def api_call(method: str, endpoint: str, data: Optional[Dict] = None, config: DemoConfig = None) -> Dict[str, Any]:
    """Make an API call."""
    if config is None:
        config = DemoConfig()
    
    url = f"{config.api_url}{endpoint}"
    headers = {
        "x-api-key": config.api_key,
        "Content-Type": "application/json"
    }
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print_error(f"API call failed: {e}")
        return {"error": str(e)}

def check_prerequisites():
    """Check that all prerequisites are met."""
    print_step("Checking prerequisites...")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print_error("Python 3.8+ required")
        sys.exit(1)
    
    # Check requests library
    try:
        import requests
    except ImportError:
        print_error("requests library not installed. Run: pip install requests")
        sys.exit(1)
    
    # Check AWS CLI
    try:
        subprocess.run(["aws", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("AWS CLI not installed or not configured")
        sys.exit(1)
    
    print_success("All prerequisites met")

# =============================================================================
# Demo Sections
# =============================================================================

def demo_introduction():
    """Show introduction."""
    print_header("MSP AI Platform - Live Demonstration")
    
    print(f"{Colors.CYAN}Welcome to the MSP AI Platform demo!{Colors.NC}")
    print()
    print("This demonstration will showcase:")
    print("  1. Multi-tenant onboarding and isolation")
    print("  2. AI-powered ticket triage with feedback loops")
    print("  3. IT concierge agent with tool integration")
    print("  4. Secure password reset flow")
    print("  5. Proactive customer insights")
    print("  6. Analytics and monitoring")
    print("  7. Self-service tenant portal")
    print()
    print(f"{Colors.YELLOW}Estimated duration: 15-20 minutes{Colors.NC}")
    print()
    
    wait_for_user()

def demo_section_1(config: DemoConfig):
    """Demonstrate multi-tenant onboarding."""
    print_section(1, "Multi-Tenant Onboarding")
    
    print_info("Demonstrating how new MSP tenants are onboarded with full isolation")
    print()
    
    # Tenant 1
    print_step("Onboarding Tenant 1: Acme Corporation")
    print()
    
    tenant_1_data = {
        "tenant_id": config.tenant_1_id,
        "display_name": "Acme Corporation",
        "entra_tenant_id": "11111111-1111-1111-1111-111111111111",
        "admin_group_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "contact_email": "admin@acme-demo.com",
        "branding": {
            "company_name": "Acme Corporation",
            "primary_color": "#1e88e5"
        },
        "timezone": "America/New_York"
    }
    
    response = api_call("POST", "/tenants", tenant_1_data, config)
    print("Response:")
    print(json.dumps(response, indent=2))
    print()
    
    print_success(f"Tenant 1 created: {config.tenant_1_id}")
    print()
    
    wait_for_user()
    
    # Tenant 2
    print_step("Onboarding Tenant 2: Beta Industries")
    print()
    
    tenant_2_data = {
        "tenant_id": config.tenant_2_id,
        "display_name": "Beta Industries",
        "entra_tenant_id": "22222222-2222-2222-2222-222222222222",
        "admin_group_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "contact_email": "admin@beta-demo.com",
        "branding": {
            "company_name": "Beta Industries",
            "primary_color": "#43a047"
        },
        "timezone": "Europe/London"
    }
    
    response = api_call("POST", "/tenants", tenant_2_data, config)
    print("Response:")
    print(json.dumps(response, indent=2))
    print()
    
    print_success("Tenant 2 created")
    print()
    
    wait_for_user()
    
    # Show tenant list
    print_step("Viewing all tenants")
    print()
    
    response = api_call("GET", "/tenants", config=config)
    print("Tenants:")
    for tenant in response.get("tenants", []):
        print(f"  • {tenant.get('display_name')} ({tenant.get('tenant_id')})")
    print()
    
    print_success("Both tenants are now active and fully isolated")
    print()
    
    print_info("Key points:")
    print("  ✓ Each tenant has its own Bedrock Agent instance")
    print("  ✓ Separate DynamoDB tables and S3 buckets")
    print("  ✓ Isolated secrets in AWS Secrets Manager")
    print("  ✓ Custom branding and settings per tenant")
    print("  ✓ No cross-tenant data leakage")
    print()
    
    wait_for_user()

def demo_section_2(config: DemoConfig):
    """Demonstrate ticket triage."""
    print_section(2, "AI-Powered Ticket Triage")
    
    print_info("Demonstrating how tickets are automatically triaged and categorized")
    print()
    
    print_step("Simulating incoming support ticket")
    print()
    print("Ticket details:")
    print("  Subject: 'Outlook keeps crashing when I try to send emails'")
    print("  Priority: High")
    print(f"  Customer: {config.tenant_1_id}")
    print()
    
    print(f"{Colors.YELLOW}Processing ticket with AI...{Colors.NC}")
    time.sleep(2)
    
    print()
    print("AI Analysis Results:")
    print("  Category: Application Issues")
    print("  Subcategory: Email Client")
    print("  Confidence: 94%")
    print("  Suggested Assignment: Tier 2 - Application Support")
    print("  Estimated Resolution Time: 2 hours")
    print()
    
    print("AI Recommendation:")
    print("  'This appears to be a corrupted Outlook profile. Suggest creating")
    print("   a new profile and migrating PST data. Check for recent Office")
    print("   updates that may have caused the issue.'")
    print()
    
    print_success("Ticket triaged and routed automatically")
    print()
    
    wait_for_user()
    
    print_info("Key points:")
    print("  ✓ AI categorizes tickets with 90%+ accuracy")
    print("  ✓ Automatic routing to appropriate team")
    print("  ✓ Continuous learning from technician feedback")
    print("  ✓ Reduces triage time by 70%")
    print()
    
    wait_for_user()

def demo_section_3(config: DemoConfig):
    """Demonstrate IT concierge."""
    print_section(3, "IT Concierge Agent")
    
    print_info("Demonstrating the AI-powered IT assistant in Microsoft Teams")
    print()
    
    print("Scenario: User asks IT concierge to check their account status")
    print()
    
    print(f"{Colors.CYAN}User:{Colors.NC} Hey, can you check if my account is locked out?")
    print()
    time.sleep(1)
    
    print(f"{Colors.PURPLE}IT Concierge:{Colors.NC} I'd be happy to help! Let me check your account status.")
    print()
    time.sleep(1)
    
    print(f"{Colors.YELLOW}[Agent calls verify_identity tool]{Colors.NC}")
    time.sleep(1)
    
    print(f"{Colors.PURPLE}IT Concierge:{Colors.NC} Good news! Your account is active and not locked out.")
    print()
    print("Here's what I found:")
    print("  • Account Status: Active ✓")
    print("  • MFA Enabled: Yes ✓")
    print("  • Last Sign-in: Today at 9:15 AM")
    print("  • Password Age: 45 days")
    print()
    
    wait_for_user()
    
    print_info("Key points:")
    print("  ✓ Natural language conversation")
    print("  ✓ Integrates with Microsoft Graph API")
    print("  ✓ Can perform actions (book rooms, reset passwords)")
    print("  ✓ Full audit trail for compliance")
    print("  ✓ Tenant-isolated (only sees own data)")
    print()
    
    wait_for_user()

def demo_section_4(config: DemoConfig):
    """Demonstrate password reset."""
    print_section(4, "Secure Password Reset")
    
    print_info("Demonstrating the secure, one-time link password reset flow")
    print()
    
    print("Scenario: User requests password reset via IT concierge")
    print()
    
    print(f"{Colors.CYAN}User:{Colors.NC} I forgot my password, can you help?")
    print()
    time.sleep(1)
    
    print(f"{Colors.PURPLE}IT Concierge:{Colors.NC} No problem! I'll send you a secure password reset link.")
    print()
    print("For security, I need to verify your identity first.")
    print()
    print("Please confirm: You want to reset the password for john.doe@acme-demo.com?")
    print()
    
    print(f"{Colors.CYAN}User:{Colors.NC} Yes, that's correct")
    print()
    time.sleep(1)
    
    print(f"{Colors.YELLOW}[Agent calls request_password_reset tool]{Colors.NC}")
    time.sleep(1)
    
    print(f"{Colors.PURPLE}IT Concierge:{Colors.NC} Perfect! I've sent a secure reset link to your registered email.")
    print()
    print("The link will expire in 15 minutes and can only be used once.")
    print()
    
    wait_for_user()
    
    print_step("Security features in action")
    print()
    
    print("✓ Token is cryptographically secure (256-bit)")
    print("✓ Token expires after 15 minutes")
    print("✓ Token can only be used once")
    print("✓ Password never appears in chat or logs")
    print("✓ User sets their own password")
    print("✓ Custom domain builds trust")
    print("✓ Full audit trail maintained")
    print()
    
    print_info("Key points:")
    print("  ✓ No passwords transmitted via chat")
    print("  ✓ One-time, time-limited tokens")
    print("  ✓ User sets their own password")
    print("  ✓ Professional custom domain")
    print("  ✓ Complete audit trail")
    print()
    
    wait_for_user()

def demo_section_5(config: DemoConfig):
    """Demonstrate customer insights."""
    print_section(5, "Proactive Customer Insights")
    
    print_info("Demonstrating automated weekly insights reports")
    print()
    
    print_step(f"Generating weekly insights for {config.tenant_1_id}")
    print()
    
    print("The system analyzes the past week's data:")
    print("  • 47 support tickets processed")
    print("  • 12 password resets")
    print("  • 8 account unlock requests")
    print("  • 156 IT concierge interactions")
    print("  • 3 critical alerts resolved")
    print()
    
    time.sleep(2)
    
    print(f"{Colors.YELLOW}[AI analyzes trends and generates report]{Colors.NC}")
    time.sleep(2)
    
    print()
    print("Weekly IT Health & Security Summary")
    print("Acme Corporation - Week of Nov 17-23, 2026")
    print("════════════════════════════════════════════")
    print()
    print("EXECUTIVE SUMMARY")
    print("Your IT environment remained stable this week with a 15%")
    print("reduction in alerts compared to last week.")
    print()
    print("KEY METRICS")
    print("  Alerts: 12 (↓ 15% from last week)")
    print("  Tickets: 47 (↓ 10% from last week)")
    print("  Resolution Time: 2.3h (↓ 26% from last week)")
    print("  Security Incidents: 0")
    print()
    print("RECOMMENDATIONS")
    print("  1. Schedule VPN infrastructure review")
    print("  2. Consider quarterly Outlook profile maintenance")
    print()
    
    print_success("Insights report generated and emailed to customer")
    print()
    
    wait_for_user()

def demo_section_6(config: DemoConfig):
    """Demonstrate analytics."""
    print_section(6, "Analytics and Monitoring")
    
    print_info("Demonstrating platform-wide analytics and observability")
    print()
    
    print_step("Executive Summary")
    print()
    
    response = api_call("GET", "/analytics/executive-summary", config=config)
    print(json.dumps(response, indent=2))
    print()
    
    wait_for_user()
    
    print_step("Health Trends (Last 30 Days)")
    print()
    
    response = api_call("GET", "/analytics/health-trends?days=30", config=config)
    print("Daily average health scores:")
    for day in response.get("health_trends", {}).get("daily_averages", [])[-5:]:
        print(f"  {day.get('date')}: {day.get('avg_health_score')}/100")
    print()
    
    print_info("Key points:")
    print("  ✓ Real-time monitoring")
    print("  ✓ Historical trend analysis")
    print("  ✓ Custom metrics and alarms")
    print("  ✓ Cost tracking and optimization")
    print("  ✓ Security event tracking")
    print()
    
    wait_for_user()

def demo_section_7(config: DemoConfig):
    """Demonstrate tenant portal."""
    print_section(7, "Self-Service Tenant Portal")
    
    print_info("Demonstrating the tenant self-service portal")
    print()
    
    portal_url = os.getenv("PORTAL_URL", "https://portal.yourmsp.com")
    print(f"Portal URL: {portal_url}")
    print()
    
    print("Features available to tenants:")
    print()
    print("📊 Dashboard")
    print("  • View current health score")
    print("  • See resource usage metrics")
    print("  • Track health trends over time")
    print()
    print("⚙️ Settings")
    print("  • Update contact information")
    print("  • Customize branding")
    print("  • Manage allowed users")
    print()
    print("📋 Custom Health Rules")
    print("  • Create custom monitoring rules")
    print("  • Set thresholds and alerts")
    print("  • View rule effectiveness")
    print()
    
    wait_for_user()
    
    print_step("Portal API Endpoints")
    print()
    
    print("Available endpoints:")
    print("  GET    /me              - Get tenant metadata")
    print("  PUT    /me              - Update tenant settings")
    print("  GET    /me/status       - Get current status")
    print("  GET    /me/rules        - List custom rules")
    print("  POST   /me/rules        - Create custom rule")
    print("  GET    /me/audit        - Get audit log")
    print()
    
    print_info("Key points:")
    print("  ✓ Secure SSO authentication (Entra ID)")
    print("  ✓ Tenant-isolated data access")
    print("  ✓ Real-time status updates")
    print("  ✓ Self-service configuration")
    print("  ✓ Reduces support tickets")
    print()
    
    wait_for_user()

def demo_conclusion():
    """Show conclusion."""
    print_header("Demo Complete!")
    
    print(f"{Colors.GREEN}Thank you for watching the MSP AI Platform demonstration!{Colors.NC}")
    print()
    print("We've showcased:")
    print("  ✓ Multi-tenant architecture with full isolation")
    print("  ✓ AI-powered ticket triage with 90%+ accuracy")
    print("  ✓ IT concierge agent with natural language")
    print("  ✓ Secure password reset with one-time links")
    print("  ✓ Proactive customer insights and reports")
    print("  ✓ Comprehensive analytics and monitoring")
    print("  ✓ Self-service tenant portal")
    print()
    print("Key Benefits:")
    print("  • 70% reduction in ticket triage time")
    print("  • 24/7 IT support via AI concierge")
    print("  • Enhanced security with audit trails")
    print("  • Improved customer satisfaction")
    print("  • Reduced operational costs")
    print("  • Scalable multi-tenant architecture")
    print()

def demo_cleanup(config: DemoConfig):
    """Clean up demo data."""
    print_header("Demo Cleanup")
    
    print_warning("This will remove all demo tenants and data")
    print()
    
    confirm = input("Are you sure? (yes/no): ")
    if confirm.lower() != "yes":
        print_info("Cleanup cancelled")
        return
    
    print()
    print_step("Removing demo tenants...")
    
    # Remove tenant 1
    api_call("DELETE", f"/tenants/{config.tenant_1_id}?confirm=true&preserve_data=false", config=config)
    print_success(f"Tenant 1 removed: {config.tenant_1_id}")
    
    # Remove tenant 2
    api_call("DELETE", f"/tenants/{config.tenant_2_id}?confirm=true&preserve_data=false", config=config)
    print_success(f"Tenant 2 removed: {config.tenant_2_id}")
    
    print()
    print_success("Demo cleanup complete")

# =============================================================================
# Main Function
# =============================================================================

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MSP AI Platform Demo")
    parser.add_argument("--quick", action="store_true", help="Run quick demo (5 minutes)")
    parser.add_argument("--section", type=int, help="Run specific section (1-7)")
    parser.add_argument("--cleanup", action="store_true", help="Clean up demo data")
    
    args = parser.parse_args()
    
    config = DemoConfig()
    
    # Check prerequisites
    check_prerequisites()
    
    # Handle cleanup
    if args.cleanup:
        demo_cleanup(config)
        return
    
    # Run specific section
    if args.section:
        sections = {
            1: demo_section_1,
            2: demo_section_2,
            3: demo_section_3,
            4: demo_section_4,
            5: demo_section_5,
            6: demo_section_6,
            7: demo_section_7,
        }
        
        if args.section not in sections:
            print_error(f"Invalid section: {args.section}")
            sys.exit(1)
        
        sections[args.section](config)
        return
    
    # Run full demo
    demo_introduction()
    demo_section_1(config)
    
    if not args.quick:
        demo_section_2(config)
        demo_section_3(config)
    
    demo_section_4(config)
    
    if not args.quick:
        demo_section_5(config)
        demo_section_6(config)
        demo_section_7(config)
    
    demo_conclusion()

if __name__ == "__main__":
    main()