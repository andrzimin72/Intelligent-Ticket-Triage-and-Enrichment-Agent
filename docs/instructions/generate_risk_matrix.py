#!/usr/bin/env python3
"""
Generate a visual Risk Matrix as PNG/WebP.

Usage:
    python scripts/generate_risk_matrix.py
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Risk data: (ID, likelihood, impact, color)
risks = [
    # Low (green)
    ("TEC-001", 1, 5, "#90EE90"),
    ("TEC-004", 2, 3, "#90EE90"),
    ("COM-005", 2, 3, "#90EE90"),
    ("COM-003", 2, 3, "#90EE90"),
    ("OPS-001", 2, 3, "#90EE90"),
    ("OPS-003", 3, 2, "#90EE90"),
    
    # Medium (yellow)
    ("OPS-002", 3, 3, "#FFD700"),
    ("OPS-004", 3, 3, "#FFD700"),
    ("OPS-006", 3, 3, "#FFD700"),
    ("TPR-003", 3, 3, "#FFD700"),
    ("BUS-002", 3, 3, "#FFD700"),
    ("TEC-002", 3, 3, "#FFD700"),
    ("TEC-003", 2, 4, "#FFD700"),
    ("COM-002", 2, 4, "#FFD700"),
    ("COM-004", 2, 4, "#FFD700"),
    ("SEC-002", 2, 4, "#FFD700"),
    ("SEC-003", 2, 4, "#FFD700"),
    ("FIN-001", 3, 3, "#FFD700"),
    ("FIN-002", 4, 2, "#FFD700"),
    ("TEC-005", 4, 2, "#FFD700"),
    
    # High (orange)
    ("SEC-001", 2, 5, "#FFA500"),
    ("SEC-004", 3, 4, "#FFA500"),
    ("SEC-005", 2, 5, "#FFA500"),
    ("SEC-006", 3, 3, "#FFA500"),  # Adjusted for visibility
    ("OPS-005", 3, 4, "#FFA500"),
    ("COM-001", 2, 5, "#FFA500"),
    ("BUS-001", 3, 4, "#FFA500"),
    ("FIN-003", 4, 3, "#FFA500"),
    ("TPR-002", 2, 4, "#FFA500"),
    
    # Critical (red)
    ("BUS-003", 1, 5, "#FF6347"),
    ("TPR-001", 2, 5, "#FF6347"),
]

# Create figure
fig, ax = plt.subplots(figsize=(12, 10))

# Background color matrix
colors_bg = np.array([
    ["#90EE90", "#90EE90", "#FFD700", "#FFD700", "#FFA500"],  # L=1
    ["#90EE90", "#FFD700", "#FFD700", "#FFA500", "#FFA500"],  # L=2
    ["#FFD700", "#FFD700", "#FFA500", "#FFA500", "#FF6347"],  # L=3
    ["#FFD700", "#FFA500", "#FFA500", "#FF6347", "#FF6347"],  # L=4
    ["#FFA500", "#FFA500", "#FF6347", "#FF6347", "#FF6347"],  # L=5
])

# Draw background
for i in range(5):
    for j in range(5):
        rect = plt.Rectangle((j, i), 1, 1, facecolor=colors_bg[i, j], 
                             edgecolor='white', linewidth=2, alpha=0.3)
        ax.add_patch(rect)

# Plot risks with slight jitter to avoid overlap
np.random.seed(42)
for risk_id, likelihood, impact, color in risks:
    # Add small random offset to prevent exact overlap
    x_offset = np.random.uniform(-0.15, 0.15)
    y_offset = np.random.uniform(-0.15, 0.15)
    
    x = (impact - 1) + 0.5 + x_offset
    y = (likelihood - 1) + 0.5 + y_offset
    
    circle = plt.Circle((x, y), 0.18, color=color, 
                        edgecolor='black', linewidth=1.5, zorder=5)
    ax.add_patch(circle)
    ax.text(x, y, risk_id, ha='center', va='center', 
           fontsize=7, fontweight='bold', zorder=6)

# Configure axes
ax.set_xlim(0, 5)
ax.set_ylim(0, 5)
ax.set_xticks([0.5, 1.5, 2.5, 3.5, 4.5])
ax.set_xticklabels(['1\nNegligible', '2\nMinor', '3\nModerate', '4\nMajor', '5\nCatastrophic'])
ax.set_yticks([0.5, 1.5, 2.5, 3.5, 4.5])
ax.set_yticklabels(['1\nRare', '2\nUnlikely', '3\nPossible', '4\nLikely', '5\nAlmost\nCertain'])
ax.set_xlabel('IMPACT →', fontsize=14, fontweight='bold', labelpad=10)
ax.set_ylabel('LIKELIHOOD →', fontsize=14, fontweight='bold', labelpad=10)
ax.set_title('MSP AI Platform — Risk Matrix', fontsize=18, fontweight='bold', pad=20)

# Add grid
ax.grid(True, linestyle='--', alpha=0.5, color='gray')

# Add legend
legend_elements = [
    mpatches.Patch(facecolor='#90EE90', edgecolor='black', label='Low (1-4): Accept'),
    mpatches.Patch(facecolor='#FFD700', edgecolor='black', label='Medium (5-9): Mitigate'),
    mpatches.Patch(facecolor='#FFA500', edgecolor='black', label='High (10-15): Active Plan'),
    mpatches.Patch(facecolor='#FF6347', edgecolor='black', label='Critical (16-25): Executive'),
]
ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1),
         fontsize=10, frameon=True)

plt.tight_layout()

# Save in both formats
plt.savefig('docs/architecture/risk_matrix.png', dpi=150, bbox_inches='tight')
try:
    plt.savefig('docs/architecture/risk_matrix.webp', format='webp', 
                dpi=150, bbox_inches='tight')
    print("✅ Generated: docs/architecture/risk_matrix.png and .webp")
except Exception as e:
    print(f"✅ Generated: docs/architecture/risk_matrix.png (WebP skipped: {e})")