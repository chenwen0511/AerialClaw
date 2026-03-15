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
Create a professional, publication-quality system architecture diagram for "AerialClaw v2.0" — an LLM-driven autonomous UAV framework with self-evolution capabilities.

STYLE:
- Modern academic paper figure style (like top robotics/AI conference papers)
- Clean, minimal, elegant. NO clipart. NO cartoon icons.
- Rounded rectangles with soft pastel fills and thin borders
- White or very light gray background
- Use a HORIZONTAL / WIDE layout (16:9), NOT a tall vertical flowchart
- Sans-serif font (like Helvetica or Arial)
- Title at top: "AerialClaw v2.0 System Architecture" in bold

LAYOUT (center brain, modules around it):

Far left: PERCEPTION block (green tones)
  - 5x Camera (VLM)
  - 3D LiDAR
  - Telemetry
  - Perception Daemon
  - Label: "Semantic Fusion"

Center: LLM BRAIN block (blue tones) — the largest, central element
  - Agent Loop: Observe → Think → Act → Reflect
  - Two-stage Planner
  - Chat Mode
  - Show the loop visually with circular arrows

Center-right top: IDENTITY block (light blue / cyan)
  - SOUL.md (personality)
  - BODY.md (hardware)
  - MEMORY.md (experience)
  - SKILLS.md (stats)

Right: FOUR-LAYER SKILL SYSTEM block (orange tones) — IMPORTANT: show 4 layers stacked
  - Motor Skills (12): takeoff, fly_to, land...
  - Cognitive Skills (4): run_python, http_request, read/write_file
  - Perception Skills: detect, observe, scan
  - Soft Skills: document-driven strategies
  - Label at bottom: "Dynamic Generation + Auto-Retire"

Bottom-left: SAFETY block (red/dark tones) — NEW in v2.0
  - Four Gates: Command Filter → Sandbox → Approval → Flight Envelope
  - Label: "Spinal Safety Architecture"
  - Show it as a filter/gate between Brain and Platform
  - Small text: "Hardcoded limits — LLM cannot bypass"

Bottom-center: PLATFORM block (gray)
  - PX4 SITL + Gazebo Harmonic
  - Universal Device Protocol (HTTP + WebSocket)
  - MAVSDK + DDS
  - Three client icons: Python / Arduino / ROS2

Bottom-right: MEMORY SYSTEM block (deep blue/indigo tones) — NEW in v2.0
  - Four layers stacked: Working / Episodic / Skill / World
  - Vector Retrieval
  - Arrow connecting to Reflection block

Right-bottom: REFLECTION & EVOLUTION block (purple tones)
  - Reflection Engine
  - Skill Evolution
  - Capability Gap Detection
  - Device Analyzer + Code Generator
  - Arrow looping back to Memory and Skills

ARROWS / DATA FLOW (use colored arrows with small labels):
1. Green arrows: Perception → Brain (sensor data flow)
2. Blue arrows: Brain → Safety → Platform (control flow, safety gate in middle!)
3. Purple arrows: Platform logs → Reflection → Memory/Skills update (learning loop)
4. Light gray arrows: User ↔ Brain (NL commands & chat)
5. Red arrow/barrier: Safety block between Brain output and Platform (emphasize filtering)

KEY REQUIREMENTS:
- The Safety block must visually sit BETWEEN the Brain and the Platform, like a gate/filter
- The Skill System must show 4 distinct layers (Motor/Cognitive/Perception/Soft)
- The Memory System must show 4 layers (Working/Episodic/Skill/World)
- Show the learning/evolution loop clearly as a cycle
- The diagram must be WIDE, not tall. Landscape orientation.
- Maximum 2-3 words per label. No sentences.
- Leave adequate whitespace
- This should look like Figure 1 in a top-tier robotics paper
"""

modules_prompt = """
Create a sleek, dark-themed module overview card grid for "AerialClaw v2.0".

STYLE:
- Dark background (#0a0e1a or similar deep navy)
- 8 cards in a 4x2 grid layout
- Each card: rounded rectangle with subtle gradient border glow
- Icon at top of each card (simple geometric/abstract, NOT clipart)
- Card title in bold white
- 3 bullet points per card in light gray
- 16:9 landscape ratio

THE 8 CARDS:

Row 1:
1. Brain (blue glow)
   • Agent Loop
   • Chat Mode
   • Two-stage Planner

2. Perception (green glow)
   • Sensor Fusion
   • VLM Analysis
   • Environment Summary

3. Skills (orange glow)
   • 12 Motor Skills
   • 4 Cognitive Skills
   • Soft Strategies

4. Safety (red glow)
   • Command Filter
   • Sandbox Isolation
   • Flight Envelope

Row 2:
5. Memory (indigo glow)
   • 4-Layer Memory
   • Vector Retrieval
   • Reflection Engine

6. Identity (cyan glow)
   • SOUL.md
   • BODY.md
   • MEMORY.md

7. Adapter (gray glow)
   • PX4 / MAVSDK
   • Protocol Adapter
   • Device Manager

8. Evolution (purple glow)
   • Device Analyzer
   • Code Generator
   • Capability Gap

REQUIREMENTS:
- Must be 8 cards, not 6
- Dark sleek aesthetic, like a tech dashboard
- Consistent card sizes and spacing
- No text outside the cards except maybe a subtle "AerialClaw v2.0" watermark
"""

aspect_ratio = "16:9"
resolution = "2K"

def save_output(part, prefix, index):
    if part.text:
        match = re.search(r'data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=]+)', part.text)
        if match:
            ext = match.group(1)
            data = base64.b64decode(match.group(2))
            fn = f"{prefix}_{index}.{ext}"
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

def generate(prompt, prefix):
    print(f"\n生成 {prefix}...")
    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=[types.Part.from_text(text=prompt)],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(aspectRatio=aspect_ratio, imageSize=resolution),
        ),
    )
    idx = 0
    for part in response.parts:
        save_output(part, prefix, idx)
        if (hasattr(part, "inline_data") and part.inline_data) or (part.text and re.search(r'data:image/', part.text)):
            idx += 1
    return idx

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("AerialClaw v2.0 图表生成器")
    n1 = generate(edit_prompt, "arch_v2")
    n2 = generate(modules_prompt, "modules_v2")
    print(f"\n完成: 架构图 {n1} 张, 模块图 {n2} 张")
