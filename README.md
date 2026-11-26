## Intelligent-Ticket-Triage-and-Enrichment-Agent
The MSP AI Platform is an enterprise-grade, multi-tenant artificial intelligence system built on Amazon Web Services (AWS). It automates IT service delivery for Managed Service Providers (MSPs) through AI-powered ticket triage, an interactive IT concierge agent, proactive customer insights, and comprehensive observability.

### 1. What exactly is the software product we have created?

This is a multi-tenant, AI-powered IT Service Management (ITSM) automation platform. It is a cloud-native, serverless software solution built on AWS that integrates directly with Microsoft Teams, ConnectWise PSA, and NinjaOne RMM. It acts as an intelligent layer between end-users and IT systems, automating ticket triage, providing 24/7 conversational IT support, and generating proactive strategic insights.

### 2. What is the platform's primary goal?

Primary Goal: To scale IT support operations by 10x without proportional increases in headcount, while simultaneously improving customer satisfaction, reducing operational costs, and maintaining strict enterprise-grade security and compliance (SOC 2 / ISO 27001).

### 3. What key tasks does it address?
a) Intelligent Triage: Automatically categorizing, prioritizing, and routing incoming IT tickets.
b) Tier 1 Automation: Resolving routine user requests (password resets, account unlocks, device status checks) without human intervention.
c) Proactive Communication: Automatically generating and delivering daily digests and weekly strategic insights to customers.
d) Secure Identity Management: Executing sensitive operations (like password resets) via a cryptographically secure, two-phase approval workflow.

### 4. What are its main functions?
a) Conversational AI Agent: A Microsoft Teams bot powered by Large Language Models (LLMs) with access to specific IT tools.
b) Retrieval-Augmented Generation (RAG): A tenant-scoped Knowledge Base that allows the AI to answer questions based on the customer’s specific internal documentation.
c) Self-Service Tenant Portal: A web interface where customers can view their health score, manage custom monitoring rules, configure webhooks, and view audit logs.
d) Automated Lifecycle Management: API-driven tenant onboarding (in <15 minutes) and safe, compliant deprovisioning.
e) Comprehensive Observability: Real-time health scoring, CloudWatch dashboards, and advanced analytics for platform performance and AI effectiveness.

### 5. In which areas of industry can this software be used?
a) Managed Service Providers (MSPs): The primary target market, to scale support across multiple diverse customer environments.
b) Internal Enterprise IT Departments: Large organizations (1,000+ employees) wanting to automate their internal IT helpdesk.
c) IT Outsourcing (ITO) Firms: Companies managing IT for specific industries (e.g., healthcare, legal) that require strict data isolation and compliance.

### 6. For which tasks is it best suited, and for which is it NOT recommended?
#### 6.1. Best Suited For:
a) High-volume, repetitive Tier 1 support (password resets, software installation requests, basic troubleshooting).
b) Information retrieval (querying internal wikis, checking ticket status, looking up device specs).
c) Standardized IT environments using common tools (Microsoft 365, ConnectWise, NinjaOne).

#### 6.2. NOT Recommended For:
a) Complex, multi-system architectural troubleshooting requiring deep human intuition.
b) Highly subjective decision-making (e.g., approving exceptional budget overrides).
c) Air-gapped or strictly on-premises environments with no internet connectivity.
d) Scenarios requiring 100% deterministic, zero-hallucination outputs (LLMs are probabilistic by nature, though guardrails mitigate this).

### 7. What are the limitations regarding its use?
a) Third-Party API Dependencies: It is bound by the rate limits, uptime, and API changes of ConnectWise, NinjaOne, and Microsoft Graph.
b) Data Quality Dependency: The RAG Knowledge Base is only as good as the documentation uploaded to it. Poorly written docs yield poor AI answers.
c) Internet Connectivity: Requires consistent, low-latency internet access to communicate with AWS and Microsoft services.
d) LLM Context Limits: Extremely long, complex ticket histories may exceed the model's context window, requiring summarization.

### 8. What are the most promising avenues for its future development?
a) AIOps / Predictive Resolution: Moving from reactive support to predicting and fixing issues (e.g., detecting a failing hard drive via RMM alerts and auto-creating a replacement ticket before the user notices).
b) Voice-Enabled Support: Integrating with Microsoft Teams voice calls for hands-free IT support.
c) Autonomous Remediation: Granting the AI agent permission to execute approved, low-risk remediation scripts (e.g., restarting a specific service) without human approval.
d) Multi-Cloud / Edge Deployment: Packaging the core logic to run in hybrid environments for highly regulated industries.

### 9. What AI software products are utilized within the platform?
a) Amazon Bedrock: The foundational AI service hosting the models.
b) Anthropic Claude 3.5 Sonnet: Used for complex reasoning, ticket triage, and strategic report generation.
c) Anthropic Claude 3 Haiku: Used for simple, high-volume, low-latency tasks (cost optimization).
d) Amazon Titan Text Embeddings v2: Used to convert text documents into vector representations for the Knowledge Base.
e) Amazon Bedrock Guardrails: Used for real-time content filtering, PII redaction, and prompt injection detection.
f) Amazon OpenSearch Serverless (AOSS): The vector database storing the embeddings for RAG.


## MSP AI Platform SetUp and QuickStart:
a) Instructions for using Demonstration Python script, Full-Setup Platform are posted in the directory folder https://github.com/andrzimin72/Intelligent-Ticket-Triage-and-Enrichment-Agent/docs/.

b) For deeper technical details, refer to the companion documents in the directory folder docs/:
- High Architecture, C4 Models and Network Infrastructure (docs/architecture/);
- Technical Whitepaper, Prerequisites, Installation, Configuration, Testing Instructions and Quick Start Guide (docs/instructions/);
- Tables of Risk Register and Risk Matrix, Key Capabilities and Key Performance Indicators (docs/instructions/).

