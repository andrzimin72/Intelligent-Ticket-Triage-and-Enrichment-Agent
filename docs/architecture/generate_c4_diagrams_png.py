import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import os

def draw_c4_diagrams():
    # C4 Color Palette
    colors = {
        'person': '#08427B', 'system': '#1168BD', 'container': '#438DD5',
        'external': '#999999', 'bg': '#FFFFFF', 'text_dark': '#333333',
        'line': '#666666', 'label': '#D9480F'
    }

    # ==========================================
    # DIAGRAM 1: SYSTEM CONTEXT
    # ==========================================
    fig1, ax1 = plt.subplots(figsize=(12, 8))
    ax1.set_xlim(0, 12); ax1.set_ylim(0, 8); ax1.axis('off')
    fig1.patch.set_facecolor(colors['bg'])

    def draw_box(ax, x, y, w, h, label, sublabel, color, text_color='white'):
        rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05", facecolor=color, edgecolor='#333333', linewidth=1.5)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2 + 0.2, label, ha='center', va='center', fontsize=12, fontweight='bold', color=text_color)
        ax.text(x + w/2, y + h/2 - 0.25, sublabel, ha='center', va='center', fontsize=9, color=text_color)

    def draw_person(ax, x, y, label, sublabel):
        circle = plt.Circle((x, y+0.4), 0.25, color=colors['person'], zorder=2)
        ax.add_patch(circle)
        body = FancyBboxPatch((x-0.35, y-0.6), 0.7, 0.8, boxstyle="round,pad=0.05", facecolor=colors['person'], edgecolor='#333333', linewidth=1.5, zorder=2)
        ax.add_patch(body)
        ax.text(x, y - 1.0, label, ha='center', va='top', fontsize=11, fontweight='bold', color=colors['text_dark'])
        ax.text(x, y - 1.3, sublabel, ha='center', va='top', fontsize=9, color=colors['external'])

    def draw_arrow(ax, x1, y1, x2, y2, label):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=colors['line'], lw=1.5))
        if label:
            mid_x, mid_y = (x1+x2)/2, (y1+y2)/2
            ax.text(mid_x, mid_y + 0.15, label, ha='center', fontsize=9, color=colors['label'], bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.9))

    # Draw Context Diagram
    draw_box(ax1, 4.5, 2.5, 4, 3, "MSP AI Platform", "Automated IT Service & AI Triage", colors['system'])
    draw_person(ax1, 1.5, 6.5, "MSP Admin", "Platform Manager")
    draw_person(ax1, 1.5, 4.0, "MSP Technician", "Support Staff")
    draw_person(ax1, 1.5, 1.5, "End User", "via MS Teams")
    
    draw_box(ax1, 9.5, 6.5, 2.5, 1.2, "Microsoft Teams", "Bot Framework", colors['external'])
    draw_box(ax1, 9.5, 4.5, 2.5, 1.2, "ConnectWise", "PSA / REST API", colors['external'])
    draw_box(ax1, 9.5, 2.5, 2.5, 1.2, "Entra ID", "Graph API", colors['external'])
    draw_box(ax1, 9.5, 0.5, 2.5, 1.2, "Amazon Bedrock", "LLM Service", colors['external'])
    
    draw_arrow(ax1, 1.85, 6.5, 4.5, 4.8, "Manages")
    draw_arrow(ax1, 1.85, 4.0, 4.5, 4.0, "Feedback")
    draw_arrow(ax1, 1.85, 1.5, 4.5, 3.2, "Chats")
    draw_arrow(ax1, 8.5, 4.8, 9.5, 7.1, "Bot Msg")
    draw_arrow(ax1, 8.5, 4.0, 9.5, 5.1, "Tickets")
    draw_arrow(ax1, 8.5, 3.2, 9.5, 3.1, "Auth")
    draw_arrow(ax1, 8.5, 2.5, 9.5, 1.1, "Prompts")
    
    ax1.set_title("C4 Level 1: System Context Diagram", fontsize=16, fontweight='bold', pad=20, color=colors['text_dark'])
    fig1.savefig("c4_context_diagram.png", format='png', dpi=150, bbox_inches='tight')
    plt.close(fig1)

    # ==========================================
    # DIAGRAM 2: CONTAINER ARCHITECTURE
    # ==========================================
    fig2, ax2 = plt.subplots(figsize=(14, 10))
    ax2.set_xlim(0, 14); ax2.set_ylim(0, 10); ax2.axis('off')
    fig2.patch.set_facecolor(colors['bg'])

    # Boundary
    boundary = FancyBboxPatch((1, 1), 12, 8, boxstyle="round,pad=0.1", facecolor='#f0f8ff', edgecolor=colors['system'], linewidth=2, linestyle='--')
    ax2.add_patch(boundary)
    ax2.text(1.5, 8.6, "MSP AI Platform (AWS)", fontsize=14, fontweight='bold', color=colors['system'])

    # API Layer
    draw_box(ax2, 1.5, 7.5, 2, 0.8, "Onboarding API", "API GW + Lambda", colors['container'])
    draw_box(ax2, 3.7, 7.5, 2, 0.8, "Reset API", "API GW + Lambda", colors['container'])
    draw_box(ax2, 5.9, 7.5, 2, 0.8, "Portal API", "API GW + Lambda", colors['container'])
    draw_box(ax2, 8.1, 7.5, 2, 0.8, "Webhooks API", "API GW + Lambda", colors['container'])

    # AI Services
    draw_box(ax2, 2.5, 5.5, 3, 1.2, "Teams Bot Adapter", "AWS Lambda", colors['container'])
    draw_box(ax2, 6.0, 5.5, 3, 1.2, "Per-Tenant Agents", "Amazon Bedrock", colors['container'])
    draw_box(ax2, 9.5, 5.5, 3, 1.2, "Knowledge Base", "Bedrock KB + AOSS", colors['container'])

    # Core Lambdas
    draw_box(ax2, 1.5, 3.5, 2.2, 0.8, "Identity Tools", "Lambda", colors['container'])
    draw_box(ax2, 3.9, 3.5, 2.2, 0.8, "Ticket Tools", "Lambda", colors['container'])
    draw_box(ax2, 6.3, 3.5, 2.2, 0.8, "Device Tools", "Lambda", colors['container'])
    draw_box(ax2, 8.7, 3.5, 2.2, 0.8, "Calendar Tools", "Lambda", colors['container'])
    draw_box(ax2, 11.1, 3.5, 2.2, 0.8, "Triage Worker", "Lambda", colors['container'])

    # Data Stores
    draw_box(ax2, 1.5, 1.5, 2.5, 1.0, "DynamoDB", "15 Tables", colors['container'])
    draw_box(ax2, 4.5, 1.5, 2.5, 1.0, "S3 Buckets", "Schemas & Docs", colors['container'])
    draw_box(ax2, 7.5, 1.5, 2.5, 1.0, "SQS Queues", "Async Jobs", colors['container'])
    draw_box(ax2, 10.5, 1.5, 2.5, 1.0, "Secrets Manager", "Credentials", colors['container'])

    # External Elements for this diagram
    draw_person(ax2, 0.2, 7.9, "Admin", "")
    draw_person(ax2, 0.2, 5.9, "End User", "")
    
    draw_box(ax2, 11.5, 7.5, 2, 0.8, "Entra ID", "Graph API", colors['external'])
    draw_box(ax2, 11.5, 5.5, 2, 0.8, "ConnectWise", "PSA", colors['external'])

    # Connections
    draw_arrow(ax2, 0.5, 7.9, 1.5, 7.9, "")
    draw_arrow(ax2, 0.5, 5.9, 2.5, 6.1, "")
    draw_arrow(ax2, 5.5, 5.5, 6.0, 6.1, "Invokes")
    draw_arrow(ax2, 6.0, 6.7, 6.0, 7.5, "")
    draw_arrow(ax2, 10.1, 7.9, 11.5, 7.9, "")
    draw_arrow(ax2, 10.1, 6.1, 11.5, 5.9, "")
    draw_arrow(ax2, 6.5, 5.5, 6.5, 4.3, "")
    draw_arrow(ax2, 6.5, 3.5, 6.5, 2.5, "")

    ax2.set_title("C4 Level 2: Container Architecture Diagram", fontsize=16, fontweight='bold', pad=20, color=colors['text_dark'])
    fig2.savefig("c4_container_diagram.png", format='png', dpi=150, bbox_inches='tight')
    plt.close(fig2)

    print("✅ Success! Generated 'c4_context_diagram.png' and 'c4_container_diagram.png' in your current directory.")

if __name__ == "__main__":
    draw_c4_diagrams()