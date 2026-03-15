import base64
import re
import sys
import os
from google import genai
from google.genai import types

client = genai.Client(
    api_key="sk-j2tHJNKxk8X0DqKcB07e4bC6Fe0e4813A2CfD25a2a17A3C2",
    http_options={"base_url": "https://api.shubiaobiao.cn"},
)

edit_prompt = """
Create a professional, publication-quality system architecture diagram for "AerialClaw v2.0" — an LLM-driven autonomous UAV framework.

STYLE:
- Academic paper figure style (top robotics/AI conference quality)
- Clean, minimal, elegant. NO clipart. NO cartoon icons.
- Rounded rectangles with soft pastel fills and thin borders
- White or very light gray background
- WIDE layout (16:9), landscape orientation
- Sans-serif font (Helvetica/Arial)
- Title at top: "AerialClaw v2.0 System Architecture"

═══════════════════════════════════════════════════════════
CRITICAL LAYOUT AND DATA FLOW — FOLLOW THIS EXACTLY:
═══════════════════════════════════════════════════════════

The diagram shows a CLEAR LEFT-TO-RIGHT FLOW with a FEEDBACK LOOP:

```
User ──NL──→ [BRAIN] ←──reads──→ [IDENTITY]
                │                      ↑
                │ selects               │ updates
                ↓                      │
         [SKILL SYSTEM]               │
                │                      │
                │ commands             │
                ↓                      │
         [SAFETY GATES] ──blocks──→ (rejected)
                │                      │
                │ approved             │
                ↓                      │
         [PLATFORM/DEVICE]            │
                │                      │
                │ sensor data          │
                ↓                      │
         [PERCEPTION]                 │
                │                      │
                │ env summary          │
                ↓                      │
         [BRAIN] (loops back)         │
                │                      │
                │ after task           │
                ↓                      │
         [REFLECTION] ──experience──→ [MEMORY] ──updates──→ IDENTITY
```

═══════════════════════════════════════════════════════════
BLOCKS — position and content:
═══════════════════════════════════════════════════════════

TOP-CENTER: User box (small, simple)
  - Bidirectional arrow to Brain: "Natural Language Commands" / "Status Reports"

CENTER: LLM BRAIN block (blue tones, LARGEST block)
  - Agent Loop shown as circular: Observe → Think → Act → Reflect
  - Two-stage Planner
  - Chat Mode
  - Arrow FROM Identity: "reads context" (dashed line)
  - Arrow TO Skill System: "selects skills"

CENTER-RIGHT: IDENTITY block (cyan/light blue)
  - SOUL.md, BODY.md, MEMORY.md, SKILLS.md, WORLD_MAP.md
  - Arrow FROM Brain: "reads" (dashed)
  - Arrow FROM Reflection/Memory: "updates docs" (purple arrow)
  - These connections are CRITICAL — Identity is not isolated!

RIGHT: FOUR-LAYER SKILL SYSTEM (orange tones)
  - Show as 4 stacked horizontal bars:
    Top:    Soft Skills (strategy docs)
    2nd:    Cognitive Skills (run_python, http_request, read/write_file)
    3rd:    Perception Skills (detect, observe, scan)
    Bottom: Motor Skills (takeoff, fly_to, land, hover...)
  - Arrow FROM Brain: "selects & composes"
  - Arrow TO Safety: "skill commands"

BOTTOM-CENTER: SAFETY GATES (red/dark tones)
  - Four gates in a row: Command Filter → Sandbox → Approval → Flight Envelope
  - Positioned BETWEEN Skill System and Platform
  - Arrow IN from Skill System
  - Arrow OUT to Platform (labeled "approved commands")
  - Small X symbol for "blocked commands"
  - Subtitle: "Spinal Safety — Hardcoded, LLM Cannot Bypass"

BOTTOM: PLATFORM block (gray)
  - PX4 SITL + Gazebo
  - Universal Device Protocol
  - MAVSDK + DDS
  - Arrow OUT to Perception: "sensor data"

LEFT: PERCEPTION block (green tones)
  - Camera (VLM), LiDAR, Telemetry
  - Perception Daemon
  - Arrow TO Brain: "environment summary"

BOTTOM-RIGHT: MEMORY SYSTEM block (indigo/deep blue)
  - Four layers: Working / Episodic / Skill / World
  - Vector Retrieval
  - Arrow FROM Reflection: "stores experience"
  - Arrow TO Brain: "recalls relevant memory" (dashed)
  - Arrow TO Identity: "updates MEMORY.md/SKILLS.md"

BOTTOM-LEFT or RIGHT: REFLECTION & EVOLUTION (purple)
  - Reflection Engine
  - Skill Evolver
  - Capability Gap Detection
  - Arrow FROM Platform: "execution logs"
  - Arrow TO Memory: "structured experience"
  - Arrow TO Identity: "updates docs"
  - This creates the LEARNING LOOP

═══════════════════════════════════════════════════════════
ARROWS (MOST IMPORTANT — every block must have connections):
═══════════════════════════════════════════════════════════

Use COLORED arrows with small text labels on each:

1. Gray arrow: User ↔ Brain ("NL commands" / "reports")
2. Blue dashed: Brain → Identity ("reads context")
3. Orange arrow: Brain → Skill System ("selects skills")
4. Orange arrow: Skill System → Safety ("skill commands")
5. RED arrow: Safety → Platform ("approved") + Safety → X ("blocked")
6. Green arrow: Platform → Perception ("sensor data")
7. Green arrow: Perception → Brain ("env summary")
8. Purple arrow: Platform → Reflection ("execution logs")
9. Purple arrow: Reflection → Memory ("experience")
10. Purple dashed: Memory → Brain ("recalls memory")
11. Purple arrow: Memory/Reflection → Identity ("updates docs")

EVERY block must have at least 2 arrows (in + out). No isolated blocks!

═══════════════════════════════════════════════════════════
KEY REQUIREMENTS:
═══════════════════════════════════════════════════════════
- EVERY block MUST be connected with arrows. NO ISOLATED BLOCKS.
- The LEARNING LOOP must be visually clear: Execute → Reflect → Memory → Brain
- Safety must sit BETWEEN skills and platform like a gate
- Identity must have arrows connecting it to Brain AND Memory
- Skill System must show 4 distinct layers
- Maximum 2-3 words per label
- Wide 16:9 layout
- Publication quality
"""

def save_output(part, prefix, index):
    if part.text:
        match = re.search(r'data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=]+)', part.text)
        if match:
            data = base64.b64decode(match.group(2))
            fn = f"{prefix}_{index}.{match.group(1)}"
            with open(fn, "wb") as f: f.write(data)
            print(f"保存: {fn}")
        else:
            print("文本:", part.text[:200])
    elif hasattr(part, "inline_data") and part.inline_data:
        mime = getattr(part.inline_data, "mime_type", "image/png")
        ext = mime.split("/")[-1]
        fn = f"{prefix}_{index}.{ext}"
        with open(fn, "wb") as f: f.write(part.inline_data.data)
        print(f"保存: {fn}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("生成 AerialClaw v2.0 架构图 (修订版)...")

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=[types.Part.from_text(text=edit_prompt)],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(aspectRatio="16:9", imageSize="2K"),
        ),
    )

    idx = 0
    for part in response.parts:
        save_output(part, "arch_v2_rev", idx)
        if (hasattr(part, "inline_data") and part.inline_data) or (part.text and re.search(r'data:image/', part.text)):
            idx += 1
    print(f"完成: {idx} 张图")
