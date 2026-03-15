"""
gen_arch_v2_clean.py — AerialClaw v2.0 架构图 (精美版)
网格对齐 + 正交箭头 + 专业配色
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Arial", "sans-serif"],
    "font.size": 9,
})

fig, ax = plt.subplots(figsize=(16, 10), dpi=250)
ax.set_xlim(0, 16)
ax.set_ylim(0, 10)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("#fafbfe")

# ── 配色 (柔和学术风) ──
COLORS = {
    "user":       ("#f8f9fa", "#868e96", "#495057"),
    "brain":      ("#dbeafe", "#3b82f6", "#1e40af"),
    "identity":   ("#ccfbf1", "#14b8a6", "#0f766e"),
    "skill_bg":   ("#fef3c7", "#f59e0b", "#92400e"),
    "safety":     ("#fee2e2", "#ef4444", "#991b1b"),
    "platform":   ("#f1f5f9", "#64748b", "#334155"),
    "perception": ("#dcfce7", "#22c55e", "#166534"),
    "memory":     ("#ede9fe", "#8b5cf6", "#5b21b6"),
    "reflection": ("#fae8ff", "#a855f7", "#7e22ce"),
}

# 技能四层色
SKILL_LAYERS = [
    ("#fef3c7", "#d97706", "Motor Skills (12)", "takeoff · fly_to · land · hover · RTL"),
    ("#ecfccb", "#65a30d", "Perception Skills", "detect · observe · scan · fuse"),
    ("#e0f2fe", "#0284c7", "Cognitive Skills (4)", "run_python · http_request · read/write"),
    ("#fce7f3", "#db2777", "Soft Skills (Docs)", "strategy documents · LLM-composed"),
]

def rounded_box(x, y, w, h, fill, edge, txtcolor, title, lines=None, 
                title_fs=10, line_fs=7.5, pad=0.08, lw=1.6, alpha=1.0):
    """精美圆角卡片"""
    box = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad={pad}",
                         facecolor=fill, edgecolor=edge, linewidth=lw, alpha=alpha)
    ax.add_patch(box)
    ty = y + h - 0.22
    ax.text(x + w/2, ty, title, ha="center", va="top",
            fontsize=title_fs, fontweight="bold", color=txtcolor)
    if lines:
        for i, line in enumerate(lines):
            ax.text(x + w/2, ty - 0.30 - i*0.24, line,
                    ha="center", va="top", fontsize=line_fs, color="#4b5563")

def ortho_arrow(x1, y1, x2, y2, color="#94a3b8", lw=1.3, label="",
                label_side="above", shrinkA=4, shrinkB=4, style="-|>", ls="-"):
    """正交箭头"""
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                shrinkA=shrinkA, shrinkB=shrinkB,
                                connectionstyle="arc3,rad=0", linestyle=ls))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        offset = 0.14 if label_side == "above" else -0.14
        ax.text(mx, my + offset, label, ha="center", va="center",
                fontsize=6.5, color=color, fontstyle="italic",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=1))

# ══════════════════════════════════════════════════════════════
#  布局 (上→下流, 左中右三列)
# ══════════════════════════════════════════════════════════════

# 标题
ax.text(8, 9.65, "AerialClaw v2.0", ha="center", fontsize=18,
        fontweight="bold", color="#1e293b")
ax.text(8, 9.35, "System Architecture", ha="center", fontsize=12,
        color="#64748b")

# ── Row 1: User ──
ux, uy, uw, uh = 6.5, 8.55, 3, 0.55
rounded_box(ux, uy, uw, uh, *COLORS["user"], "Operator",
            ["Natural language commands & dialogue"], title_fs=9, line_fs=7)

# ── Row 2: Perception | Brain | Identity ──
# Perception
px, py, pw, ph = 0.4, 5.8, 3.6, 2.4
rounded_box(px, py, pw, ph, *COLORS["perception"], "Perception",
            ["5× Camera (VLM) · 3D LiDAR", "PerceptionDaemon (passive, 3s)",
             "VLM Analyzer (active, on-demand)", "→ Semantic env summary"])

# Brain (中央核心, 最大)
bx, by, bw, bh = 4.5, 5.8, 5, 2.4
rounded_box(bx, by, bw, bh, *COLORS["brain"], "LLM Brain", 
            ["Observe → Think → Act → Reflect",
             "Two-Stage Skill Planner",
             "Chat Mode · Memory-Augmented"], lw=2.2, title_fs=12)

# Identity
ix, iy, iw, ih = 10, 5.8, 2.8, 2.4
rounded_box(ix, iy, iw, ih, *COLORS["identity"], "Identity",
            ["SOUL.md — personality", "BODY.md — hardware",
             "MEMORY.md — experience", "SKILLS.md — statistics",
             "WORLD_MAP.md — environment"], line_fs=7)

# ── Row 2.5: 右侧 Reflection ──
rx, ry, rw, rh = 13.2, 5.8, 2.5, 2.4
rounded_box(rx, ry, rw, rh, *COLORS["reflection"], "Evolution",
            ["Reflection Engine", "Skill Evolver",
             "Capability Gap Detect", "Code Generator"], line_fs=7)

# ── Row 3: Skill System (四层) ──
sx, sy, sw = 4.5, 3.5, 8.3
layer_h = 0.42
total_h = len(SKILL_LAYERS) * layer_h + 0.45

# 外框
outer = FancyBboxPatch((sx, sy), sw, total_h, boxstyle="round,pad=0.08",
                       facecolor="#fffbeb", edgecolor="#d97706", linewidth=1.8)
ax.add_patch(outer)
ax.text(sx + sw/2, sy + total_h - 0.18, "Four-Layer Skill System",
        ha="center", va="top", fontsize=10, fontweight="bold", color="#92400e")

for i, (fill, edge, name, desc) in enumerate(SKILL_LAYERS):
    ly = sy + 0.1 + (len(SKILL_LAYERS)-1-i) * layer_h
    layer = FancyBboxPatch((sx+0.12, ly), sw-0.24, layer_h-0.06,
                           boxstyle="round,pad=0.04", facecolor=fill,
                           edgecolor=edge, linewidth=1, alpha=0.95)
    ax.add_patch(layer)
    ax.text(sx + 0.28, ly + (layer_h-0.06)/2, name, va="center",
            fontsize=8, fontweight="bold", color=edge)
    ax.text(sx + sw - 0.28, ly + (layer_h-0.06)/2, desc, va="center",
            ha="right", fontsize=7, color="#6b7280")

# ── Row 4: Memory | Safety | (Reflection 在右上) ──
# Memory
mx, my, mw, mh = 0.4, 3.3, 3.6, 2.1
rounded_box(mx, my, mw, mh, *COLORS["memory"], "Memory System",
            ["Working · Episodic · Skill · World",
             "Vector semantic retrieval",
             "Cross-task experience transfer"])

# Safety
sfx, sfy, sfw, sfh = 4.5, 1.8, 8.3, 1.3
rounded_box(sfx, sfy, sfw, sfh, *COLORS["safety"], "Spinal Safety Architecture",
            ["Command Filter → Sandbox → Approval → Flight Envelope",
             "Hardcoded limits (10m/s · 120m · 15% battery) — LLM cannot bypass"],
            title_fs=10, line_fs=7.5)

# ── Row 5: Platform ──
plx, ply, plw, plh = 4.5, 0.15, 8.3, 1.3
rounded_box(plx, ply, plw, plh, *COLORS["platform"], "Platform & Devices",
            ["PX4 SITL + Gazebo · MAVSDK + DDS · Universal Device Protocol",
             "Clients: Python / Arduino (ESP32) / ROS2"], line_fs=7.5)

# ══════════════════════════════════════════════════════════════
#  箭头 (正交, 整洁)
# ══════════════════════════════════════════════════════════════

# User → Brain (下)
ortho_arrow(8, 8.55, 8, 8.25, "#64748b", lw=1.5, label="commands ↕ reports")

# Perception → Brain (右)
ortho_arrow(4.0, 7.0, 4.5, 7.0, "#22c55e", lw=1.5, label="env summary")

# Brain ← Identity (左)
ortho_arrow(10.0, 7.0, 9.5, 7.0, "#14b8a6", lw=1.2, label="reads context", ls="--")

# Brain → Skill System (下)
ortho_arrow(7, 5.8, 7, 5.65, "#3b82f6", lw=1.5, label="selects & composes")

# Skill System → Safety (下)
ortho_arrow(8.6, 3.5, 8.6, 3.15, "#ef4444", lw=1.5, label="commands")

# Safety → Platform (下)
ortho_arrow(8.6, 1.8, 8.6, 1.5, "#ef4444", lw=1.5, label="approved ✓")

# Platform → Perception (左, 上)
ortho_arrow(4.5, 0.8, 2.2, 5.8, "#22c55e", lw=1.2, label="sensor data")

# Platform → Reflection (右上, 执行日志)
ortho_arrow(12.8, 0.8, 14.45, 5.8, "#a855f7", lw=1.2, label="execution logs")

# Reflection → Memory (左)
ortho_arrow(13.2, 6.5, 4.0, 4.8, "#8b5cf6", lw=1.2, label="experience", ls="--")

# Memory → Brain (上)
ortho_arrow(2.2, 5.4, 4.5, 6.5, "#8b5cf6", lw=1.2, label="recalls", ls="--")

# Reflection → Identity (左, 更新文档)
ortho_arrow(13.2, 7.2, 12.8, 7.2, "#a855f7", lw=1, label="updates", ls="--")

# Safety 拒绝标注
ax.text(12.2, 2.3, "✕ blocked", fontsize=8, color="#ef4444",
        fontweight="bold", fontstyle="italic")

# ── 学习闭环标注 ──
ax.text(14.5, 5.5, "Learning", fontsize=7.5, color="#7c3aed",
        fontweight="bold", fontstyle="italic", rotation=0)
ax.text(14.5, 5.25, "Loop ↻", fontsize=7.5, color="#7c3aed",
        fontweight="bold", fontstyle="italic")

plt.tight_layout(pad=0.3)
plt.savefig("arch_v2_clean.png", dpi=250, bbox_inches="tight",
            facecolor="#fafbfe", edgecolor="none")
print("✅ arch_v2_clean.png")
