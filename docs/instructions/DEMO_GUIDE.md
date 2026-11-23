## MSP AI Platform - Demonstration Guide

This guide explains how to run and customize the platform demonstration.

### Overview

The demonstration showcases all core features of the MSP AI platform:

1. **Multi-Tenant Onboarding** - Creating isolated tenant environments
2. **AI Ticket Triage** - Automatic categorization and routing
3. **IT Concierge Agent** - Natural language IT support
4. **Secure Password Reset** - One-time link password resets
5. **Customer Insights** - Proactive weekly reports
6. **Analytics & Monitoring** - Platform-wide observability
7. **Tenant Portal** - Self-service configuration

### Prerequisites

Before running the demo:

- [ ] Platform deployed to dev environment
- [ ] AWS CLI configured with dev profile
- [ ] `jq` installed (`brew install jq` on macOS)
- [ ] `curl` installed
- [ ] Python 3.8+ (for Python version)
- [ ] `requests` library (`pip install requests`)

### Running the Demo

### Bash Version

```bash
# Make script executable
chmod +x scripts/demo.sh

# Run full demo (15-20 minutes)
./scripts/demo.sh

# Run quick demo (5 minutes)
./scripts/demo.sh --quick

# Run specific section
./scripts/demo.sh --section 3

# Clean up demo data
./scripts/demo.sh --cleanup
```

### Python Version

```bash
# Install dependencies
pip install requests

# Run full demo
python scripts/demo.py

# Run quick demo
python scripts/demo.py --quick

# Run specific section
python scripts/demo.py --section 5

# Clean up demo data
python scripts/demo.py --cleanup
```

### Demo Sections

### Section 1: Multi-Tenant Onboarding

Duration: 2-3 minutes

a) What it shows:

-Creating two demo tenants (Acme Corp and Beta Inc)

-Each tenant gets isolated resources

-Custom branding and settings

-Tenant listing and status

b) Key points to emphasize:

-Complete data isolation between tenants

-Separate Bedrock Agent instances

-Custom branding per tenant

-Scalable architecture

### Section 2: AI Ticket Triage

Duration: 2-3 minutes

a) What it shows:

-Incoming ticket simulation

-AI categorization with confidence scores

-Automatic routing recommendations

-Feedback loop for continuous improvement

b) Key points to emphasize:

-90%+ accuracy in categorization

-Reduces triage time by 70%

-Learns from technician feedback

-Integrates with ConnectWise

### Section 3: IT Concierge Agent

Duration: 3-4 minutes

a) What it shows:

-Natural language conversation in Teams

-Account status checks

-Conference room booking

-Audit trail logging

b) Key points to emphasize:

-24/7 availability

-Natural language understanding

-Integrates with Microsoft Graph

-Full audit compliance

### Section 4: Secure Password Reset

Duration: 2-3 minutes

a) What it shows:

-Password reset request via chat

-Identity verification

-One-time link generation

-Security features

b) Key points to emphasize:

-No passwords in chat

-256-bit secure tokens

-15-minute expiration

-Single-use enforcement

-Custom domain for trust

### Section 5: Customer Insights

Duration: 2-3 minutes

a) What it shows:

-Automated weekly analysis

-Trend identification

-Actionable recommendations

-Professional report format

b) Key points to emphasize:

-Proactive customer communication

-Builds trust and value

-Identifies issues before they escalate

-Customizable per tenant

### Section 6: Analytics & Monitoring

Duration: 2-3 minutes

a) What it shows:

-Executive summary

-Health trends over time

-Webhook delivery statistics

-CloudWatch dashboards

b) Key points to emphasize:

-Real-time monitoring

-Historical trend analysis

-Cost tracking

-Security event tracking

### Section 7: Tenant Portal

Duration: 2-3 minutes

a) What it shows:

-Self-service portal interface

-API endpoints

-Tenant configuration

-Audit log viewing

b) Key points to emphasize:

-Reduces support tickets

-Secure SSO authentication

-Real-time status updates

-Self-service configuration

### Customizing the Demo

#### Using Real Data

To use real tenant data instead of demo data:

a) Edit the demo script

b) Replace DEMO_TENANT_1 and DEMO_TENANT_2 with actual tenant IDs

c) Update branding and settings to match real tenants

d) Use real ticket examples from your history

#### Adding Your Own Scenarios

You can add custom scenarios by:

a) Creating new demo sections

b) Using your actual ticket data

c) Showcasing specific customer success stories

d) Demonstrating unique integrations

#### Recording the Demo
To record the demo for later use:

macOS:

```bash
# Using QuickTime
# Or use asciinema for terminal recording
brew install asciinema
asciinema rec demo.rec
./scripts/demo.sh
# Upload to asciinema.org or convert to GIF
```

Linux:

```bash
# Using asciinema
sudo apt install asciinema
asciinema rec demo.rec
./scripts/demo.sh
```

Windows:

```powershell
# Using Windows Terminal recording
# Or use a screen recording tool like OBS
```

#### Success Metrics

Track these metrics to measure demo effectiveness:

a) Completion rate: % of demos completed without errors

b) Engagement: Number of questions asked

c) Follow-up requests: % requesting more information

d) Conversion rate: % moving to pilot/production

e) Demo duration: Average time to complete

f) Technical issues: Number of issues encountered

### What the Demo Shows

Multi-Tenant Architecture - Creates two isolated tenants

Ticket Triage - Simulates AI processing a support ticket

IT Concierge - Shows Teams conversation with agent

Password Reset - Demonstrates secure reset flow

Customer Insights - Shows weekly report generation

Analytics - Displays metrics and dashboards

Tenant Portal - Shows self-service interface

### Customization Tips

#### Use Real Data:

Edit DEMO_TENANT_1 and DEMO_TENANT_2 to use actual tenant IDs

Replace demo ticket examples with real ones from your history

Update branding to match your actual customers

#### Add Scenarios:

Create custom demo sections for specific use cases

Add your unique integrations

Showcase customer success stories

#### Record the Demo:

```bash
# Using asciinema (recommended)
brew install asciinema  # macOS
asciinema rec demo.rec
./scripts/demo.sh
# Upload to asciinema.org or share the .rec file
```

### Quick Start

```bash
# 1. Make scripts executable
chmod +x scripts/demo.sh scripts/demo.py

# 2. Set environment variables
export ENV=dev
export API_URL=$(terraform output -raw tenant_onboarding_api_url)
export API_KEY=$(aws apigatewayv2 get-api-key --api-key $(terraform output -raw onboarding_api_key_id) --include-value --query 'value' --output text)

# 3. Run the demo
./scripts/demo.sh
```

#### This demo script will help you:

Showcase the platform to stakeholders

Train new team members

Validate all components work together

Create marketing materials

Prepare for sales presentations


