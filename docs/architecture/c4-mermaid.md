# MSP AI Platform - C4 Architecture (Mermaid)

These diagrams use Mermaid syntax and render directly in GitHub, GitLab, and most Markdown viewers.

## Level 1: System Context

```mermaid
graph TB
    subgraph Users
        MSP_STAFF[MSP IT Staff]
        TECHNICIAN[MSP Technician]
        LEADERSHIP[MSP Leadership]
        END_USER[End User]
        CUSTOMER[Customer IT Liaison]
    end
    
    subgraph MSP AI Platform
        TRIAGE[Ticket Triage System]
        CONCIERGE[IT Concierge Agent]
        INSIGHTS[Customer Insights]
        PORTAL[Tenant Portal]
        ANALYTICS[Analytics Engine]
    end
    
    subgraph External Systems
        TEAMS[Microsoft Teams]
        ENTRA[Entra ID]
        CW[ConnectWise PSA]
        NINJA[NinjaOne RMM]
        BEDROCK[Amazon Bedrock]
        SES[Amazon SES]
        ALERTS[Slack / PagerDuty]
    end
    
    END_USER -->|Chats| TEAMS
    TEAMS --> CONCIERGE
    CONCIERGE --> ENTRA
    CONCIERGE --> BEDROCK
    
    TECHNICIAN --> CW
    CW --> TRIAGE
    TRIAGE --> BEDROCK
    TRIAGE --> NINJA
    
    CUSTOMER -->|Receives reports| SES
    INSIGHTS --> SES
    INSIGHTS --> BEDROCK
    
    LEADERSHIP --> ANALYTICS
    ANALYTICS --> BEDROCK
    ANALYTICS --> ALERTS
    
    MSP_STAFF --> PORTAL
    PORTAL --> ENTRA
```

## Level 2: Container Diagram

```mermaid
graph TB
    subgraph API Layer
        ONBOARDING_API[Tenant Onboarding API]
        RESET_API[Password Reset API]
        PORTAL_API[Portal API]
        WEBHOOK_API[Webhooks API]
    end
    
    subgraph AI Services
        TEAMS_BOT[Teams Bot Adapter]
        AGENTS[Per-Tenant Bedrock Agents]
        KB[Knowledge Base + AOSS]
    end
    
    subgraph Core Lambdas
        IDENTITY[Identity Tools]
        TICKETS[Ticket Tools]
        DEVICES[Device Tools]
        CALENDAR[Calendar Tools]
        TRIAGE_ORCH[Triage Orchestrator]
        TRIAGE_WORKER[Triage Worker]
    end
    
    subgraph Customer-Facing
        DIGEST_ORCH[Digest Orchestrator]
        DIGEST_WORKER[Digest Worker]
        INSIGHTS_ORCH[Insights Orchestrator]
        INSIGHTS_WORKER[Insights Worker]
    end
    
    subgraph Multi-Tenant
        PROV_WORKER[Provisioning Worker]
        STATUS_SNAP[Status Snapshot]
        WEBHOOK_NOTIF[Webhook Notifier]
        ANALYTICS_AGG[Analytics Aggregation]
    end
    
    subgraph Feedback Loops
        FB_COLLECTOR[Feedback Collector]
        FB_SYNC[Feedback Sync]
        AGENT_FB[Agent Feedback]
    end
    
    subgraph Data Stores
        DDB[(DynamoDB - 15 tables)]
        S3[(S3 - 5 buckets)]
        SQS[(SQS - 6 queues)]
        SM[(Secrets Manager)]
    end
    
    subgraph External
        TEAMS[Microsoft Teams]
        ENTRA[Entra ID]
        CW[ConnectWise]
        NINJA[NinjaOne]
        BEDROCK[Amazon Bedrock]
        SES[Amazon SES]
    end
    
    TEAMS --> TEAMS_BOT
    TEAMS_BOT --> AGENTS
    AGENTS --> BEDROCK
    AGENTS --> KB
    
    IDENTITY --> ENTRA
    TICKETS --> CW
    DEVICES --> NINJA
    CALENDAR --> ENTRA
    
    TRIAGE_ORCH --> SQS
    TRIAGE_WORKER --> BEDROCK
    
    DIGEST_WORKER --> BEDROCK
    DIGEST_WORKER --> SES
    INSIGHTS_WORKER --> BEDROCK
    INSIGHTS_WORKER --> SES
    
    FB_SYNC --> S3
    STATUS_SNAP --> DDB
    ANALYTICS_AGG --> DDB
    
    ONBOARDING_API --> SQS
    PROV_WORKER --> BEDROCK
    PROV_WORKER --> DDB
    
    TEAMS_BOT --> DDB
    TEAMS_BOT --> S3
    WEBHOOK_NOTIF --> DDB
```

## Level 3: Component - Tenant Onboarding API

```mermaid
graph TB
    subgraph Tenant Onboarding API
        ROUTER[Request Router]
        
        subgraph Lifecycle
            ONBOARD[Onboarding Handler]
            DEPROV[Deprovision Handler]
            HYBRID[Hybrid Mode Logic]
        end
        
        subgraph Status
            STATUS_COMP[Status Computation]
            STATUS_CACHE[Status Cache]
            SYS_STATUS[System Status]
        end
        
        subgraph Analytics
            HEALTH_TRENDS[Health Trends]
            WEBHOOK_STATS[Webhook Delivery Stats]
            RULE_STATS[Rule Effectiveness]
            EXEC_SUMMARY[Executive Summary]
        end
        
        subgraph Helpers
            TENANT_RESOLVER[Tenant Resolver]
            AGENT_VERIFIER[Agent Verifier]
            METRICS_EMITTER[CloudWatch Metrics]
        end
    end
    
    subgraph Data
        TENANT_REG[(Tenant Registry)]
        CACHE_DB[(Status Cache)]
        ANALYTICS_DB[(Analytics Summary)]
        PROV_QUEUE[(Provisioning Queue)]
        BEDROCK_API[Bedrock Agent API]
        CW[CloudWatch]
    end
    
    ROUTER --> ONBOARD
    ROUTER --> DEPROV
    ROUTER --> STATUS_COMP
    ROUTER --> HEALTH_TRENDS
    
    ONBOARD --> TENANT_RESOLVER
    ONBOARD --> HYBRID
    ONBOARD --> PROV_QUEUE
    ONBOARD --> TENANT_REG
    
    HYBRID --> AGENT_VERIFIER
    AGENT_VERIFIER --> BEDROCK_API
    
    STATUS_COMP --> STATUS_CACHE
    STATUS_CACHE --> CACHE_DB
    STATUS_COMP --> TENANT_REG
    STATUS_COMP --> METRICS_EMITTER
    METRICS_EMITTER --> CW
    
    HEALTH_TRENDS --> ANALYTICS_DB
    WEBHOOK_STATS --> ANALYTICS_DB
    RULE_STATS --> ANALYTICS_DB
    EXEC_SUMMARY --> ANALYTICS_DB
```

## Data Flow: Password Reset

```mermaid
sequenceDiagram
    participant U as End User
    participant T as Microsoft Teams
    participant B as Teams Bot
    participant A as Bedrock Agent
    participant I as Identity Tools
    participant G as Graph API
    participant R as Reset Lambda
    participant D as DynamoDB
    participant S as SES
    participant E as Email
    
    U->>T: "I forgot my password"
    T->>B: Bot Framework message
    B->>B: Validate JWT
    B->>B: Resolve tenant
    B->>A: Invoke agent
    A->>I: request_password_reset
    I->>G: Verify user identity
    G-->>I: User info
    I->>I: Create confirmation
    I-->>A: Pending approval
    A-->>B: Response + card
    B-->>T: Adaptive Card
    T-->>U: Shows Approve/Deny
    
    U->>T: Clicks Approve
    T->>B: Invoke activity
    B->>I: Approve operation
    I->>D: Update status
    B-->>T: "Approved"
    
    U->>T: "Continue"
    T->>B: Bot Framework message
    B->>A: Invoke agent
    A->>I: execute_password_reset
    I->>I: Generate token
    I->>D: Store token
    I->>R: Build reset URL
    I->>S: Send email
    S->>E: Reset email
    E-->>U: Receives email
    I-->>A: Success
    A-->>B: Response
    B-->>T: "Email sent"
    T-->>U: Confirmation
```

## Multi-Tenant Isolation

```mermaid
graph LR
    subgraph Tenant A - Acme Corp
        A_AGENT[Bedrock Agent A]
        A_SECRETS[Secrets A]
        A_EXAMPLES[S3 Examples A]
        A_KB[KB Documents A]
        A_DATA[DynamoDB Data A]
    end
    
    subgraph Tenant B - Beta Inc
        B_AGENT[Bedrock Agent B]
        B_SECRETS[Secrets B]
        B_EXAMPLES[S3 Examples B]
        B_KB[KB Documents B]
        B_DATA[DynamoDB Data B]
    end
    
    subgraph Shared Infrastructure
        API[API Gateway]
        LAMBDAS[Lambda Functions]
        REGISTRY[Tenant Registry]
    end
    
    API --> A_AGENT
    API --> B_AGENT
    LAMBDAS --> A_SECRETS
    LAMBDAS --> B_SECRETS
    A_AGENT --> A_EXAMPLES
    B_AGENT --> B_EXAMPLES
    A_AGENT --> A_KB
    B_AGENT --> B_KB
    A_AGENT --> A_DATA
    B_AGENT --> B_DATA
    
    LAMBDAS --> REGISTRY
```