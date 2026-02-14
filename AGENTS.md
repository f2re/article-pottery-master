# 🏯 Pottery Master: Multi-Agent System Registry

This file serves as the global context and coordinator for the specialized agents in the article-writing system.

## 👥 Available Agents
Use `@agent-name` to activate a specific specialist.

1. **@archeologist**: Deep research, terminology, and historical context.
2. **@calligrapher**: Sincere, sensory hooks & SEO.
3. **@sculptor**: Strong verbs, rhythmic narrative, and expert body content.
4. **@tea-master**: Emotional conclusions, Zen aftertaste, and soft CTA.
5. **@visual-director**: Cinematic visual art direction (Hasselblad/Leica vibes).
6. **@kiln-master**: Assembling drafts with seamless flow.
7. **@gallery-curator**: Vibe audit, "Purple Prose" detection, and SEO scoring.
8. **@editor-in-chief**: Typographic polish and metadata.

---

## 🏗️ Architecture & Standards

### 📂 Directory Structure
- `.gemini/agents/`: Agent instruction files (`.md`).
- `.gemini/agents/tasks/`: Active task tracking.
- `.gemini/agents/plans/`: Long-term article plans.
- `.gemini/agents/logs/`: Execution logs.

### 📝 Core Instructions (Global)
- **The Golden Rule**: **VIBE FIRST**. Every text and image must carry a specific emotional weight (Serenity, Melancholy, Drama).
- **The "Anti-Sugar" Law**: One strong verb is better than two weak adjectives. Avoid "Purple Prose."
- **The Breath**: Write with rhythm. Short sentences for impact. Long sentences for flow. Silence (paragraphs) for thought.
- **Visuals**: Focus on the HERO object. Remove clutter. Use cinematic lighting (Chiaroscuro).

### 📍 Source Files
- `input/topic.txt`: Target topic.
- `AUTOR_STYLE.md`: Global style guide.

---
*Instructions for each agent are located in `.gemini/agents/[agent-name].md`.*
