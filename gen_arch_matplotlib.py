"""
gen_arch_v2.py — AerialClaw v2.0 系统架构图 (matplotlib 手绘版)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np

# ── 字体 ──
plt.rcParams["font.family"] = ["Helvetica Neue", "Arial", "sans-serif"]
plt.rcParams["font.size"] = 9

fig, ax = plt.subplots(1, 1, figsize=(18, 10), dpi=200)
ax.set_xlim(0, 18)
ax.set_ylim(0, 10)
ax.set_aspect("equal")
ax.axis("off")
fig.patch.set_facecolor("white")

# ── 配色 ──
C = {
    "brain":      ("#e3f2fd", "#1565c0"),   # 浅蓝, 深蓝
    "identity":   ("#e0f7fa", "#00838f"),   # 浅青, 深青
    "skill":      ("#fff3e0", "#e65100"),   # 浅橙, 深橙
    "safety":     ("#fce4ec", "#c62828"),   # 浅红, 深红
    "platform":   ("#f5f5f5", "#424242"),   # 浅灰, 深灰
    "perception": ("#e8f5e9", "#2e7d32"),   # 浅绿, 深绿
    "memory":     ("#ede7f6", "#4527a0"),   # 浅紫, 深紫
    "reflection": ("#f3e5f5", "#6a1b9a"),   # 浅紫, 深紫
    "user":       ("#fafafa", "#616161"),   # 浅灰, 中灰
}

def box(x, y, w, h, fill, edge, title, items=None, title_size=11, item_size=8, radius=0.15):
    """画一个圆角矩形模块"""
    fancy = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad={radius}",
                           facecolor=fill, edgecolor=edge, linewidth=1.5)
    ax.add_patch(fancy)
    ax.text(x + w/2, y + h - 0.28, title, ha="center", va="top",
            fontsize=title_size, fontweight="bold", color=edge)
    if items:
        for i, item in enumerate(items):
            ax.text(x + w/2, y + h - 0.62 - i * 0.28, item,
                    ha="center", va="top", fontsize=item_size, color="#333333")

def arrow(x1, y1, x2, y2, color="#666", style="-|>", lw=1.2, label="", ls="-"):
    """画箭头"""
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw, ls=ls))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.12, label, ha="center", va="bottom",
                fontsize=7, color=color, style="italic")

# ══════════════════════════════════════════════════════════════
#  布局
# ══════════════════════════════════════════════════════════════

# 标题
ax.text(9, 9.7, "AerialClaw v2.0 System Architecture", ha="center", va="top",
        fontsize=16, fontweight="bold", color="#1a1a1a")

# ── User (顶部中央) ──
box(7.8, 8.7, 2.4, 0.7, *C["user"], "User", ["Natural Language"], title_size=10)

# ── Brain (中央核心) ──
box(5.5, 5.8, 7, 2.5, *C["brain"], "LLM Brain",
    ["Agent Loop: Observe → Think → Act → Reflect",
     "Two-Stage Planner  |  Chat Mode",
     "Memory-Augmented Planning"])

# ── Identity (右上) ──
box(13.5, 6.5, 3.5, 2.2, *C["identity"], "Identity System",
    ["SOUL.md  —  personality",
     "BODY.md  —  hardware",
     "MEMORY.md  —  experience",
     "SKILLS.md  —  statistics",
     "WORLD_MAP.md  —  environment"])

# ── Skill System (右中) ──
# 四层堆叠
sk_x, sk_y, sk_w = 13.5, 3.0, 3.5
layer_h = 0.65
layers = [
    ("Soft Skills", "Strategy documents, LLM-composed", "#fff3e0", "#e65100"),
    ("Cognitive Skills", "run_python, http_request, r/w file", "#fff8e1", "#f57f17"),
    ("Perception Skills", "detect, observe, scan, fuse", "#f1f8e9", "#558b2f"),
    ("Motor Skills", "takeoff, fly_to, land, hover (12)", "#fbe9e7", "#bf360c"),
]
# 外框
fancy = FancyBboxPatch((sk_x, sk_y), sk_w, len(layers)*layer_h + 0.5,
                       boxstyle="round,pad=0.12", facecolor="#fff9f0",
                       edgecolor="#e65100", linewidth=1.5)
ax.add_patch(fancy)
ax.text(sk_x + sk_w/2, sk_y + len(layers)*layer_h + 0.35, "Four-Layer Skill System",
        ha="center", va="top", fontsize=11, fontweight="bold", color="#e65100")

for i, (name, desc, fill, edge) in enumerate(layers):
    ly = sk_y + 0.15 + (len(layers)-1-i) * layer_h
    rect = FancyBboxPatch((sk_x+0.1, ly), sk_w-0.2, layer_h-0.08,
                          boxstyle="round,pad=0.05", facecolor=fill,
                          edgecolor=edge, linewidth=1, alpha=0.9)
    ax.add_patch(rect)
    ax.text(sk_x + 0.25, ly + layer_h/2, name, va="center", fontsize=8.5,
            fontweight="bold", color=edge)
    ax.text(sk_x + sk_w - 0.25, ly + layer_h/2, desc, va="center", ha="right",
            fontsize=7, color="#555")

# ── Safety Gates (中下) ──
sf_x, sf_y = 5.5, 3.3
box(sf_x, sf_y, 7, 1.8, *C["safety"], "Spinal Safety Architecture",
    ["Command Filter → Sandbox → Approval → Flight Envelope",
     "Hardcoded physical limits — LLM cannot bypass",
     "Three levels: strict / standard / permissive"], item_size=7.5)

# ── Platform (底部中央) ──
box(5.5, 0.8, 7, 2.0, *C["platform"], "Platform & Devices",
    ["PX4 SITL + Gazebo Harmonic  |  MAVSDK + DDS",
     "Universal Device Protocol (HTTP + WebSocket)",
     "Clients: Python / Arduino (ESP32) / ROS2"])

# ── Perception (左侧) ──
box(0.5, 5.5, 4.2, 2.8, *C["perception"], "Perception System",
    ["5× Camera (VLM)  |  3D LiDAR",
     "Telemetry  |  IMU  |  GPS",
     "Passive: PerceptionDaemon (3s)",
     "Active: VLM deep analysis",
     "→ Semantic environment summary"])

# ── Memory (左下) ──
box(0.5, 2.5, 4.2, 2.5, *C["memory"], "Memory System",
    ["Working — current context",
     "Episodic — task experiences",
     "Skill — execution statistics",
     "World — environment knowledge",
     "Vector semantic retrieval"])

# ── Reflection (左最下) ──
box(0.5, 0.5, 4.2, 1.6, *C["reflection"], "Reflection & Evolution",
    ["Reflection Engine  |  Skill Evolver",
     "Capability Gap Detection",
     "Device Analyzer  |  Code Generator"])

# ══════════════════════════════════════════════════════════════
#  箭头 (数据流)
# ══════════════════════════════════════════════════════════════

# User ↔ Brain
arrow(9, 8.7, 9, 8.35, "#616161", lw=1.5, label="commands")
arrow(9, 8.3, 9, 8.65, "#616161", lw=1, label="")  # 双向

# Brain → Identity (reads)
arrow(12.5, 7.2, 13.5, 7.2, "#00838f", lw=1.2, label="reads", ls="--")

# Brain → Skill System (selects)
arrow(12.5, 6.5, 13.5, 5.8, "#e65100", lw=1.5, label="selects")

# Skill System → Safety (commands down)
arrow(15.25, 3.0, 12.5, 4.2, "#c62828", lw=1.5, label="skill commands")

# Safety → Platform (approved)
arrow(9, 3.3, 9, 2.8, "#c62828", lw=1.5, label="approved")

# Safety → X (blocked)
ax.text(12.8, 4.0, "✕ blocked", fontsize=8, color="#c62828", fontweight="bold")

# Platform → Perception (sensor data)
arrow(5.5, 1.8, 4.7, 5.5, "#2e7d32", lw=1.5, label="sensor data")

# Perception → Brain (env summary)
arrow(4.0, 8.0, 5.5, 7.5, "#2e7d32", lw=1.5, label="env summary")

# Platform → Reflection (execution logs)
arrow(5.5, 1.0, 4.7, 1.2, "#6a1b9a", lw=1.2, label="logs")

# Reflection → Memory (experience)
arrow(2.6, 2.1, 2.6, 2.5, "#6a1b9a", lw=1.5, label="experience")

# Memory → Brain (recalls)
arrow(2.6, 5.0, 5.5, 6.5, "#4527a0", lw=1.2, label="recalls memory", ls="--")

# Memory/Reflection → Identity (updates docs)
arrow(4.7, 4.0, 13.5, 7.8, "#6a1b9a", lw=1, label="updates docs", ls="--")

# ── 学习闭环标注 ──
ax.annotate("Learning Loop", xy=(1.5, 1.0), fontsize=8, color="#6a1b9a",
            fontweight="bold", style="italic")

# ── 保存 ──
plt.tight_layout(pad=0.5)
plt.savefig("arch_v2_matplotlib.png", dpi=200, bbox_inches="tight",
            facecolor="white", edgecolor="none")
print("✅ 保存: arch_v2_matplotlib.png")
