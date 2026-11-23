## Architecture Diagrams

This directory contains C4 Model architecture diagrams for the MSP AI Platform.

### Diagrams

| Diagram | File | Description |
|---------|------|-------------|
| **System Context** | `c4-context.puml` | System boundary and external actors |
| **Container** | `c4-container.puml` | High-level technology containers |
| **Component: Onboarding** | `c4-component-onboarding.puml` | Tenant onboarding API internals |
| **Component: Teams Bot** | `c4-component-teams-bot.puml` | Teams bot adapter internals |
| **Deployment** | `c4-deployment.puml` | AWS deployment topology |
| **Mermaid Versions** | `c4-mermaid.md` | GitHub-renderable diagrams |
| **Main Documentation** | `ARCHITECTURE.md` | Complete architecture docs |

### Quick Start

#### View Diagrams

**Option 1: Mermaid (easiest)**
- Open `c4-mermaid.md` in GitHub, GitLab, or any Mermaid-compatible viewer
- Diagrams render automatically

**Option 2: PlantUML (professional)**
```bash
# Install PlantUML
brew install plantuml  # macOS
# or
apt-get install plantuml  # Ubuntu

# Render all diagrams
plantuml *.puml

# View generated PNGs
ls *.png
